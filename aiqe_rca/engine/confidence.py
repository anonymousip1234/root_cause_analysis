"""Deterministic confidence assessment."""

from __future__ import annotations

from aiqe_rca.models.alignment import AlignmentLabel, AlignmentResult
from aiqe_rca.models.gaps import DataGap, GapSeverity
from aiqe_rca.models.hypothesis import Hypothesis, RankLabel
from aiqe_rca.models.report import ConfidenceLevel


def assess_confidence(
    hypotheses: list[Hypothesis],
    alignments: list[AlignmentResult],
    gaps: list[DataGap],
) -> ConfidenceLevel:
    """Assign Low, Medium, or High confidence from current-run evidence only."""
    if not hypotheses or not alignments:
        return ConfidenceLevel.LOW

    primary = next((hypothesis for hypothesis in hypotheses if hypothesis.rank_label == RankLabel.PRIMARY), None)
    if primary is None:
        return ConfidenceLevel.LOW

    primary_alignments = [
        alignment for alignment in alignments if alignment.hypothesis_id == primary.id
    ]
    primary_support = sum(
        1 for alignment in primary_alignments if alignment.classification == AlignmentLabel.SUPPORTING
    )
    primary_weakening = sum(
        1 for alignment in primary_alignments if alignment.classification == AlignmentLabel.WEAKENING
    )
    primary_contradictions = sum(
        1 for alignment in primary_alignments if alignment.classification == AlignmentLabel.CONTRADICTING
    )
    critical_gaps = sum(1 for gap in gaps if gap.severity == GapSeverity.CRITICAL)
    moderate_gaps = sum(1 for gap in gaps if gap.severity == GapSeverity.MODERATE)

    if primary_support == 0 or primary_contradictions > 0 or critical_gaps >= 2:
        return ConfidenceLevel.LOW

    if (
        primary_support >= 3
        and primary_weakening == 0
        and primary_contradictions == 0
        and critical_gaps == 0
        and moderate_gaps == 0
    ):
        return ConfidenceLevel.HIGH

    return ConfidenceLevel.MEDIUM
