"""Alignment classifier — classifies evidence-hypothesis relationships.

For each (hypothesis, evidence) pair, determines:
- Supporting: evidence is consistent with the hypothesis
- Weakening: evidence softens confidence in the hypothesis without fully ruling it out
- Contradicting: evidence directly conflicts with the hypothesis
- Indeterminate: evidence is related but unclear

Uses deterministic keyword, phrase, and template-specific pattern analysis.
"""

import re

import yaml

from aiqe_rca.config import settings
from aiqe_rca.models.alignment import AlignmentLabel, AlignmentResult
from aiqe_rca.models.evidence import EvidenceElement
from aiqe_rca.models.hypothesis import Hypothesis

SUPPORTING_INDICATORS = [
    "consistent with",
    "out of spec",
    "out of control",
    "non-conformance",
    "skipping",
    "skipped",
    "not followed",
    "violation",
    "exceeded",
    "above limit",
    "below limit",
    "higher defect rate",
    "higher failure rate",
    "blistering",
    "cracking",
    "peeling",
    "delamination",
    "residue",
    "contamination",
    "open container",
    "expired",
    "missing",
    "absent",
]

WEAKENING_INDICATORS = [
    "some lots passed",
    "adjacent lots",
]

CONTRADICTING_INDICATORS = [
    "verified",
    "confirmed good",
    "all lots passed",
    "no defect",
    "no issue",
    "normal",
    "acceptable",
    "meets requirement",
]

NEGATION_PREFIXES = [
    "no ",
    "not ",
    "without ",
    "never ",
    "none ",
    "neither ",
]


def _load_template_map() -> dict[str, dict]:
    """Load template metadata for template-specific evidence patterns."""
    templates_path = settings.rules_dir / "domain_templates.yaml"
    with open(templates_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return {template["id"]: template for template in data.get("templates", [])}


_TEMPLATE_MAP = _load_template_map()


def _has_indicator(text: str, indicators: list[str]) -> tuple[int, list[str]]:
    """Return count and the matched indicator phrases."""
    text_lower = text.lower()
    matches: list[str] = []
    for indicator in indicators:
        if indicator.lower() in text_lower:
            matches.append(indicator)
    return len(matches), matches


def _check_negation_context(text: str, phrase: str) -> bool:
    """Check if a phrase appears in a negated context."""
    text_lower = text.lower()
    phrase_lower = phrase.lower()
    idx = text_lower.find(phrase_lower)
    if idx < 0:
        return False
    prefix_window = text_lower[max(0, idx - 20) : idx]
    return any(neg in prefix_window for neg in NEGATION_PREFIXES)


def _keyword_relevance(evidence_text: str, hypothesis_keywords: list[str]) -> int:
    """Count how many hypothesis keywords appear in the evidence text."""
    text_lower = evidence_text.lower()
    count = 0
    for kw in hypothesis_keywords:
        kw_lower = kw.lower()
        if re.search(r"\b" + re.escape(kw_lower) + r"\b", text_lower):
            count += 1
        elif len(kw_lower) >= 5 and kw_lower[:5] in text_lower:
            count += 1
    return count


def _template_patterns(hypothesis: Hypothesis) -> tuple[list[str], list[str], list[str]]:
    """Get template-specific support, weakening, and contradiction patterns."""
    template = _TEMPLATE_MAP.get(hypothesis.template_id or "", {})
    return (
        template.get("support_indicators", []),
        template.get("weakening_indicators", []),
        template.get("contradicting_indicators", []),
    )


def _format_rationale(label: AlignmentLabel, phrases: list[str]) -> str:
    """Build a concise rationale for the assigned relationship label."""
    joined = ", ".join(sorted(set(phrases[:3]))) if phrases else "related evidence"
    if label == AlignmentLabel.SUPPORTING:
        return f"Evidence supports this hypothesis via: {joined}."
    if label == AlignmentLabel.WEAKENING:
        return f"Evidence weakens this hypothesis via: {joined}."
    if label == AlignmentLabel.CONTRADICTING:
        return f"Evidence contradicts this hypothesis via: {joined}."
    return "Evidence is related but contains mixed or unclear signals."


def classify_alignment(
    hypothesis: Hypothesis,
    evidence: EvidenceElement,
) -> AlignmentResult:
    """Classify the relationship between a hypothesis and an evidence element."""
    text = evidence.text_content

    relevance = _keyword_relevance(text, hypothesis.keywords)
    support_patterns, weakening_patterns, contradiction_patterns = _template_patterns(
        hypothesis
    )

    pattern_relevance = sum(
        1
        for phrase in support_patterns + weakening_patterns + contradiction_patterns
        if phrase.lower() in text.lower()
    )
    if relevance == 0 and pattern_relevance == 0:
        return AlignmentResult(
            hypothesis_id=hypothesis.id,
            evidence_id=evidence.id,
            classification=AlignmentLabel.INDETERMINATE,
            rationale="Evidence does not contain hypothesis-specific cues.",
        )

    generic_support_count, generic_support_matches = _has_indicator(text, SUPPORTING_INDICATORS)
    template_support_count, template_support_matches = _has_indicator(text, support_patterns)
    support_count = generic_support_count + template_support_count
    support_matches = generic_support_matches + template_support_matches
    weakening_count, weakening_matches = _has_indicator(
        text, WEAKENING_INDICATORS + weakening_patterns
    )
    contradiction_count, contradiction_matches = _has_indicator(
        text, CONTRADICTING_INDICATORS + contradiction_patterns
    )

    # Negated support phrases become weakening signals.
    for phrase in list(support_matches):
        if _check_negation_context(text, phrase):
            support_count -= 1
            weakening_count += 1
            weakening_matches.append(f"negated {phrase}")

    if contradiction_count > 0 and support_count == 0:
        label = AlignmentLabel.CONTRADICTING
        rationale_matches = contradiction_matches
    elif weakening_count > 0 and support_count == 0 and contradiction_count == 0:
        label = AlignmentLabel.WEAKENING
        rationale_matches = weakening_matches
    elif support_count > 0 and contradiction_count == 0 and weakening_count == 0:
        label = AlignmentLabel.SUPPORTING
        rationale_matches = support_matches
    elif support_count > 0 and (weakening_count > 0 or contradiction_count > 0):
        if template_support_count > 0 and template_support_count >= (weakening_count + contradiction_count):
            label = AlignmentLabel.SUPPORTING
            rationale_matches = support_matches + weakening_matches + contradiction_matches
        elif weakening_count >= support_count and template_support_count == 0:
            label = AlignmentLabel.WEAKENING
            rationale_matches = weakening_matches + support_matches
        elif contradiction_count > support_count:
            label = AlignmentLabel.CONTRADICTING
            rationale_matches = contradiction_matches + support_matches
        elif weakening_count > support_count:
            label = AlignmentLabel.WEAKENING
            rationale_matches = weakening_matches + support_matches
        else:
            label = AlignmentLabel.INDETERMINATE
            rationale_matches = support_matches + weakening_matches + contradiction_matches
    elif weakening_count > 0 and contradiction_count > 0:
        label = AlignmentLabel.INDETERMINATE
        rationale_matches = weakening_matches + contradiction_matches
    else:
        label = AlignmentLabel.INDETERMINATE
        rationale_matches = []

    return AlignmentResult(
        hypothesis_id=hypothesis.id,
        evidence_id=evidence.id,
        classification=label,
        rationale=_format_rationale(label, rationale_matches),
    )


def classify_all_alignments(
    hypotheses: list[Hypothesis],
    evidence_elements: list[EvidenceElement],
) -> list[AlignmentResult]:
    """Classify alignment for all associated (hypothesis, evidence) pairs."""
    results: list[AlignmentResult] = []
    evidence_map = {e.id: e for e in evidence_elements}

    for hypothesis in hypotheses:
        for evidence_id in hypothesis.associated_evidence_ids:
            evidence = evidence_map.get(evidence_id)
            if evidence is None:
                continue
            results.append(classify_alignment(hypothesis, evidence))

    return results
