"""
RAG embedding service for semantic job matching.

Uses sentence-transformers/all-MiniLM-L6-v2 (384-dim, normalized)
to encode job descriptions and resumes for cosine similarity search.
"""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer
    from sqlalchemy.orm import Session

# ── Lazy-loaded singleton model ───────────────────────────────────────────────

_model: SentenceTransformer | None = None
_model_lock = threading.Lock()
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


# ── Encoding helpers ──────────────────────────────────────────────────────────

def encode_text(text: str) -> list[float]:
    """Encode a single text string into a 384-dim normalized vector."""
    model = _get_model()
    vector = model.encode(text, normalize_embeddings=True)
    return vector.tolist()


def encode_texts(texts: list[str], batch_size: int = 32) -> list[list[float]]:
    """Encode multiple texts into 384-dim normalized vectors."""
    model = _get_model()
    vectors = model.encode(texts, batch_size=batch_size, normalize_embeddings=True)
    return vectors.tolist()


def build_job_embed_text(
    title: str,
    description: str,
    skills: list[str] | str | None,
) -> str:
    """
    Combine job fields into a single text optimised for embedding.

    Title is doubled for emphasis, skills are joined, and description
    is truncated to keep total length manageable.
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


# ── In-memory matrix cache for fast similarity search ─────────────────────────

_job_matrix: np.ndarray | None = None
_job_ids: list[int] = []
_matrix_lock = threading.Lock()
_matrix_ts: float = 0.0
_MATRIX_TTL = 300  # 5 minutes


def invalidate_matrix_cache() -> None:
    """Force rebuild on next similarity search."""
    global _job_matrix, _job_ids, _matrix_ts
    with _matrix_lock:
        _job_matrix = None
        _job_ids = []
        _matrix_ts = 0.0


def _refresh_matrix_if_stale(db_session: Session) -> None:
    """Rebuild the matrix from DB if older than TTL."""
    global _job_matrix, _job_ids, _matrix_ts
    now = time.monotonic()
    if _job_matrix is not None and (now - _matrix_ts) < _MATRIX_TTL:
        return

    with _matrix_lock:
        # Double-check after acquiring lock
        if _job_matrix is not None and (time.monotonic() - _matrix_ts) < _MATRIX_TTL:
            return

        from models import ScrapedJob

        rows = (
            db_session.query(ScrapedJob.id, ScrapedJob.embedding_vector)
            .filter(ScrapedJob.embedding_vector.isnot(None))
            .all()
        )

        if not rows:
            _job_matrix = None
            _job_ids = []
            _matrix_ts = time.monotonic()
            return

        ids = []
        vectors = []
        for job_id, vec in rows:
            if vec and isinstance(vec, list) and len(vec) > 0:
                ids.append(job_id)
                vectors.append(vec)

        if not vectors:
            _job_matrix = None
            _job_ids = []
            _matrix_ts = time.monotonic()
            return

        _job_ids = ids
        _job_matrix = np.array(vectors, dtype=np.float32)
        _matrix_ts = time.monotonic()


def find_similar_jobs(
    query_vector: list[float],
    db_session: Session,
    top_k: int = 50,
) -> list[tuple[int, float]]:
    """
    Return (job_id, cosine_similarity) pairs sorted by descending similarity.

    Uses cached in-memory matrix, refreshed every 5 minutes.
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

    # Get top-k indices
    k = min(top_k, len(similarities))
    top_indices = np.argpartition(similarities, -k)[-k:]
    top_indices = top_indices[np.argsort(similarities[top_indices])[::-1]]

    return [
        (_job_ids[idx], float(similarities[idx]))
        for idx in top_indices
        if similarities[idx] > 0
    ]
