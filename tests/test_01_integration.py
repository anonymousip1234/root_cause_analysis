"""Test Case 01 — Integration test using the actual Lab Test Report.

Validates the full pipeline: parse → hypotheses → evidence association →
alignment → gaps → ranking → confidence → report generation.

Uses Test01_LabTestReport.docx as input.
"""

import os
from pathlib import Path

import pytest

from aiqe_rca.audit.hasher import compute_input_hash
from aiqe_rca.engine.pipeline import run_analysis
from aiqe_rca.models.hypothesis import RankLabel
from aiqe_rca.models.report import ConfidenceLevel
from aiqe_rca.report.generator import generate_report
from aiqe_rca.report.language_lint import lint_report

DOCS_DIR = Path(__file__).parent.parent / "docs"
LAB_REPORT_PATH = DOCS_DIR / "Test01_LabTestReport.docx"

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
