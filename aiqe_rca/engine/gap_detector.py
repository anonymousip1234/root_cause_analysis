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
