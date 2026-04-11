"""Integration coverage for the Phase-2 deterministic RCA pipeline."""

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


def test_hypotheses_are_ranked_and_traceable():
    result, _, _ = _run_report()

    assert result.hypotheses[0].rank_label == RankLabel.PRIMARY
    assert all(hypothesis.rank_label != RankLabel.UNRANKED for hypothesis in result.hypotheses)

    current_input = (
        PROBLEM_STATEMENT + " " + " ".join(content.decode("utf-8") for content in TEST_FILES.values())
    ).lower()
    for hypothesis in result.pre_ranking_hypotheses:
        assert hypothesis.process_step
        assert any(token in current_input for token in hypothesis.process_step.split())


def test_primary_hypothesis_is_input_driven_and_non_contradicted():
    result, _, payload = _run_report()

    primary = result.hypotheses[0]
    primary_tags = [
        row["tag"]
        for row in payload["reasoning_artifact"]["evidence_classification_table"]
        if row["hypothesis"] == primary.process_step
    ]

    assert "coolant" in (primary.process_step or "")
    assert AlignmentLabel.CONTRADICTING.value not in primary_tags


def test_false_leads_are_explicitly_contradicted_or_deprioritized():
    result, _, payload = _run_report()

    spindle = next(
        (hypothesis for hypothesis in result.hypotheses if hypothesis.process_step == "spindle speed"),
        None,
    )

    assert spindle is not None
    assert spindle.rank_label == RankLabel.DEPRIORITIZED
    assert any(
        entry["hypothesis"] == "spindle speed"
        for entry in payload["reasoning_artifact"]["contradiction_log"]
    )


def test_reasoning_artifact_package_is_complete_and_separate():
    _, _, payload = _run_report()

    assert "reasoning_artifact" in payload
    assert "reasoning_artifact" not in payload["analysis"]
    assert len(payload["reasoning_artifact"]["pre_ranking_hypotheses"]) >= 2
    assert len(payload["reasoning_artifact"]["evidence_classification_table"]) > 0
    assert len(payload["reasoning_artifact"]["contradiction_log"]) >= 1
    assert len(payload["reasoning_artifact"]["gap_log"]) >= 1
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
