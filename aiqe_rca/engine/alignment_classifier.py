"""Expected-vs-observed alignment classifier.

Classifies each evidence-hypothesis pair into exactly one relationship tag:
- supporting:     observed behavior confirms expected conditions for this hypothesis
- weakening:      partially conflicts or reduces confidence in this hypothesis
- contradicting:  directly conflicts with expected conditions for this hypothesis
- indeterminate:  only when evidence is genuinely not classifiable

Core rule (non-negotiable): classification is driven by expected-vs-observed
behavior comparison, NOT keyword presence alone. Evidence is never marked
supporting simply because it contains domain-related terms.

PFMEA / Control Plan sources (DR / PC categories) describe possible causes,
not observed conditions — they are treated as indeterminate unless they contain
explicit contradictory signals or observed measurement language.
"""

from __future__ import annotations

import re

import yaml

from aiqe_rca.config import settings
from aiqe_rca.models.alignment import AlignmentLabel, AlignmentResult
from aiqe_rca.models.evidence import EvidenceCategory, EvidenceElement
from aiqe_rca.models.hypothesis import Hypothesis

_SIGNAL_GROUPS_CACHE: dict[str, dict] | None = None


def _get_signal_groups() -> dict[str, dict]:
    """Load signal groups once per process for group-specific pattern lookup."""
    global _SIGNAL_GROUPS_CACHE
    if _SIGNAL_GROUPS_CACHE is None:
        path = settings.rules_dir / "signal_groups.yaml"
        with open(path, encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
        _SIGNAL_GROUPS_CACHE = {
            group["id"]: group for group in data.get("signal_groups", [])
        }
    return _SIGNAL_GROUPS_CACHE


# Tokens indicating observed anomaly — confirm an expected problem condition
_POSITIVE_STATE_TOKENS = frozenset({
    "elevated", "increased", "increasing", "high", "higher", "abnormal",
    "excessive", "irregular", "variable", "unstable", "degraded", "degrading",
    "worn", "drift", "shifted", "failure", "failed", "fail", "failing",
    "defect", "defective", "detected", "observed", "found",
    "measured", "correlation", "correlated", "significant", "exceeded",
    "out", "nonconformance", "nonconforming", "reject", "rejected",
    "anomaly", "deviation", "spike", "spikes", "drop", "drops",
    "blistering", "blister", "crack", "cracking", "peel", "peeling",
    "chatter", "runout", "contamination", "residue",
    "inconsistent", "fluctuated", "fluctuating", "varied", "varying",
    "intermittent", "erratic", "abnormally",
})

# Tokens indicating normal / acceptable state — negate an expected problem condition
_NEGATIVE_STATE_TOKENS = frozenset({
    "low", "minimal", "minor", "reduced", "decreased", "negligible",
    "normal", "nominal", "stable", "steady", "unchanged", "consistent",
    "within", "acceptable", "verified", "pass", "passed", "passing",
    "absent", "negative", "clean", "clear", "good", "compliant",
    "conforming", "controlled", "managed", "satisfactory",
    "remained", "remaining", "maintained", "maintaining",
})

_NEGATION_PREFIXES = ("no", "not", "without", "never", "none")


def _normalize_text(text: str) -> str:
    """Normalize whitespace and casing for deterministic text matching."""
    return re.sub(r"\s+", " ", text.lower()).strip()


def _tokenize(text: str) -> list[str]:
    """Extract stable tokens from free text."""
    return re.findall(r"[a-z0-9]+(?:[/-][a-z0-9]+)*", _normalize_text(text))


def _split_statements(text: str) -> list[str]:
    """Break evidence into coarse reasoning statements."""
    normalized = text.replace("•", ". ").replace(";", ". ")
    return [part.strip() for part in re.split(r"[.\n]+", normalized) if part.strip()]


def _contains_phrase(text: str, phrase: str) -> bool:
    """Return True when a phrase is present as a word-bounded match."""
    if not phrase:
        return False
    return (
        re.search(
            r"\b" + re.escape(_normalize_text(phrase)) + r"\b",
            _normalize_text(text),
        )
        is not None
    )


def _collect_hypothesis_terms(hypothesis: Hypothesis) -> list[str]:
    """Build the hypothesis term set used to evaluate domain relevance."""
    terms: set[str] = set()
    if hypothesis.process_step:
        terms.add(_normalize_text(hypothesis.process_step))
    for keyword in hypothesis.keywords:
        normalized = _normalize_text(keyword)
        if normalized:
            terms.add(normalized)
    return sorted(terms, key=lambda item: (-len(item.split()), -len(item), item))


def _matched_terms(text: str, terms: list[str]) -> list[str]:
    """Return hypothesis terms explicitly present in the evidence text."""
    return [term for term in terms if _contains_phrase(text, term)]


def _term_negated(statement: str, term: str) -> bool:
    """Return True when the matched term appears with a nearby negation prefix."""
    normalized_statement = _normalize_text(statement)
    normalized_term = _normalize_text(term)
    match = re.search(r"\b" + re.escape(normalized_term) + r"\b", normalized_statement)
    if match is None:
        return False
    prefix = normalized_statement[max(0, match.start() - 24) : match.start()]
    prefix_tokens = _tokenize(prefix)[-3:]
    return any(token in _NEGATION_PREFIXES for token in prefix_tokens)


def _count_pattern_hits(text: str, patterns: tuple[str, ...]) -> list[str]:
    """Return all matched pattern phrases in deterministic order."""
    matches = [pattern for pattern in patterns if _contains_phrase(text, pattern)]
    return sorted(set(matches))


def _group_contradicting_patterns(hypothesis: Hypothesis) -> tuple[str, ...]:
    """Return contradicting patterns specific to this hypothesis's signal group."""
    groups = _get_signal_groups()
    group = groups.get(hypothesis.template_id or "")
    if group is None:
        return ()
    return tuple(group.get("contradicting_signals", []))


def _derive_expected_conditions(hypothesis: Hypothesis) -> list[str]:
    """Return observable conditions expected if this hypothesis is true."""
    groups = _get_signal_groups()
    group = groups.get(hypothesis.template_id or "")
    if group is None:
        return []
    return group.get("expected_conditions", [])


def _score_expected_observable(statement: str, condition: str) -> str:
    """
    Classify a single statement against a single expected condition.

    Returns one of: 'confirming', 'negating', 'domain_only', 'absent'

    - confirming:  condition tokens present and positive state signals dominate
    - negating:    condition tokens present and explicit negation or negative state dominates
    - domain_only: condition tokens present but state is ambiguous
    - absent:      condition tokens not meaningfully present
    """
    norm_stmt = _normalize_text(statement)

    # Extract key tokens from condition (length >= 4 to avoid trivial words)
    condition_tokens = [t for t in _tokenize(_normalize_text(condition)) if len(t) >= 4]
    if not condition_tokens:
        return "absent"

    stmt_token_set = set(_tokenize(norm_stmt))
    matched = [t for t in condition_tokens if t in stmt_token_set]

    if not matched:
        return "absent"

    match_ratio = len(matched) / len(condition_tokens)
    if match_ratio < 0.30:
        return "absent"

    # Check explicit negation (no/not/without directly before a matched token)
    directly_negated = any(_term_negated(statement, t) for t in matched)

    # Collect window tokens around each matched term (±40 chars) for state detection
    window_tokens: set[str] = set()
    for token in matched:
        m = re.search(r"\b" + re.escape(token) + r"\b", norm_stmt)
        if m:
            window = norm_stmt[max(0, m.start() - 40) : m.end() + 40]
            window_tokens.update(_tokenize(window))

    pos_count = len(window_tokens & _POSITIVE_STATE_TOKENS)
    neg_count = len(window_tokens & _NEGATIVE_STATE_TOKENS)

    if directly_negated:
        return "negating"

    if neg_count > pos_count and match_ratio >= 0.40:
        return "negating"

    if pos_count > 0 and match_ratio >= 0.40:
        return "confirming"

    if match_ratio >= 0.50:
        # Condition tokens clearly present but no state signal — topic mentioned, state unclear
        return "domain_only"

    return "absent"


def _score_expected_vs_observed(
    evidence_text: str,
    expected_conditions: list[str],
    hypothesis_terms: list[str],
) -> tuple[int, int, int]:
    """
    Score evidence against expected conditions.

    Returns: (confirming, negating, domain_only)
    - confirming:  count of statements that confirm at least one expected condition
    - negating:    count of statements that negate at least one expected condition
    - domain_only: count of statements that are domain-relevant but neither confirm nor negate
    """
    statements = _split_statements(evidence_text)
    confirming = 0
    negating = 0
    domain_only = 0

    if not expected_conditions:
        # Fallback when no expected_conditions are defined: use state tokens near hypothesis terms
        for stmt in statements:
            term_hits = _matched_terms(stmt, hypothesis_terms)
            if not term_hits:
                continue
            stmt_tokens = set(_tokenize(_normalize_text(stmt)))
            pos_count = len(stmt_tokens & _POSITIVE_STATE_TOKENS)
            neg_count = len(stmt_tokens & _NEGATIVE_STATE_TOKENS)
            directly_negated = any(_term_negated(stmt, t) for t in term_hits)
            if directly_negated or (neg_count > 0 and neg_count > pos_count):
                negating += 1
            elif pos_count > 0:
                confirming += 1
            else:
                domain_only += 1
        return confirming, negating, domain_only

    for stmt in statements:
        stmt_confirming = 0
        stmt_negating = 0
        stmt_domain = 0

        for condition in expected_conditions:
            result = _score_expected_observable(stmt, condition)
            if result == "confirming":
                stmt_confirming += 1
            elif result == "negating":
                stmt_negating += 1
            elif result == "domain_only":
                stmt_domain += 1

        # Classify this statement's net contribution
        if stmt_confirming > 0 and stmt_negating == 0:
            confirming += 1
        elif stmt_negating > 0 and stmt_confirming == 0:
            negating += 1
        elif stmt_confirming > 0 and stmt_negating > 0:
            # Mixed statement: evidence partially confirms and partially negates (weakening)
            confirming += 1
            negating += 1
        elif stmt_domain > 0:
            # Domain-relevant but no clear state signal
            if _matched_terms(stmt, hypothesis_terms):
                domain_only += 1
        else:
            # Basic term check as last resort for domain relevance
            if _matched_terms(stmt, hypothesis_terms):
                domain_only += 1

    return confirming, negating, domain_only


def _is_process_document(evidence: EvidenceElement) -> bool:
    """Return True for PFMEA/Control Plan sources (possible-cause documents, not observations)."""
    return evidence.category in (
        EvidenceCategory.DESIGN_REQUIREMENTS,
        EvidenceCategory.PROCESS_CONTROL,
    )


def _contains_observed_data(text: str) -> bool:
    """Return True when text contains language indicating actual observed measurements."""
    observed_markers = (
        "measured", "recorded", "observed", "detected", "confirmed",
        "reading", "data shows", "results show", "test result",
        "lab result", "sample result", "analysis shows",
        "out of spec", "out of control", "failed", "rejected",
    )
    norm = _normalize_text(text)
    return any(_contains_phrase(norm, marker) for marker in observed_markers)


def _collect_confirmed_negated(
    evidence_text: str,
    expected_conditions: list[str],
) -> tuple[list[str], list[str]]:
    """Collect which specific conditions were confirmed and negated for rationale building."""
    confirmed: list[str] = []
    negated: list[str] = []
    for stmt in _split_statements(evidence_text):
        for condition in expected_conditions:
            result = _score_expected_observable(stmt, condition)
            if result == "confirming" and condition not in confirmed:
                confirmed.append(condition)
            elif result == "negating" and condition not in negated:
                negated.append(condition)
    return confirmed, negated


def _build_rationale(
    label: AlignmentLabel,
    hypothesis: Hypothesis,
    confirmed_conditions: list[str],
    negated_conditions: list[str],
    contra_phrases: list[str],
) -> str:
    """Build a concise explanation for the assigned relationship."""
    hyp_name = hypothesis.process_step or hypothesis.id

    if label == AlignmentLabel.SUPPORTING:
        if confirmed_conditions:
            conds = ", ".join(confirmed_conditions[:2])
            return f"Observed evidence confirms expected conditions for this hypothesis: {conds}."
        return f"Observed evidence aligns with expected behavior for {hyp_name}."

    if label == AlignmentLabel.WEAKENING:
        if negated_conditions and confirmed_conditions:
            return (
                f"Evidence is mixed: some observations align with expected conditions while "
                f"others reduce confidence in {hyp_name}."
            )
        if negated_conditions:
            conds = ", ".join(negated_conditions[:2])
            return f"Evidence partially conflicts with expected conditions for this hypothesis: {conds}."
        return (
            f"Evidence is domain-relevant but does not directly confirm "
            f"expected conditions for {hyp_name}."
        )

    if label == AlignmentLabel.CONTRADICTING:
        if contra_phrases:
            phrases = ", ".join(contra_phrases[:2])
            return f"Evidence directly contradicts expected conditions for {hyp_name}: {phrases}."
        if negated_conditions:
            conds = ", ".join(negated_conditions[:2])
            return (
                f"Evidence contradicts expected conditions for {hyp_name} "
                f"— non-occurrence of: {conds}."
            )
        return f"Evidence is inconsistent with expected behavior for {hyp_name}."

    return "Evidence mentions related context but cannot be classified against expected conditions."


def classify_alignment(
    hypothesis: Hypothesis,
    evidence: EvidenceElement,
) -> AlignmentResult:
    """Classify the evidence-to-hypothesis relationship using expected-vs-observed logic."""
    evidence_text = evidence.text_content
    hypothesis_terms = _collect_hypothesis_terms(hypothesis)
    expected_conditions = _derive_expected_conditions(hypothesis)
    contradicting_patterns = _group_contradicting_patterns(hypothesis)

    # Check for explicit contradicting signals from the YAML definition
    norm_text = _normalize_text(evidence_text)
    contra_hits = _count_pattern_hits(norm_text, contradicting_patterns)

    # PFMEA / Control Plan: treat as indeterminate unless contradicted or contains observed data
    if _is_process_document(evidence) and not _contains_observed_data(evidence_text):
        if contra_hits:
            label = AlignmentLabel.CONTRADICTING
        else:
            label = AlignmentLabel.INDETERMINATE
        return AlignmentResult(
            hypothesis_id=hypothesis.id,
            evidence_id=evidence.id,
            classification=label,
            rationale=_build_rationale(label, hypothesis, [], [], list(contra_hits)),
        )

    # Score evidence against expected conditions (expected-vs-observed core logic)
    confirming, negating, domain_only = _score_expected_vs_observed(
        evidence_text, expected_conditions, hypothesis_terms
    )

    # Combine explicit contradicting hits with negation score
    total_against = len(contra_hits) + negating

    # Collect specific conditions for rationale
    confirmed_conditions, negated_conditions = _collect_confirmed_negated(
        evidence_text, expected_conditions
    )
    negated_conditions = sorted(set(negated_conditions + list(contra_hits)))

    # Classification decision
    if total_against == 0 and confirming == 0 and domain_only == 0:
        label = AlignmentLabel.INDETERMINATE
    elif total_against > confirming:
        label = AlignmentLabel.CONTRADICTING
    elif confirming > 0 and confirming > total_against:
        label = AlignmentLabel.SUPPORTING
    elif confirming > 0 or domain_only > 0:
        # Domain-relevant with partial confirmation, mixed evidence, or ambiguous state → weakening
        label = AlignmentLabel.WEAKENING
    else:
        label = AlignmentLabel.INDETERMINATE

    return AlignmentResult(
        hypothesis_id=hypothesis.id,
        evidence_id=evidence.id,
        classification=label,
        rationale=_build_rationale(
            label,
            hypothesis,
            confirmed_conditions[:3],
            negated_conditions[:3],
            list(contra_hits),
        ),
    )


def classify_all_alignments(
    hypotheses: list[Hypothesis],
    evidence_elements: list[EvidenceElement],
) -> list[AlignmentResult]:
    """Classify all associated evidence-hypothesis pairs."""
    evidence_map = {evidence.id: evidence for evidence in evidence_elements}
    results: list[AlignmentResult] = []

    for hypothesis in hypotheses:
        for evidence_id in hypothesis.associated_evidence_ids:
            evidence = evidence_map.get(evidence_id)
            if evidence is None:
                continue
            results.append(classify_alignment(hypothesis, evidence))

    return results
