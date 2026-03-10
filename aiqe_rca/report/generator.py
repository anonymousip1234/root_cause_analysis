"""Report generator.

Assembles the 5-section report from AnalysisResult. Produces structured data
for the HTML/PDF template. Applies fallback strings when data is insufficient.
Runs language lint before finalizing.

IMPORTANT: This generator produces clean, analytical text suitable for
an engineer audience. It never exposes raw parsed document text, evidence IDs,
internal keywords, or table row dumps.
"""

import re

from aiqe_rca.models.alignment import AlignmentLabel
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
    "why_aiqe_believes_this": (
        "Evidence mapping unavailable: inputs could not be parsed into "
        "traceable evidence elements."
    ),
    "immediate_actions_to_test": (
        "Investigation focus cannot be prioritized until additional "
        "targeted evidence is available."
    ),
    "analysis_confidence_statement": (
        "Insufficient evidence to state this reliably."
    ),
}

_RANK_DISPLAY = {
    RankLabel.PRIMARY: "Primary Driver",
    RankLabel.SECONDARY: "Secondary Contributor",
    RankLabel.CONDITIONAL_AMPLIFIER: "Conditional Amplifier",
    RankLabel.UNRANKED: "Unranked",
}

# Analytical description templates per domain template ID.
# These produce clean, engineer-readable hypothesis descriptions
# instead of dumping raw parsed document text.
_HYPOTHESIS_DESCRIPTIONS = {
    "TMPL_SURFACE_PREP": (
        "Residual contamination and surface energy variation following surface "
        "preparation may intermittently prevent full adhesive bonding, "
        "increasing susceptibility to blister formation under stress."
    ),
    "TMPL_PROCESS_PARAM": (
        "Variability in process parameters such as cure temperature, pressure, "
        "or cycle time may reduce process robustness, increasing susceptibility "
        "to defect formation under marginal conditions."
    ),
    "TMPL_MATERIAL_HANDLING": (
        "Improper material handling, extended staging time, or storage degradation "
        "may amplify marginal surface conditions, accelerating bond failure "
        "when upstream variation is present."
    ),
    "TMPL_EQUIPMENT_CONDITION": (
        "Equipment mechanical condition including vibration, wear, or alignment "
        "issues may introduce dimensional or process variation that correlates "
        "with intermittent out-of-spec conditions."
    ),
    "TMPL_HUMAN_DISCIPLINE": (
        "Inconsistent operator compliance or procedural discipline across shifts "
        "or lines may introduce variability in critical process steps, "
        "explaining shift-specific or line-specific defect concentration."
    ),
    "TMPL_ENVIRONMENTAL": (
        "Environmental exposure such as humidity, temperature, or contaminant "
        "ingress during processing or storage may amplify marginal conditions, "
        "particularly when combined with other contributing factors."
    ),
    "TMPL_DESIGN_GEOMETRY": (
        "Product geometry or design features create difficulty in achieving "
        "uniform coverage, coating, or machining, making certain regions "
        "inherently more sensitive to process variation."
    ),
    "TMPL_DETECTION_GAP": (
        "Current detection and inspection methods may not capture the failure "
        "mode effectively, allowing marginal conditions to escape to "
        "downstream operations or the customer."
    ),
}


def _get_hypothesis_description(h: Hypothesis) -> str:
    """Get a clean analytical description for a hypothesis.

    Uses predefined templates instead of raw evidence text.
    """
    if h.template_id and h.template_id in _HYPOTHESIS_DESCRIPTIONS:
        return _HYPOTHESIS_DESCRIPTIONS[h.template_id]
    return h.description


def _build_executive_summary_paragraphs(result: AnalysisResult) -> list[str]:
    """Build executive summary as a list of paragraphs (max 2)."""
    if not result.hypotheses or not result.alignments:
        return [FALLBACKS["executive_diagnostic_summary"]]

    primary = next(
        (h for h in result.hypotheses if h.rank_label == RankLabel.PRIMARY), None
    )
    secondary = next(
        (h for h in result.hypotheses if h.rank_label == RankLabel.SECONDARY), None
    )
    amplifier = next(
        (h for h in result.hypotheses if h.rank_label == RankLabel.CONDITIONAL_AMPLIFIER), None
    )

    contradicting_count = sum(
        1 for a in result.alignments if a.classification == AlignmentLabel.CONTRADICTING
    )

    paragraphs = []

    # Paragraph 1: main finding
    p1_parts = []
    if primary:
        p1_parts.append(
            f"AIQE identified an intermittent failure pattern driven primarily by "
            f"{primary.process_step.lower()} and "
        )
        if secondary:
            p1_parts.append(f"{secondary.process_step.lower()}. ")
        else:
            p1_parts.append("related process variation. ")

    if primary:
        p1_parts.append(
            "The defect presents as a condition not originating from a single fixed parameter, "
            "making traditional RCA ineffective."
        )

    if p1_parts:
        paragraphs.append("".join(p1_parts))

    # Paragraph 2: amplifier / process-sensitive context
    p2_parts = []
    if amplifier:
        p2_parts.append(
            f"The process-sensitive, time-dependent, and {amplifier.process_step.lower()}-amplified "
            f"nature of the failure explains why corrective actions have historically worked "
            f"temporarily and then failed without warning."
        )
    elif result.gaps:
        gap_labels = [g.description.split(".")[0].split("Expected")[0].strip().lower()
                      for g in result.gaps[:2]]
        p2_parts.append(
            f"Confidence is limited by {' and '.join(gap_labels)}."
        )
    if p2_parts:
        paragraphs.append(" ".join(p2_parts))

    return paragraphs if paragraphs else [FALLBACKS["executive_diagnostic_summary"]]


def _build_hypotheses_list(result: AnalysisResult) -> list[dict]:
    """Build structured hypothesis list with clean analytical descriptions."""
    if not result.hypotheses:
        return []

    items = []
    for h in result.hypotheses:
        rank_display = _RANK_DISPLAY.get(h.rank_label, "Unranked")
        description = _get_hypothesis_description(h)
        items.append({
            "name": h.process_step,
            "rank": rank_display,
            "description": description,
        })

    return items


def _describe_source(filename: str) -> str:
    """Convert a filename to a readable source description for report text."""
    fname = filename.lower()
    if "pfmea" in fname or "fmea" in fname:
        return "PFMEA analysis"
    if "spc" in fname:
        return "SPC data"
    if "lab" in fname:
        return "lab test data"
    if "audit" in fname:
        return "audit records"
    if "inspection" in fname:
        return "inspection records"
    if "control" in fname and "plan" in fname:
        return "control plan documentation"
    if "test" in fname:
        return "test report data"
    if fname.endswith((".csv", ".xlsx")):
        return "tabular process data"
    return "submitted evidence"


def _find_hypothesis_keywords_in_evidence(
    hypothesis: Hypothesis,
    evidence: EvidenceElement,
) -> list[str]:
    """Find which hypothesis keywords are present in the evidence text."""
    text_lower = evidence.text_content.lower()
    found = []
    for kw in hypothesis.keywords:
        kw_lower = kw.lower()
        if re.search(r"\b" + re.escape(kw_lower) + r"\b", text_lower):
            found.append(kw_lower)
        elif len(kw_lower) >= 5 and kw_lower[:5] in text_lower:
            found.append(kw_lower)
    return found


# Category display names for gap reasoning bullets
_CATEGORY_NAMES = {
    "DR": "design/requirements (DFMEA, engineering specifications)",
    "PC": "process control (control plans, work instructions)",
    "PV": "SPC or process performance variation",
    "DA": "detection/audit (inspection records, audit findings)",
    "RC": "corrective action history (8D, CAPA, containment)",
}


def _build_why_bullets(result: AnalysisResult) -> list[str]:
    """Build 'Why AIQE Believes This' as analytical reasoning bullets.

    Produces domain-specific analytical statements by examining which hypothesis
    keywords appear in supporting evidence and what source types provided the data.
    Never exposes raw evidence text or mechanical classifier rationale.
    """
    if not result.alignments:
        return [FALLBACKS["why_aiqe_believes_this"]]

    evidence_map = {e.id: e for e in result.evidence_elements}
    bullets: list[str] = []

    # Build per-hypothesis analytical bullets from supporting evidence
    for h in result.hypotheses:
        supporting = [
            a for a in result.alignments
            if a.hypothesis_id == h.id and a.classification == AlignmentLabel.SUPPORTING
        ]
        if not supporting:
            continue

        # Collect source descriptions and domain keywords found
        sources: set[str] = set()
        keywords_found: set[str] = set()
        for a in supporting:
            ev = evidence_map.get(a.evidence_id)
            if ev:
                sources.add(_describe_source(ev.source))
                kws = _find_hypothesis_keywords_in_evidence(h, ev)
                keywords_found.update(kws)

        source_str = " and ".join(sorted(sources)) if sources else "Available evidence"
        # Ensure first letter is capitalized without lowering acronyms
        if source_str and source_str[0].islower():
            source_str = source_str[0].upper() + source_str[1:]

        # Pick up to 3 most domain-specific keywords (skip generic ones)
        generic = {"time", "shift", "line", "data", "manual", "parameter", "error",
                   "customer", "complaint", "finding", "busy", "audit"}
        # Acronyms that should stay uppercased
        acronyms = {"spc", "atp", "cmm", "pfmea", "dfmea", "ncr", "wip", "capa"}
        specific_kws = [k for k in sorted(keywords_found) if k not in generic][:3]
        if not specific_kws:
            specific_kws = sorted(keywords_found)[:3]
        # Fix casing for acronyms
        display_kws = [k.upper() if k in acronyms else k for k in specific_kws]

        process_label = h.process_step.lower() if h.process_step else "the identified failure mode"
        kw_phrase = ", ".join(display_kws) if display_kws else "relevant conditions"

        bullet = (
            f"{source_str} identifies {kw_phrase} "
            f"consistent with {process_label}"
        )
        bullets.append(bullet)

    # Add contradiction bullet if any exist
    contradicting = [
        a for a in result.alignments
        if a.classification == AlignmentLabel.CONTRADICTING
    ]
    if contradicting:
        sources = set()
        for a in contradicting:
            ev = evidence_map.get(a.evidence_id)
            if ev:
                sources.add(_describe_source(ev.source))
        source_str = " and ".join(sorted(sources)) if sources else "some evidence"
        bullets.append(
            f"Some {source_str} shows passing conditions for certain parameters, "
            f"suggesting the failure mode may be intermittent rather than systemic"
        )

    # Add gap reasoning
    for gap in result.gaps[:2]:
        cat_val = gap.category.value if hasattr(gap.category, "value") else str(gap.category)
        cat_name = _CATEGORY_NAMES.get(cat_val, cat_val)
        bullets.append(
            f"No {cat_name} data was provided, limiting confidence in this area"
        )

    return bullets[:5] if bullets else [FALLBACKS["why_aiqe_believes_this"]]


def _build_action_items(result: AnalysisResult) -> tuple[str, list[str]]:
    """Build (intro_text, numbered_items) for Immediate Actions."""
    if not result.hypotheses:
        return "", [FALLBACKS["immediate_actions_to_test"]]

    primary = next(
        (h for h in result.hypotheses if h.rank_label == RankLabel.PRIMARY), None
    )
    secondary = next(
        (h for h in result.hypotheses if h.rank_label == RankLabel.SECONDARY), None
    )

    intro = "Current confidence supports immediate targeted testing."
    actions = []

    if primary:
        actions.append(
            f"Log and control time between critical process steps "
            f"related to {primary.process_step.lower()}"
        )

    if secondary:
        actions.append(
            f"Isolate {secondary.process_step.lower()} variables "
            f"used during recent failure events"
        )

    if primary:
        actions.append(
            f"Run short-term surface condition validation "
            f"prior to the next production run"
        )

    actions.append(
        "Compare process exposure profiles between passing and failing lots"
    )

    return intro, actions[:4]


def _build_confidence_statement(result: AnalysisResult) -> str:
    """Build the confidence/next-steps footer."""
    return (
        "Current confidence supports immediate targeted testing. "
        "If the issue persists after corrective actions, AIQE recommends "
        "re-analysis using newly captured data to isolate residual contributors."
    )


def generate_report(
    result: AnalysisResult,
    input_hash: str,
    timestamp: str,
) -> ReportOutput:
    """Generate the full 5-section report from analysis results."""
    exec_paragraphs = _build_executive_summary_paragraphs(result)
    hyp_list = _build_hypotheses_list(result)
    why_bullets = _build_why_bullets(result)
    actions_intro, action_items = _build_action_items(result)
    confidence_stmt = _build_confidence_statement(result)

    # Flat text for JSON and lint
    hyp_text_lines = []
    for h in hyp_list:
        hyp_text_lines.append(f"{h['name']} ({h['rank']}): {h['description']}")

    sections = [
        ReportSection(
            title="Executive Diagnostic Summary",
            content="\n\n".join(exec_paragraphs),
        ),
        ReportSection(
            title="Most Likely Root Cause Hypotheses",
            content="\n".join(hyp_text_lines) if hyp_text_lines else FALLBACKS["contributing_hypotheses"],
        ),
        ReportSection(
            title="Diagnostic Evidence",
            content="\n".join(f"- {b}" for b in why_bullets),
        ),
        ReportSection(
            title="Recommended Testing / Validation",
            content="\n".join(f"{i+1}. {a}" for i, a in enumerate(action_items)),
        ),
        ReportSection(
            title="Analysis Confidence Statement",
            content=confidence_stmt,
        ),
    ]

    # Language lint
    lint_input = [(s.title, s.content) for s in sections]
    lint_result = lint_report(lint_input)
    if not lint_result.passed:
        for v in lint_result.violations:
            for s in sections:
                if s.title == v["section"]:
                    s.content = s.content.replace(v["term"], "[...]")

    # Evidence trace map
    trace_map: dict[str, list[str]] = {}
    for evidence in result.evidence_elements:
        if evidence.source not in trace_map:
            trace_map[evidence.source] = []
        trace_map[evidence.source].append(evidence.id)

    report = ReportOutput(
        header=result.header,
        sections=sections,
        evidence_trace_map=trace_map,
        input_hash=input_hash,
        timestamp=timestamp,
        analysis_result=result,
    )

    report._template_data = {  # type: ignore[attr-defined]
        "executive_summary_paragraphs": exec_paragraphs,
        "hypotheses": hyp_list,
        "why_bullets": why_bullets,
        "actions_intro": actions_intro,
        "action_items": action_items,
        "confidence_statement": confidence_stmt,
    }

    return report
