"""Language lint engine.

Scans report sections for disallowed wording (directive verbs, absolutes,
math/scoring terms) before finalization. Must pass before a report is emitted.
"""

import re

import yaml

from aiqe_rca.config import settings

# Section key mapping for lint rules
_SECTION_KEY_MAP = {
    "Executive Diagnostic Summary": "executive_diagnostic_summary",
    "Most Likely Root Cause Hypotheses": "contributing_hypotheses",
    "Why AIQE Believes This": "why_aiqe_believes_this",
    "Immediate Actions to Test": "immediate_actions_to_test",
    "Analysis Confidence Statement": "analysis_confidence_statement",
}


def _load_language_rules() -> dict:
    """Load language rules from YAML."""
    rules_path = settings.rules_dir / "language_rules.yaml"
    with open(rules_path) as f:
        return yaml.safe_load(f)


class LintResult:
    """Result of a language lint check."""

    def __init__(self):
        self.passed = True
        self.violations: list[dict[str, str]] = []

    def add_violation(self, section: str, term: str, context: str):
        self.passed = False
        self.violations.append({
            "section": section,
            "term": term,
            "context": context,
        })


def lint_section(section_title: str, content: str, rules: dict) -> list[dict[str, str]]:
    """Lint a single section against language rules.

    Returns list of violations (empty = passed).
    """
    violations: list[dict[str, str]] = []
    content_lower = content.lower()

    # Check global disallowed terms
    global_disallowed = rules.get("global_disallowed", [])
    for term in global_disallowed:
        if term.lower() in content_lower:
            violations.append({
                "section": section_title,
                "term": term,
                "context": f"Global disallowed term '{term}' found in section.",
            })

    # Check section-specific disallowed patterns
    section_key = _SECTION_KEY_MAP.get(section_title, "")
    section_rules = rules.get("sections", {}).get(section_key, {})
    for pattern in section_rules.get("disallowed_patterns", []):
        if pattern.lower() in content_lower:
            violations.append({
                "section": section_title,
                "term": pattern,
                "context": f"Section-specific disallowed pattern '{pattern}' found.",
            })

    return violations


def lint_report(sections: list[tuple[str, str]]) -> LintResult:
    """Lint all report sections.

    Args:
        sections: List of (section_title, section_content) tuples.

    Returns:
        LintResult with pass/fail and all violations.
    """
    rules = _load_language_rules()
    result = LintResult()

    for title, content in sections:
        violations = lint_section(title, content, rules)
        for v in violations:
            result.add_violation(v["section"], v["term"], v["context"])

    return result
