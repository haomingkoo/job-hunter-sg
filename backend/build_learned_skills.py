"""Build the frequency-based Tier 2 skills taxonomy."""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("learned_skills")

# Ensure local imports work when run as a script
sys.path.insert(0, ".")

from models import ScrapedJob
from sqlalchemy.orm import Session, load_only

TIER2_THRESHOLD = 50
OUTPUT_DIR = Path(__file__).resolve().parent / "data"
OUTPUT_PATH = OUTPUT_DIR / "learned_skills.json"


def build_learned_skills(
    db_session: Session,
    threshold: int = TIER2_THRESHOLD,
) -> dict:
    """Count distinct-job term frequency and return the learned taxonomy."""
    term_counter: Counter[str] = Counter()
    total_jobs = 0

    query = (
        db_session.query(ScrapedJob)
        .filter(ScrapedJob.job_terms_preview.isnot(None))
        .options(load_only(ScrapedJob.id, ScrapedJob.job_terms_preview))
    )

    log.info("Scanning jobs for term frequencies...")
    t0 = time.time()

    for job in query.yield_per(500):
        terms = job.job_terms_preview
        if not isinstance(terms, list):
            continue
        total_jobs += 1
        # Count each unique term once per job (set dedup)
        unique_terms = {t.strip().lower() for t in terms if isinstance(t, str) and t.strip()}
        term_counter.update(unique_terms)

    elapsed = time.time() - t0
    log.info(f"Scanned {total_jobs} jobs in {elapsed:.1f}s, found {len(term_counter)} unique terms")

    # Filter to terms meeting the threshold
    learned = {
        term: count
        for term, count in term_counter.most_common()
        if count >= threshold
    }

    log.info(f"Tier 2 skills (>={threshold} jobs): {len(learned)} terms")

    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_jobs_scanned": total_jobs,
        "tier2_threshold": threshold,
        "skills": learned,
    }
    return result


def save_learned_skills(result: dict) -> Path:
    """Write the result dict to the JSON file. Creates data/ if needed."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(result, indent=2, ensure_ascii=False))
    log.info(f"Saved {len(result['skills'])} learned skills to {OUTPUT_PATH}")
    return OUTPUT_PATH


def load_learned_skills() -> set[str]:
    """
    Read the learned_skills.json file and return the set of skill terms.
    Returns an empty set if the file does not exist yet.
    """
    if not OUTPUT_PATH.exists():
        return set()
    try:
        data = json.loads(OUTPUT_PATH.read_text())
        return set(data.get("skills", {}).keys())
    except (json.JSONDecodeError, KeyError):
        log.warning(f"Failed to parse {OUTPUT_PATH}, returning empty set")
        return set()


def main() -> None:
    parser = argparse.ArgumentParser(description="Build frequency-based learned skills (Tier 2)")
    parser.add_argument(
        "--threshold", type=int, default=TIER2_THRESHOLD,
        help=f"Minimum number of jobs a term must appear in (default: {TIER2_THRESHOLD})",
    )
    args = parser.parse_args()

    from database import SessionLocal, init_db

    init_db()
    db = SessionLocal()
    try:
        result = build_learned_skills(db, threshold=args.threshold)
        save_learned_skills(result)

        # Print top 20 for quick inspection
        top = list(result["skills"].items())[:20]
        log.info("Top 20 learned skills:")
        for term, count in top:
            log.info(f"  {term}: {count} jobs")
    finally:
        db.close()


if __name__ == "__main__":
    main()
