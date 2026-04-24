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

        total = query.count()
        if limit:
            total = min(total, limit)
        if total == 0:
            print("No jobs to backfill.")
            return

        print(f"Backfilling embeddings for {total} jobs...")

        batch_size = 32
        processed = 0
        t0 = time.time()

        last_id = 0
        while processed < total:
            batch = (
                query
                .filter(ScrapedJob.id > last_id)
                .order_by(ScrapedJob.id.asc())
                .limit(min(batch_size, total - processed))
                .all()
            )
            if not batch:
                break
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

            db.commit()
            processed += len(batch)
            last_id = batch[-1].id
            db.expunge_all()
            elapsed = time.time() - t0
            rate = processed / elapsed if elapsed > 0 else 0
            print(
                f"  [{processed}/{total}] "
                f"{processed * 100 // total}% "
                f"({rate:.1f} jobs/sec)"
            )

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
