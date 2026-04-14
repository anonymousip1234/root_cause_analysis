"""Integration coverage for the Phase-2 deterministic RCA pipeline.

Tests enforce the AIQE Hypothesis Abstraction Guide:
    - Hypotheses are cause-level groupings, not extracted terms.
    - Language is diagnostic, never definitive.
    - Contradicted / false-lead candidates are explicitly deprioritized.
"""

from __future__ import annotations

import json

from aiqe_rca.audit.hasher import compute_input_hash
from aiqe_rca.engine.pipeline import run_analysis
from aiqe_rca.models.alignment import AlignmentLabel
from aiqe_rca.models.hypothesis import RankLabel
from aiqe_rca.models.report import ConfidenceLevel
from aiqe_rca.report.generator import generate_report
from aiqe_rca.report.language_lint import lint_report
from aiqe_rca.report.renderer import render_json

PROBLEM_STATEMENT = (
    "Intermittent chatter marks on finished shafts. "
    "Spindle speed stayed stable while coolant flow varied between lots."
)

TEST_FILES = {
    "observations_01.txt": (
        b"Coolant flow was inconsistent between failing lots and passing lots. "
        b"Chatter marks increased during low-flow periods. "
        b"Spindle speed remained within limits."
    ),
    "observations_02.txt": (
        b"No tool wear was observed during inspection. "
        b"Feed rate showed no recorded changes. "
        b"Surface finish worsened when coolant delivery fluctuated."
    ),
}

# Diagnostic phrasing required by the Hypothesis Abstraction Guide.
_DIAGNOSTIC_PHRASES = (
    "could be driven by",
    "may indicate",
    "is consistent with",
    "may be explained by",
    "may be contributing",
    "may be influencing",
    "could affect",
    "may allow",
)

# Raw extracted terms the guide forbids as standalone hypothesis names.
_FORBIDDEN_RAW_TERMS = {
    "vibration",
    "chatter",
    "chatter marks",
    "surface",
    "coolant",
    "coolant flow",
    "adhesive",
    "blistering",
    "measurement",
    "potential failure",
    "spindle speed",
    "tool wear",
}


def _run_report():
    result = run_analysis(PROBLEM_STATEMENT, TEST_FILES)
    input_hash = compute_input_hash(PROBLEM_STATEMENT, TEST_FILES)
    report = generate_report(result, input_hash, "2026-04-11T00:00:00Z")
    payload = json.loads(render_json(report))
    return result, report, payload


def test_pipeline_produces_result():
    result, _, _ = _run_report()

    assert len(result.evidence_elements) > 0
    assert 2 <= len(result.hypotheses) <= 4
    assert len(result.alignments) > 0


def test_hypotheses_are_cause_level_not_extracted_terms():
    """Each hypothesis must be a cause-level grouping, not a raw term."""
    result, _, _ = _run_report()

    for hypothesis in result.hypotheses:
        name = (hypothesis.process_step or "").strip().lower()
        # Not a bare forbidden term
        assert name not in _FORBIDDEN_RAW_TERMS, (
            f"Hypothesis '{name}' is a raw extracted term; must be cause-level."
        )
        # Must use diagnostic phrasing somewhere in the name
        assert any(phrase in name for phrase in _DIAGNOSTIC_PHRASES), (
            f"Hypothesis '{name}' does not use diagnostic language."
        )
        # Must be grouped (multi-word explanation, not a single token)
        assert len(name.split()) >= 5, f"Hypothesis '{name}' is too short to be cause-level."


def test_hypotheses_signals_are_traceable_to_input():
    """Every hypothesis must be grounded in current-input signal tokens."""
    result, _, _ = _run_report()

    current_input = (
        PROBLEM_STATEMENT + " " + " ".join(content.decode("utf-8") for content in TEST_FILES.values())
    ).lower()
    for hypothesis in result.pre_ranking_hypotheses + result.hypotheses:
        assert hypothesis.keywords, f"Hypothesis {hypothesis.id} has no signal keywords."
        assert any(keyword.lower() in current_input for keyword in hypothesis.keywords), (
            f"None of hypothesis {hypothesis.id}'s signals appear in the current input."
        )


def test_primary_is_cause_level_and_non_contradicted():
    """Primary hypothesis must be the best-supported cause-level grouping."""
    result, _, payload = _run_report()

    primary = result.hypotheses[0]
    assert primary.rank_label == RankLabel.PRIMARY
    assert "coolant instability" in (primary.process_step or "").lower()

    primary_tags = [
        row["tag"]
        for row in payload["reasoning_artifact"]["evidence_classification_table"]
        if row["hypothesis"] == primary.process_step
    ]
    assert AlignmentLabel.CONTRADICTING.value not in primary_tags


def test_false_leads_are_explicitly_contradicted_or_deprioritized():
    """Machining instability (tool wear / spindle / feed rate) must be deprioritized."""
    result, _, payload = _run_report()

    machining = next(
        (
            hypothesis
            for hypothesis in result.hypotheses
            if (hypothesis.template_id or "") == "SG_MACHINING_INSTABILITY"
        ),
        None,
    )
    assert machining is not None, "Machining instability grouping should be surfaced as a false lead."
    assert machining.rank_label == RankLabel.DEPRIORITIZED

    machining_tags = {
        row["tag"]
        for row in payload["reasoning_artifact"]["evidence_classification_table"]
        if row["hypothesis"] == machining.process_step
    }
    assert AlignmentLabel.CONTRADICTING.value in machining_tags


def test_reasoning_artifact_package_is_complete_and_separate():
    _, _, payload = _run_report()

    assert "reasoning_artifact" in payload
    assert "reasoning_artifact" not in payload["analysis"]
    assert len(payload["reasoning_artifact"]["pre_ranking_hypotheses"]) >= 2
    assert len(payload["reasoning_artifact"]["evidence_classification_table"]) > 0
    assert len(payload["reasoning_artifact"]["contradiction_log"]) >= 1
    assert len(payload["reasoning_artifact"]["prioritization_summary"]) >= 2
    assert payload["reasoning_artifact"]["stateless_confirmation"] == (
        "This run used only current input. No prior context reused."
    )


def test_evidence_relationship_tags_cover_required_phase2_labels():
    _, _, payload = _run_report()

    tags = {row["tag"] for row in payload["reasoning_artifact"]["evidence_classification_table"]}
    assert AlignmentLabel.SUPPORTING.value in tags
    assert AlignmentLabel.CONTRADICTING.value in tags
    assert tags.issubset(
        {
            AlignmentLabel.SUPPORTING.value,
            AlignmentLabel.WEAKENING.value,
            AlignmentLabel.CONTRADICTING.value,
            AlignmentLabel.INDETERMINATE.value,
        }
    )


def test_confidence_is_medium_for_indirect_but_directional_case():
    result, report, payload = _run_report()

    assert result.confidence == ConfidenceLevel.MEDIUM
    assert payload["analysis"]["confidence"] == ConfidenceLevel.MEDIUM.value
    assert "Confidence is Medium" in report.sections[4].content


def test_report_has_5_sections_and_clean_language():
    _, report, _ = _run_report()

    assert len(report.sections) == 5
    lint_input = [(section.title, section.content) for section in report.sections]
    lint_result = lint_report(lint_input)
    assert lint_result.passed


def test_report_language_is_diagnostic_not_definitive():
    """Generated report text must avoid definitive causal phrasing."""
    _, report, _ = _run_report()

    body = "\n".join(section.content.lower() for section in report.sections)
    for forbidden in ("is causing", "is due to", "is caused by", "root cause is"):
        assert forbidden not in body, f"Forbidden definitive phrase found: {forbidden}"


def test_deterministic_output_across_runs():
    first_result, first_report, first_payload = _run_report()
    second_result, second_report, second_payload = _run_report()

    assert [h.process_step for h in first_result.hypotheses] == [
        h.process_step for h in second_result.hypotheses
    ]
    assert [section.content for section in first_report.sections] == [
        section.content for section in second_report.sections
    ]
    assert first_payload["reasoning_artifact"] == second_payload["reasoning_artifact"]


def test_stateless_metadata_and_trace_map_are_present():
    _, report, payload = _run_report()

    assert payload["analysis"]["stateless_execution"]["isolated_per_request"] is True
    assert payload["analysis"]["stateless_execution"]["shared_request_context"] is False
    assert payload["analysis"]["stateless_execution"]["confirmation"] == (
        "This run used only current input. No prior context reused."
    )
    assert "observations_01.txt" in report.evidence_trace_map
