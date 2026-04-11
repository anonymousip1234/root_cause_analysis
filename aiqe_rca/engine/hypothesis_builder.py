"""Input-driven hypothesis builder.

Generates 2-4 candidate hypotheses from the current problem statement and
parsed evidence only. No prior domain templates or persisted vocabulary are used.
"""

import re
from collections import defaultdict

from aiqe_rca.config import settings
from aiqe_rca.models.evidence import EvidenceElement
from aiqe_rca.models.hypothesis import Hypothesis, RankLabel

_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "if",
    "in",
    "into",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "their",
    "this",
    "to",
    "was",
    "were",
    "with",
    "while",
    "after",
    "before",
    "during",
    "under",
    "than",
    "then",
    "than",
    "current",
    "controls",
    "control",
    "function",
    "process",
    "part",
    "customer",
    "supplier",
    "revision",
    "date",
    "range",
    "step",
    "effect",
    "sev",
    "occ",
    "det",
    "rpn",
    "report",
    "data",
    "notes",
    "review",
    "line",
    "shift",
    "lot",
    "lots",
    "between",
    "across",
    "during",
    "within",
    "remain",
    "remained",
    "observed",
    "show",
    "shows",
    "showed",
    "stable",
    "stayed",
    "unchanged",
    "limits",
    "passed",
    "normal",
    "acceptable",
    "verified",
    "noted",
    "noting",
    "found",
    "inspection",
    "recorded",
    "period",
    "periods",
    "current",
}

_ISSUE_CUES = {
    "failure",
    "defect",
    "issue",
    "problem",
    "cause",
    "variation",
    "drift",
    "wear",
    "flow",
    "vibration",
    "chatter",
    "instability",
    "inconsistent",
    "intermittent",
    "correlation",
    "coverage",
    "contamination",
    "coolant",
    "feed",
    "tool",
    "pressure",
    "temperature",
    "open",
    "leak",
    "blistering",
}


def _normalize_text(text: str) -> str:
    """Normalize whitespace for deterministic text matching."""
    return re.sub(r"\s+", " ", text.lower()).strip()


def _tokenize(text: str) -> list[str]:
    """Tokenize text while preserving slash and hyphen compounds."""
    return re.findall(r"[a-z0-9]+(?:[/-][a-z0-9]+)*", _normalize_text(text))


def _build_combined_text(
    problem_statement: str, evidence_elements: list[EvidenceElement]
) -> str:
    """Combine problem statement and evidence into one searchable string."""
    parts = [problem_statement]
    parts.extend(e.text_content for e in evidence_elements)
    return " ".join(parts)


def _split_sentences(text: str) -> list[str]:
    """Split evidence into coarse reasoning statements."""
    normalized = text.replace("•", ". ").replace(";", ". ")
    parts = re.split(r"[.\n]+", normalized)
    return [part.strip() for part in parts if part.strip()]


def _valid_phrase(tokens: list[str]) -> bool:
    """Filter out low-signal phrases."""
    if not tokens:
        return False
    if all(token in _STOPWORDS for token in tokens):
        return False
    if len(tokens) == 1 and tokens[0] not in _ISSUE_CUES and len(tokens[0]) < 7:
        return False
    if all(token.isdigit() for token in tokens):
        return False
    return True


def _extract_signal_candidates(problem_statement: str, evidence_elements: list[EvidenceElement]) -> list[dict]:
    """Extract phrase candidates directly from the current input package."""
    candidates: dict[str, dict] = defaultdict(
        lambda: {"count": 0, "problem_hits": 0, "cue_hits": 0, "sources": set(), "tokens": []}
    )

    source_texts = [("problem_statement", problem_statement)] + [
        (e.source, e.text_content) for e in evidence_elements
    ]

    for source, text in source_texts:
        for sentence in _split_sentences(text):
            sentence_tokens = _tokenize(sentence)
            cue_hit = any(token in _ISSUE_CUES for token in sentence_tokens)
            filtered = [token for token in sentence_tokens if token not in _STOPWORDS]

            for n in (3, 2, 1):
                for idx in range(len(filtered) - n + 1):
                    ngram = filtered[idx : idx + n]
                    if not _valid_phrase(ngram):
                        continue
                    phrase = " ".join(ngram)
                    if len(phrase) < 5:
                        continue

                    item = candidates[phrase]
                    item["count"] += 1
                    item["tokens"] = ngram
                    item["sources"].add(source)
                    if source == "problem_statement":
                        item["problem_hits"] += 1
                    if cue_hit:
                        item["cue_hits"] += 1

    scored: list[dict] = []
    for phrase, stats in candidates.items():
        tokens = stats["tokens"]
        unique_sources = len(stats["sources"])
        informative = any(token in _ISSUE_CUES for token in tokens)
        if not informative and unique_sources < 2:
            continue
        score = (
            stats["count"] * 1.5
            + stats["problem_hits"] * 1.0
            + stats["cue_hits"] * 0.75
            + unique_sources * 0.5
            + (1.0 if len(tokens) >= 2 else -0.25)
        )
        scored.append(
            {
                "phrase": phrase,
                "tokens": tokens,
                "score": score,
                "sources": sorted(stats["sources"]),
            }
        )

    scored.sort(key=lambda item: (-item["score"], -len(item["tokens"]), item["phrase"]))
    return scored


def _select_distinct_signals(candidates: list[dict], min_h: int, max_h: int) -> list[dict]:
    """Select 2-4 distinct phrases without reusing the same core tokens."""
    selected: list[dict] = []
    used_tokens: set[str] = set()

    for candidate in candidates:
        if len(candidate["tokens"]) == 1:
            token = candidate["tokens"][0]
            has_longer_neighbor = any(
                other is not candidate
                and token in other["tokens"]
                and len(other["tokens"]) > 1
                and other["score"] >= candidate["score"] - 1.0
                for other in candidates
            )
            if has_longer_neighbor:
                continue
        phrase_tokens = set(candidate["tokens"])
        replacement_index = next(
            (
                index
                for index, existing in enumerate(selected)
                if set(existing["tokens"]) & phrase_tokens
                and len(existing["tokens"]) == 1
                and len(candidate["tokens"]) > 1
            ),
            None,
        )
        if replacement_index is not None:
            selected[replacement_index] = candidate
            used_tokens = set().union(*(set(item["tokens"]) for item in selected))
            continue
        if phrase_tokens and len(phrase_tokens & used_tokens) >= max(1, len(phrase_tokens) - 1):
            continue
        selected.append(candidate)
        used_tokens.update(phrase_tokens)
        if len(selected) >= max_h:
            break

    if len(selected) < min_h:
        for candidate in candidates:
            if candidate in selected:
                continue
            selected.append(candidate)
            if len(selected) >= min_h:
                break

    return selected[:max_h]


def build_hypotheses(
    problem_statement: str,
    evidence_elements: list[EvidenceElement],
    min_hypotheses: int | None = None,
    max_hypotheses: int | None = None,
) -> list[Hypothesis]:
    """Generate 2-4 candidate hypotheses from current input signals only."""
    min_h = min_hypotheses if min_hypotheses is not None else settings.min_hypotheses
    max_h = max_hypotheses if max_hypotheses is not None else settings.max_hypotheses

    candidates = _extract_signal_candidates(problem_statement, evidence_elements)
    selected = _select_distinct_signals(candidates, min_h=min_h, max_h=max_h)

    hypotheses: list[Hypothesis] = []
    for idx, candidate in enumerate(selected, start=1):
        phrase = candidate["phrase"]
        tokens = candidate["tokens"]
        keywords = sorted(set(tokens + [phrase]))
        hypotheses.append(
            Hypothesis(
                id=f"H{idx}",
                description=f"Current input repeatedly references {phrase} in connection with the reported issue.",
                template_id=None,
                process_step=phrase,
                rank_label=RankLabel.UNRANKED,
                keywords=keywords,
                net_support=0,
                gap_severity=0,
                associated_evidence_ids=[],
            )
        )

    return hypotheses
