"""Alignment classifier — classifies evidence-hypothesis relationships.

For each (hypothesis, evidence) pair, determines:
- Supporting: evidence is consistent with the hypothesis
- Contradicting: evidence conflicts with the hypothesis
- Indeterminate: evidence is related but unclear

Uses rule-based keyword/phrase analysis. No ML or LLM.
"""

import re

from aiqe_rca.models.alignment import AlignmentLabel, AlignmentResult
from aiqe_rca.models.evidence import EvidenceElement
from aiqe_rca.models.hypothesis import Hypothesis

# Phrases that indicate evidence SUPPORTS a hypothesis when present
SUPPORTING_INDICATORS = [
    "observed",
    "detected",
    "found",
    "reported",
    "noted",
    "showed",
    "indicates",
    "consistent with",
    "out of spec",
    "out of control",
    "failed",
    "defect",
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
    "vibration",
    "wear",
    "open container",
    "expired",
    "missing",
    "absent",
    "not documented",
    "no record",
]

# Phrases that indicate evidence CONTRADICTS a hypothesis
CONTRADICTING_INDICATORS = [
    "in control",
    "within limits",
    "within spec",
    "passed",
    "no change",
    "no shift",
    "stable",
    "compliant",
    "verified",
    "confirmed good",
    "no defect",
    "no issue",
    "normal",
    "acceptable",
    "meets requirement",
    "no correlation",
    "no trend",
    "no variation",
    "matched good lots",
]

# Negation prefixes that flip meaning
NEGATION_PREFIXES = [
    "no ",
    "not ",
    "without ",
    "never ",
    "none ",
    "neither ",
]


def _has_indicator(text: str, indicators: list[str]) -> tuple[bool, str]:
    """Check if text contains any of the indicator phrases.

    Returns (found, matched_phrase).
    """
    text_lower = text.lower()
    for indicator in indicators:
        if indicator.lower() in text_lower:
            return True, indicator
    return False, ""


def _check_negation_context(text: str, phrase: str) -> bool:
    """Check if a phrase appears in a negated context."""
    text_lower = text.lower()
    phrase_lower = phrase.lower()
    idx = text_lower.find(phrase_lower)
    if idx < 0:
        return False
    # Check if any negation prefix appears shortly before the phrase
    prefix_window = text_lower[max(0, idx - 20) : idx]
    for neg in NEGATION_PREFIXES:
        if neg in prefix_window:
            return True
    return False


def _keyword_relevance(evidence_text: str, hypothesis_keywords: list[str]) -> int:
    """Count how many hypothesis keywords appear in the evidence text.

    Uses substring matching (not word-boundary) to catch morphological variants
    like 'cleaning' matching 'cleanliness', 'contamination' matching 'contaminated'.
    """
    text_lower = evidence_text.lower()
    count = 0
    for kw in hypothesis_keywords:
        kw_lower = kw.lower()
        # Try exact word boundary first
        if re.search(r"\b" + re.escape(kw_lower) + r"\b", text_lower):
            count += 1
        # Fallback: check if the keyword stem (first 5+ chars) appears as substring
        elif len(kw_lower) >= 5 and kw_lower[:5] in text_lower:
            count += 1
    return count


def classify_alignment(
    hypothesis: Hypothesis,
    evidence: EvidenceElement,
) -> AlignmentResult:
    """Classify the relationship between a hypothesis and an evidence element.

    Logic:
    1. Check keyword relevance — if evidence has no keywords in common, it's indeterminate.
    2. Check for supporting indicators in evidence text.
    3. Check for contradicting indicators in evidence text.
    4. If supporting indicators found and they relate to hypothesis direction → Supporting.
    5. If contradicting indicators found → Contradicting.
    6. If both or neither → Indeterminate.
    """
    text = evidence.text_content

    # Step 1: Check if evidence is even relevant to this hypothesis
    relevance = _keyword_relevance(text, hypothesis.keywords)
    if relevance == 0:
        return AlignmentResult(
            hypothesis_id=hypothesis.id,
            evidence_id=evidence.id,
            classification=AlignmentLabel.INDETERMINATE,
            rationale="Evidence does not contain keywords related to this hypothesis.",
        )

    # Step 2: Check for supporting indicators
    has_support, support_phrase = _has_indicator(text, SUPPORTING_INDICATORS)
    support_negated = _check_negation_context(text, support_phrase) if has_support else False

    # Step 3: Check for contradicting indicators
    has_contradict, contradict_phrase = _has_indicator(text, CONTRADICTING_INDICATORS)
    contradict_negated = _check_negation_context(text, contradict_phrase) if has_contradict else False

    # Flip if negated
    effective_support = (has_support and not support_negated) or (has_contradict and contradict_negated)
    effective_contradict = (has_contradict and not contradict_negated) or (has_support and support_negated)

    # Step 4: Classify
    if effective_support and not effective_contradict:
        return AlignmentResult(
            hypothesis_id=hypothesis.id,
            evidence_id=evidence.id,
            classification=AlignmentLabel.SUPPORTING,
            rationale=f"Evidence contains supporting indicator: '{support_phrase}' relevant to hypothesis keywords.",
        )
    elif effective_contradict and not effective_support:
        return AlignmentResult(
            hypothesis_id=hypothesis.id,
            evidence_id=evidence.id,
            classification=AlignmentLabel.CONTRADICTING,
            rationale=f"Evidence contains contradicting indicator: '{contradict_phrase}' suggesting conditions counter to hypothesis.",
        )
    else:
        # Both or neither
        rationale = "Evidence is related but contains mixed or unclear signals."
        if effective_support and effective_contradict:
            rationale = (
                f"Evidence contains both supporting ('{support_phrase}') and "
                f"contradicting ('{contradict_phrase}') signals."
            )
        return AlignmentResult(
            hypothesis_id=hypothesis.id,
            evidence_id=evidence.id,
            classification=AlignmentLabel.INDETERMINATE,
            rationale=rationale,
        )


def classify_all_alignments(
    hypotheses: list[Hypothesis],
    evidence_elements: list[EvidenceElement],
) -> list[AlignmentResult]:
    """Classify alignment for all associated (hypothesis, evidence) pairs.

    Only classifies pairs where the evidence is associated with the hypothesis.

    Returns:
        List of AlignmentResult objects.
    """
    results: list[AlignmentResult] = []
    evidence_map = {e.id: e for e in evidence_elements}

    for hypothesis in hypotheses:
        for evidence_id in hypothesis.associated_evidence_ids:
            evidence = evidence_map.get(evidence_id)
            if evidence is None:
                continue
            result = classify_alignment(hypothesis, evidence)
            results.append(result)

    return results
