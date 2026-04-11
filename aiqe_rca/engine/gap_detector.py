"""Input-driven data gap detection.

Gaps are derived from the current evidence package and the current candidate
hypotheses only. No domain templates or prior-run expectations are used.
"""

from __future__ import annotations

import re

from aiqe_rca.models.alignment import AlignmentLabel, AlignmentResult
from aiqe_rca.models.evidence import EvidenceCategory, EvidenceElement
from aiqe_rca.models.gaps import DataGap, GapSeverity
from aiqe_rca.models.hypothesis import Hypothesis

_QUANT_PATTERNS = (
    "%",
    "ppm",
    "cpk",
    "sigma",
    "trend",
    "chart",
    "spc",
    "sample",
    "count",
    "rate",
    "within limits",
)

_COMPARISON_PATTERNS = (
    "pass",
    "fail",
    "passing",
    "failing",
    "before",
    "after",
    "versus",
    "compared",
    "shift",
    "lot",
    "batch",
    "press",
    "tool",
)


def _normalize_text(text: str) -> str:
    """Normalize free text for deterministic matching."""
    return re.sub(r"\s+", " ", text.lower()).strip()


def _contains_any(text: str, patterns: tuple[str, ...]) -> bool:
    """Return True if any pattern appears in the text."""
    normalized = _normalize_text(text)
    for pattern in patterns:
        if pattern in {"%"}:
            if pattern in normalized:
                return True
            continue
        if re.search(r"\b" + re.escape(pattern) + r"\b", normalized):
            return True
    return False


def _dominant_category(evidence: list[EvidenceElement]) -> EvidenceCategory:
    """Return the most common evidence category for a hypothesis."""
    if not evidence:
        return EvidenceCategory.UNCATEGORIZED

    counts: dict[EvidenceCategory, int] = {}
    for item in evidence:
        counts[item.category] = counts.get(item.category, 0) + 1

    return sorted(
        counts.items(),
        key=lambda item: (-item[1], item[0].value),
    )[0][0]


def _add_gap(
    gaps: list[DataGap],
    category: EvidenceCategory,
    description: str,
    severity: GapSeverity,
    affects_hypotheses: list[str],
) -> None:
    """Append a unique gap only once."""
    if any(
        gap.description == description and gap.affects_hypotheses == affects_hypotheses
        for gap in gaps
    ):
        return
    gaps.append(
        DataGap(
            category=category,
            description=description,
            severity=severity,
            affects_hypotheses=affects_hypotheses,
        )
    )


def detect_gaps(
    evidence_elements: list[EvidenceElement],
    hypotheses: list[Hypothesis] | None = None,
    alignments: list[AlignmentResult] | None = None,
) -> list[DataGap]:
    """Detect confidence-limiting gaps from the current input package."""
    gaps: list[DataGap] = []
    hypotheses = hypotheses or []
    alignments = alignments or []

    all_hypothesis_ids = [hypothesis.id for hypothesis in hypotheses]
    source_count = len({evidence.source for evidence in evidence_elements})
    if evidence_elements and source_count <= 1 and all_hypothesis_ids:
        _add_gap(
            gaps,
            EvidenceCategory.UNCATEGORIZED,
            "Cross-source corroboration is limited because the current input package contains only one source.",
            GapSeverity.MODERATE,
            all_hypothesis_ids,
        )

    alignment_map: dict[str, list[AlignmentResult]] = {}
    for alignment in alignments:
        alignment_map.setdefault(alignment.hypothesis_id, []).append(alignment)

    evidence_map = {evidence.id: evidence for evidence in evidence_elements}

    for hypothesis in hypotheses:
        associated_evidence = [
            evidence_map[evidence_id]
            for evidence_id in hypothesis.associated_evidence_ids
            if evidence_id in evidence_map
        ]
        affected = [hypothesis.id]
        category = _dominant_category(associated_evidence)
        process_name = hypothesis.process_step or hypothesis.id

        if not associated_evidence:
            _add_gap(
                gaps,
                EvidenceCategory.UNCATEGORIZED,
                f"No extracted evidence was associated with '{process_name}'.",
                GapSeverity.CRITICAL,
                affected,
            )
            continue

        supporting_count = sum(
            1
            for alignment in alignment_map.get(hypothesis.id, [])
            if alignment.classification == AlignmentLabel.SUPPORTING
        )

        distinct_sources = sorted({evidence.source for evidence in associated_evidence})
        if supporting_count == 0:
            _add_gap(
                gaps,
                category,
                f"No direct supporting evidence confirms '{process_name}'; the current signal remains indirect.",
                GapSeverity.CRITICAL,
                affected,
            )

        if len(distinct_sources) == 1:
            _add_gap(
                gaps,
                category,
                f"Cross-source corroboration for '{process_name}' is limited to a single source.",
                GapSeverity.MODERATE,
                affected,
            )

        if not any(_contains_any(evidence.text_content, _QUANT_PATTERNS) for evidence in associated_evidence):
            _add_gap(
                gaps,
                category,
                f"Quantitative or measured confirmation for '{process_name}' is missing from the current input.",
                GapSeverity.MODERATE,
                affected,
            )

        if not any(_contains_any(evidence.text_content, _COMPARISON_PATTERNS) for evidence in associated_evidence):
            _add_gap(
                gaps,
                category,
                f"Pass/fail or condition-to-condition comparison for '{process_name}' is not explicit in the current input.",
                GapSeverity.MINOR,
                affected,
            )

    return gaps
