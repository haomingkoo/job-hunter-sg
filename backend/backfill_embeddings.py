"""
Backfill embedding vectors for scraped jobs that are missing them.

Usage:
    python backfill_embeddings.py            # backfill jobs missing embeddings
    python backfill_embeddings.py --force     # re-embed all jobs
    python backfill_embeddings.py --limit 500 # process at most 500 jobs
"""

from __future__ import annotations

import argparse
import sys
import time

from database import SessionLocal
from embedding_service import build_job_embed_text, encode_texts
from models import ScrapedJob


def backfill(force: bool = False, limit: int | None = None) -> None:
    db = SessionLocal()
    try:
        query = db.query(ScrapedJob)
        if not force:
            query = query.filter(ScrapedJob.embedding_vector.is_(None))
        if limit:
            query = query.limit(limit)

        jobs = query.all()
        total = len(jobs)
        if total == 0:
            print("No jobs to backfill.")
            return

        print(f"Backfilling embeddings for {total} jobs...")

        batch_size = 32
        processed = 0
        t0 = time.time()

        for i in range(0, total, batch_size):
            batch = jobs[i : i + batch_size]
            texts = [
                build_job_embed_text(
                    job.title,
                    job.description,
                    job.skills if isinstance(job.skills, list) else [],
                )
                for job in batch
            ]
            vectors = encode_texts(texts, batch_size=batch_size)

            for job, vec in zip(batch, vectors):
                job.embedding_vector = vec

            db.flush()
            processed += len(batch)
            elapsed = time.time() - t0
            rate = processed / elapsed if elapsed > 0 else 0
            print(
                f"  [{processed}/{total}] "
                f"{processed * 100 // total}% "
                f"({rate:.1f} jobs/sec)"
            )

        db.commit()
        elapsed = time.time() - t0
        print(f"Done. {processed} jobs embedded in {elapsed:.1f}s.")

    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill job embedding vectors")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-embed all jobs, even those with existing vectors",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of jobs to process",
    )
    args = parser.parse_args()
    backfill(force=args.force, limit=args.limit)
