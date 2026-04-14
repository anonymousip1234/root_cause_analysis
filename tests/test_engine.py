"""Tests for the deterministic, input-driven RCA engine."""

from __future__ import annotations

import pytest

from aiqe_rca.engine.alignment_classifier import classify_alignment
from aiqe_rca.engine.confidence import assess_confidence
from aiqe_rca.engine.evidence_associator import associate_evidence
from aiqe_rca.engine.gap_detector import detect_gaps
from aiqe_rca.engine.hypothesis_builder import build_hypotheses
from aiqe_rca.engine.ranker import rank_hypotheses
from aiqe_rca.models.alignment import AlignmentLabel, AlignmentResult
from aiqe_rca.models.evidence import EvidenceCategory, EvidenceElement, SourceType
from aiqe_rca.models.gaps import DataGap, GapSeverity
from aiqe_rca.models.hypothesis import Hypothesis, RankLabel
from aiqe_rca.models.report import ConfidenceLevel


def _make_evidence(eid: str, text: str, source: str = "test_doc.txt") -> EvidenceElement:
    return EvidenceElement(
        id=eid,
        source=source,
        source_type=SourceType.TXT,
        text_content=text,
    )


def _make_hypothesis(hid: str, process_step: str, keywords: list[str]) -> Hypothesis:
    return Hypothesis(
        id=hid,
        description=f"Current input repeatedly references {process_step}.",
        process_step=process_step,
        keywords=keywords,
    )


def test_hypothesis_builder_returns_2_to_4():
    problem = "Intermittent chatter marks with coolant flow variation and stable spindle speed."
    evidence = [
        _make_evidence("E1", "Coolant flow was inconsistent across failing lots."),
        _make_evidence("E2", "Chatter marks increased during low-flow periods."),
        _make_evidence("E3", "Spindle speed remained within limits."),
    ]

    hypotheses = build_hypotheses(problem, evidence)

    assert 2 <= len(hypotheses) <= 4
    # Hypotheses must be grouped into signal-group templates, not promoted
    # directly from extracted terms.
    assert all(h.template_id for h in hypotheses)
    assert any("coolant instability" in (h.process_step or "") for h in hypotheses)


def test_hypothesis_builder_deterministic():
    problem = "Coolant flow variation and chatter marks on shafts."
    evidence = [_make_evidence("E1", "Coolant flow was inconsistent during the event.")]

    runs = [build_hypotheses(problem, evidence) for _ in range(3)]
    labels = [[(h.id, h.process_step) for h in run] for run in runs]

    assert all(run == labels[0] for run in labels)


def test_hypothesis_builder_uses_current_input_signals_only():
    """Each hypothesis must be grounded in signals that appear in current input."""
    problem = "Tool wear and chatter marks were observed."
    evidence = [_make_evidence("E1", "Coolant flow was steady but tool wear was visible.")]

    hypotheses = build_hypotheses(problem, evidence)
    current_input = f"{problem} {' '.join(item.text_content for item in evidence)}".lower()

    for hypothesis in hypotheses:
        assert hypothesis.keywords, f"{hypothesis.id} has no signal keywords"
        # At least one signal member must appear in the current input.
        assert any(keyword.lower() in current_input for keyword in hypothesis.keywords), (
            f"{hypothesis.id} has no signals traceable to current input"
        )


def test_classify_supporting():
    hypothesis = _make_hypothesis(
        "H1",
        "coolant flow",
        ["coolant", "flow", "coolant flow"],
    )
    evidence = _make_evidence("E1", "Coolant flow was inconsistent during failing lots.")

    result = classify_alignment(hypothesis, evidence)

    assert result.classification == AlignmentLabel.SUPPORTING


def test_classify_contradicting():
    hypothesis = _make_hypothesis(
        "H1",
        "spindle speed",
        ["spindle", "speed", "spindle speed"],
    )
    evidence = _make_evidence("E2", "Spindle speed remained within limits with no recorded changes.")

    result = classify_alignment(hypothesis, evidence)

    assert result.classification == AlignmentLabel.CONTRADICTING


def test_classify_weakening():
    hypothesis = _make_hypothesis(
        "H1",
        "tool wear",
        ["tool", "wear", "tool wear"],
    )
    evidence = _make_evidence("E3", "Tool wear is possible, but current evidence is limited and unclear.")

    result = classify_alignment(hypothesis, evidence)

    assert result.classification == AlignmentLabel.WEAKENING


def test_classify_indeterminate_no_matching_terms():
    hypothesis = _make_hypothesis(
        "H1",
        "coolant flow",
        ["coolant", "flow", "coolant flow"],
    )
    evidence = _make_evidence("E4", "Operator training records were reviewed last month.")

    result = classify_alignment(hypothesis, evidence)

    assert result.classification == AlignmentLabel.INDETERMINATE


def test_ranker_assigns_primary_secondary_and_deprioritized():
    h1 = _make_hypothesis("H1", "coolant flow", ["coolant", "flow"])
    h2 = _make_hypothesis("H2", "chatter marks", ["chatter", "marks"])
    h3 = _make_hypothesis("H3", "spindle speed", ["spindle", "speed"])

    alignments = [
        AlignmentResult(hypothesis_id="H1", evidence_id="E1", classification=AlignmentLabel.SUPPORTING, rationale="test"),
        AlignmentResult(hypothesis_id="H1", evidence_id="E2", classification=AlignmentLabel.SUPPORTING, rationale="test"),
        AlignmentResult(hypothesis_id="H2", evidence_id="E3", classification=AlignmentLabel.SUPPORTING, rationale="test"),
        AlignmentResult(hypothesis_id="H3", evidence_id="E4", classification=AlignmentLabel.CONTRADICTING, rationale="test"),
    ]

    ranked = rank_hypotheses([h1, h2, h3], alignments, [])

    assert ranked[0].rank_label == RankLabel.PRIMARY
    assert ranked[0].id == "H1"
    assert ranked[1].rank_label == RankLabel.SECONDARY
    assert ranked[2].rank_label == RankLabel.DEPRIORITIZED


def test_ranker_prevents_contradicted_primary_when_non_contradicted_exists():
    h1 = _make_hypothesis("H1", "spindle speed", ["spindle", "speed"])
    h2 = _make_hypothesis("H2", "coolant flow", ["coolant", "flow"])

    alignments = [
        AlignmentResult(hypothesis_id="H1", evidence_id="E1", classification=AlignmentLabel.CONTRADICTING, rationale="test"),
        AlignmentResult(hypothesis_id="H2", evidence_id="E2", classification=AlignmentLabel.SUPPORTING, rationale="test"),
    ]

    ranked = rank_hypotheses([h1, h2], alignments, [])

    assert ranked[0].id == "H2"
    assert ranked[0].rank_label == RankLabel.PRIMARY


def test_confidence_low_when_no_evidence():
    assert assess_confidence([], [], []) == ConfidenceLevel.LOW


def test_confidence_medium_when_primary_supported_but_gaps_present():
    hypothesis = _make_hypothesis("H1", "coolant flow", ["coolant", "flow"])
    hypothesis.rank_label = RankLabel.PRIMARY
    alignments = [
        AlignmentResult(hypothesis_id="H1", evidence_id="E1", classification=AlignmentLabel.SUPPORTING, rationale="test"),
        AlignmentResult(hypothesis_id="H1", evidence_id="E2", classification=AlignmentLabel.SUPPORTING, rationale="test"),
    ]
    gaps = [
        DataGap(
            category=EvidenceCategory.UNCATEGORIZED,
            description="Quantitative confirmation for 'coolant flow' is missing.",
            severity=GapSeverity.MODERATE,
            affects_hypotheses=["H1"],
        )
    ]

    assert assess_confidence([hypothesis], alignments, gaps) == ConfidenceLevel.MEDIUM


def test_associate_evidence_falls_back_without_embeddings(monkeypatch):
    hypothesis = _make_hypothesis(
        "H1",
        "coolant flow",
        ["coolant", "flow", "coolant flow"],
    )
    evidence = _make_evidence(
        "E1",
        "Coolant flow was inconsistent during the defect event.",
    )

    monkeypatch.setattr(
        "aiqe_rca.engine.evidence_associator.EmbeddingModel.encode",
        lambda texts: (_ for _ in ()).throw(RuntimeError("offline")),
    )

    updated = associate_evidence([hypothesis], [evidence])
    assert updated[0].associated_evidence_ids == ["E1"]


def test_gap_detector_flags_missing_direct_support_and_cross_source_confirmation():
    hypothesis = _make_hypothesis("H1", "spindle speed", ["spindle", "speed"])
    hypothesis.associated_evidence_ids = ["E1"]
    evidence = [_make_evidence("E1", "Spindle speed remained within limits.", source="one_source.txt")]
    alignments = [
        AlignmentResult(
            hypothesis_id="H1",
            evidence_id="E1",
            classification=AlignmentLabel.CONTRADICTING,
            rationale="test",
        )
    ]

    gaps = detect_gaps(evidence, [hypothesis], alignments)
    descriptions = [gap.description for gap in gaps]

    assert any("No direct supporting evidence confirms" in description for description in descriptions)
    assert any("Cross-source corroboration" in description for description in descriptions)


def test_gap_detector_adds_global_single_source_gap():
    evidence = [_make_evidence("E1", "Coolant flow was inconsistent.", source="one_source.txt")]
    hypothesis = _make_hypothesis("H1", "coolant flow", ["coolant", "flow"])
    hypothesis.associated_evidence_ids = ["E1"]
    alignments = [
        AlignmentResult(
            hypothesis_id="H1",
            evidence_id="E1",
            classification=AlignmentLabel.SUPPORTING,
            rationale="test",
        )
    ]

    gaps = detect_gaps(evidence, [hypothesis], alignments)

    assert any(
        gap.description == "Cross-source corroboration is limited because the current input package contains only one source."
        for gap in gaps
    )
