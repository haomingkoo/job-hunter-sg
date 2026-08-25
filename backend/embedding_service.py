"""
RAG embedding service for semantic job matching.

Uses sentence-transformers/all-MiniLM-L6-v2 (384-dim, normalized)
to encode job descriptions and resumes for cosine similarity search.
"""

from __future__ import annotations

import hashlib
import threading
import time
from datetime import timedelta
from typing import TYPE_CHECKING, Callable

import numpy as np
from sqlalchemy import func

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer
    from sqlalchemy.orm import Session

_model: SentenceTransformer | None = None
_model_lock = threading.Lock()
_encode_lock = threading.Lock()
EMBEDDING_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
EMBEDDING_MODEL_REVISION = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"
EMBEDDING_MODEL_IDENTITY = f"{EMBEDDING_MODEL_NAME}@{EMBEDDING_MODEL_REVISION}"


class EmbeddingIndexUnavailable(RuntimeError):
    """The public corpus is not fully backed by current, proven vectors."""


def _get_model() -> SentenceTransformer:
    """Return singleton SentenceTransformer, loading on first call."""
    global _model
    if _model is not None:
        return _model
    with _model_lock:
        if _model is not None:
            return _model
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(
            EMBEDDING_MODEL_NAME,
            revision=EMBEDDING_MODEL_REVISION,
        )
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


def job_embedding_input_sha256(
    title: str,
    description: str,
    skills: list[str] | str | None,
) -> str:
    """Identify the exact normalized text supplied to the encoder."""
    text = build_job_embed_text(title, description, skills)
    return hashlib.sha256(text.encode()).hexdigest()


def embedding_fields_are_current(
    *,
    title: str,
    description: str,
    skills: list[str] | str | None,
    vector: list[float] | None,
    input_sha256: str,
    model_identity: str,
) -> bool:
    """Return whether vector provenance matches the exact encoder input."""
    return (
        bool(vector)
        and input_sha256 == job_embedding_input_sha256(title, description, skills)
        and model_identity == EMBEDDING_MODEL_IDENTITY
    )


def embedding_is_current(job) -> bool:
    """Return whether a row's vector is proven current for its text and model."""
    return embedding_fields_are_current(
        title=job.title or "",
        description=job.description or "",
        skills=job.skills,
        vector=job.embedding_vector,
        input_sha256=job.embedding_input_sha256 or "",
        model_identity=job.embedding_model_identity or "",
    )


def stamp_job_embedding(job, vector: list[float]) -> bool:
    """Store proven provenance, returning whether vector bytes need rewriting."""
    vector_changed = job.embedding_vector != vector
    if vector_changed:
        job.embedding_vector = vector
    job.embedding_input_sha256 = job_embedding_input_sha256(
        job.title or "",
        job.description or "",
        job.skills,
    )
    job.embedding_model_identity = EMBEDDING_MODEL_IDENTITY
    return vector_changed


def invalidate_job_embedding_if_stale(job) -> bool:
    """Clear a vector whose text or pinned model provenance no longer matches."""
    if embedding_is_current(job):
        return False
    job.embedding_vector = None
    job.embedding_input_sha256 = ""
    job.embedding_model_identity = ""
    return True


def embedding_readiness_marker(db_session: Session) -> str:
    """Bind a completed exact-provenance scan to this corpus and encoder."""
    from job_visibility import job_corpus_marker

    value = f"{job_corpus_marker(db_session)}\0{EMBEDDING_MODEL_IDENTITY}"
    return hashlib.sha256(value.encode()).hexdigest()


def embedding_readiness_is_current(db_session: Session) -> bool:
    """Return whether a completed exact-provenance scan covers this corpus."""
    from models import UsageLog

    marker = embedding_readiness_marker(db_session)
    return db_session.query(UsageLog.id).filter(
        UsageLog.action == "job_embedding_ready",
        UsageLog.detail == marker,
    ).first() is not None


def refresh_job_embeddings(
    db_session: Session,
    *,
    force: bool = False,
    limit: int | None = None,
    batch_size: int = 32,
    page_size: int = 500,
    on_progress: Callable[[dict[str, int | bool]], None] | None = None,
) -> dict[str, int | bool]:
    """Refresh public-job vectors and publish one cross-process generation."""
    from job_visibility import apply_public_job_visibility
    from models import ScrapedJob, UsageLog

    query = apply_public_job_visibility(db_session.query(ScrapedJob))
    searchable = query.count()
    scanned = 0
    refreshed = 0
    vector_rewrites = 0
    deferred_due_to_limit = False
    last_id = 0
    while True:
        page = (
            query.filter(ScrapedJob.id > last_id)
            .order_by(ScrapedJob.id.asc())
            .limit(page_size)
            .all()
        )
        if not page:
            break
        last_id = page[-1].id
        scanned += len(page)
        batch = [job for job in page if force or not embedding_is_current(job)]
        if limit is not None:
            remaining = max(0, limit - refreshed)
            deferred_due_to_limit = deferred_due_to_limit or len(batch) > remaining
            batch = batch[:remaining]
        if batch:
            vectors = encode_texts(
                [
                    build_job_embed_text(job.title, job.description, job.skills)
                    for job in batch
                ],
                batch_size=batch_size,
            )
            vector_rewrites += sum(
                stamp_job_embedding(job, vector)
                for job, vector in zip(batch, vectors)
            )
            db_session.commit()
            refreshed += len(batch)
        db_session.expunge_all()
        state = {
            "searchable": searchable,
            "scanned": scanned,
            "refreshed": refreshed,
            "vector_rewrites": vector_rewrites,
            "complete": scanned == searchable and not deferred_due_to_limit,
        }
        if on_progress is not None:
            on_progress(state)
        if limit is not None and refreshed >= limit:
            break

    complete = scanned == searchable and not deferred_due_to_limit
    if refreshed:
        db_session.add(UsageLog(
            user_id=None,
            action="job_embedding_refresh",
            detail=(
                f"scanned={scanned};refreshed={refreshed};"
                f"vector_rewrites={vector_rewrites};complete={int(complete)};"
                f"model={EMBEDDING_MODEL_IDENTITY}"
            ),
        ))
    if complete and not embedding_readiness_is_current(db_session):
        db_session.add(UsageLog(
            user_id=None,
            action="job_embedding_ready",
            detail=embedding_readiness_marker(db_session),
        ))
    if refreshed or complete:
        db_session.commit()
    if refreshed:
        invalidate_matrix_cache()
    return {
        "searchable": searchable,
        "scanned": scanned,
        "refreshed": refreshed,
        "vector_rewrites": vector_rewrites,
        "complete": complete,
    }


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
        searchable_count = apply_public_job_visibility(
            db_session.query(func.count(ScrapedJob.id))
        ).scalar() or 0
        query = (
            apply_public_job_visibility(
                db_session.query(
                    ScrapedJob.id,
                    ScrapedJob.title,
                    ScrapedJob.description,
                    ScrapedJob.skills,
                    ScrapedJob.embedding_vector,
                    ScrapedJob.embedding_input_sha256,
                    ScrapedJob.embedding_model_identity,
                )
            )
            .filter(
                ScrapedJob.embedding_vector.isnot(None),
                ScrapedJob.embedding_input_sha256.isnot(None),
                func.length(ScrapedJob.embedding_input_sha256) == 64,
                ScrapedJob.embedding_model_identity == EMBEDDING_MODEL_IDENTITY,
            )
            .yield_per(500)
        )
        for job_id, title, description, skills, vector, input_hash, model_identity in query:
            if embedding_fields_are_current(
                title=title or "",
                description=description or "",
                skills=skills,
                vector=vector,
                input_sha256=input_hash or "",
                model_identity=model_identity or "",
            ):
                ids.append(job_id)
                vectors.append(vector)

        if searchable_count == 0:
            _matrix_ts = time.monotonic()
            _matrix_generation_id = generation_id
            return
        if len(ids) != searchable_count:
            _matrix_ts = 0.0
            _matrix_generation_id = generation_id
            raise EmbeddingIndexUnavailable(
                f"embedding index coverage is {len(ids)}/{searchable_count}"
            )

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
        candidate_ids = [_job_ids[index] for index in eligible_indices]
        candidate_matrix = _job_matrix[eligible_indices]
    else:
        candidate_ids = _job_ids
        candidate_matrix = _job_matrix

    return rank_embedding_matrix(query_vector, candidate_ids, candidate_matrix, top_k)


def rank_embedding_matrix(
    query_vector: list[float],
    job_ids: list[int],
    matrix: np.ndarray,
    top_k: int,
) -> list[tuple[int, float]]:
    if top_k <= 0 or not job_ids or matrix.size == 0:
        return []
    query = np.array(query_vector, dtype=np.float32).reshape(1, -1)
    norm = np.linalg.norm(query)
    if norm > 0:
        query = query / norm
    similarities = (matrix @ query.T).flatten()
    valid_indices = np.flatnonzero(similarities > 0)
    if len(valid_indices) == 0:
        return []
    # A full NumPy lexsort is cheap at the current corpus size and, unlike an
    # argpartition, makes ties at the top-k boundary reproducible. Lower job ID
    # is the stable secondary key.
    valid_job_ids = np.array(
        [job_ids[index] for index in valid_indices],
        dtype=np.int64,
    )
    order = np.lexsort((valid_job_ids, -similarities[valid_indices]))
    top_indices = valid_indices[order[:top_k]]

    return [
        (job_ids[index], float(similarities[index]))
        for index in top_indices
    ]


def find_similar_jobs_for_ids(
    query_vector: list[float],
    db_session: Session,
    eligible_job_ids: set[int],
    top_k: int = 50,
) -> list[tuple[int, float]]:
    """Rank a small, prevalidated job set without loading the global matrix."""
    if not eligible_job_ids:
        return []

    from job_visibility import apply_public_job_visibility
    from models import ScrapedJob

    rows = (
        apply_public_job_visibility(db_session.query(
            ScrapedJob.id,
            ScrapedJob.title,
            ScrapedJob.description,
            ScrapedJob.skills,
            ScrapedJob.embedding_vector,
            ScrapedJob.embedding_input_sha256,
            ScrapedJob.embedding_model_identity,
        ))
        .filter(ScrapedJob.id.in_(eligible_job_ids))
        .all()
    )
    current = [
        (job_id, vector)
        for job_id, title, description, skills, vector, input_hash, model_identity in rows
        if embedding_fields_are_current(
            title=title or "",
            description=description or "",
            skills=skills,
            vector=vector,
            input_sha256=input_hash or "",
            model_identity=model_identity or "",
        )
    ]
    ids = [job_id for job_id, _vector in current]
    vectors = [vector for _job_id, vector in current]
    if len(current) != len(rows):
        raise EmbeddingIndexUnavailable(
            f"eligible embedding coverage is {len(current)}/{len(rows)}"
        )
    if not vectors:
        return []

    return rank_embedding_matrix(
        query_vector,
        ids,
        np.array(vectors, dtype=np.float32),
        top_k,
    )
