"""Contradiction-aware hypothesis ranking."""

from __future__ import annotations

from aiqe_rca.models.alignment import AlignmentLabel, AlignmentResult
from aiqe_rca.models.gaps import DataGap, GapSeverity
from aiqe_rca.models.hypothesis import Hypothesis, RankLabel


def _count_alignments(
    hypothesis_id: str,
    alignments: list[AlignmentResult],
) -> tuple[int, int, int, int]:
    """Return supporting, weakening, contradictory, and indeterminate counts."""
    supporting = 0
    weakening = 0
    contradictory = 0
    indeterminate = 0

    for alignment in alignments:
        if alignment.hypothesis_id != hypothesis_id:
            continue
        if alignment.classification == AlignmentLabel.SUPPORTING:
            supporting += 1
        elif alignment.classification == AlignmentLabel.WEAKENING:
            weakening += 1
        elif alignment.classification == AlignmentLabel.CONTRADICTING:
            contradictory += 1
        else:
            indeterminate += 1

    return supporting, weakening, contradictory, indeterminate


def _compute_gap_severity(hypothesis_id: str, gaps: list[DataGap]) -> int:
    """Compute a deterministic penalty score from affected data gaps."""
    severity = 0
    for gap in gaps:
        if hypothesis_id not in gap.affects_hypotheses:
            continue
        if gap.severity == GapSeverity.CRITICAL:
            severity += 2
        elif gap.severity == GapSeverity.MODERATE:
            severity += 1
    return severity


def _score_hypothesis(
    supporting: int,
    weakening: int,
    contradictory: int,
    gap_penalty: int,
) -> int:
    """Apply the Phase-2 contradiction-aware scoring rule."""
    return (supporting * 2) - weakening - (contradictory * 3) - gap_penalty


def rank_hypotheses(
    hypotheses: list[Hypothesis],
    alignments: list[AlignmentResult],
    gaps: list[DataGap],
) -> list[Hypothesis]:
    """Rank hypotheses using support, contradiction, and gap penalties.

    Primary ranking rule:
    - score = support*2 - weakening - contradiction*3 - gap_penalty
    - a contradicted hypothesis cannot be Primary if a non-contradicted alternative exists
      with an equal or better ranking position
    """
    counts_by_hypothesis: dict[str, tuple[int, int, int, int]] = {}
    for hypothesis in hypotheses:
        supporting, weakening, contradictory, indeterminate = _count_alignments(
            hypothesis.id,
            alignments,
        )
        counts_by_hypothesis[hypothesis.id] = (
            supporting,
            weakening,
            contradictory,
            indeterminate,
        )
        hypothesis.gap_severity = _compute_gap_severity(hypothesis.id, gaps)
        hypothesis.net_support = _score_hypothesis(
            supporting,
            weakening,
            contradictory,
            hypothesis.gap_severity,
        )

    ranked = sorted(
        hypotheses,
        key=lambda hypothesis: (
            -hypothesis.net_support,
            counts_by_hypothesis[hypothesis.id][2],
            counts_by_hypothesis[hypothesis.id][1],
            hypothesis.id,
        ),
    )

    non_contradicted = [
        hypothesis
        for hypothesis in ranked
        if counts_by_hypothesis[hypothesis.id][2] == 0
    ]
    if non_contradicted:
        primary = non_contradicted[0]
        remaining = [hypothesis for hypothesis in ranked if hypothesis.id != primary.id]
        ranked = [primary] + remaining

    secondary_assigned = False
    for index, hypothesis in enumerate(ranked):
        supporting, weakening, contradictory, _ = counts_by_hypothesis[hypothesis.id]
        if index == 0:
            hypothesis.rank_label = RankLabel.PRIMARY
            continue
        is_false_lead = (
            contradictory > 0
            or hypothesis.net_support < 0
            or weakening >= max(supporting, 1)
        )
        if is_false_lead:
            hypothesis.rank_label = RankLabel.DEPRIORITIZED
            continue
        if not secondary_assigned:
            hypothesis.rank_label = RankLabel.SECONDARY
            secondary_assigned = True
        else:
            hypothesis.rank_label = RankLabel.CONDITIONAL_AMPLIFIER

    hypotheses[:] = ranked
    return hypotheses
