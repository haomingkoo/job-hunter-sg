"""
RAG embedding service for semantic job matching.

Uses sentence-transformers/all-MiniLM-L6-v2 (384-dim, normalized)
to encode job descriptions and resumes for cosine similarity search.
"""

from __future__ import annotations

import threading
import time
from datetime import timedelta
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer
    from sqlalchemy.orm import Session

_model: SentenceTransformer | None = None
_model_lock = threading.Lock()
_encode_lock = threading.Lock()
_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"


def _get_model() -> SentenceTransformer:
    """Return singleton SentenceTransformer, loading on first call."""
    global _model
    if _model is not None:
        return _model
    with _model_lock:
        if _model is not None:
            return _model
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(_MODEL_NAME)
        return _model


def encode_text(text: str) -> list[float]:
    """Encode a single text string into a 384-dim normalized vector."""
    model = _get_model()
    # Agent graphs can dispatch several tool calls from one turn in parallel.
    # Serialize the shared native model's forward pass; database work remains
    # concurrent and a whole batch still runs as one inference call.
    with _encode_lock:
        vector = model.encode(text, normalize_embeddings=True)
    return vector.tolist()


def encode_texts(texts: list[str], batch_size: int = 32) -> list[list[float]]:
    """Encode multiple texts into 384-dim normalized vectors."""
    model = _get_model()
    with _encode_lock:
        vectors = model.encode(texts, batch_size=batch_size, normalize_embeddings=True)
    return vectors.tolist()


def build_job_embed_text(
    title: str,
    description: str,
    skills: list[str] | str | None,
) -> str:
    """Combine job fields into one embedding input.

    The title is repeated twice to weight it, and the description is truncated
    to 1500 characters to cap total length.
    """
    title_part = (title or "").strip()
    if isinstance(skills, list):
        skills_part = ", ".join(str(s) for s in skills if s)
    elif isinstance(skills, str):
        skills_part = skills.strip()
    else:
        skills_part = ""
    desc_part = (description or "").strip()[:1500]

    parts = [title_part, title_part, skills_part, desc_part]
    return " ".join(p for p in parts if p)



_job_matrix: np.ndarray | None = None
_job_ids: list[int] = []
_matrix_lock = threading.Lock()
_matrix_ts: float = 0.0
_MATRIX_TTL = timedelta(days=1).total_seconds()
_matrix_generation_id: int | None = None


def _embedding_generation_id(db_session: Session) -> int | None:
    from models import UsageLog

    row = (
        db_session.query(UsageLog.id)
        .filter(UsageLog.action == "job_embedding_refresh")
        .order_by(UsageLog.id.desc())
        .first()
    )
    return int(row[0]) if row else None


def invalidate_matrix_cache() -> None:
    """Force rebuild on next similarity search."""
    global _job_matrix, _job_ids, _matrix_ts, _matrix_generation_id
    with _matrix_lock:
        _job_matrix = None
        _job_ids = []
        _matrix_ts = 0.0
        _matrix_generation_id = None


def is_similarity_matrix_ready() -> bool:
    """Return True only when similarity search can run without rebuilding."""
    with _matrix_lock:
        return (
            _job_matrix is not None
            and len(_job_ids) > 0
            and (time.monotonic() - _matrix_ts) < _MATRIX_TTL
        )


def _refresh_matrix_if_stale(db_session: Session) -> None:
    """Refresh the matrix from currently searchable jobs when stale."""
    global _job_matrix, _job_ids, _matrix_ts, _matrix_generation_id
    now = time.monotonic()
    generation_id = _embedding_generation_id(db_session)
    if (
        _job_matrix is not None
        and generation_id == _matrix_generation_id
        and (now - _matrix_ts) < _MATRIX_TTL
    ):
        return

    with _matrix_lock:
        if (
            _job_matrix is not None
            and generation_id == _matrix_generation_id
            and (time.monotonic() - _matrix_ts) < _MATRIX_TTL
        ):
            return

        from job_visibility import apply_public_job_visibility
        from models import ScrapedJob

        # Release the old matrix before loading new data so peak memory
        # stays ~1× matrix size instead of ~3× (old + vectors list + new).
        _job_matrix = None
        _job_ids = []

        ids: list[int] = []
        vectors: list[list[float]] = []
        query = (
            apply_public_job_visibility(
                db_session.query(ScrapedJob.id, ScrapedJob.embedding_vector)
            )
            .filter(ScrapedJob.embedding_vector.isnot(None))
            .yield_per(500)
        )
        for job_id, vec in query:
            if vec and isinstance(vec, list) and len(vec) > 0:
                ids.append(job_id)
                vectors.append(vec)

        if not vectors:
            _matrix_ts = time.monotonic()
            _matrix_generation_id = generation_id
            return

        matrix = np.array(vectors, dtype=np.float32)
        vectors.clear()  # free Python list memory before publishing matrix
        _job_ids = ids
        _job_matrix = matrix
        _matrix_ts = time.monotonic()
        _matrix_generation_id = generation_id


def find_similar_jobs(
    query_vector: list[float],
    db_session: Session,
    top_k: int = 50,
    *,
    eligible_job_ids: set[int] | None = None,
) -> list[tuple[int, float]]:
    """Return (job_id, cosine_similarity) pairs, highest similarity first.

    Served from the in-memory matrix cache, rebuilt when stale.
    """
    _refresh_matrix_if_stale(db_session)

    if _job_matrix is None or len(_job_ids) == 0:
        return []

    query = np.array(query_vector, dtype=np.float32).reshape(1, -1)
    # Normalize query (should already be, but be safe)
    norm = np.linalg.norm(query)
    if norm > 0:
        query = query / norm

    # Cosine similarity via dot product (vectors are normalized)
    similarities = (_job_matrix @ query.T).flatten()

    if eligible_job_ids is not None:
        eligible_indices = np.fromiter(
            (
                index
                for index, job_id in enumerate(_job_ids)
                if job_id in eligible_job_ids
            ),
            dtype=np.int64,
        )
        if len(eligible_indices) == 0:
            return []
        candidate_similarities = similarities[eligible_indices]
    else:
        eligible_indices = np.arange(len(_job_ids))
        candidate_similarities = similarities

    k = min(top_k, len(candidate_similarities))
    top_indices = np.argpartition(candidate_similarities, -k)[-k:]
    top_indices = top_indices[np.argsort(candidate_similarities[top_indices])[::-1]]

    return [
        (_job_ids[int(eligible_indices[idx])], float(candidate_similarities[idx]))
        for idx in top_indices
        if candidate_similarities[idx] > 0
    ]
