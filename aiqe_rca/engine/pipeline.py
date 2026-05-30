"""Pipeline orchestrator — runs the full deterministic analysis flow.

v3 Architecture (per AIQE Phase 2 Developer Implementation Spec v3):

  parse → categorize → [SOURCE ROLE GATE] → build hypotheses
       → pattern facts → merge pattern-triggered hypotheses
       → [OBSERVATION-ONLY] associate evidence
       → [OBSERVATION-ONLY] classify alignments
       → detect gaps → rank → assess confidence → report

Critical invariant: PFMEA, Control Plan, and any other EXPECTATION-role source
(DR / PC category) MUST NOT enter the evidence association or classification steps.
"If PFMEA or Control Plan appears in evidence output, Phase 2 fails."
(v3 spec Section 5 and Section 14)
"""

import logging
import re

from aiqe_rca.config import settings

logger = logging.getLogger(__name__)
from aiqe_rca.engine.alignment_classifier import classify_all_alignments
from aiqe_rca.engine.confidence import assess_confidence
from aiqe_rca.engine.evidence_associator import associate_evidence
from aiqe_rca.engine.evidence_categorizer import categorize_evidence, enrich_image_evidence
from aiqe_rca.engine.gap_detector import detect_gaps
from aiqe_rca.engine.hypothesis_builder import build_hypotheses
from aiqe_rca.engine.pattern_facts import (
    build_pattern_facts,
    generate_pattern_hypotheses,
    INTERACTION_TEMPLATE_IDS,
)
from aiqe_rca.engine.ranker import rank_hypotheses
from aiqe_rca.models.evidence import EvidenceCategory, EvidenceElement, SourceType
from aiqe_rca.models.hypothesis import Hypothesis, RankLabel
from aiqe_rca.models.report import (
    AnalysisResult,
    ConfidenceLevel,
    ImageStatus,
    ReportHeader,
    SourceRoleAuditEntry,
)
from aiqe_rca.parser.router import parse_multiple_files


# Source categories that represent expectation / design intent documents.
# These must never enter the evidence reasoning pipeline.
_EXPECTATION_CATEGORIES: frozenset[EvidenceCategory] = frozenset({
    EvidenceCategory.DESIGN_REQUIREMENTS,   # PFMEA, DFMEA, engineering specs
    EvidenceCategory.PROCESS_CONTROL,       # Control plan, work instructions, SOPs
})


def _build_source_role_audit(
    all_evidence: list[EvidenceElement],
    observation_ids: set[str],
) -> list[SourceRoleAuditEntry]:
    """AG-1 Rev-C: one audit entry per source file proving the gate was applied."""
    by_source: dict[str, SourceRoleAuditEntry] = {}
    for e in all_evidence:
        if e.source not in by_source:
            is_obs = e.id in observation_ids
            if is_obs:
                role: str = "OBSERVATION"
            elif e.category in _EXPECTATION_CATEGORIES:
                role = "EXPECTATION"
            else:
                role = "CONTEXT"
            by_source[e.source] = SourceRoleAuditEntry(
                filename=e.source,
                source_role=role,
                created_evidence_items=0,
                evidence_creation_allowed=is_obs,
            )
        if e.id in observation_ids:
            by_source[e.source].created_evidence_items += 1
    return list(by_source.values())


def _build_image_statuses(
    all_evidence: list[EvidenceElement],
    file_keys: list[str],
) -> list[ImageStatus]:
    """AG-8 Rev-C: explicit status for every uploaded image — never SILENT."""
    image_extensions = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif"}
    image_files = [
        k for k in file_keys
        if any(k.lower().endswith(ext) for ext in image_extensions)
    ]
    if not image_files:
        return []

    # Group evidence by source
    by_source: dict[str, list[EvidenceElement]] = {}
    for e in all_evidence:
        if e.source_type == SourceType.IMAGE:
            by_source.setdefault(e.source, []).append(e)

    statuses: list[ImageStatus] = []
    for filename in image_files:
        elements = by_source.get(filename, [])
        if not elements:
            statuses.append(ImageStatus(
                filename=filename,
                status="FAIL",
                reason="Image was uploaded but no evidence element was created — possible parse failure.",
            ))
            continue

        is_real_ocr = any(
            (e.page_ref or "").startswith("OCR extraction") for e in elements
        )
        if is_real_ocr:
            statuses.append(ImageStatus(
                filename=filename,
                status="CONTRIBUTORY",
                reason="OCR text extracted and entered evidence graph.",
                created_evidence_item_ids=[e.id for e in elements],
            ))
        else:
            statuses.append(ImageStatus(
                filename=filename,
                status="NON_CONTRIBUTORY",
                reason=(
                    "Image was processed. No reliable OCR text extracted; "
                    "filename-derived signals included in evidence graph where possible."
                ),
                created_evidence_item_ids=[e.id for e in elements],
            ))
    return statuses


def _filter_observation_evidence(
    evidence_elements: list[EvidenceElement],
) -> list[EvidenceElement]:
    """Return only observation-role evidence (DR/PC are excluded).

    This is the hard source role gate mandated by v3 spec Section 5.
    Expectation sources (PFMEA, Control Plan) describe what SHOULD happen;
    they cannot confirm, weaken, or contradict what WAS observed.
    """
    return [e for e in evidence_elements if e.category not in _EXPECTATION_CATEGORIES]


def _merge_hypotheses(
    signal_group_hypotheses: list[Hypothesis],
    pattern_hypotheses: list[Hypothesis],
    max_hypotheses: int,
) -> list[Hypothesis]:
    """Merge pattern-triggered and signal-group hypotheses into a ranked-capped list.

    Pattern-triggered hypotheses take priority slots (v3 spec Section 7).
    Signal-group hypotheses fill remaining slots, skipping duplicates.
    All IDs are renumbered deterministically.
    """
    # Collect template IDs already covered by pattern hypotheses
    seen_template_ids = {h.template_id for h in pattern_hypotheses if h.template_id}

    # Add signal-group hypotheses that don't duplicate pattern hypothesis templates
    additional: list[Hypothesis] = []
    for h in signal_group_hypotheses:
        if h.template_id in seen_template_ids:
            continue
        additional.append(h)
        if len(pattern_hypotheses) + len(additional) >= max_hypotheses:
            break

    merged = pattern_hypotheses + additional

    # Renumber IDs deterministically (H1, H2, ...)
    for index, hypothesis in enumerate(merged, start=1):
        hypothesis.id = f"H{index}"

    return merged[:max_hypotheses]


def _extract_header_fields(
    problem_statement: str,
    evidence_elements: list[EvidenceElement],
    confidence: ConfidenceLevel,
) -> ReportHeader:
    """Extract report header fields from inputs.

    All regex operations are individually guarded — a malformed evidence element
    must never crash header extraction (Rev-C crash-path hardening).
    """
    header = ReportHeader(analysis_confidence=confidence)

    try:
        part_pattern = r"(?:Part|Product|Component|Assembly)[:\s]+([^\n;]{5,80})"
        for e in evidence_elements:
            try:
                match = re.search(part_pattern, e.text_content or "", re.IGNORECASE)
                if match:
                    header.part_process = match.group(1).strip()
                    break
            except Exception:
                continue

        if header.part_process == "Not available from current inputs.":
            ps_match = re.search(part_pattern, problem_statement or "", re.IGNORECASE)
            if ps_match:
                header.part_process = ps_match.group(1).strip()
    except Exception:
        logger.exception("Header part/process extraction failed (non-fatal)")

    try:
        if problem_statement and problem_statement.strip():
            first_sentence = problem_statement.split(".")[0].strip()
            if len(first_sentence) > 150:
                first_sentence = first_sentence[:150] + "..."
            header.defect_symptom = first_sentence
    except Exception:
        logger.exception("Header defect/symptom extraction failed (non-fatal)")

    try:
        date_pattern = r"\b\d{4}[-/]\d{1,2}[-/]\d{1,2}\b"
        dates_found: list[str] = []
        for e in evidence_elements:
            try:
                dates_found.extend(re.findall(date_pattern, e.text_content or ""))
            except Exception:
                continue
        if len(dates_found) >= 2:
            dates_found.sort()
            header.date_range = f"{dates_found[0]} to {dates_found[-1]}"
        elif len(dates_found) == 1:
            header.date_range = dates_found[0]
        else:
            ps_dates = re.findall(date_pattern, problem_statement or "")
            if ps_dates:
                ps_dates.sort()
                header.date_range = (
                    f"{ps_dates[0]} to {ps_dates[-1]}" if len(ps_dates) >= 2 else ps_dates[0]
                )
    except Exception:
        logger.exception("Header date range extraction failed (non-fatal)")

    return header


def run_analysis(
    problem_statement: str,
    files: dict[str, bytes],
    _file_keys: list[str] | None = None,
) -> AnalysisResult:
    """Run the full deterministic v3 RCA pipeline.

    Args:
        problem_statement: User-provided problem description.
        files: Mapping of filename -> file content bytes.

    Returns:
        Complete AnalysisResult ready for report generation.
    """
    # -----------------------------------------------------------------------
    # Step 1 — Parse all documents into evidence elements
    # (individual file failures are skipped — never abort the whole pipeline)
    # -----------------------------------------------------------------------
    evidence_elements = parse_multiple_files(files)

    # Defensive: ensure every element has non-None text_content
    for _ev in evidence_elements:
        if not _ev.text_content:
            _ev.text_content = ""

    # -----------------------------------------------------------------------
    # Step 1b — Categorize evidence (DR/PC/PV/DA/RC/UN)
    # Must run before the source role gate so PFMEA/CP are identified.
    # -----------------------------------------------------------------------
    try:
        evidence_elements = categorize_evidence(evidence_elements)
    except Exception:
        logger.exception("Evidence categorization failed — continuing with UNCATEGORIZED evidence.")

    # -----------------------------------------------------------------------
    # SOURCE ROLE GATE — separate EXPECTATION from OBSERVATION sources.
    # PFMEA and Control Plan documents are expectation sources; they define
    # what *should* happen. Only observation evidence may enter the reasoning
    # pipeline (association, classification, gap detection).
    # -----------------------------------------------------------------------
    observation_evidence = _filter_observation_evidence(evidence_elements)

    # -----------------------------------------------------------------------
    # Step 2 — Build signal-group hypotheses.
    # Uses ALL evidence (including PFMEA/CP) for signal matching so that
    # hypothesis domains reflect what the input package describes.
    # -----------------------------------------------------------------------
    signal_hypotheses = build_hypotheses(problem_statement, evidence_elements)

    # -----------------------------------------------------------------------
    # Step 2b — Build pattern facts from OBSERVATION evidence only.
    # -----------------------------------------------------------------------
    try:
        pattern_facts = build_pattern_facts(observation_evidence)
        pattern_hypotheses = generate_pattern_hypotheses(pattern_facts)
    except Exception:
        logger.exception("Pattern fact building failed — continuing without pattern-triggered hypotheses.")
        pattern_facts = []
        pattern_hypotheses = []

    # -----------------------------------------------------------------------
    # Step 2c — Merge pattern-triggered and signal-group hypotheses.
    # Pattern hypotheses take priority; signal-group hypotheses fill remaining
    # slots up to max_hypotheses (v3 spec Section 7).
    # -----------------------------------------------------------------------
    max_h = settings.max_hypotheses
    min_h = settings.min_hypotheses
    hypotheses = _merge_hypotheses(signal_hypotheses, pattern_hypotheses, max_h)

    # Pad to minimum if needed (rare edge case)
    if len(hypotheses) < min_h and len(signal_hypotheses) > len(hypotheses):
        seen = {h.template_id for h in hypotheses}
        for h in signal_hypotheses:
            if h.template_id not in seen:
                hypotheses.append(h)
                seen.add(h.template_id)
            if len(hypotheses) >= min_h:
                break
        for i, h in enumerate(hypotheses, start=1):
            h.id = f"H{i}"

    # -----------------------------------------------------------------------
    # Step 2d — Enrich image evidence using hypothesis keyword vocabulary.
    # Must run after hypothesis building (keywords available) and before
    # association (enriched text improves overlap scores).
    # -----------------------------------------------------------------------
    all_keywords: list[str] = sorted(
        {kw for h in hypotheses for kw in h.keywords}
    )
    evidence_elements = enrich_image_evidence(evidence_elements, all_keywords)
    # Re-sync observation_evidence list after enrichment (image elements are shared objects)
    observation_evidence = _filter_observation_evidence(evidence_elements)

    # -----------------------------------------------------------------------
    # Step 3 — Associate evidence to hypotheses.
    # ONLY observation evidence is passed — EXPECTATION sources are excluded.
    # -----------------------------------------------------------------------
    hypotheses = associate_evidence(hypotheses, observation_evidence)

    # -----------------------------------------------------------------------
    # Step 4 — Classify alignment for all associated pairs.
    # ONLY observation evidence is passed.
    # -----------------------------------------------------------------------
    alignments = classify_all_alignments(hypotheses, observation_evidence)

    # Preserve the candidate list before prioritization for reasoning artifacts.
    pre_ranking_hypotheses = [h.model_copy(deep=True) for h in hypotheses]

    # -----------------------------------------------------------------------
    # Step 5 — Detect data gaps from observation evidence.
    # -----------------------------------------------------------------------
    gaps = detect_gaps(observation_evidence, hypotheses, alignments)

    # -----------------------------------------------------------------------
    # Step 6 — Rank hypotheses.
    # Pattern facts are passed so the ranker can apply interaction influence
    # rules (stack-up hypotheses get tier-0 priority when they have support).
    # -----------------------------------------------------------------------
    hypotheses = rank_hypotheses(hypotheses, alignments, gaps, pattern_facts=pattern_facts)

    # -----------------------------------------------------------------------
    # Step 7 — Assess overall confidence.
    # -----------------------------------------------------------------------
    confidence = assess_confidence(hypotheses, alignments, gaps)

    # -----------------------------------------------------------------------
    # Step 8 — Extract header fields.
    # -----------------------------------------------------------------------
    header = _extract_header_fields(problem_statement, evidence_elements, confidence)

    # -----------------------------------------------------------------------
    # Step 9 — Build audit objects (AG-1 source role proof, AG-8 image status)
    # -----------------------------------------------------------------------
    obs_ids = {e.id for e in observation_evidence}
    source_role_audit = _build_source_role_audit(evidence_elements, obs_ids)
    image_statuses = _build_image_statuses(evidence_elements, _file_keys or sorted(files.keys()))

    # Determine ranking mode for AG-3 transparency
    ranking_mode = (
        "UNRESOLVED_COMPETING_HYPOTHESES"
        if all(h.rank_label == RankLabel.UNRESOLVED for h in hypotheses)
        else "PROMOTED_PRIMARY"
    )

    return AnalysisResult(
        evidence_elements=evidence_elements,      # ALL elements (for tracing)
        pre_ranking_hypotheses=pre_ranking_hypotheses,
        hypotheses=hypotheses,
        alignments=alignments,                    # OBSERVATION-ONLY alignments
        gaps=gaps,
        confidence=confidence,
        header=header,
        problem_statement=problem_statement,
        ranking_mode=ranking_mode,
        source_role_audit=source_role_audit,
        image_statuses=image_statuses,
    )
