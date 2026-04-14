"""Signal-group based hypothesis builder.

Implements the AIQE Hypothesis Abstraction Guide (Phase 2):
    1. Extract signal tokens from the current input package.
    2. Group related signals using the signal_groups rules file.
    3. Convert each matched group into a cause-level, diagnostic hypothesis
       expressed as a plausible contributor (never definitive).

Core rule (non-negotiable): individual extracted terms are never promoted
directly into hypotheses. Hypotheses must be cause-level groupings that
explain *why* signals occur, while remaining diagnostic.
"""

from __future__ import annotations

import re

import yaml

from aiqe_rca.config import settings
from aiqe_rca.models.evidence import EvidenceElement
from aiqe_rca.models.hypothesis import Hypothesis, RankLabel


def _normalize_text(text: str) -> str:
    """Lowercase and collapse whitespace for deterministic matching."""
    return re.sub(r"\s+", " ", text.lower()).strip()


def _phrase_present(text: str, phrase: str) -> bool:
    """Return True if the phrase appears as a word-bounded match."""
    if not phrase:
        return False
    pattern = r"\b" + re.escape(_normalize_text(phrase)) + r"\b"
    return re.search(pattern, text) is not None


def _build_combined_text(
    problem_statement: str, evidence_elements: list[EvidenceElement]
) -> str:
    """Combine problem statement and evidence into one normalized string."""
    parts = [problem_statement]
    parts.extend(element.text_content for element in evidence_elements)
    return _normalize_text(" ".join(parts))


def _load_signal_groups() -> list[dict]:
    """Load the signal group rules from YAML."""
    path = settings.rules_dir / "signal_groups.yaml"
    with open(path, encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    return list(data.get("signal_groups", []))


def _matched_signals(group: dict, combined_text: str) -> list[str]:
    """Return every signal phrase from a group that is present in the input."""
    matches: list[str] = []
    for signal in group.get("signals", []):
        if _phrase_present(combined_text, signal):
            matches.append(signal)
    # Deterministic order, unique.
    seen: set[str] = set()
    ordered: list[str] = []
    for signal in matches:
        key = signal.lower()
        if key in seen:
            continue
        seen.add(key)
        ordered.append(signal)
    return ordered


def _matched_contradicting_signals(group: dict, combined_text: str) -> list[str]:
    """Return contradiction markers from a group that are present in the input."""
    matches: list[str] = []
    for signal in group.get("contradicting_signals", []):
        if _phrase_present(combined_text, signal):
            matches.append(signal)
    return matches


def _score_group(
    matched_signals: list[str],
    contradicting_signals: list[str],
    problem_hits: int,
) -> float:
    """Rank groups by how strongly the current input evokes them.

    Higher support and problem-statement hits push the group up.
    Contradicting markers push it down but do not disqualify it — a group
    that is both evoked and contradicted must still appear so the alignment
    classifier can tag it explicitly.
    """
    return (
        len(matched_signals) * 1.5
        + problem_hits * 0.75
        - len(contradicting_signals) * 0.5
    )


def build_hypotheses(
    problem_statement: str,
    evidence_elements: list[EvidenceElement],
    min_hypotheses: int | None = None,
    max_hypotheses: int | None = None,
) -> list[Hypothesis]:
    """Generate 2-4 cause-level diagnostic hypotheses from the current input."""
    min_h = min_hypotheses if min_hypotheses is not None else settings.min_hypotheses
    max_h = max_hypotheses if max_hypotheses is not None else settings.max_hypotheses

    combined_text = _build_combined_text(problem_statement, evidence_elements)
    normalized_problem = _normalize_text(problem_statement)

    groups = _load_signal_groups()
    scored: list[dict] = []
    for group in groups:
        matched = _matched_signals(group, combined_text)
        contradicting = _matched_contradicting_signals(group, combined_text)
        if not matched and not contradicting:
            continue
        problem_hits = sum(
            1 for signal in matched if _phrase_present(normalized_problem, signal)
        )
        scored.append(
            {
                "group": group,
                "matched_signals": matched,
                "contradicting_signals": contradicting,
                "problem_hits": problem_hits,
                "score": _score_group(matched, contradicting, problem_hits),
            }
        )

    # Partition into supporting candidates (more matched than contradicting)
    # and false-lead candidates (contradicting signals dominate). The guide
    # requires that contradicted explanations be explicitly surfaced, so we
    # reserve slots for them instead of dropping them off the bottom of the
    # ranking.
    supporting_candidates = sorted(
        [item for item in scored if len(item["matched_signals"]) >= len(item["contradicting_signals"])],
        key=lambda item: (
            -item["score"],
            -len(item["matched_signals"]),
            item["group"]["id"],
        ),
    )
    false_lead_candidates = sorted(
        [item for item in scored if len(item["contradicting_signals"]) > len(item["matched_signals"])],
        key=lambda item: (
            -len(item["contradicting_signals"]),
            -item["score"],
            item["group"]["id"],
        ),
    )

    supporting_slots = max(min_h, max_h - min(len(false_lead_candidates), max(0, max_h - 2)))
    supporting_slots = min(supporting_slots, max_h)
    selected = supporting_candidates[:supporting_slots]
    for candidate in false_lead_candidates:
        if len(selected) >= max_h:
            break
        selected.append(candidate)

    # If we have fewer than the minimum, pad with the next best groups from
    # the YAML order so the pipeline still runs deterministically.
    if len(selected) < min_h:
        selected_ids = {item["group"]["id"] for item in selected}
        for group in groups:
            if group["id"] in selected_ids:
                continue
            matched = _matched_signals(group, combined_text) or list(
                group.get("signals", [])[:1]
            )
            selected.append(
                {
                    "group": group,
                    "matched_signals": matched,
                    "contradicting_signals": _matched_contradicting_signals(group, combined_text),
                    "problem_hits": 0,
                    "score": 0.0,
                }
            )
            if len(selected) >= min_h:
                break

    hypotheses: list[Hypothesis] = []
    for index, item in enumerate(selected, start=1):
        group = item["group"]
        # Keywords passed downstream are the signal member terms. The
        # alignment classifier uses these to find evidence matches without
        # the hypothesis name itself leaking into evidence linkage.
        keywords = sorted(
            {signal.lower() for signal in group.get("signals", [])}
            | {signal.lower() for signal in item["matched_signals"]}
        )
        description = (
            f"The current input is consistent with {group['name']}. "
            f"Matched signals: {', '.join(item['matched_signals']) or 'none'}."
        )
        hypotheses.append(
            Hypothesis(
                id=f"H{index}",
                description=description,
                template_id=group["id"],
                process_step=group["name"],
                rank_label=RankLabel.UNRANKED,
                keywords=keywords,
                net_support=0,
                gap_severity=0,
                associated_evidence_ids=[],
            )
        )

    return hypotheses
