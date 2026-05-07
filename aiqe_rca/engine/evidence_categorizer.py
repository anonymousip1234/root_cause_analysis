"""Deterministic evidence categorizer.

Assigns DR / PC / PV / DA / RC / UN to each evidence element based on
source filename patterns first, then text-content patterns.

This step is critical so that PFMEA and Control Plan documents are correctly
identified and handled by the alignment classifier, which treats them as
possible-cause documents (INDETERMINATE unless contradicted), not as
observational evidence.

Categories:
  DR  Design Requirements  — PFMEA, DFMEA, engineering specs, drawings
  PC  Process Control      — Control plan, work instructions, SOPs
  PV  Performance Variation — SPC charts, yield data, defect rate trends
  DA  Detection Audit      — Inspection results, audit findings, gauge readings
  RC  Response Corrective  — Containment actions, CAPA, 8D, rework responses
  UN  Uncategorized        — Default when no pattern matches
"""

from __future__ import annotations

import re

from aiqe_rca.models.evidence import EvidenceCategory, EvidenceElement


# --- Filename-based rules (checked first; more reliable than text content) ---

_FILENAME_RULES: list[tuple[re.Pattern[str], EvidenceCategory]] = [
    (re.compile(r"pfmea|dfmea|fmea|failure.?mode", re.I), EvidenceCategory.DESIGN_REQUIREMENTS),
    (re.compile(r"control.?plan|ctrl.?plan|cp_", re.I), EvidenceCategory.PROCESS_CONTROL),
    (re.compile(r"work.?instruction|sop_|_sop|standard.?op", re.I), EvidenceCategory.PROCESS_CONTROL),
    (re.compile(r"\bspc\b|control.?chart|cpk|sigma.?level", re.I), EvidenceCategory.PERFORMANCE_VARIATION),
    (re.compile(r"yield|fallout|scrap|defect.?rate|nonconform|ppm", re.I), EvidenceCategory.PERFORMANCE_VARIATION),
    (re.compile(r"inspection|audit|detection|gauge|gage|measurement.?result", re.I), EvidenceCategory.DETECTION_AUDIT),
    (re.compile(r"rework|repair|corrective|contain|8d|capa|d8_", re.I), EvidenceCategory.RESPONSE_CORRECTIVE),
]

# --- Text-content rules (checked when filename gives no signal) ---

_TEXT_RULES: list[tuple[re.Pattern[str], EvidenceCategory]] = [
    # DR — design / PFMEA language
    (
        re.compile(
            r"\bfmea\b|failure mode.*effect|design.*failure|potential failure mode"
            r"|rpn\s*=|\bdfmea\b|engineering spec|drawing\s+number",
            re.I,
        ),
        EvidenceCategory.DESIGN_REQUIREMENTS,
    ),
    # PC — control plan / work instruction language
    (
        re.compile(
            r"\bcontrol plan\b|work instruction|standard operating procedure|\bsop\b"
            r"|reaction plan|control method|frequency of inspection|sample size.*per",
            re.I,
        ),
        EvidenceCategory.PROCESS_CONTROL,
    ),
    # PV — performance variation / SPC / measurement data
    (
        re.compile(
            r"\bspc\b|control chart|cpk\s*=|\bsigma\b|yield\s*[:=]|fallout\s*[:=]"
            r"|defect rate|ppm\s*[:=]|in control|out of control|process capability",
            re.I,
        ),
        EvidenceCategory.PERFORMANCE_VARIATION,
    ),
    # DA — detection / inspection / audit
    (
        re.compile(
            r"inspection result|audit finding|gauge reading|visual inspection.*(pass|fail)"
            r"|measurement result|gage study|gage r&r|detection.*pass|detection.*fail",
            re.I,
        ),
        EvidenceCategory.DETECTION_AUDIT,
    ),
    # RC — corrective / containment
    (
        re.compile(
            r"\bcontainment\b|rework action|corrective action|\bcapa\b"
            r"|8d report|root cause.*action|immediate action|interim action",
            re.I,
        ),
        EvidenceCategory.RESPONSE_CORRECTIVE,
    ),
]


def _apply_rules(
    rules: list[tuple[re.Pattern[str], EvidenceCategory]],
    text: str,
) -> EvidenceCategory | None:
    """Return the first matching category or None."""
    for pattern, category in rules:
        if pattern.search(text):
            return category
    return None


def categorize_evidence(
    elements: list[EvidenceElement],
) -> list[EvidenceElement]:
    """Assign evidence categories to all un-categorized elements.

    Already-categorized elements are left unchanged so callers can override
    specific elements before calling this function.
    """
    for element in elements:
        if element.category != EvidenceCategory.UNCATEGORIZED:
            continue

        # 1. Try filename
        category = _apply_rules(_FILENAME_RULES, element.source)

        # 2. Fall back to text content
        if category is None:
            category = _apply_rules(_TEXT_RULES, element.text_content)

        if category is not None:
            element.category = category

    return elements


def enrich_image_evidence(
    elements: list[EvidenceElement],
    hypothesis_keywords: list[str],
) -> list[EvidenceElement]:
    """Expand image fallback text with matched hypothesis signal terms.

    When OCR is unavailable, image elements contain only filename-derived tokens.
    This function finds hypothesis keywords whose tokens overlap with those tokens
    and appends them to the evidence text, so the associator and classifier can
    link the image to the correct hypothesis.

    Only applied to IMAGE elements whose page_ref indicates no real OCR was done.
    """
    if not hypothesis_keywords:
        return elements

    for element in elements:
        if element.source_type.value != "image":
            continue
        if element.page_ref == "OCR extraction":
            continue  # Real OCR text — no enrichment needed

        element_tokens = set(re.findall(r"[a-z]{4,}", element.text_content.lower()))
        if not element_tokens:
            continue

        matched_keywords: list[str] = []
        for kw in hypothesis_keywords:
            kw_tokens = re.findall(r"[a-z]{4,}", kw.lower())
            if not kw_tokens:
                continue
            # Accept if any keyword token shares a ≥5-char prefix with any element token
            matched = any(
                any(
                    et.startswith(kt[:5]) or kt.startswith(et[:5])
                    for et in element_tokens
                    if len(et) >= 5 and len(kt) >= 5
                )
                for kt in kw_tokens
            ) or any(kt in element_tokens for kt in kw_tokens)

            if matched and kw not in matched_keywords:
                matched_keywords.append(kw)

        if matched_keywords:
            # Deterministic order
            matched_keywords = sorted(matched_keywords)[:8]
            element.text_content += (
                f" Visual evidence may relate to: {', '.join(matched_keywords)}."
            )

    return elements
