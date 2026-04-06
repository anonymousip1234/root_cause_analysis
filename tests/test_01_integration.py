"""Test Case 01 — Integration test using the actual Lab Test Report.

Validates the full pipeline: parse → hypotheses → evidence association →
alignment → gaps → ranking → confidence → report generation.

Uses Test01_LabTestReport.docx as input.
"""

import os
import json
from pathlib import Path

import pytest

from aiqe_rca.audit.hasher import compute_input_hash
from aiqe_rca.engine.pipeline import run_analysis
from aiqe_rca.models.hypothesis import RankLabel
from aiqe_rca.models.report import ConfidenceLevel
from aiqe_rca.report.generator import generate_report
from aiqe_rca.report.language_lint import lint_report
from aiqe_rca.report.renderer import render_json

DOCS_DIR = Path(__file__).parent.parent / "docs"
LAB_REPORT_PATH = DOCS_DIR / "Test01_LabTestReport.docx"
PFMEA_PATH = DOCS_DIR / "Test01_PFMEA.pdf"

PROBLEM_STATEMENT = (
    "Intermittent rubber-to-metal bond failures at final inspection on one product family. "
    "Failures occur mostly on Line 2, 2nd shift, with no recorded changes to cure time or "
    "cure temperature. Visual inspection shows blistering near the edge of the bonded area."
)


@pytest.fixture
def test01_files():
    """Load Test01 input files."""
    files = {}
    if LAB_REPORT_PATH.exists():
        files["Test01_LabTestReport.docx"] = LAB_REPORT_PATH.read_bytes()
    if PFMEA_PATH.exists():
        files["Test01_PFMEA.pdf"] = PFMEA_PATH.read_bytes()
    return files


@pytest.mark.skipif(
    not LAB_REPORT_PATH.exists(),
    reason="Test01_LabTestReport.docx not found in docs/",
)
class TestCase01:
    """Test Case 01 — Contradictory Evidence (rubber-to-metal bond)."""

    def test_pipeline_produces_result(self, test01_files):
        """Pipeline runs without error and returns AnalysisResult."""
        result = run_analysis(PROBLEM_STATEMENT, test01_files)
        assert result is not None
        assert len(result.evidence_elements) > 0
        assert len(result.hypotheses) >= 2
        assert len(result.hypotheses) <= 4

    def test_hypotheses_are_ranked(self, test01_files):
        """All hypotheses have valid rank labels."""
        result = run_analysis(PROBLEM_STATEMENT, test01_files)
        labels = [h.rank_label for h in result.hypotheses]
        assert RankLabel.PRIMARY in labels
        assert RankLabel.UNRANKED not in labels

    def test_alignments_exist(self, test01_files):
        """At least some evidence is classified as supporting or contradicting."""
        result = run_analysis(PROBLEM_STATEMENT, test01_files)
        assert len(result.alignments) > 0

    def test_confidence_is_qualitative(self, test01_files):
        """Confidence is Low, Medium, or High — never a number."""
        result = run_analysis(PROBLEM_STATEMENT, test01_files)
        assert result.confidence in (
            ConfidenceLevel.LOW,
            ConfidenceLevel.MEDIUM,
            ConfidenceLevel.HIGH,
        )

    def test_test01_matches_canonical_ranking(self, test01_files):
        """Canonical Test 1 should favor upstream surface condition over cure/equipment."""
        result = run_analysis(PROBLEM_STATEMENT, test01_files)

        assert result.hypotheses[0].template_id == "TMPL_SURFACE_PREP"
        assert result.hypotheses[1].template_id == "TMPL_DESIGN_GEOMETRY"
        assert any(
            h.template_id == "TMPL_MATERIAL_HANDLING"
            and h.rank_label == RankLabel.CONDITIONAL_AMPLIFIER
            for h in result.hypotheses
        )
        assert any(
            h.template_id == "TMPL_PROCESS_PARAM"
            and h.rank_label == RankLabel.DEPRIORITIZED
            for h in result.hypotheses
        )
        assert result.confidence == ConfidenceLevel.MEDIUM

    def test_test01_explicitly_weaken_false_leads(self, test01_files):
        """Cure and press/tool explanations should be explicitly weakened."""
        result = run_analysis(PROBLEM_STATEMENT, test01_files)
        report = generate_report(
            result,
            compute_input_hash(PROBLEM_STATEMENT, test01_files),
            "2025-01-01T00:00:00Z",
        )

        relationships = getattr(report, "_template_data", {}).get("relationship_entries", [])
        process_contradicted = any(
            item["template_id"] == "TMPL_PROCESS_PARAM" and item["relationship"] == "contradicting"
            for item in relationships
        )
        assert process_contradicted
        assert "equipment-only explanation" in report.sections[0].content
        assert "[contradictory] Equipment / Press-Tool Variation:" in report.sections[2].content
        assert "[contradictory] Process Parameter Variation:" in report.sections[2].content

    def test_test01_report_contains_relationship_tags_and_gaps(self, test01_files):
        """Diagnostic evidence section must carry explicit tags and confidence-limiting gaps."""
        result = run_analysis(PROBLEM_STATEMENT, test01_files)
        report = generate_report(
            result,
            compute_input_hash(PROBLEM_STATEMENT, test01_files),
            "2025-01-01T00:00:00Z",
        )
        diagnostic = report.sections[2].content
        assert "[supporting]" in diagnostic
        assert "[contradictory]" in diagnostic
        assert "[gap]" in diagnostic
        assert "Adhesive handling variability" in diagnostic
        assert "Storage / staging conditions" in diagnostic
        assert "Environmental humidity exposure" in diagnostic
        assert "Adhesive coverage verification" in diagnostic

    def test_reasoning_artifact_package_is_complete(self, test01_files):
        """Reasoning artifact package should expose the full canonical audit trail."""
        result = run_analysis(PROBLEM_STATEMENT, test01_files)
        report = generate_report(
            result,
            compute_input_hash(PROBLEM_STATEMENT, test01_files),
            "2025-01-01T00:00:00Z",
        )
        payload = json.loads(render_json(report))
        artifacts = payload["analysis"]["reasoning_artifacts"]

        assert len(artifacts["pre_ranking_hypotheses"]) >= 2
        assert len(artifacts["evidence_classification_table"]) > 0
        assert len(artifacts["contradiction_log"]) >= 2
        assert len(artifacts["gap_log"]) >= 4
        assert len(artifacts["prioritization_summary"]) >= 4
        assert "isolated and deterministic" in artifacts["stateless_note"]

    def test_report_has_5_sections(self, test01_files):
        """Generated report has exactly 5 sections."""
        result = run_analysis(PROBLEM_STATEMENT, test01_files)
        input_hash = compute_input_hash(PROBLEM_STATEMENT, test01_files)
        report = generate_report(result, input_hash, "2025-01-01T00:00:00Z")
        assert len(report.sections) == 5
        titles = [s.title for s in report.sections]
        assert "Executive Diagnostic Summary" in titles
        assert "Most Likely Root Cause Hypotheses" in titles
        assert "Diagnostic Evidence" in titles
        assert "Recommended Testing / Validation" in titles
        assert "Analysis Confidence Statement" in titles

    def test_report_no_disallowed_language(self, test01_files):
        """Language lint passes on the generated report."""
        result = run_analysis(PROBLEM_STATEMENT, test01_files)
        input_hash = compute_input_hash(PROBLEM_STATEMENT, test01_files)
        report = generate_report(result, input_hash, "2025-01-01T00:00:00Z")
        lint_input = [(s.title, s.content) for s in report.sections]
        lint_result = lint_report(lint_input)
        # Report generator sanitizes violations, so this should pass
        # But if any slip through, flag them
        if not lint_result.passed:
            violation_terms = [v["term"] for v in lint_result.violations]
            pytest.fail(f"Language lint violations: {violation_terms}")

    def test_determinism(self, test01_files):
        """Same inputs produce identical outputs across multiple runs."""
        results = []
        for _ in range(3):
            result = run_analysis(PROBLEM_STATEMENT, test01_files)
            input_hash = compute_input_hash(PROBLEM_STATEMENT, test01_files)
            report = generate_report(result, input_hash, "2025-01-01T00:00:00Z")
            results.append(report)

        # Compare section content across runs
        for i in range(1, len(results)):
            for j, section in enumerate(results[i].sections):
                assert section.content == results[0].sections[j].content, (
                    f"Non-deterministic output in section '{section.title}' "
                    f"between run 0 and run {i}"
                )

    def test_input_hash_deterministic(self, test01_files):
        """Input hash is identical for identical inputs."""
        hash1 = compute_input_hash(PROBLEM_STATEMENT, test01_files)
        hash2 = compute_input_hash(PROBLEM_STATEMENT, test01_files)
        assert hash1 == hash2

    def test_evidence_trace_map_populated(self, test01_files):
        """Report includes an evidence trace map linking sources to evidence."""
        result = run_analysis(PROBLEM_STATEMENT, test01_files)
        input_hash = compute_input_hash(PROBLEM_STATEMENT, test01_files)
        report = generate_report(result, input_hash, "2025-01-01T00:00:00Z")
        assert len(report.evidence_trace_map) > 0
        assert "Test01_LabTestReport.docx" in report.evidence_trace_map

    def test_report_json_includes_stateless_metadata(self, test01_files):
        """Machine-readable JSON should expose explicit stateless execution metadata."""
        result = run_analysis(PROBLEM_STATEMENT, test01_files)
        input_hash = compute_input_hash(PROBLEM_STATEMENT, test01_files)
        report = generate_report(result, input_hash, "2025-01-01T00:00:00Z")
        payload = json.loads(render_json(report))
        assert payload["analysis"]["stateless_execution"]["isolated_per_request"] is True
        assert payload["analysis"]["stateless_execution"]["shared_request_context"] is False
