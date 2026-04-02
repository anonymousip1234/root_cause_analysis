"""Tests for the core deterministic engine."""

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


def _make_evidence(eid: str, text: str) -> EvidenceElement:
    return EvidenceElement(
        id=eid,
        source="test_doc.pdf",
        source_type=SourceType.PDF,
        text_content=text,
    )


# --- Hypothesis Builder Tests ---

def test_hypothesis_builder_returns_2_to_4():
    problem = "Intermittent bond failures with blistering near edges on Line 2"
    evidence = [
        _make_evidence("E1", "SPC data shows cure temperature is in control"),
        _make_evidence("E2", "Operators skipping manual wipe step on busy shifts"),
        _make_evidence("E3", "Adhesive containers found open past exposure time"),
    ]
    hypotheses = build_hypotheses(problem, evidence)
    assert 2 <= len(hypotheses) <= 4


def test_hypothesis_builder_deterministic():
    problem = "Bond failures with surface contamination and blistering"
    evidence = [
        _make_evidence("E1", "Surface cleaning not performed consistently"),
    ]
    runs = [build_hypotheses(problem, evidence) for _ in range(3)]
    ids = [[h.id for h in run] for run in runs]
    assert all(i == ids[0] for i in ids)


def test_hypothesis_builder_matches_surface_template():
    problem = "Surface contamination before bonding causing adhesion failure"
    evidence = [
        _make_evidence("E1", "Residue found on parts after cleaning step"),
    ]
    hypotheses = build_hypotheses(problem, evidence)
    template_ids = [h.template_id for h in hypotheses]
    assert "TMPL_SURFACE_PREP" in template_ids


# --- Alignment Classifier Tests ---

def test_classify_supporting():
    h = Hypothesis(
        id="H1",
        description="Surface contamination",
        keywords=["contamination", "cleaning", "residue"],
    )
    e = _make_evidence("E1", "Visible residue detected on parts before bonding")
    result = classify_alignment(h, e)
    assert result.classification == AlignmentLabel.SUPPORTING


def test_classify_contradicting():
    h = Hypothesis(
        id="H1",
        description="Surface contamination",
        keywords=["contamination", "cleaning", "residue"],
    )
    e = _make_evidence("E2", "All lots passed cleanliness inspection within limits")
    result = classify_alignment(h, e)
    assert result.classification == AlignmentLabel.CONTRADICTING


def test_classify_weakening():
    h = Hypothesis(
        id="H1",
        description="Process parameter variation",
        template_id="TMPL_PROCESS_PARAM",
        keywords=["cure", "temperature", "cure time", "cure temperature", "stable process parameters"],
    )
    e = _make_evidence("E2", "SPC data for cure temperature and cure time remain in control with no process shifts detected")
    result = classify_alignment(h, e)
    assert result.classification == AlignmentLabel.WEAKENING


def test_classify_indeterminate_no_keywords():
    h = Hypothesis(
        id="H1",
        description="Surface contamination",
        keywords=["contamination", "cleaning", "residue"],
    )
    e = _make_evidence("E3", "Oven temperature was recorded at 180 degrees")
    result = classify_alignment(h, e)
    assert result.classification == AlignmentLabel.INDETERMINATE


# --- Ranker Tests ---

def test_ranker_assigns_labels():
    h1 = Hypothesis(id="H1", description="Hypothesis A", keywords=[])
    h2 = Hypothesis(id="H2", description="Hypothesis B", keywords=[])
    h3 = Hypothesis(id="H3", description="Hypothesis C", keywords=[])

    alignments = [
        AlignmentResult(hypothesis_id="H1", evidence_id="E1", classification=AlignmentLabel.SUPPORTING, rationale="test"),
        AlignmentResult(hypothesis_id="H1", evidence_id="E2", classification=AlignmentLabel.SUPPORTING, rationale="test"),
        AlignmentResult(hypothesis_id="H2", evidence_id="E3", classification=AlignmentLabel.SUPPORTING, rationale="test"),
        AlignmentResult(hypothesis_id="H2", evidence_id="E4", classification=AlignmentLabel.CONTRADICTING, rationale="test"),
        AlignmentResult(hypothesis_id="H3", evidence_id="E5", classification=AlignmentLabel.INDETERMINATE, rationale="test"),
    ]

    ranked = rank_hypotheses([h1, h2, h3], alignments, [])
    assert ranked[0].rank_label == RankLabel.PRIMARY
    assert ranked[0].id == "H1"  # Highest net support
    assert ranked[1].rank_label == RankLabel.SECONDARY
    assert ranked[2].rank_label == RankLabel.CONDITIONAL_AMPLIFIER


def test_ranker_deterministic():
    h1 = Hypothesis(id="H1", description="A", keywords=[])
    h2 = Hypothesis(id="H2", description="B", keywords=[])
    alignments = [
        AlignmentResult(hypothesis_id="H1", evidence_id="E1", classification=AlignmentLabel.SUPPORTING, rationale="t"),
    ]
    for _ in range(5):
        result = rank_hypotheses([h1.model_copy(), h2.model_copy()], alignments, [])
        assert result[0].id == "H1"


# --- Confidence Tests ---

def test_confidence_low_when_no_evidence():
    assert assess_confidence([], [], []) == ConfidenceLevel.LOW


def test_confidence_with_gaps_reduces():
    h1 = Hypothesis(id="H1", description="Test", keywords=[], rank_label=RankLabel.PRIMARY, net_support=2)
    alignments = [
        AlignmentResult(hypothesis_id="H1", evidence_id="E1", classification=AlignmentLabel.SUPPORTING, rationale="t"),
        AlignmentResult(hypothesis_id="H1", evidence_id="E2", classification=AlignmentLabel.SUPPORTING, rationale="t"),
    ]
    gaps = [
        DataGap(category=EvidenceCategory.DESIGN_REQUIREMENTS, description="No DFMEA", severity=GapSeverity.CRITICAL, affects_hypotheses=["H1"]),
        DataGap(category=EvidenceCategory.PROCESS_CONTROL, description="No control plan", severity=GapSeverity.CRITICAL, affects_hypotheses=["H1"]),
        DataGap(category=EvidenceCategory.PERFORMANCE_VARIATION, description="No SPC", severity=GapSeverity.CRITICAL, affects_hypotheses=["H1"]),
    ]
    result = assess_confidence([h1], alignments, gaps)
    # With 3 critical gaps, confidence should be reduced
    assert result in (ConfidenceLevel.LOW, ConfidenceLevel.MEDIUM)


def test_associate_evidence_falls_back_without_embeddings(monkeypatch):
    hypothesis = Hypothesis(
        id="H1",
        description="Surface contamination before bonding",
        template_id="TMPL_SURFACE_PREP",
        process_step="Upstream Surface / Adhesive Condition Variation",
        keywords=["surface", "contamination", "manual wipe", "adhesive"],
    )
    evidence = _make_evidence(
        "E1",
        "Operators were observed skipping the manual wipe step before adhesive bonding.",
    )

    monkeypatch.setattr(
        "aiqe_rca.engine.evidence_associator.EmbeddingModel.encode",
        lambda texts: (_ for _ in ()).throw(RuntimeError("offline")),
    )

    updated = associate_evidence([hypothesis], [evidence])
    assert updated[0].associated_evidence_ids == ["E1"]


# --- Gap Detector Tests ---

def test_gap_detector_finds_missing_categories():
    # Evidence that only covers detection/audit
    evidence = [
        _make_evidence("E1", "Audit report shows inspection findings and non-conformance detected"),
    ]
    gaps = detect_gaps(evidence)
    # Should find gaps in categories with no coverage
    gap_categories = [g.category for g in gaps]
    # At minimum, RC (Response/Corrective) should be flagged as missing
    assert any(g.severity == GapSeverity.CRITICAL for g in gaps)
