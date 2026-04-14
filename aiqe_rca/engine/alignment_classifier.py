"""Input-driven alignment classifier.

Classifies each evidence-hypothesis pair into exactly one relationship tag:
- supporting
- weakening
- contradictory
- indeterminate

The classifier uses only the current hypothesis wording and current evidence
text. No domain templates or persisted priors are consulted.
"""

from __future__ import annotations

import re

import yaml

from aiqe_rca.config import settings
from aiqe_rca.models.alignment import AlignmentLabel, AlignmentResult
from aiqe_rca.models.evidence import EvidenceElement
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

_SUPPORTING_PATTERNS = (
    "failure",
    "defect",
    "issue",
    "problem",
    "out of spec",
    "out of control",
    "variation",
    "variable",
    "drift",
    "wear",
    "worn",
    "damage",
    "damaged",
    "contamination",
    "residue",
    "skipped",
    "missing",
    "abnormal",
    "inconsistent",
    "intermittent",
    "high",
    "higher",
    "elevated",
    "spike",
    "drop",
    "fallout",
    "blister",
    "crack",
    "peel",
    "delamination",
    "chatter",
    "vibration",
    "correlation",
    "linked",
    "associated",
)

_WEAKENING_PATTERNS = (
    "possible",
    "possibly",
    "may",
    "might",
    "could",
    "appears",
    "suggests",
    "limited",
    "unclear",
    "mixed",
    "isolated",
    "partial",
    "some lots passed",
    "adjacent lots",
)

_CONTRADICTORY_PATTERNS = (
    "no correlation",
    "no clear correlation",
    "no consistent shift",
    "no shift",
    "no recorded changes",
    "no change",
    "no issue",
    "no defect",
    "no evidence",
    "no abnormality",
    "stable",
    "in control",
    "within limits",
    "normal",
    "acceptable",
    "passed",
    "all lots passed",
    "verified",
    "confirmed",
    "unchanged",
    "consistent",
)

_NEGATION_PREFIXES = (
    "no",
    "not",
    "without",
    "never",
    "none",
)


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
    return re.search(r"\b" + re.escape(_normalize_text(phrase)) + r"\b", _normalize_text(text)) is not None


def _collect_hypothesis_terms(hypothesis: Hypothesis) -> list[str]:
    """Build the current-input term set used to evaluate relevance."""
    terms = set()
    if hypothesis.process_step:
        terms.add(_normalize_text(hypothesis.process_step))
    for keyword in hypothesis.keywords:
        normalized = _normalize_text(keyword)
        if normalized:
            terms.add(normalized)
    ordered = sorted(terms, key=lambda item: (-len(item.split()), -len(item), item))
    return ordered


def _matched_terms(text: str, terms: list[str]) -> list[str]:
    """Return hypothesis terms explicitly present in the evidence text."""
    return [term for term in terms if _contains_phrase(text, term)]


def _term_negated(statement: str, term: str) -> bool:
    """Return True when the matched hypothesis term appears with a nearby negation."""
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
    """Return contradicting patterns specific to this hypothesis's signal group.

    Generic contradictory patterns (e.g., "stable", "within limits") only apply
    when the hypothesis is itself about stability/control. For cause-level
    groups, we rely exclusively on the group's own contradicting_signals so
    that a contradiction for one group never leaks into another.
    """
    groups = _get_signal_groups()
    group = groups.get(hypothesis.template_id or "")
    if group is None:
        return _CONTRADICTORY_PATTERNS
    return tuple(group.get("contradicting_signals", []))


def _score_statement(
    statement: str,
    hypothesis: Hypothesis,
    hypothesis_terms: list[str],
) -> tuple[int, int, int, list[str]]:
    """Score one evidence statement against one hypothesis.

    Returns:
        supporting_score, weakening_score, contradictory_score, matched_phrases
    """
    term_hits = _matched_terms(statement, hypothesis_terms)
    contradicting_patterns = _group_contradicting_patterns(hypothesis)
    contradictory_hits = _count_pattern_hits(statement, contradicting_patterns)

    if not term_hits and not contradictory_hits:
        return 0, 0, 0, []

    supporting_hits = _count_pattern_hits(statement, _SUPPORTING_PATTERNS)
    weakening_hits = _count_pattern_hits(statement, _WEAKENING_PATTERNS)
    negated_terms = [term for term in term_hits if _term_negated(statement, term)]

    supporting_score = len(supporting_hits) if term_hits else 0
    weakening_score = len(weakening_hits) if term_hits else 0
    contradictory_score = len(contradictory_hits) + len(negated_terms)

    # If the statement directly names the hypothesis signal and also references the
    # problem/failure state, treat it as supportive even without a canned pattern.
    if term_hits and supporting_score == 0 and contradictory_score == 0:
        statement_tokens = set(_tokenize(statement))
        if statement_tokens.intersection({"failure", "defect", "issue", "problem", "variation", "fallout"}):
            supporting_score += 1

    matched_phrases = sorted(set(term_hits + supporting_hits + weakening_hits + contradictory_hits + negated_terms))
    return supporting_score, weakening_score, contradictory_score, matched_phrases


def _format_rationale(label: AlignmentLabel, phrases: list[str]) -> str:
    """Build a concise explanation for the assigned relationship."""
    details = ", ".join(phrases[:4]) if phrases else "current evidence wording"
    if label == AlignmentLabel.SUPPORTING:
        return f"Evidence supports this hypothesis through: {details}."
    if label == AlignmentLabel.WEAKENING:
        return f"Evidence weakens this hypothesis through: {details}."
    if label == AlignmentLabel.CONTRADICTING:
        return f"Evidence contradicts this hypothesis through: {details}."
    return "Evidence mentions related context but does not clearly support or refute this hypothesis."


def classify_alignment(
    hypothesis: Hypothesis,
    evidence: EvidenceElement,
) -> AlignmentResult:
    """Classify the evidence-to-hypothesis relationship for one pair."""
    evidence_text = evidence.text_content
    hypothesis_terms = _collect_hypothesis_terms(hypothesis)
    statements = _split_statements(evidence_text)

    total_supporting = 0
    total_weakening = 0
    total_contradictory = 0
    matched_phrases: list[str] = []

    for statement in statements:
        supporting_score, weakening_score, contradictory_score, phrases = _score_statement(
            statement,
            hypothesis,
            hypothesis_terms,
        )
        total_supporting += supporting_score
        total_weakening += weakening_score
        total_contradictory += contradictory_score
        matched_phrases.extend(phrases)

    if not matched_phrases:
        label = AlignmentLabel.INDETERMINATE
    elif total_contradictory > max(total_supporting, total_weakening):
        label = AlignmentLabel.CONTRADICTING
    elif total_supporting > max(total_weakening, total_contradictory):
        label = AlignmentLabel.SUPPORTING
    elif total_weakening > max(total_supporting, total_contradictory):
        label = AlignmentLabel.WEAKENING
    elif total_contradictory > 0:
        label = AlignmentLabel.CONTRADICTING
    elif total_weakening > 0:
        label = AlignmentLabel.WEAKENING
    elif total_supporting > 0:
        label = AlignmentLabel.SUPPORTING
    else:
        label = AlignmentLabel.INDETERMINATE

    return AlignmentResult(
        hypothesis_id=hypothesis.id,
        evidence_id=evidence.id,
        classification=label,
        rationale=_format_rationale(label, sorted(set(matched_phrases))),
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
