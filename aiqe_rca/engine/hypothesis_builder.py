"""Rule-based hypothesis builder.

Generates 2–4 candidate hypotheses by matching the problem statement
and parsed evidence against domain failure pattern templates.
No ML or LLM involved — purely deterministic keyword matching.
"""

import re

import yaml

from aiqe_rca.config import settings
from aiqe_rca.models.evidence import EvidenceElement
from aiqe_rca.models.hypothesis import Hypothesis, RankLabel

_GENERIC_KEYWORDS = {
    "line",
    "shift",
    "time",
    "temp",
    "test",
    "audit",
    "visual",
    "manual",
    "finding",
    "customer",
    "inspection",
    "detection",
    "material",
    "data",
}


def _load_domain_templates() -> list[dict]:
    """Load domain templates from YAML config."""
    templates_path = settings.rules_dir / "domain_templates.yaml"
    with open(templates_path) as f:
        data = yaml.safe_load(f)
    return data.get("templates", [])


def _compute_keyword_hits(text: str, keywords: list[str]) -> int:
    """Count how many keywords appear in the text (case-insensitive, whole-word)."""
    return int(_compute_weighted_keyword_hits(text, keywords))


def _keyword_weight(keyword: str) -> float:
    """Weight keywords by specificity to reduce false-lead template inflation."""
    kw = keyword.lower().strip()
    if kw in _GENERIC_KEYWORDS:
        return 0.2
    if " " in kw:
        return 1.6
    if len(kw) >= 8:
        return 1.25
    if len(kw) >= 5:
        return 1.0
    return 0.5


def _compute_weighted_keyword_hits(text: str, keywords: list[str]) -> float:
    """Compute a weighted keyword hit score."""
    text_lower = text.lower()
    hits = 0.0
    for kw in keywords:
        # Use word boundary matching for multi-word keywords
        pattern = re.escape(kw.lower())
        if re.search(r"\b" + pattern + r"\b", text_lower):
            hits += _keyword_weight(kw)
    return hits


def _count_phrase_hits(text: str, phrases: list[str]) -> int:
    """Count phrase occurrences using deterministic substring matching."""
    text_lower = text.lower()
    return sum(1 for phrase in phrases if phrase.lower() in text_lower)


def _build_combined_text(
    problem_statement: str, evidence_elements: list[EvidenceElement]
) -> str:
    """Combine problem statement and all evidence text into one searchable string."""
    parts = [problem_statement]
    for e in evidence_elements:
        parts.append(e.text_content)
    return " ".join(parts)


def build_hypotheses(
    problem_statement: str,
    evidence_elements: list[EvidenceElement],
    min_hypotheses: int | None = None,
    max_hypotheses: int | None = None,
) -> list[Hypothesis]:
    """Generate 2–4 candidate hypotheses from problem statement + evidence.

    Logic:
    1. Load all domain templates.
    2. Score each template by keyword hits against combined text.
    3. Select top N templates (within min/max bounds).
    4. Convert to Hypothesis objects.

    Args:
        problem_statement: User-provided problem description.
        evidence_elements: Parsed evidence from uploaded documents.
        min_hypotheses: Override minimum (default from config).
        max_hypotheses: Override maximum (default from config).

    Returns:
        List of Hypothesis objects (unranked at this stage).
    """
    min_h = min_hypotheses if min_hypotheses is not None else settings.min_hypotheses
    max_h = max_hypotheses if max_hypotheses is not None else settings.max_hypotheses

    templates = _load_domain_templates()
    combined_text = _build_combined_text(problem_statement, evidence_elements)

    # Score each template using weighted keywords, explicit support cues,
    # and weakening penalties to reduce false-lead templates.
    scored: list[tuple[dict, float]] = []
    for tmpl in templates:
        keywords = tmpl.get("keywords", [])
        aliases = tmpl.get("aliases", [])
        keyword_score = _compute_weighted_keyword_hits(combined_text, keywords + aliases)
        support_boost = _count_phrase_hits(combined_text, tmpl.get("support_indicators", [])) * 0.75
        weakening_penalty = _count_phrase_hits(
            combined_text, tmpl.get("weakening_indicators", [])
        ) * 1.1
        selection_bias = float(tmpl.get("selection_bias", 0.0))
        score = keyword_score + support_boost + selection_bias - weakening_penalty
        if score > 0:
            scored.append((tmpl, score))

    # Sort by hits descending (deterministic: stable sort, then by template id for ties)
    scored.sort(key=lambda x: (-x[1], x[0]["id"]))

    # Select within bounds
    selected = scored[:max_h]

    # Ensure minimum: if we have fewer matches than min_h, pad with top unmatched templates
    if len(selected) < min_h:
        selected_ids = {s[0]["id"] for s in selected}
        for tmpl in templates:
            if tmpl["id"] not in selected_ids:
                selected.append((tmpl, 0))
                if len(selected) >= min_h:
                    break

    # Convert to Hypothesis objects
    hypotheses: list[Hypothesis] = []
    for idx, (tmpl, hits) in enumerate(selected, start=1):
        hypotheses.append(
            Hypothesis(
                id=f"H{idx}",
                description=tmpl["description"],
                template_id=tmpl["id"],
                process_step=tmpl["name"],
                rank_label=RankLabel.UNRANKED,
                keywords=tmpl.get("keywords", []) + tmpl.get("aliases", []),
                net_support=0,
                gap_severity=0,
                associated_evidence_ids=[],
            )
        )

    return hypotheses
