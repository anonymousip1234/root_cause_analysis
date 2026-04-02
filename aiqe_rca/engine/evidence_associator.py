"""Evidence-to-hypothesis association engine.

Uses keyword overlap + fixed local embeddings (all-MiniLM-L6-v2) to link
evidence elements to hypotheses. Fully deterministic — CPU-only, pinned model.
"""

import re

import numpy as np

from aiqe_rca.config import settings
from aiqe_rca.models.evidence import EvidenceElement
from aiqe_rca.models.hypothesis import Hypothesis

_TOKEN_STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "into",
    "that",
    "this",
    "were",
    "was",
    "have",
    "has",
    "been",
    "being",
    "show",
    "shows",
    "showed",
    "data",
    "test",
    "report",
    "step",
    "process",
    "failure",
    "variation",
}


class EmbeddingModel:
    """Singleton wrapper for the pinned sentence-transformers model."""

    _instance = None
    _model = None

    @classmethod
    def get_model(cls):
        if cls._model is None:
            from sentence_transformers import SentenceTransformer

            cls._model = SentenceTransformer(
                settings.embedding_model_name,
                device=settings.embedding_device,
                local_files_only=True,
            )
        return cls._model

    @classmethod
    def encode(cls, texts: list[str]) -> np.ndarray:
        model = cls.get_model()
        return model.encode(
            texts,
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )


def _keyword_overlap_score(text: str, keywords: list[str]) -> float:
    """Compute normalized keyword overlap between text and keyword list."""
    if not keywords:
        return 0.0
    text_lower = text.lower()
    hits = 0
    for kw in keywords:
        pattern = re.escape(kw.lower())
        if re.search(r"\b" + pattern + r"\b", text_lower):
            hits += 1
    return hits / len(keywords)


def _normalize_tokens(text: str) -> set[str]:
    """Convert text into a deterministic set of informative tokens."""
    tokens = re.findall(r"[a-z0-9]{3,}", text.lower())
    return {
        token
        for token in tokens
        if token not in _TOKEN_STOPWORDS and not token.isdigit()
    }


def _lexical_similarity(a_text: str, b_text: str) -> float:
    """Compute a lightweight deterministic lexical similarity score."""
    a_tokens = _normalize_tokens(a_text)
    b_tokens = _normalize_tokens(b_text)
    if not a_tokens or not b_tokens:
        return 0.0
    intersection = len(a_tokens & b_tokens)
    denominator = max(1, min(len(a_tokens), len(b_tokens)))
    return intersection / denominator


def _pattern_bonus(text: str, phrases: list[str]) -> float:
    """Boost association when explicit hypothesis phrases appear."""
    text_lower = text.lower()
    hits = sum(1 for phrase in phrases if phrase.lower() in text_lower)
    return min(hits * 0.15, 0.45)


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Compute cosine similarity between two normalized vectors."""
    return float(np.dot(a, b))


def associate_evidence(
    hypotheses: list[Hypothesis],
    evidence_elements: list[EvidenceElement],
    keyword_weight: float | None = None,
    embedding_weight: float | None = None,
    threshold: float | None = None,
) -> list[Hypothesis]:
    """Associate evidence elements with hypotheses based on relevance.

    For each (hypothesis, evidence) pair:
    1. Compute keyword overlap score
    2. Compute embedding cosine similarity
    3. Combined score = keyword_weight * kw_score + embedding_weight * emb_score
    4. If combined >= threshold, associate evidence to hypothesis

    Args:
        hypotheses: Candidate hypotheses (will be updated in-place with evidence IDs).
        evidence_elements: All parsed evidence elements.
        keyword_weight: Weight for keyword score (default from config).
        embedding_weight: Weight for embedding score (default from config).
        threshold: Association threshold (default from config).

    Returns:
        Updated hypotheses with associated_evidence_ids populated.
    """
    kw_w = keyword_weight if keyword_weight is not None else settings.keyword_weight
    emb_w = embedding_weight if embedding_weight is not None else settings.embedding_weight
    thresh = threshold if threshold is not None else settings.association_threshold

    if not evidence_elements or not hypotheses:
        return hypotheses

    hypothesis_texts = [f"{h.process_step}: {h.description}" for h in hypotheses]
    evidence_texts = [e.text_content for e in evidence_elements]

    # Try fixed local embeddings only if the model is already present locally.
    h_embeddings = None
    e_embeddings = None
    try:
        all_texts = hypothesis_texts + evidence_texts
        all_embeddings = EmbeddingModel.encode(all_texts)
        h_embeddings = all_embeddings[: len(hypotheses)]
        e_embeddings = all_embeddings[len(hypotheses) :]
    except Exception:
        # Fall back to lexical association only.
        h_embeddings = None
        e_embeddings = None

    # Associate
    for h_idx, hypothesis in enumerate(hypotheses):
        associated_ids: list[str] = []
        alias_terms = getattr(hypothesis, "keywords", [])
        for e_idx, evidence in enumerate(evidence_elements):
            # Keyword score
            kw_score = _keyword_overlap_score(evidence.text_content, hypothesis.keywords)
            lexical_score = _lexical_similarity(
                evidence.text_content,
                f"{hypothesis.process_step or ''} {hypothesis.description} {' '.join(alias_terms)}",
            )
            phrase_score = _pattern_bonus(evidence.text_content, alias_terms)

            emb_score = 0.0
            if h_embeddings is not None and e_embeddings is not None:
                emb_score = _cosine_similarity(h_embeddings[h_idx], e_embeddings[e_idx])
                emb_score = max(0.0, emb_score)

            lexical_combined = 0.65 * kw_score + 0.25 * lexical_score + 0.10 * phrase_score
            combined = lexical_combined
            if emb_score > 0.0:
                combined = (kw_w * kw_score) + (0.25 * lexical_score) + (0.10 * phrase_score) + (
                    emb_w * emb_score * 0.5
                )

            if combined >= max(thresh, 0.10):
                associated_ids.append(evidence.id)

        hypothesis.associated_evidence_ids = associated_ids

    return hypotheses
