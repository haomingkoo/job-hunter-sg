"""A repost of unchanged content must update the listing, not add another one.

dedup_key, source_posting_id and url all identify a *posting*. An employer
reposting the same role gets fresh values for all three, so before content
hashing every repost read as a brand new job and accumulated forever. Measured
on the 16,390-row local corpus: 2,367 rows (14.4%) were content duplicates.
"""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base
from job_store import compute_content_hash, find_existing_scraped_job
from models import (
    InterviewStory,
    JobAlertDelivery,
    ResumeVersion,
    ScrapedJob,
    StoryUsage,
    TailoredResume,
    TrackedJob,
    User,
)
from sanitizer import sanitize_job


DESCRIPTION = "Operate virtualisation platforms and storage systems for enterprise clients."


def _session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _listing(**overrides):
    base = {
        "title": "Platform Operations Engineer",
        "company": "TESCOM PTE LTD",
        "location": "Singapore",
        "salary": "$5,000 - $6,000",
        "employment_type": "Full Time",
        "description": DESCRIPTION,
        "source": "MyCareersFuture",
    }
    base.update(overrides)
    return base


def test_sanitize_job_stamps_a_content_hash():
    assert sanitize_job(_listing())["content_hash"]


def test_a_repost_with_fresh_identifiers_matches_the_existing_listing():
    db = _session()
    first = sanitize_job(_listing(dedup_key="mcf-aaa", source_posting_id="aaa", url="https://x/aaa"))
    db.add(ScrapedJob(**first, posted_date="2026-06-01"))
    db.commit()

    # Same content, new posting: every identifier differs, as it does in production.
    repost = sanitize_job(_listing(dedup_key="mcf-bbb", source_posting_id="bbb", url="https://x/bbb"))

    assert find_existing_scraped_job(db, repost) is not None


def test_a_genuinely_different_role_is_not_collapsed():
    db = _session()
    db.add(ScrapedJob(**sanitize_job(_listing(dedup_key="mcf-aaa")), posted_date="2026-06-01"))
    db.commit()

    other = sanitize_job(_listing(dedup_key="mcf-ccc", title="Network Engineer"))

    assert find_existing_scraped_job(db, other) is None


def test_the_same_role_on_a_different_board_still_appears():
    """Cross-source collapsing would hide that a role is advertised in two places."""
    db = _session()
    db.add(ScrapedJob(**sanitize_job(_listing(dedup_key="mcf-aaa")), posted_date="2026-06-01"))
    db.commit()

    elsewhere = sanitize_job(_listing(dedup_key="jooble-1", source="Jooble"))

    assert find_existing_scraped_job(db, elsewhere) is None


def test_a_listing_with_no_description_is_never_content_matched():
    """Too little signal to claim two rows are the same listing."""
    db = _session()
    db.add(ScrapedJob(**sanitize_job(_listing(description="", dedup_key="mcf-aaa")), posted_date="2026-06-01"))
    db.commit()

    assert compute_content_hash(_listing(description="")) == ""
    assert find_existing_scraped_job(db, sanitize_job(_listing(description="", dedup_key="mcf-zzz"))) is None


def test_the_hash_ignores_whitespace_and_case_but_not_salary():
    spaced = compute_content_hash(_listing(description=f"  {DESCRIPTION.upper()}  \n"))
    plain = compute_content_hash(_listing())
    assert spaced == plain

    assert compute_content_hash(_listing(salary="$9,000 - $10,000")) != plain


def test_backfill_stamps_existing_rows_and_terminates():
    """Pre-existing rows have no hash, so without a backfill the fallback never fires."""
    from job_store import backfill_content_hashes

    db = _session()
    db.add(
        ScrapedJob(
            title="A", company="C", description=DESCRIPTION, source="MyCareersFuture", dedup_key="a"
        )
    )
    db.add(
        ScrapedJob(title="B", company="C", description="", source="MyCareersFuture", dedup_key="b")
    )
    db.commit()

    assert backfill_content_hashes(db) == 2
    # The description-less row must not be re-selected forever.
    assert backfill_content_hashes(db) == 0

    hashed = db.query(ScrapedJob).filter(ScrapedJob.title == "A").one()
    assert len(hashed.content_hash) == 64


def test_visible_hash_backfill_skips_hidden_legacy_rows():
    from job_store import backfill_content_hashes

    db = _session()
    db.add_all(
        [
            ScrapedJob(
                title="Visible", company="C", description=DESCRIPTION, dedup_key="visible"
            ),
            ScrapedJob(
                title="Hidden",
                company="C",
                description=DESCRIPTION,
                dedup_key="hidden",
                hidden=1,
            ),
        ]
    )
    db.commit()

    assert backfill_content_hashes(db, public_only=True) == 1
    assert db.query(ScrapedJob).filter_by(dedup_key="visible").one().content_hash
    assert db.query(ScrapedJob).filter_by(dedup_key="hidden").one().content_hash == ""


def test_legacy_prune_preserves_visible_archived_and_every_user_linked_job():
    from job_store import prune_unreferenced_legacy_hidden_jobs

    db = _session()
    user = User(email="owner@example.test", password_hash="hash", name="Owner")
    db.add(user)
    db.flush()
    removable = ScrapedJob(title="Remove", company="C", dedup_key="remove", hidden=1)
    linked_jobs = {
        name: ScrapedJob(
            title=f"Keep {name}",
            company="C",
            dedup_key=f"linked-{name}",
            hidden=1,
        )
        for name in ("tracked", "tailored", "resume", "story", "alert")
    }
    archived = ScrapedJob(
        title="Keep archive",
        company="C",
        dedup_key="archive",
        hidden=1,
        retirement_reason="source_retired",
    )
    visible = ScrapedJob(title="Keep visible", company="C", dedup_key="visible")
    db.add_all((removable, *linked_jobs.values(), archived, visible))
    db.flush()
    story = InterviewStory(user_id=user.id, title="Example")
    db.add(story)
    db.flush()
    db.add_all(
        (
            TrackedJob(
                user_id=user.id,
                company="C",
                role="Role",
                scraped_job_id=linked_jobs["tracked"].id,
            ),
            TailoredResume(
                user_id=user.id,
                job_id=linked_jobs["tailored"].id,
                session_id="session-1",
            ),
            ResumeVersion(
                user_id=user.id,
                label="Saved",
                job_id=linked_jobs["resume"].id,
            ),
            StoryUsage(
                story_id=story.id,
                user_id=user.id,
                job_id=linked_jobs["story"].id,
            ),
            JobAlertDelivery(
                user_id=user.id,
                scraped_job_id=linked_jobs["alert"].id,
            ),
        )
    )
    db.commit()

    assert prune_unreferenced_legacy_hidden_jobs(db, 10) == 1
    assert {row.dedup_key for row in db.query(ScrapedJob)} == {
        "linked-tracked",
        "linked-tailored",
        "linked-resume",
        "linked-story",
        "linked-alert",
        "archive",
        "visible",
    }
