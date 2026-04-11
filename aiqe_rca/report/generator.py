"""Generic report generator for the deterministic Phase-2 RCA engine."""

from __future__ import annotations

import re

from aiqe_rca.models.alignment import AlignmentLabel, AlignmentResult
from aiqe_rca.models.evidence import EvidenceElement
from aiqe_rca.models.hypothesis import Hypothesis, RankLabel
from aiqe_rca.models.report import AnalysisResult, ReportOutput, ReportSection
from aiqe_rca.report.language_lint import lint_report

FALLBACKS = {
    "summary": "Current inputs do not provide enough traceable evidence to produce a reliable synthesis.",
    "hypotheses": "No defensible hypotheses were generated from the current input package.",
    "diagnostics": "No evidence-hypothesis relationships were generated from the current input package.",
    "testing": "Additional targeted evidence is required before validation work can be prioritized.",
    "confidence": "Confidence is limited because the current input package does not contain enough direct confirmation.",
}

_RANK_DISPLAY = {
    RankLabel.PRIMARY: "Primary Contributor",
    RankLabel.SECONDARY: "Secondary Contributor",
    RankLabel.CONDITIONAL_AMPLIFIER: "Conditional Amplifier",
    RankLabel.DEPRIORITIZED: "Deprioritized Alternative",
    RankLabel.UNRANKED: "Unranked",
}

_ALLOWED_TAGS = {
    AlignmentLabel.SUPPORTING.value,
    AlignmentLabel.WEAKENING.value,
    AlignmentLabel.CONTRADICTING.value,
    AlignmentLabel.INDETERMINATE.value,
}


def _normalize_text(text: str) -> str:
    """Normalize whitespace and casing for deterministic comparisons."""
    return re.sub(r"\s+", " ", text.lower()).strip()


def _contains_phrase(haystack: str, needle: str) -> bool:
    """Return True when the needle appears as a word-bounded phrase."""
    if not needle:
        return False
    return re.search(r"\b" + re.escape(_normalize_text(needle)) + r"\b", _normalize_text(haystack)) is not None


def _tokens_in_text(haystack: str, phrase: str) -> bool:
    """Allow phrases that are directly inferable from current-input tokens."""
    haystack_tokens = set(re.findall(r"[a-z0-9]+(?:[/-][a-z0-9]+)*", _normalize_text(haystack)))
    phrase_tokens = [
        token
        for token in re.findall(r"[a-z0-9]+(?:[/-][a-z0-9]+)*", _normalize_text(phrase))
        if len(token) >= 3
    ]
    return bool(phrase_tokens) and all(token in haystack_tokens for token in phrase_tokens)


def _describe_source(source: str) -> str:
    """Return a human-readable source label."""
    return source or "submitted evidence"


def _clean_text(text: str) -> str:
    """Normalize evidence summaries for report output."""
    return re.sub(r"\s+", " ", text.replace("•", "-")).strip().strip("- ").strip()


def _summarize_evidence(evidence: EvidenceElement) -> str:
    """Create a concise evidence summary."""
    text = _clean_text(evidence.text_content)
    return text if len(text) <= 220 else text[:217].rstrip() + "..."


def _alignment_priority(alignment: AlignmentResult) -> tuple[int, str]:
    """Sort alignments by relationship type and evidence id."""
    order = {
        AlignmentLabel.SUPPORTING: 0,
        AlignmentLabel.WEAKENING: 1,
        AlignmentLabel.CONTRADICTING: 2,
        AlignmentLabel.INDETERMINATE: 3,
    }
    return order.get(alignment.classification, 9), alignment.evidence_id


def _build_hypothesis_view(hypothesis: Hypothesis) -> dict:
    """Convert a hypothesis to a renderable structure."""
    return {
        "id": hypothesis.id,
        "name": hypothesis.process_step or hypothesis.id,
        "rank": _RANK_DISPLAY.get(hypothesis.rank_label, "Unranked"),
        "description": hypothesis.description,
        "score": hypothesis.net_support,
        "gap_severity": hypothesis.gap_severity,
    }


def _count_by_label(
    alignments: list[AlignmentResult],
    hypothesis_id: str,
) -> dict[str, int]:
    """Return the relationship counts for one hypothesis."""
    return {
        "supporting": sum(
            1
            for alignment in alignments
            if alignment.hypothesis_id == hypothesis_id
            and alignment.classification == AlignmentLabel.SUPPORTING
        ),
        "weakening": sum(
            1
            for alignment in alignments
            if alignment.hypothesis_id == hypothesis_id
            and alignment.classification == AlignmentLabel.WEAKENING
        ),
        "contradictory": sum(
            1
            for alignment in alignments
            if alignment.hypothesis_id == hypothesis_id
            and alignment.classification == AlignmentLabel.CONTRADICTING
        ),
        "indeterminate": sum(
            1
            for alignment in alignments
            if alignment.hypothesis_id == hypothesis_id
            and alignment.classification == AlignmentLabel.INDETERMINATE
        ),
    }


def _build_executive_summary(result: AnalysisResult) -> list[str]:
    """Build a concise, generic executive summary."""
    if not result.hypotheses:
        return [FALLBACKS["summary"]]

    primary = next((item for item in result.hypotheses if item.rank_label == RankLabel.PRIMARY), None)
    secondary = next((item for item in result.hypotheses if item.rank_label == RankLabel.SECONDARY), None)
    if primary is None:
        return [FALLBACKS["summary"]]

    primary_counts = _count_by_label(result.alignments, primary.id)
    paragraph_one = (
        f"Primary contributor: {primary.process_step or primary.id}. "
        f"It ranked first because the current input produced {primary_counts['supporting']} supporting, "
        f"{primary_counts['weakening']} weakening, and {primary_counts['contradictory']} contradictory relationships for this hypothesis."
    )

    paragraph_two_parts = []
    if secondary is not None:
        secondary_counts = _count_by_label(result.alignments, secondary.id)
        paragraph_two_parts.append(
            f"Secondary contributor: {secondary.process_step or secondary.id} "
            f"with {secondary_counts['supporting']} supporting relationships and "
            f"{secondary_counts['contradictory']} contradictions."
        )
    if result.gaps:
        paragraph_two_parts.append(
            f"Confidence remains {result.confidence.value} because {len(result.gaps)} explicit data gaps still limit direct confirmation."
        )

    summary = [paragraph_one]
    if paragraph_two_parts:
        summary.append(" ".join(paragraph_two_parts))
    return summary


def _build_relationship_entries(result: AnalysisResult) -> list[dict]:
    """Build the explicit evidence classification table."""
    evidence_map = {evidence.id: evidence for evidence in result.evidence_elements}
    hypothesis_map = {hypothesis.id: hypothesis for hypothesis in result.hypotheses}
    entries: list[dict] = []

    for alignment in sorted(result.alignments, key=_alignment_priority):
        evidence = evidence_map.get(alignment.evidence_id)
        hypothesis = hypothesis_map.get(alignment.hypothesis_id)
        if evidence is None or hypothesis is None:
            continue
        entries.append(
            {
                "source": evidence.source,
                "source_display": _describe_source(evidence.source),
                "evidence": _summarize_evidence(evidence),
                "hypothesis_id": hypothesis.id,
                "hypothesis": hypothesis.process_step or hypothesis.id,
                "tag": alignment.classification.value,
                "rationale": alignment.rationale,
            }
        )

    return entries


def _build_contradiction_log(relationship_entries: list[dict]) -> list[dict]:
    """Extract the contradiction log from the classified relationships."""
    return [
        {
            "hypothesis": entry["hypothesis"],
            "contradicting_evidence": entry["evidence"],
            "source": entry["source"],
            "reason": entry["rationale"],
        }
        for entry in relationship_entries
        if entry["tag"] == AlignmentLabel.CONTRADICTING.value
    ]


def _build_gap_log(result: AnalysisResult) -> list[dict]:
    """Build the explicit gap log."""
    hypothesis_map = {hypothesis.id: hypothesis.process_step or hypothesis.id for hypothesis in result.hypotheses}
    return [
        {
            "missing_signals": gap.description,
            "severity": gap.severity.value,
            "impacted_hypotheses": [
                hypothesis_map.get(hypothesis_id, hypothesis_id)
                for hypothesis_id in gap.affects_hypotheses
            ],
            "category": gap.category.value,
        }
        for gap in result.gaps
    ]


def _build_prioritization_summary(
    result: AnalysisResult,
    relationship_entries: list[dict],
) -> list[dict]:
    """Explain why each hypothesis landed where it did."""
    summary: list[dict] = []
    for hypothesis in result.hypotheses:
        counts = _count_by_label(result.alignments, hypothesis.id)
        gap_count = sum(
            1 for gap in result.gaps if hypothesis.id in gap.affects_hypotheses
        )
        summary.append(
            {
                "hypothesis": hypothesis.process_step or hypothesis.id,
                "rank": _RANK_DISPLAY.get(hypothesis.rank_label, "Unranked"),
                "supporting_count": counts["supporting"],
                "weakening_count": counts["weakening"],
                "contradictory_count": counts["contradictory"],
                "gap_count": gap_count,
                "summary": (
                    f"Ranked as {_RANK_DISPLAY.get(hypothesis.rank_label, 'Unranked')} because "
                    f"support={counts['supporting']}, weakening={counts['weakening']}, "
                    f"contradiction={counts['contradictory']}, gaps={gap_count}, "
                    f"and final score={hypothesis.net_support}."
                ),
            }
        )
    return summary


def _build_stateless_note() -> str:
    """Return the explicit stateless confirmation required by Phase 2."""
    return "This run used only current input. No prior context reused."


def _build_diagnostic_bullets(
    relationship_entries: list[dict],
    gap_log: list[dict],
) -> list[str]:
    """Build diagnostic bullets with explicit relationship tags."""
    bullets = [
        f"[{entry['tag']}] {entry['hypothesis']} <- {entry['source_display']}: {entry['evidence']}"
        for entry in relationship_entries
    ]
    bullets.extend(
        f"[gap] {gap['missing_signals']} Impacted hypotheses: {', '.join(gap['impacted_hypotheses']) or 'none'}."
        for gap in gap_log
    )
    return bullets or [FALLBACKS["diagnostics"]]


def _build_action_items(result: AnalysisResult, contradiction_log: list[dict], gap_log: list[dict]) -> list[str]:
    """Build targeted validation actions from current findings."""
    actions: list[str] = []

    primary = next((item for item in result.hypotheses if item.rank_label == RankLabel.PRIMARY), None)
    if primary is not None:
        actions.append(
            f"Collect direct confirmation for '{primary.process_step or primary.id}' across passing and failing conditions."
        )

    for contradiction in contradiction_log[:1]:
        actions.append(
            f"Re-check '{contradiction['hypothesis']}' against the contradictory evidence from {contradiction['source']}."
        )

    for gap in gap_log[:2]:
        actions.append(f"Close data gap: {gap['missing_signals']}")

    if not actions:
        actions.append(FALLBACKS["testing"])

    # Keep the list short and deterministic.
    unique_actions: list[str] = []
    for action in actions:
        if action not in unique_actions:
            unique_actions.append(action)
    return unique_actions[:4]


def _build_confidence_statement(result: AnalysisResult) -> str:
    """Explain the assigned confidence level."""
    if result.confidence.value == "High":
        return (
            "Confidence is High because the leading hypothesis has direct support, no contradictions, and no material data gaps."
        )
    if result.confidence.value == "Medium":
        return (
            "Confidence is Medium because the ranking is directionally clear, but explicit gaps or indirect evidence still limit direct confirmation."
        )
    return (
        "Confidence is Low because the current input does not provide enough direct support to separate the remaining hypotheses cleanly."
    )


def _validate_result_against_current_input(
    result: AnalysisResult,
    reasoning_artifact: dict,
) -> None:
    """Fail fast if the generated output cannot be traced to current input."""
    current_input_text = _normalize_text(
        " ".join([result.problem_statement] + [evidence.text_content for evidence in result.evidence_elements])
    )

    errors: list[str] = []
    for hypothesis in result.pre_ranking_hypotheses + result.hypotheses:
        process_name = hypothesis.process_step or ""
        if process_name and not (
            _contains_phrase(current_input_text, process_name)
            or _tokens_in_text(current_input_text, process_name)
        ):
            errors.append(f"Hypothesis term is not traceable to current input: {process_name}")

    for entry in reasoning_artifact.get("evidence_classification_table", []):
        if entry.get("tag") not in _ALLOWED_TAGS:
            errors.append(f"Invalid evidence tag: {entry.get('tag')}")
        if entry.get("hypothesis") and not (
            _contains_phrase(current_input_text, entry["hypothesis"])
            or _tokens_in_text(current_input_text, entry["hypothesis"])
        ):
            errors.append(f"Artifact hypothesis is not traceable to current input: {entry['hypothesis']}")

    for required_key in (
        "pre_ranking_hypotheses",
        "evidence_classification_table",
        "contradiction_log",
        "gap_log",
        "prioritization_summary",
        "stateless_confirmation",
    ):
        if required_key not in reasoning_artifact:
            errors.append(f"Missing reasoning artifact key: {required_key}")

    primary = next((hypothesis for hypothesis in result.hypotheses if hypothesis.rank_label == RankLabel.PRIMARY), None)
    if primary is not None:
        primary_counts = _count_by_label(result.alignments, primary.id)
        if primary_counts["contradictory"] > 0:
            non_contradicted_exists = any(
                _count_by_label(result.alignments, hypothesis.id)["contradictory"] == 0
                for hypothesis in result.hypotheses
                if hypothesis.id != primary.id
            )
            if non_contradicted_exists:
                errors.append("Primary hypothesis still carries contradictions while a non-contradicted alternative exists.")

    if reasoning_artifact.get("stateless_confirmation") != _build_stateless_note():
        errors.append("Stateless confirmation does not match the required explicit statement.")

    if errors:
        raise ValueError("Output validation failed: " + " | ".join(errors))


def generate_report(
    result: AnalysisResult,
    input_hash: str,
    timestamp: str,
) -> ReportOutput:
    """Generate the Phase-2 report and separate reasoning artifact."""
    executive_summary = _build_executive_summary(result)
    ranked_hypotheses = [_build_hypothesis_view(hypothesis) for hypothesis in result.hypotheses]
    pre_ranking_hypotheses = [
        _build_hypothesis_view(hypothesis) for hypothesis in result.pre_ranking_hypotheses
    ]
    relationship_entries = _build_relationship_entries(result)
    contradiction_log = _build_contradiction_log(relationship_entries)
    gap_log = _build_gap_log(result)
    prioritization_summary = _build_prioritization_summary(result, relationship_entries)
    diagnostic_bullets = _build_diagnostic_bullets(relationship_entries, gap_log)
    action_items = _build_action_items(result, contradiction_log, gap_log)
    confidence_statement = _build_confidence_statement(result)

    reasoning_artifact = {
        "pre_ranking_hypotheses": pre_ranking_hypotheses,
        "evidence_classification_table": [
            {
                "source": entry["source"],
                "evidence": entry["evidence"],
                "hypothesis": entry["hypothesis"],
                "tag": entry["tag"],
            }
            for entry in relationship_entries
        ],
        "contradiction_log": contradiction_log,
        "gap_log": gap_log,
        "prioritization_summary": prioritization_summary,
        "stateless_confirmation": _build_stateless_note(),
    }

    _validate_result_against_current_input(result, reasoning_artifact)

    hypothesis_lines = [
        f"{item['rank']}: {item['name']} (gap severity={item['gap_severity']}) - {item['description']}"
        for item in ranked_hypotheses
    ]

    sections = [
        ReportSection(
            title="Executive Diagnostic Summary",
            content="\n\n".join(paragraph for paragraph in executive_summary if paragraph.strip()),
        ),
        ReportSection(
            title="Most Likely Root Cause Hypotheses",
            content="\n".join(hypothesis_lines) if hypothesis_lines else FALLBACKS["hypotheses"],
        ),
        ReportSection(
            title="Diagnostic Evidence",
            content="\n".join(f"- {bullet}" for bullet in diagnostic_bullets),
        ),
        ReportSection(
            title="Recommended Testing / Validation",
            content="\n".join(f"{index + 1}. {item}" for index, item in enumerate(action_items)),
        ),
        ReportSection(
            title="Analysis Confidence Statement",
            content=confidence_statement or FALLBACKS["confidence"],
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
        "hypotheses": ranked_hypotheses,
        "why_bullets": diagnostic_bullets,
        "actions_intro": "",
        "action_items": action_items,
        "confidence_statement": confidence_statement,
        "relationship_entries": relationship_entries,
        "contradictions": contradiction_log,
        "gaps": gap_log,
        "pre_ranking_hypotheses": pre_ranking_hypotheses,
        "prioritization_summary": prioritization_summary,
        "stateless_confirmation": reasoning_artifact["stateless_confirmation"],
        "reasoning_artifact": reasoning_artifact,
    }

    return report
