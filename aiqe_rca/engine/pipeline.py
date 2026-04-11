"""Pipeline orchestrator — runs the full deterministic analysis flow.

Chains: parse → build hypotheses → associate evidence → classify alignments →
        detect gaps → rank → assess confidence → return AnalysisResult

Same inputs always produce the same output.
"""

from aiqe_rca.engine.alignment_classifier import classify_all_alignments
from aiqe_rca.engine.confidence import assess_confidence
from aiqe_rca.engine.evidence_associator import associate_evidence
from aiqe_rca.engine.gap_detector import detect_gaps
from aiqe_rca.engine.hypothesis_builder import build_hypotheses
from aiqe_rca.engine.ranker import rank_hypotheses
from aiqe_rca.models.evidence import EvidenceElement
from aiqe_rca.models.report import AnalysisResult, ConfidenceLevel, ReportHeader
from aiqe_rca.parser.router import parse_multiple_files


def _extract_header_fields(
    problem_statement: str,
    evidence_elements: list[EvidenceElement],
    confidence: ConfidenceLevel,
) -> ReportHeader:
    """Extract report header fields from inputs.

    Attempts to infer Part/Process, Defect/Symptom, and Date Range from the
    problem statement and evidence. Falls back to standard defaults.
    """
    header = ReportHeader(analysis_confidence=confidence)

    import re

    # Part/Process — extract from evidence (look for "Part:" fields)
    part_pattern = r"(?:Part|Product|Component|Assembly)[:\s]+([^\n;]{5,80})"
    for e in evidence_elements:
        match = re.search(part_pattern, e.text_content, re.IGNORECASE)
        if match:
            header.part_process = match.group(1).strip()
            break

    # Also try problem statement for part references
    if header.part_process == "Not available from current inputs.":
        ps_match = re.search(part_pattern, problem_statement, re.IGNORECASE)
        if ps_match:
            header.part_process = ps_match.group(1).strip()

    # Defect/Symptom — use problem statement first sentence (clean)
    if problem_statement.strip():
        first_sentence = problem_statement.split(".")[0].strip()
        if len(first_sentence) > 150:
            first_sentence = first_sentence[:150] + "..."
        header.defect_symptom = first_sentence

    # Date range — look for date patterns in evidence
    import re

    date_pattern = r"\b\d{4}[-/]\d{1,2}[-/]\d{1,2}\b"
    dates_found: list[str] = []
    for e in evidence_elements:
        matches = re.findall(date_pattern, e.text_content)
        dates_found.extend(matches)
    if len(dates_found) >= 2:
        dates_found.sort()
        header.date_range = f"{dates_found[0]} to {dates_found[-1]}"
    elif len(dates_found) == 1:
        header.date_range = dates_found[0]

    # Also check problem statement for dates
    ps_dates = re.findall(date_pattern, problem_statement)
    if ps_dates and header.date_range == "Not available from current inputs.":
        ps_dates.sort()
        if len(ps_dates) >= 2:
            header.date_range = f"{ps_dates[0]} to {ps_dates[-1]}"
        else:
            header.date_range = ps_dates[0]

    return header


def run_analysis(
    problem_statement: str,
    files: dict[str, bytes],
) -> AnalysisResult:
    """Run the full deterministic RCA pipeline.

    Args:
        problem_statement: User-provided problem description.
        files: Mapping of filename -> file content bytes.

    Returns:
        Complete AnalysisResult ready for report generation.
    """
    # Step 1: Parse all documents into evidence elements
    evidence_elements = parse_multiple_files(files)

    # Step 2: Build candidate hypotheses (2–4, rule-based)
    hypotheses = build_hypotheses(problem_statement, evidence_elements)

    # Step 3: Associate evidence to hypotheses (keyword + embedding)
    hypotheses = associate_evidence(hypotheses, evidence_elements)

    # Step 4: Classify alignment for all associated pairs
    alignments = classify_all_alignments(hypotheses, evidence_elements)

    # Preserve the candidate list before prioritization for reasoning artifacts.
    pre_ranking_hypotheses = [h.model_copy(deep=True) for h in hypotheses]

    # Step 5: Detect data gaps
    gaps = detect_gaps(evidence_elements, hypotheses, alignments)

    # Step 6: Rank hypotheses (Primary / Secondary / Conditional Amplifier)
    hypotheses = rank_hypotheses(hypotheses, alignments, gaps)

    # Step 7: Assess overall confidence (Low / Medium / High)
    confidence = assess_confidence(hypotheses, alignments, gaps)

    # Step 8: Extract header fields
    header = _extract_header_fields(problem_statement, evidence_elements, confidence)

    return AnalysisResult(
        evidence_elements=evidence_elements,
        pre_ranking_hypotheses=pre_ranking_hypotheses,
        hypotheses=hypotheses,
        alignments=alignments,
        gaps=gaps,
        confidence=confidence,
        header=header,
        problem_statement=problem_statement,
    )
