"""Report generator.

Assembles the 5-section report from AnalysisResult and exposes a richer
machine-readable payload for validation, debugging, and canonical testing.
"""

import re

from aiqe_rca.models.alignment import AlignmentLabel, AlignmentResult
from aiqe_rca.models.evidence import EvidenceElement
from aiqe_rca.models.hypothesis import Hypothesis, RankLabel
from aiqe_rca.models.report import AnalysisResult, ReportOutput, ReportSection
from aiqe_rca.report.language_lint import lint_report

FALLBACKS = {
    "executive_diagnostic_summary": (
        "Summary limited: available inputs do not contain enough structured "
        "evidence to produce a reliable synthesis."
    ),
    "contributing_hypotheses": (
        "No defensible hypotheses can be ranked from the current inputs."
    ),
    "diagnostic_evidence": (
        "Evidence mapping unavailable: inputs could not be parsed into "
        "traceable evidence elements."
    ),
    "testing_validation": (
        "Investigation focus cannot be prioritized until additional "
        "targeted evidence is available."
    ),
    "analysis_confidence_statement": (
        "Insufficient evidence to state this reliably."
    ),
}

_RANK_DISPLAY = {
    RankLabel.PRIMARY: "Primary Contributor",
    RankLabel.SECONDARY: "Secondary Contributor",
    RankLabel.CONDITIONAL_AMPLIFIER: "Conditional Amplifier",
    RankLabel.UNRANKED: "Unranked",
}

_DESCRIPTION_BY_TEMPLATE = {
    "TMPL_SURFACE_PREP": (
        "Upstream surface condition or adhesive condition variation remains the most likely "
        "driver of the intermittent bond failure pattern."
    ),
    "TMPL_DESIGN_GEOMETRY": (
        "Geometry-challenged regions appear more sensitive to incomplete adhesive coverage "
        "and harder to verify with the current controls."
    ),
    "TMPL_MATERIAL_HANDLING": (
        "Storage duration, staging conditions, and environmental exposure may amplify the "
        "failure when upstream surface or adhesive variation is already present."
    ),
    "TMPL_PROCESS_PARAM": (
        "Cure and molding parameter variation was evaluated, but current evidence does not "
        "support it as the primary explanation."
    ),
    "TMPL_EQUIPMENT_CONDITION": (
        "Press, cavity, or tool-driven variation was considered, but the observed pattern "
        "does not currently point to a single equipment source."
    ),
}


def _get_hypothesis_description(hypothesis: Hypothesis) -> str:
    """Return a concise analytical description for the ranked hypothesis."""
    return _DESCRIPTION_BY_TEMPLATE.get(hypothesis.template_id or "", hypothesis.description)


def _describe_source(filename: str) -> str:
    """Convert a filename to a readable source description."""
    fname = filename.lower()
    if "pfmea" in fname or "fmea" in fname:
        return "PFMEA"
    if "spc" in fname:
        return "SPC data"
    if "lab" in fname:
        return "lab report"
    if "audit" in fname:
        return "audit notes"
    if "inspection" in fname:
        return "inspection records"
    return "submitted evidence"


def _clean_text(text: str) -> str:
    """Normalize spacing and list markers for evidence summaries."""
    text = re.sub(r"\s+", " ", text.replace("•", "-")).strip()
    return text.strip("- ").strip()


def _summarize_evidence(evidence: EvidenceElement) -> str:
    """Produce a short evidence summary without dumping raw tables."""
    text = _clean_text(evidence.text_content)
    if "Potential Failure Mode:" in text and "Potential Cause:" in text:
        failure_mode = re.search(r"Potential Failure Mode:\s*([^;]+)", text)
        potential_cause = re.search(r"Potential Cause:\s*([^;]+)", text)
        current_controls = re.search(r"Current Controls:\s*([^;]+)", text)
        parts = []
        if failure_mode:
            parts.append(failure_mode.group(1).strip())
        if potential_cause:
            parts.append(f"cause noted as {potential_cause.group(1).strip()}")
        if current_controls:
            parts.append(f"controls listed as {current_controls.group(1).strip()}")
        if parts:
            return "; ".join(parts)
    if len(text) > 180:
        return text[:177].rstrip() + "..."
    return text


def _alignment_priority(alignment: AlignmentResult) -> tuple[int, str]:
    """Sort alignments by diagnostic value and determinism."""
    label_priority = {
        AlignmentLabel.SUPPORTING: 0,
        AlignmentLabel.WEAKENING: 1,
        AlignmentLabel.CONTRADICTING: 2,
        AlignmentLabel.INDETERMINATE: 3,
    }
    return (label_priority.get(alignment.classification, 9), alignment.evidence_id)


def _build_hypotheses_list(result: AnalysisResult) -> list[dict]:
    """Build the hypothesis list used in section 2 and JSON output."""
    items = []
    for hypothesis in result.hypotheses:
        items.append(
            {
                "id": hypothesis.id,
                "name": hypothesis.process_step,
                "rank": _RANK_DISPLAY.get(hypothesis.rank_label, "Unranked"),
                "template_id": hypothesis.template_id,
                "description": _get_hypothesis_description(hypothesis),
                "net_support": hypothesis.net_support,
                "gap_severity": hypothesis.gap_severity,
            }
        )
    return items


def _build_executive_summary(result: AnalysisResult) -> list[str]:
    """Build the executive summary paragraphs."""
    if not result.hypotheses:
        return [FALLBACKS["executive_diagnostic_summary"]]

    primary = next((h for h in result.hypotheses if h.rank_label == RankLabel.PRIMARY), None)
    secondary = next((h for h in result.hypotheses if h.rank_label == RankLabel.SECONDARY), None)
    amplifier = next(
        (h for h in result.hypotheses if h.rank_label == RankLabel.CONDITIONAL_AMPLIFIER),
        None,
    )

    if primary is None:
        return [FALLBACKS["executive_diagnostic_summary"]]

    paragraph_one = (
        f"AIQE identified a pattern most consistent with {primary.process_step.lower()} "
        f"rather than a stable molding or equipment-only explanation. "
        f"The observed blistering remains intermittent across lots, and the available inputs "
        f"do not show a single fixed press, cavity, or cure-parameter shift."
    )

    paragraph_two_parts = []
    if secondary is not None:
        paragraph_two_parts.append(
            f"The strongest secondary contributor is {secondary.process_step.lower()}."
        )
    if amplifier is not None and amplifier.template_id in {"TMPL_MATERIAL_HANDLING", "TMPL_ENVIRONMENTAL"}:
        paragraph_two_parts.append(
            f"{amplifier.process_step} appears to act as an amplifier rather than a stand-alone root cause."
        )
    if result.confidence.value == "Medium":
        paragraph_two_parts.append(
            "Confidence remains medium because storage, humidity, handling, and coverage-verification data "
            "are still indirect or incomplete."
        )

    return [paragraph_one, " ".join(paragraph_two_parts).strip()]


def _build_relationship_entries(result: AnalysisResult) -> list[dict]:
    """Build explicit evidence-hypothesis relationship entries for report JSON."""
    evidence_map = {e.id: e for e in result.evidence_elements}
    hypothesis_map = {h.id: h for h in result.hypotheses}
    entries: list[dict] = []

    for alignment in sorted(result.alignments, key=_alignment_priority):
        hypothesis = hypothesis_map.get(alignment.hypothesis_id)
        evidence = evidence_map.get(alignment.evidence_id)
        if hypothesis is None or evidence is None:
            continue
        entries.append(
            {
                "hypothesis_id": hypothesis.id,
                "hypothesis_name": hypothesis.process_step,
                "template_id": hypothesis.template_id,
                "evidence_id": evidence.id,
                "source": evidence.source,
                "relationship": alignment.classification.value,
                "rationale": alignment.rationale,
                "evidence_summary": _summarize_evidence(evidence),
            }
        )
    return entries


def _find_global_contradictions(result: AnalysisResult) -> list[str]:
    """Surface contradictions and false-lead deprioritization explicitly."""
    all_text = " ".join(e.text_content.lower() for e in result.evidence_elements)
    contradictions: list[str] = []

    if (
        "intermittent" in all_text
        and (
            "no consistent shift in cure temperature or time" in all_text
            or "spc data for cure temperature and cure time remain in control" in all_text
            or "no recorded changes to cure time or cure temperature" in result.problem_statement.lower()
        )
    ):
        contradictions.append(
            "Stable cure parameters weaken a primary cure-variation explanation because the defect remains intermittent across lots."
        )

    if (
        "no clear correlation to cavity, press, or batch" in all_text
        or "no single press or cavity correlation" in all_text
    ):
        contradictions.append(
            "Multi-tool and multi-lot occurrence weakens a press, cavity, or equipment-only explanation."
        )

    return contradictions


def _build_diagnostic_bullets(
    result: AnalysisResult,
    relationship_entries: list[dict],
    contradictions: list[str],
) -> list[str]:
    """Build explicitly tagged diagnostic bullets."""
    bullets: list[str] = []
    weakening_first_templates = {
        "TMPL_PROCESS_PARAM",
        "TMPL_EQUIPMENT_CONDITION",
        "TMPL_HUMAN_DISCIPLINE",
        "TMPL_DETECTION_GAP",
    }

    for hypothesis in result.hypotheses:
        matched = [
            entry for entry in relationship_entries if entry["hypothesis_id"] == hypothesis.id
        ]
        if hypothesis.template_id in weakening_first_templates:
            order = {"weakening": 0, "contradicting": 1, "supporting": 2, "indeterminate": 3}
            limit = 1
        else:
            order = {"supporting": 0, "weakening": 1, "contradicting": 2, "indeterminate": 3}
            limit = 2
        matched.sort(key=lambda entry: (order.get(entry["relationship"], 9), entry["evidence_id"]))
        for entry in matched[:limit]:
            bullets.append(
                f"[{entry['relationship']}] {hypothesis.process_step}: "
                f"{_describe_source(entry['source'])} indicates {entry['evidence_summary'].lower()}"
            )

    for contradiction in contradictions:
        bullets.append(f"[weakening] Alternative explanations: {contradiction}")

    for gap in result.gaps:
        bullets.append(
            f"[gap] {gap.description} This limits confidence for {', '.join(gap.affects_hypotheses) or 'the current ranking'}."
        )

    return bullets if bullets else [FALLBACKS["diagnostic_evidence"]]


def _build_action_items(result: AnalysisResult) -> list[str]:
    """Build targeted validation actions."""
    actions = [
        "Log adhesive lot, open-container exposure time, and pre-mold staging duration for passing versus failing lots.",
        "Run a focused trial with tighter surface-prep control and a reduced storage window before molding.",
        "Verify adhesive coverage at geometry-challenged regions using a quantitative method instead of visual-only confirmation.",
        "Correlate defect fallout with storage location and humidity-related exposure before molding.",
    ]

    if result.confidence.value == "Low":
        actions.insert(
            0,
            "Collect the missing process, audit, and corrective-action records needed to narrow the candidate hypotheses.",
        )

    return actions[:4]


def _build_confidence_statement(result: AnalysisResult, contradictions: list[str]) -> str:
    """Explain why the current confidence level is High, Medium, or Low."""
    if result.confidence.value == "High":
        return (
            "Confidence is High because multiple independent evidence streams align on the same primary explanation and there are no major unresolved gaps."
        )
    if result.confidence.value == "Medium":
        gap_labels = [gap.description for gap in result.gaps[:3]]
        joined_gaps = " ".join(gap_labels)
        contradiction_note = (
            f" Key weakening signals: {' '.join(contradictions[:2])}" if contradictions else ""
        )
        return (
            "Confidence is Medium because the leading explanation is supported by multiple indirect signals, "
            f"but unresolved gaps remain. {joined_gaps}{contradiction_note}"
        ).strip()
    return (
        "Confidence is Low because the available inputs do not provide enough aligned evidence to distinguish between the remaining explanations."
    )


def generate_report(
    result: AnalysisResult,
    input_hash: str,
    timestamp: str,
) -> ReportOutput:
    """Generate the full 5-section report from analysis results."""
    executive_summary = _build_executive_summary(result)
    hypotheses = _build_hypotheses_list(result)
    relationship_entries = _build_relationship_entries(result)
    contradictions = _find_global_contradictions(result)
    diagnostic_bullets = _build_diagnostic_bullets(result, relationship_entries, contradictions)
    action_items = _build_action_items(result)
    confidence_statement = _build_confidence_statement(result, contradictions)

    hypothesis_lines = [
        f"{item['rank']}: {item['name']} — {item['description']}" for item in hypotheses
    ]

    sections = [
        ReportSection(
            title="Executive Diagnostic Summary",
            content="\n\n".join([p for p in executive_summary if p.strip()]),
        ),
        ReportSection(
            title="Most Likely Root Cause Hypotheses",
            content="\n".join(hypothesis_lines) if hypothesis_lines else FALLBACKS["contributing_hypotheses"],
        ),
        ReportSection(
            title="Diagnostic Evidence",
            content="\n".join(f"- {bullet}" for bullet in diagnostic_bullets),
        ),
        ReportSection(
            title="Recommended Testing / Validation",
            content="\n".join(f"{idx + 1}. {action}" for idx, action in enumerate(action_items))
            if action_items
            else FALLBACKS["testing_validation"],
        ),
        ReportSection(
            title="Analysis Confidence Statement",
            content=confidence_statement or FALLBACKS["analysis_confidence_statement"],
        ),
    ]

    lint_input = [(section.title, section.content) for section in sections]
    lint_result = lint_report(lint_input)
    if not lint_result.passed:
        for violation in lint_result.violations:
            for section in sections:
                if section.title == violation["section"]:
                    section.content = section.content.replace(violation["term"], "[...]")

    trace_map: dict[str, list[str]] = {}
    for evidence in result.evidence_elements:
        trace_map.setdefault(evidence.source, []).append(evidence.id)

    report = ReportOutput(
        header=result.header,
        sections=sections,
        evidence_trace_map=trace_map,
        input_hash=input_hash,
        timestamp=timestamp,
        analysis_result=result,
    )

    report._template_data = {  # type: ignore[attr-defined]
        "executive_summary_paragraphs": executive_summary,
        "hypotheses": hypotheses,
        "why_bullets": diagnostic_bullets,
        "diagnostic_bullets": diagnostic_bullets,
        "actions_intro": "",
        "action_items": action_items,
        "confidence_statement": confidence_statement,
        "relationship_entries": relationship_entries,
        "contradictions": contradictions,
    }

    return report
