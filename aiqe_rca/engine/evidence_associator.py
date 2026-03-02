"""Evidence-to-hypothesis association engine.

Uses keyword overlap + fixed local embeddings (all-MiniLM-L6-v2) to link
evidence elements to hypotheses. Fully deterministic — CPU-only, pinned model.
"""

import re
from functools import lru_cache

import numpy as np

from aiqe_rca.config import settings
from aiqe_rca.models.evidence import EvidenceElement
from aiqe_rca.models.hypothesis import Hypothesis


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

    # Build hypothesis description texts for embedding
    hypothesis_texts = [
        f"{h.process_step}: {h.description}" for h in hypotheses
    ]
    evidence_texts = [e.text_content for e in evidence_elements]

    # Compute embeddings (deterministic: CPU, same model, same inputs → same outputs)
    all_texts = hypothesis_texts + evidence_texts
    all_embeddings = EmbeddingModel.encode(all_texts)

    h_embeddings = all_embeddings[: len(hypotheses)]
    e_embeddings = all_embeddings[len(hypotheses) :]

    # Associate
    for h_idx, hypothesis in enumerate(hypotheses):
        associated_ids: list[str] = []
        for e_idx, evidence in enumerate(evidence_elements):
            # Keyword score
            kw_score = _keyword_overlap_score(evidence.text_content, hypothesis.keywords)

            # Embedding similarity
            emb_score = _cosine_similarity(h_embeddings[h_idx], e_embeddings[e_idx])
            # Clamp to [0, 1]
            emb_score = max(0.0, emb_score)

            combined = kw_w * kw_score + emb_w * emb_score

            if combined >= thresh:
                associated_ids.append(evidence.id)

        hypothesis.associated_evidence_ids = associated_ids

    return hypotheses
