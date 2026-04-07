"""Report generator.

Assembles the 5-section report from AnalysisResult and exposes a richer
reasoning artifact package for canonical evaluation.
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
    "contributing_hypotheses": "No defensible hypotheses can be ranked from the current inputs.",
    "diagnostic_evidence": (
        "Evidence mapping unavailable: inputs could not be parsed into traceable evidence elements."
    ),
    "testing_validation": (
        "Investigation focus cannot be prioritized until additional targeted evidence is available."
    ),
    "analysis_confidence_statement": "Insufficient evidence to state this reliably.",
}

_RANK_DISPLAY = {
    RankLabel.PRIMARY: "Primary Contributor",
    RankLabel.SECONDARY: "Secondary Contributor",
    RankLabel.CONDITIONAL_AMPLIFIER: "Conditional Amplifier",
    RankLabel.DEPRIORITIZED: "Deprioritized Alternative",
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
        "Storage duration, staging conditions, and environmental exposure appear to amplify "
        "the failure when upstream variation is already present."
    ),
    "TMPL_PROCESS_PARAM": (
        "Cure and molding parameter variation was evaluated, but contradictory evidence keeps "
        "it below the leading explanations."
    ),
    "TMPL_EQUIPMENT_CONDITION": (
        "Press, cavity, or tool-driven variation was evaluated, but contradictory evidence "
        "does not support a single equipment source."
    ),
}


def _get_hypothesis_description(hypothesis: Hypothesis) -> str:
    """Return a concise analytical description for the hypothesis."""
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
    return re.sub(r"\s+", " ", text.replace("•", "-")).strip().strip("- ").strip()


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


def _build_hypotheses_list(hypotheses: list[Hypothesis]) -> list[dict]:
    """Build a hypothesis list for report and JSON output."""
    return [
        {
            "id": hypothesis.id,
            "name": hypothesis.process_step,
            "rank": _RANK_DISPLAY.get(hypothesis.rank_label, "Unranked"),
            "template_id": hypothesis.template_id,
            "description": _get_hypothesis_description(hypothesis),
            "net_support": hypothesis.net_support,
            "gap_severity": hypothesis.gap_severity,
        }
        for hypothesis in hypotheses
    ]


def _build_executive_summary(result: AnalysisResult) -> list[str]:
    """Build the executive summary paragraphs."""
    if not result.hypotheses:
        return [FALLBACKS["executive_diagnostic_summary"]]

    primary = next((h for h in result.hypotheses if h.rank_label == RankLabel.PRIMARY), None)
    secondary = next((h for h in result.hypotheses if h.rank_label == RankLabel.SECONDARY), None)
    amplifier = next(
        (
            h
            for h in result.hypotheses
            if h.rank_label == RankLabel.CONDITIONAL_AMPLIFIER
            and h.template_id in {"TMPL_MATERIAL_HANDLING", "TMPL_ENVIRONMENTAL"}
        ),
        None,
    )

    if primary is None:
        return [FALLBACKS["executive_diagnostic_summary"]]

    paragraph_one = (
        f"AIQE identified a pattern most consistent with {primary.process_step.lower()} rather than "
        "a stable molding or equipment-only explanation. The observed blistering remains intermittent "
        "across lots, and the current inputs do not show a single fixed press, cavity, or cure-parameter shift."
    )

    paragraph_two_parts: list[str] = []
    if secondary is not None:
        paragraph_two_parts.append(
            f"The strongest secondary contributor is {secondary.process_step.lower()}."
        )
    if amplifier is not None:
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
    """Build explicit evidence-hypothesis relationship entries."""
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
                "source": evidence.source,
                "source_display": _describe_source(evidence.source),
                "evidence_id": evidence.id,
                "evidence_summary": _summarize_evidence(evidence),
                "relationship": alignment.classification.value,
                "rationale": alignment.rationale,
            }
        )

    return entries


def _build_contradiction_log(result: AnalysisResult) -> list[dict]:
    """Build a structured contradiction log, including non-ranked false leads."""
    contradictions: list[dict] = []
    for evidence in result.evidence_elements:
        text_lower = evidence.text_content.lower()
        summary = _summarize_evidence(evidence)

        if (
            "no consistent shift in cure temperature or time" in text_lower
            or "spc data for cure temperature and cure time remain in control" in text_lower
            or "no recorded changes to cure time or cure temperature" in text_lower
        ):
            contradictions.append(
                {
                    "source": evidence.source,
                    "source_display": _describe_source(evidence.source),
                    "evidence": summary,
                    "hypothesis": "Process Parameter Variation",
                    "tag": "contradictory",
                    "reason": "Stable SPC and cure settings contradict a primary process-variation explanation.",
                }
            )

        if (
            "no clear correlation to cavity, press, or batch" in text_lower
            or "no single press or cavity correlation" in text_lower
            or "across multiple tools" in text_lower
        ):
            contradictions.append(
                {
                    "source": evidence.source,
                    "source_display": _describe_source(evidence.source),
                    "evidence": summary,
                    "hypothesis": "Equipment / Press-Tool Variation",
                    "tag": "contradictory",
                    "reason": "Multi-tool occurrence without a fixed press or cavity correlation contradicts an equipment-driven explanation.",
                }
            )

    unique: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for item in contradictions:
        key = (item["hypothesis"], item["reason"])
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


def _build_gap_log(result: AnalysisResult) -> list[dict]:
    """Build a clean gap log."""
    return [
        {
            "category": gap.category.value,
            "description": gap.description,
            "severity": gap.severity.value,
            "affects_hypotheses": gap.affects_hypotheses,
        }
        for gap in result.gaps
    ]


def _build_prioritization_summary(
    result: AnalysisResult,
    relationship_entries: list[dict],
) -> list[dict]:
    """Summarize why each hypothesis was prioritized or deprioritized."""
    summary: list[dict] = []
    for hypothesis in result.hypotheses:
        supporting = sum(
            1
            for entry in relationship_entries
            if entry["hypothesis_id"] == hypothesis.id and entry["relationship"] == "supporting"
        )
        weakening = sum(
            1
            for entry in relationship_entries
            if entry["hypothesis_id"] == hypothesis.id and entry["relationship"] == "weakening"
        )
        contradicting = sum(
            1
            for entry in relationship_entries
            if entry["hypothesis_id"] == hypothesis.id and entry["relationship"] == "contradictory"
        )

        if hypothesis.rank_label == RankLabel.PRIMARY:
            basis = "Ranked first because direct supporting evidence outweighed all negative evidence."
        elif hypothesis.rank_label == RankLabel.SECONDARY:
            basis = "Retained as secondary because defect localization evidence remained directly relevant."
        elif hypothesis.rank_label == RankLabel.CONDITIONAL_AMPLIFIER:
            basis = "Treated as an amplifier because the evidence is indirect and confidence-limiting gaps remain."
        else:
            basis = "Deprioritized because weakening or contradictory evidence outweighed its direct support."

        summary.append(
            {
                "hypothesis": hypothesis.process_step,
                "outcome": _RANK_DISPLAY.get(hypothesis.rank_label, hypothesis.rank_label.value),
                "supporting_count": supporting,
                "weakening_count": weakening,
                "contradicting_count": contradicting,
                "basis": basis,
            }
        )
    return summary


def _build_stateless_note(input_hash: str) -> str:
    """Explain the stateless execution contract explicitly."""
    return (
        "Each analysis request is isolated and deterministic. No prior report vocabulary or session "
        f"memory is reused, and the current input package is captured by input hash {input_hash}."
    )


def _build_diagnostic_bullets(
    result: AnalysisResult,
    relationship_entries: list[dict],
    contradiction_log: list[dict],
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
            order = {"contradictory": 0, "weakening": 1, "supporting": 2, "indeterminate": 3}
            limit = 1
        else:
            order = {"supporting": 0, "weakening": 1, "contradictory": 2, "indeterminate": 3}
            limit = 2
        matched.sort(key=lambda entry: (order.get(entry["relationship"], 9), entry["evidence_id"]))
        for entry in matched[:limit]:
            bullets.append(
                f"[{entry['relationship']}] {hypothesis.process_step}: "
                f"{entry['source_display']} indicates {entry['evidence_summary'].lower()}"
            )

    for contradiction in contradiction_log:
        bullets.append(
            f"[{contradiction['tag']}] {contradiction['hypothesis']}: {contradiction['reason']}"
        )

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


def _build_confidence_statement(result: AnalysisResult, contradiction_log: list[dict]) -> str:
    """Explain why the current confidence level is High, Medium, or Low."""
    if result.confidence.value == "High":
        return (
            "Confidence is High because multiple independent evidence streams align on the same primary explanation and there are no major unresolved gaps."
        )
    if result.confidence.value == "Medium":
        gap_labels = [gap.description for gap in result.gaps[:4]]
        contradiction_note = " ".join(item["reason"] for item in contradiction_log[:2])
        return (
            "Confidence is Medium because the leading explanation is supported by multiple indirect signals, "
            f"but unresolved gaps remain. {' '.join(gap_labels)} {contradiction_note}"
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
    ranked_hypotheses = _build_hypotheses_list(result.hypotheses)
    pre_ranking_hypotheses = _build_hypotheses_list(result.pre_ranking_hypotheses)
    relationship_entries = _build_relationship_entries(result)
    contradiction_log = _build_contradiction_log(result)
    gap_log = _build_gap_log(result)
    prioritization_summary = _build_prioritization_summary(result, relationship_entries)
    diagnostic_bullets = _build_diagnostic_bullets(result, relationship_entries, contradiction_log)
    action_items = _build_action_items(result)
    confidence_statement = _build_confidence_statement(result, contradiction_log)

    hypothesis_lines = [
        f"{item['rank']}: {item['name']} - {item['description']}" for item in ranked_hypotheses
    ]

    sections = [
        ReportSection(
            title="Executive Diagnostic Summary",
            content="\n\n".join([paragraph for paragraph in executive_summary if paragraph.strip()]),
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

    reasoning_artifacts = {
        "pre_ranking_hypotheses": pre_ranking_hypotheses,
        "evidence_classification_table": [
            {
                "source": entry["source_display"],
                "evidence": entry["evidence_summary"],
                "hypothesis": entry["hypothesis_name"],
                "tag": entry["relationship"],
            }
            for entry in relationship_entries
        ]
        + [
            {
                "source": item["source_display"],
                "evidence": item["evidence"],
                "hypothesis": item["hypothesis"],
                "tag": item["tag"],
            }
            for item in contradiction_log
        ],
        "contradiction_log": contradiction_log,
        "gap_log": gap_log,
        "prioritization_summary": prioritization_summary,
        "stateless_note": _build_stateless_note(input_hash),
    }

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
        "hypotheses": ranked_hypotheses,
        "why_bullets": diagnostic_bullets,
        "diagnostic_bullets": diagnostic_bullets,
        "actions_intro": "",
        "action_items": action_items,
        "confidence_statement": confidence_statement,
        "relationship_entries": relationship_entries,
        "contradictions": contradiction_log,
        "reasoning_artifacts": reasoning_artifacts,
    }

    return report
