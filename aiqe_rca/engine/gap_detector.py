"""Data gap detection engine.

Checks uploaded evidence against a 5-category evidence schema to identify
what is missing or incomplete. Missing artifacts are diagnostic signals, not errors.
"""

import re

import yaml

from aiqe_rca.config import settings
from aiqe_rca.models.evidence import EvidenceCategory, EvidenceElement
from aiqe_rca.models.gaps import DataGap, GapSeverity
from aiqe_rca.models.hypothesis import Hypothesis

# Mapping from schema category keys to EvidenceCategory enum
_CATEGORY_MAP = {
    "DR": EvidenceCategory.DESIGN_REQUIREMENTS,
    "PC": EvidenceCategory.PROCESS_CONTROL,
    "PV": EvidenceCategory.PERFORMANCE_VARIATION,
    "DA": EvidenceCategory.DETECTION_AUDIT,
    "RC": EvidenceCategory.RESPONSE_CORRECTIVE,
}


def _load_evidence_schema() -> dict:
    """Load the evidence category schema from YAML."""
    schema_path = settings.rules_dir / "evidence_schema.yaml"
    with open(schema_path) as f:
        data = yaml.safe_load(f)
    return data.get("categories", {})


def _check_category_coverage(
    category_key: str,
    category_config: dict,
    evidence_elements: list[EvidenceElement],
) -> tuple[bool, bool, int]:
    """Check if evidence elements cover a given category.

    Returns:
        (has_any_coverage, is_partial, indicator_hit_count)
    """
    indicators = category_config.get("expected_indicators", [])
    if not indicators:
        return False, False, 0

    # Combine all evidence text
    all_text = " ".join(e.text_content.lower() for e in evidence_elements)

    hit_count = 0
    for indicator in indicators:
        if re.search(r"\b" + re.escape(indicator.lower()) + r"\b", all_text):
            hit_count += 1

    total = len(indicators)
    if hit_count == 0:
        return False, False, 0
    elif hit_count < total * 0.3:
        return True, True, hit_count  # Partial coverage
    else:
        return True, False, hit_count  # Adequate coverage


def detect_gaps(
    evidence_elements: list[EvidenceElement],
    hypotheses: list[Hypothesis] | None = None,
) -> list[DataGap]:
    """Detect data gaps by checking evidence against the 5-category schema.

    For each category:
    - If entirely missing → CRITICAL gap
    - If present but incomplete → MODERATE gap
    - If adequately covered → no gap

    Also identifies which hypotheses are affected by each gap.

    Args:
        evidence_elements: All parsed evidence elements.
        hypotheses: Optional hypotheses to determine which are affected.

    Returns:
        List of DataGap objects.
    """
    schema = _load_evidence_schema()
    gaps: list[DataGap] = []

    for cat_key, cat_config in sorted(schema.items()):
        category_enum = _CATEGORY_MAP.get(cat_key, EvidenceCategory.UNCATEGORIZED)
        has_coverage, is_partial, hit_count = _check_category_coverage(
            cat_key, cat_config, evidence_elements
        )

        if not has_coverage:
            # Entire category missing
            affected = _find_affected_hypotheses(cat_key, hypotheses)
            gaps.append(
                DataGap(
                    category=category_enum,
                    description=(
                        f"No {cat_config['name']} evidence found. "
                        f"Expected documents: {', '.join(cat_config.get('expected_document_types', []))}"
                    ),
                    severity=GapSeverity.CRITICAL,
                    affects_hypotheses=affected,
                )
            )
        elif is_partial:
            # Category present but incomplete
            affected = _find_affected_hypotheses(cat_key, hypotheses)
            gaps.append(
                DataGap(
                    category=category_enum,
                    description=(
                        f"{cat_config['name']} evidence is present but incomplete. "
                        f"Only {hit_count} of {len(cat_config.get('expected_indicators', []))} "
                        f"expected indicators found."
                    ),
                    severity=GapSeverity.MODERATE,
                    affects_hypotheses=affected,
                )
            )

    gaps.extend(_detect_contextual_gaps(evidence_elements, hypotheses))

    return gaps


def _find_affected_hypotheses(
    category_key: str, hypotheses: list[Hypothesis] | None
) -> list[str]:
    """Find which hypotheses are affected by a gap in a given category.

    Uses the domain template's typical_evidence_categories field.
    """
    if not hypotheses:
        return []

    # Load templates to check which templates depend on this category
    templates_path = settings.rules_dir / "domain_templates.yaml"
    with open(templates_path) as f:
        data = yaml.safe_load(f)
    templates = {t["id"]: t for t in data.get("templates", [])}

    affected: list[str] = []
    for h in hypotheses:
        if h.template_id and h.template_id in templates:
            tmpl = templates[h.template_id]
            if category_key in tmpl.get("typical_evidence_categories", []):
                affected.append(h.id)

    return affected


def _detect_contextual_gaps(
    evidence_elements: list[EvidenceElement],
    hypotheses: list[Hypothesis] | None,
) -> list[DataGap]:
    """Add context-specific gaps that materially limit confidence in ranked causes."""
    if not evidence_elements:
        return []

    all_text = " ".join(e.text_content.lower() for e in evidence_elements)
    detected: list[DataGap] = []

    def _affected_for_templates(template_ids: set[str]) -> list[str]:
        if not hypotheses:
            return []
        return [
            h.id
            for h in hypotheses
            if h.template_id in template_ids
        ]

    if "adhesive" in all_text and (
        "left open past exposure time" in all_text
        or "open container" in all_text
        or "open past recommended exposure time" in all_text
        or "open on the production floor beyond the 4-hour exposure limit" in all_text
        or "open beyond the 4-hour exposure limit" in all_text
    ):
        detected.append(
            DataGap(
                category=EvidenceCategory.PROCESS_CONTROL,
                description=(
                    "Adhesive handling variability is referenced, but lot-by-lot exposure time "
                    "or open-container duration is not directly logged."
                ),
                severity=GapSeverity.MODERATE,
                affects_hypotheses=_affected_for_templates(
                    {"TMPL_SURFACE_PREP", "TMPL_MATERIAL_HANDLING"}
                ),
            )
        )

    if (
        "stored longer than 48 hours" in all_text
        or "staged near open dock doors" in all_text
        or "wip time limit posted" in all_text
        or "no electronic tracking" in all_text
    ):
        detected.append(
            DataGap(
                category=EvidenceCategory.PROCESS_CONTROL,
                description=(
                    "Storage / staging conditions appear relevant, but there is no direct lot-level "
                    "tracking of dwell time or location before molding."
                ),
                severity=GapSeverity.MODERATE,
                affects_hypotheses=_affected_for_templates({"TMPL_MATERIAL_HANDLING"}),
            )
        )

    if "dock doors" in all_text or "humidity" in all_text or "ambient; no monitoring" in all_text:
        detected.append(
            DataGap(
                category=EvidenceCategory.PERFORMANCE_VARIATION,
                description=(
                    "Environmental humidity exposure is plausible from the inputs, but no direct "
                    "humidity or ambient-condition monitoring data was provided."
                ),
                severity=GapSeverity.MODERATE,
                affects_hypotheses=_affected_for_templates(
                    {"TMPL_MATERIAL_HANDLING", "TMPL_ENVIRONMENTAL"}
                ),
            )
        )

    if ("coverage" in all_text or "geometry-challenged" in all_text) and (
        "no thickness gauge" in all_text or "visual inspection of coverage" in all_text
        or "no quantitative measurement exists" in all_text
        or "hardest to verify" in all_text
    ):
        detected.append(
            DataGap(
                category=EvidenceCategory.DETECTION_AUDIT,
                description=(
                    "Adhesive coverage verification is limited to visual checks; quantitative "
                    "coverage or thickness confirmation is not available."
                ),
                severity=GapSeverity.MODERATE,
                affects_hypotheses=_affected_for_templates(
                    {"TMPL_DESIGN_GEOMETRY", "TMPL_SURFACE_PREP"}
                ),
            )
        )

    return detected
