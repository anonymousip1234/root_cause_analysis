"""Hypothesis ranking engine.

Ranks hypotheses as Primary / Secondary / Conditional Amplifier based on
net evidence support and gap severity. Internal scores are never exposed.
Same inputs → same ranking every time.
"""

from aiqe_rca.models.alignment import AlignmentLabel, AlignmentResult
from aiqe_rca.models.gaps import DataGap, GapSeverity
from aiqe_rca.models.hypothesis import Hypothesis, RankLabel


def _count_alignments(
    hypothesis_id: str, alignments: list[AlignmentResult]
) -> tuple[int, int, int]:
    """Count supporting, contradicting, and indeterminate alignments for a hypothesis."""
    supporting = 0
    contradicting = 0
    indeterminate = 0
    for a in alignments:
        if a.hypothesis_id != hypothesis_id:
            continue
        if a.classification == AlignmentLabel.SUPPORTING:
            supporting += 1
        elif a.classification == AlignmentLabel.CONTRADICTING:
            contradicting += 1
        else:
            indeterminate += 1
    return supporting, contradicting, indeterminate


def _compute_gap_severity(hypothesis_id: str, gaps: list[DataGap]) -> int:
    """Compute gap severity score for a hypothesis.

    Each gap that affects this hypothesis contributes:
    - CRITICAL: 3 points
    - MODERATE: 1 point
    - MINOR: 0 points
    """
    severity = 0
    for gap in gaps:
        if hypothesis_id in gap.affects_hypotheses:
            if gap.severity == GapSeverity.CRITICAL:
                severity += 3
            elif gap.severity == GapSeverity.MODERATE:
                severity += 1
    return severity


def rank_hypotheses(
    hypotheses: list[Hypothesis],
    alignments: list[AlignmentResult],
    gaps: list[DataGap],
) -> list[Hypothesis]:
    """Rank hypotheses and assign labels: Primary / Secondary / Conditional Amplifier.

    Logic:
    1. For each hypothesis compute net_support = supporting - contradicting.
    2. Compute gap_severity for each hypothesis.
    3. Compute composite = net_support - gap_severity (internal only).
    4. Sort descending by composite (ties broken by hypothesis ID for determinism).
    5. Assign labels:
       - First hypothesis → Primary Contributor
       - Second → Secondary Contributor
       - Third and fourth → Conditional Amplifier

    Returns:
        Hypotheses sorted and labeled (modified in-place and returned).
    """
    # Compute scores
    for h in hypotheses:
        supporting, contradicting, _ = _count_alignments(h.id, alignments)
        h.net_support = supporting - contradicting
        h.gap_severity = _compute_gap_severity(h.id, gaps)

    # Sort: highest composite first, ties broken by ID
    hypotheses.sort(
        key=lambda h: (-(h.net_support - h.gap_severity), h.id)
    )

    # Assign labels
    for idx, h in enumerate(hypotheses):
        if idx == 0:
            h.rank_label = RankLabel.PRIMARY
        elif idx == 1:
            h.rank_label = RankLabel.SECONDARY
        else:
            h.rank_label = RankLabel.CONDITIONAL_AMPLIFIER

    return hypotheses
