"""Pattern fact layer — detects higher-level diagnostic patterns from observation evidence.

This layer sits between raw evidence and hypothesis generation. It converts
observation-derived evidence items into diagnostic facts (INTERMITTENT_FAILURE,
NO_SINGLE_VARIABLE_SEPARATION, MULTIPLE_VARIABLES_NEAR_LIMIT, etc.) that can
trigger pattern-specific hypothesis classes such as CUMULATIVE_STACKUP and
TEMPORAL_DEGRADATION.

Per v3 spec Section 6: without this layer the system defaults to document-listed
causes because it cannot detect interaction, stack-up, temporal, or detection-gap
patterns from observations alone.

All detection is deterministic — identical inputs produce identical pattern facts.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel

from aiqe_rca.models.evidence import EvidenceElement
from aiqe_rca.models.hypothesis import Hypothesis, RankLabel


# ---------------------------------------------------------------------------
# PatternFact model
# ---------------------------------------------------------------------------

class PatternFact(BaseModel):
    """A higher-level diagnostic fact derived from one or more observation items."""

    fact_id: str
    fact_type: str
    summary: str
    supporting_evidence_ids: list[str]
    confidence_basis: Literal["DIRECT", "INFERRED_FROM_MULTIPLE_OBSERVATIONS", "WEAK"]


# ---------------------------------------------------------------------------
# Detection signal dictionaries
# ---------------------------------------------------------------------------

_INTERMITTENT_SIGNALS = (
    "intermittent", "occasional", "sporadic", "random failure",
    "sometimes fails", "not every part", "some parts pass", "some units",
    "inconsistent occurrence", "not all", "only some",
)

_NO_SINGLE_VARIABLE_SIGNALS = (
    "no single press", "no single machine", "no single cavity", "no single tool",
    "no clear correlation", "across presses", "across machines", "multiple machines",
    "multiple presses", "across lots", "across shifts", "all shifts", "multi-tool",
    "multi-machine", "no consistent shift", "no single variable",
    "no isolated variable", "cannot isolate",
)

_NEAR_LIMIT_SIGNALS = (
    "near limit", "approaching limit", "close to spec", "trending toward",
    "borderline", "near tolerance", "near the limit", "at the edge of",
    "just within", "marginal", "tolerance stack", "near specification",
    "close to limit", "near acceptance",
)

_AFTER_INTEGRATION_SIGNALS = (
    "after assembly", "after integration", "after cycling", "after testing",
    "in-service failure", "field failure", "found after", "post-assembly",
    "only at final", "assembly stage", "integration stage", "during cycling",
    "after full assembly", "end-use failure", "downstream failure",
)

_DETECTION_ESCAPE_SIGNALS = (
    "escaped detection", "passed inspection", "missed by inspection",
    "found at customer", "field return", "customer complaint",
    "detected downstream", "not caught", "inspection gap", "escaped",
    "detection gap", "missed defect", "slipped through",
)

_END_OF_RUN_SIGNALS = (
    "end of run", "end of tool life", "tool life", "near end of life",
    "last parts", "degradation over", "wear over time", "run length",
    "after many cycles", "as tool aged", "toward end",
)

_ENVIRONMENTAL_SIGNALS = (
    "humidity", "moisture exposure", "storage exposure",
    "temperature variation", "environmental", "ambient conditions",
    "open container", "dock doors", "shelf life exceeded",
)

_NORMAL_UPSTREAM_SIGNALS = (
    "upstream checks passed", "in-process checks", "all process checks",
    "process parameters within", "no in-process defects",
    "passed all checks", "no upstream failure",
)


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def _any_signal(text: str, signals: tuple[str, ...]) -> bool:
    norm = _normalize(text)
    return any(s in norm for s in signals)


def _matching_ids(
    elements: list[EvidenceElement],
    signals: tuple[str, ...],
) -> list[str]:
    return [e.id for e in elements if _any_signal(e.text_content, signals)]


# ---------------------------------------------------------------------------
# Pattern fact builder
# ---------------------------------------------------------------------------

def build_pattern_facts(
    observation_evidence: list[EvidenceElement],
) -> list[PatternFact]:
    """Detect diagnostic pattern facts from observation-only evidence elements.

    Returns a deterministic list of PatternFact objects in stable order.
    Must only receive observation evidence (DR/PC must already be filtered).
    """
    facts: list[PatternFact] = []
    all_text = " ".join(_normalize(e.text_content) for e in observation_evidence)

    # --- INTERMITTENT_FAILURE ---
    ids = _matching_ids(observation_evidence, _INTERMITTENT_SIGNALS)
    if ids:
        facts.append(PatternFact(
            fact_id="PF_INTERMITTENT",
            fact_type="INTERMITTENT_FAILURE",
            summary=(
                "Failures are intermittent rather than fixed to every part or every run, "
                "suggesting a condition-level variation rather than a constant defect."
            ),
            supporting_evidence_ids=ids,
            confidence_basis="DIRECT",
        ))

    # --- NO_SINGLE_VARIABLE_SEPARATION ---
    ids = _matching_ids(observation_evidence, _NO_SINGLE_VARIABLE_SIGNALS)
    if ids:
        facts.append(PatternFact(
            fact_id="PF_NO_SINGLE_VARIABLE",
            fact_type="NO_SINGLE_VARIABLE_SEPARATION",
            summary=(
                "No single machine, operator, variable, or process condition consistently "
                "separates passing from failing units."
            ),
            supporting_evidence_ids=ids,
            confidence_basis="DIRECT",
        ))

    # --- MULTIPLE_VARIABLES_NEAR_LIMIT ---
    ids = _matching_ids(observation_evidence, _NEAR_LIMIT_SIGNALS)
    if ids:
        facts.append(PatternFact(
            fact_id="PF_NEAR_LIMITS",
            fact_type="MULTIPLE_VARIABLES_NEAR_LIMIT",
            summary=(
                "One or more variables remain within specification but trend near acceptance "
                "limits, which may contribute to marginal or stack-up conditions."
            ),
            supporting_evidence_ids=ids,
            confidence_basis="INFERRED_FROM_MULTIPLE_OBSERVATIONS",
        ))

    # --- FAILURE_AFTER_INTEGRATION ---
    ids = _matching_ids(observation_evidence, _AFTER_INTEGRATION_SIGNALS)
    if ids:
        facts.append(PatternFact(
            fact_id="PF_AFTER_INTEGRATION",
            fact_type="FAILURE_AFTER_INTEGRATION",
            summary=(
                "Failure appears after full assembly, integration, or cycling rather than "
                "at isolated process checks, suggesting a functional or cumulative condition."
            ),
            supporting_evidence_ids=ids,
            confidence_basis="DIRECT",
        ))

    # --- DETECTION_ESCAPE_SIGNAL ---
    ids = _matching_ids(observation_evidence, _DETECTION_ESCAPE_SIGNALS)
    if ids:
        facts.append(PatternFact(
            fact_id="PF_DETECTION_ESCAPE",
            fact_type="DETECTION_ESCAPE_SIGNAL",
            summary=(
                "Evidence indicates defects escaped existing detection methods, "
                "pointing to a detection gap in the current inspection regime."
            ),
            supporting_evidence_ids=ids,
            confidence_basis="DIRECT",
        ))

    # --- END_OF_RUN_DEGRADATION ---
    ids = _matching_ids(observation_evidence, _END_OF_RUN_SIGNALS)
    if ids:
        facts.append(PatternFact(
            fact_id="PF_END_OF_RUN",
            fact_type="END_OF_RUN_DEGRADATION",
            summary=(
                "Failure likelihood increases toward end of tool life, run length, "
                "or storage duration, suggesting a degradation-linked mechanism."
            ),
            supporting_evidence_ids=ids,
            confidence_basis="DIRECT",
        ))

    # --- ENVIRONMENTAL_EXPOSURE_SIGNAL ---
    ids = _matching_ids(observation_evidence, _ENVIRONMENTAL_SIGNALS)
    if ids:
        facts.append(PatternFact(
            fact_id="PF_ENVIRONMENTAL",
            fact_type="ENVIRONMENTAL_EXPOSURE_SIGNAL",
            summary="Environmental or storage exposure signals are present in the evidence.",
            supporting_evidence_ids=ids,
            confidence_basis="DIRECT",
        ))

    # --- NORMAL_UPSTREAM_CHECKS ---
    ids = _matching_ids(observation_evidence, _NORMAL_UPSTREAM_SIGNALS)
    if ids:
        facts.append(PatternFact(
            fact_id="PF_NORMAL_UPSTREAM",
            fact_type="NORMAL_UPSTREAM_CHECKS",
            summary=(
                "Upstream process checks appear normal while downstream or field failures "
                "are present, narrowing the failure window."
            ),
            supporting_evidence_ids=ids,
            confidence_basis="INFERRED_FROM_MULTIPLE_OBSERVATIONS",
        ))

    return facts


# ---------------------------------------------------------------------------
# Trigger functions
# ---------------------------------------------------------------------------

def _has_fact(facts: list[PatternFact], fact_type: str) -> bool:
    return any(f.fact_type == fact_type for f in facts)


def trigger_stackup_interaction(facts: list[PatternFact]) -> bool:
    """True when pattern evidence suggests a cumulative stack-up / multi-variable interaction."""
    return (
        _has_fact(facts, "NO_SINGLE_VARIABLE_SEPARATION")
        and _has_fact(facts, "INTERMITTENT_FAILURE")
    ) or (
        _has_fact(facts, "NO_SINGLE_VARIABLE_SEPARATION")
        and _has_fact(facts, "MULTIPLE_VARIABLES_NEAR_LIMIT")
    ) or (
        _has_fact(facts, "NO_SINGLE_VARIABLE_SEPARATION")
        and _has_fact(facts, "FAILURE_AFTER_INTEGRATION")
    )


def trigger_temporal_degradation(facts: list[PatternFact]) -> bool:
    """True when evidence suggests failure grows with time or usage."""
    return _has_fact(facts, "END_OF_RUN_DEGRADATION")


def trigger_detection_gap_pattern(facts: list[PatternFact]) -> bool:
    """True when evidence suggests defects are escaping detection."""
    return _has_fact(facts, "DETECTION_ESCAPE_SIGNAL") or (
        _has_fact(facts, "FAILURE_AFTER_INTEGRATION")
        and _has_fact(facts, "NORMAL_UPSTREAM_CHECKS")
    )


# ---------------------------------------------------------------------------
# Pattern-triggered hypothesis generator
# ---------------------------------------------------------------------------

_PATTERN_HYPOTHESIS_TEMPLATES = {
    "stackup": {
        "template_id": "SG_CUMULATIVE_STACKUP",
        "process_step": (
            "cumulative stack-up or multi-variable interaction where individually "
            "acceptable conditions combine to produce failure"
        ),
        "description": (
            "The current input is consistent with a cumulative stack-up or "
            "multi-variable interaction — no single variable separates passing "
            "from failing units, which is consistent with individually acceptable "
            "conditions combining to produce failure only at certain combinations."
        ),
        "keywords": [
            "no single variable", "multiple variables", "stack-up",
            "interaction", "cumulative", "no single press", "no single machine",
            "across presses", "intermittent", "variables within spec",
        ],
    },
    "temporal": {
        "template_id": "SG_TEMPORAL_DEGRADATION",
        "process_step": (
            "temporal or end-of-run degradation that may be driving a progressive failure pattern"
        ),
        "description": (
            "The current input is consistent with a temporal or degradation-linked condition — "
            "failure likelihood may increase with run time, tool life, cycle count, "
            "or storage duration rather than being present uniformly."
        ),
        "keywords": [
            "end of run", "tool life", "degradation", "wear over time",
            "last parts", "toward end", "run length",
        ],
    },
    "detection_gap": {
        "template_id": "SG_INSPECTION_DETECTION_GAP",
        "process_step": (
            "inspection or detection gap that may allow defects to escape current checks"
        ),
        "description": (
            "The current input is consistent with an inspection or detection gap — "
            "defects may be passing existing checks and only becoming visible "
            "at downstream stages or in the field."
        ),
        "keywords": [
            "escaped detection", "passed inspection", "detection gap",
            "found at customer", "field return", "missed by inspection",
        ],
    },
}


def generate_pattern_hypotheses(facts: list[PatternFact]) -> list[Hypothesis]:
    """Generate pattern-triggered hypothesis objects from detected PatternFacts.

    These hypotheses are generated from observed evidence patterns and take
    priority over signal-group hypotheses in the final ranked list per v3 spec.
    """
    generated: list[Hypothesis] = []
    seen_template_ids: set[str] = set()

    if trigger_stackup_interaction(facts):
        tmpl = _PATTERN_HYPOTHESIS_TEMPLATES["stackup"]
        if tmpl["template_id"] not in seen_template_ids:
            generated.append(Hypothesis(
                id="HP1",  # Will be re-numbered in merge step
                description=tmpl["description"],
                template_id=tmpl["template_id"],
                process_step=tmpl["process_step"],
                rank_label=RankLabel.UNRANKED,
                keywords=tmpl["keywords"],
                net_support=0,
                gap_severity=0,
                associated_evidence_ids=[],
            ))
            seen_template_ids.add(tmpl["template_id"])

    if trigger_temporal_degradation(facts):
        tmpl = _PATTERN_HYPOTHESIS_TEMPLATES["temporal"]
        if tmpl["template_id"] not in seen_template_ids:
            generated.append(Hypothesis(
                id="HP2",
                description=tmpl["description"],
                template_id=tmpl["template_id"],
                process_step=tmpl["process_step"],
                rank_label=RankLabel.UNRANKED,
                keywords=tmpl["keywords"],
                net_support=0,
                gap_severity=0,
                associated_evidence_ids=[],
            ))
            seen_template_ids.add(tmpl["template_id"])

    if trigger_detection_gap_pattern(facts):
        tmpl = _PATTERN_HYPOTHESIS_TEMPLATES["detection_gap"]
        if tmpl["template_id"] not in seen_template_ids:
            generated.append(Hypothesis(
                id="HP3",
                description=tmpl["description"],
                template_id=tmpl["template_id"],
                process_step=tmpl["process_step"],
                rank_label=RankLabel.UNRANKED,
                keywords=tmpl["keywords"],
                net_support=0,
                gap_severity=0,
                associated_evidence_ids=[],
            ))
            seen_template_ids.add(tmpl["template_id"])

    return generated


# ---------------------------------------------------------------------------
# Template IDs used by the ranker for tier-0 priority
# ---------------------------------------------------------------------------

INTERACTION_TEMPLATE_IDS: frozenset[str] = frozenset({
    "SG_CUMULATIVE_STACKUP",
    "SG_COMPOUNDING_MULTI_FACTOR",
})

SINGLE_PROCESS_TEMPLATE_IDS: frozenset[str] = frozenset({
    "SG_MACHINING_INSTABILITY",
    "SG_COOLANT_INSTABILITY",
    "SG_SURFACE_BOND_CONDITION",
    "SG_PROCESS_PARAMETER_VARIATION",
    "SG_EQUIPMENT_SETUP_VARIATION",
})
