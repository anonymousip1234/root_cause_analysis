"""Confidence assessment engine.

Assigns qualitative confidence level (Low / Medium / High) to the overall analysis.
Confidence is reduced when the leading explanation is indirect, when strong gaps remain,
or when material weakening/contradictory signals are present.
"""

from aiqe_rca.models.alignment import AlignmentLabel, AlignmentResult
from aiqe_rca.models.gaps import DataGap, GapSeverity
from aiqe_rca.models.hypothesis import Hypothesis, RankLabel
from aiqe_rca.models.report import ConfidenceLevel


def assess_confidence(
    hypotheses: list[Hypothesis],
    alignments: list[AlignmentResult],
    gaps: list[DataGap],
) -> ConfidenceLevel:
    """Assess overall analysis confidence using deterministic qualitative rules."""
    if not hypotheses or not alignments:
        return ConfidenceLevel.LOW

    primary = next((h for h in hypotheses if h.rank_label == RankLabel.PRIMARY), None)
    if primary is None:
        return ConfidenceLevel.LOW

    primary_alignments = [a for a in alignments if a.hypothesis_id == primary.id]
    primary_support = sum(
        1 for a in primary_alignments if a.classification == AlignmentLabel.SUPPORTING
    )
    primary_weakening = sum(
        1 for a in primary_alignments if a.classification == AlignmentLabel.WEAKENING
    )
    contradictions = sum(
        1 for a in alignments if a.classification == AlignmentLabel.CONTRADICTING
    )
    critical_gaps = sum(1 for g in gaps if g.severity == GapSeverity.CRITICAL)
    moderate_gaps = sum(1 for g in gaps if g.severity == GapSeverity.MODERATE)

    contextual_gap_terms = (
        "handling variability",
        "storage / staging",
        "humidity",
        "coverage verification",
        "visual only",
    )
    contextual_gaps = sum(
        1
        for g in gaps
        if any(term in g.description.lower() for term in contextual_gap_terms)
    )

    if primary_support == 0 or critical_gaps >= 3 or contradictions >= 3:
        return ConfidenceLevel.LOW

    if (
        primary_support >= 3
        and primary_weakening == 0
        and contradictions == 0
        and critical_gaps == 0
        and moderate_gaps <= 1
        and contextual_gaps == 0
    ):
        return ConfidenceLevel.HIGH

    return ConfidenceLevel.MEDIUM
