"""Confidence assessment engine.

Assigns qualitative confidence level (Low / Medium / High) to the overall analysis.
No percentages, no scores exposed — purely qualitative.
"""

from aiqe_rca.models.alignment import AlignmentLabel, AlignmentResult
from aiqe_rca.models.gaps import DataGap, GapSeverity
from aiqe_rca.models.hypothesis import Hypothesis
from aiqe_rca.models.report import ConfidenceLevel


def assess_confidence(
    hypotheses: list[Hypothesis],
    alignments: list[AlignmentResult],
    gaps: list[DataGap],
) -> ConfidenceLevel:
    """Assess overall analysis confidence.

    Factors:
    1. Evidence coverage — total evidence count and association breadth.
    2. Contradiction ratio — high contradictions reduce confidence.
    3. Gap severity — many or critical gaps reduce confidence.
    4. Primary hypothesis strength — strong primary = higher confidence.

    Returns:
        ConfidenceLevel (Low / Medium / High).
    """
    if not hypotheses or not alignments:
        return ConfidenceLevel.LOW

    # Factor 1: Evidence breadth
    total_evidence = len({a.evidence_id for a in alignments})
    evidence_score = min(total_evidence / 10.0, 1.0)  # Cap at 10 pieces

    # Factor 2: Contradiction ratio
    supporting = sum(1 for a in alignments if a.classification == AlignmentLabel.SUPPORTING)
    contradicting = sum(1 for a in alignments if a.classification == AlignmentLabel.CONTRADICTING)
    total_classified = supporting + contradicting
    if total_classified > 0:
        contradiction_ratio = contradicting / total_classified
    else:
        contradiction_ratio = 0.5  # No data → moderate uncertainty

    # Factor 3: Gap severity
    critical_gaps = sum(1 for g in gaps if g.severity == GapSeverity.CRITICAL)
    moderate_gaps = sum(1 for g in gaps if g.severity == GapSeverity.MODERATE)
    gap_penalty = critical_gaps * 0.3 + moderate_gaps * 0.1

    # Factor 4: Primary hypothesis net support
    primary = next((h for h in hypotheses if h.rank_label.value == "Primary Contributor"), None)
    primary_strength = 0.0
    if primary and primary.net_support > 0:
        primary_strength = min(primary.net_support / 5.0, 1.0)

    # Composite (internal only, never exposed)
    composite = (
        evidence_score * 0.25
        + (1.0 - contradiction_ratio) * 0.30
        + primary_strength * 0.30
        - gap_penalty * 0.15
    )

    # Map to qualitative level
    if composite >= 0.55:
        return ConfidenceLevel.HIGH
    elif composite >= 0.30:
        return ConfidenceLevel.MEDIUM
    else:
        return ConfidenceLevel.LOW
