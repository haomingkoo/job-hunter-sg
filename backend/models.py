"""
SQLAlchemy ORM models.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _generate_api_key() -> str:
    return secrets.token_hex(32)


def _generate_token_version() -> int:
    # Prevent a deleted account's JWT from authenticating a later SQLite row
    # that happens to reuse the same integer primary key.
    return secrets.randbelow(1_000_000_000) + 1


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # Normal accounts use "user"; "admin" is an authorization role, not a plan.
    tier: Mapped[str] = mapped_column(String(20), default="user", nullable=False)
    api_key: Mapped[str] = mapped_column(
        String(64), unique=True, default=_generate_api_key, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    last_login: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    token_version: Mapped[int] = mapped_column(
        Integer,
        default=_generate_token_version,
        nullable=False,
    )
    terms_accepted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    privacy_accepted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    tracked_jobs: Mapped[list[TrackedJob]] = relationship(
        "TrackedJob", back_populates="user", cascade="all, delete-orphan"
    )


class ScrapedJob(Base):
    __tablename__ = "scraped_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    company: Mapped[str] = mapped_column(String(500), nullable=False)
    location: Mapped[str] = mapped_column(String(500), default="")
    salary: Mapped[str] = mapped_column(String(200), default="")
    salary_floor: Mapped[int] = mapped_column(Integer, default=0)
    source: Mapped[str] = mapped_column(String(200), default="")
    url: Mapped[str] = mapped_column(Text, default="")
    posted_date: Mapped[str] = mapped_column(String(100), default="")
    closing_date: Mapped[str] = mapped_column(String(100), default="")
    employment_type: Mapped[str] = mapped_column(String(100), default="")
    seniority: Mapped[str] = mapped_column(String(100), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    skills: Mapped[dict | list | None] = mapped_column(JSON, default=list)
    agency: Mapped[str] = mapped_column(String(300), default="")
    source_posting_id: Mapped[str] = mapped_column(String(300), default="")
    openings: Mapped[int] = mapped_column(Integer, default=1)
    dedup_key: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    search_keyword: Mapped[str] = mapped_column(String(300), default="")
    sector: Mapped[str] = mapped_column(String(100), default="")
    company_ssic_code: Mapped[str] = mapped_column(String(10), default="")
    company_ssic_description: Mapped[str] = mapped_column(String(300), default="")
    company_ssic_source: Mapped[str] = mapped_column(String(30), default="")
    skills_flat: Mapped[str] = mapped_column(Text, default="")
    scraped_at: Mapped[str] = mapped_column(String(50), default="")
    posted_at_sort: Mapped[str] = mapped_column(String(50), default="")

    # Pre-parsed JD data for instant resume tailoring (populated at scrape time)
    parsed_jd: Mapped[dict | None] = mapped_column(JSON, nullable=True, default=None)
    jd_summary: Mapped[str] = mapped_column(Text, default="")
    jd_summary_generated_at: Mapped[str] = mapped_column(String(50), default="")
    jd_summary_status: Mapped[str] = mapped_column(String(100), default="")

    # Cached skill term labels for fast list-page rendering (JSON array of strings)
    job_terms_preview: Mapped[list | None] = mapped_column(JSON, nullable=True, default=None)

    # Hidden from listings (stale duplicate kept for FK references)
    hidden: Mapped[bool] = mapped_column(Integer, default=0)

    # RAG embedding vector (384-dim, all-MiniLM-L6-v2)
    embedding_vector: Mapped[list | None] = mapped_column(JSON, nullable=True, default=None)

    __table_args__ = (
        Index("ix_scraped_jobs_keyword", "search_keyword"),
        Index("ix_scraped_jobs_posted_sort", "posted_at_sort"),
        Index("ix_scraped_jobs_source", "source"),
        Index("ix_scraped_jobs_location", "location"),
        Index("ix_scraped_jobs_seniority", "seniority"),
        Index("ix_scraped_jobs_emp_type", "employment_type"),
        Index("ix_scraped_jobs_sector", "sector"),
        Index("ix_scraped_jobs_source_posting", "source", "source_posting_id"),
        Index("ix_scraped_jobs_ssic_code", "company_ssic_code"),
        Index("ix_scraped_jobs_ssic_source", "company_ssic_source"),
        Index("ix_scraped_jobs_salary_floor", "salary_floor"),
    )


class TrackedJob(Base):
    __tablename__ = "tracked_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    company: Mapped[str] = mapped_column(String(500), nullable=False)
    role: Mapped[str] = mapped_column(String(500), nullable=False)
    date_applied: Mapped[str | None] = mapped_column(String(50), nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="applied")
    source: Mapped[str] = mapped_column(String(200), default="")
    source_url: Mapped[str] = mapped_column(Text, default="")
    job_description: Mapped[str] = mapped_column(Text, default="")
    role_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True, default=dict)
    follow_up_date: Mapped[str | None] = mapped_column(String(50), nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    scraped_job_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("scraped_jobs.id"), nullable=True
    )
    resume_version_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("resume_versions.id"), nullable=True
    )
    # Stage history: [{stage, date, notes}] - tracks progression through hiring pipeline
    stage_history: Mapped[list | None] = mapped_column(JSON, nullable=True, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)

    user: Mapped[User] = relationship("User", back_populates="tracked_jobs")


class UserMemory(Base):
    """
    Persistent memory for each user — injected into AI prompts so the
    coach "remembers" their background, goals, and past feedback.
    Users can view and edit their memory.
    """
    __tablename__ = "user_memories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), unique=True, nullable=False)

    # Profile — extracted from resume or entered manually
    resume_text: Mapped[str] = mapped_column(Text, default="")
    target_roles: Mapped[str] = mapped_column(Text, default="")        # e.g. "PM, Data Engineer, SWE"
    target_companies: Mapped[str] = mapped_column(Text, default="")    # e.g. "GovTech, Grab, DBS"
    career_goals: Mapped[str] = mapped_column(Text, default="")        # free text
    strengths: Mapped[str] = mapped_column(Text, default="")           # AI-identified or user-edited
    areas_to_improve: Mapped[str] = mapped_column(Text, default="")    # AI-identified or user-edited
    preferred_industry: Mapped[str] = mapped_column(String(500), default="")
    years_experience: Mapped[str] = mapped_column(String(50), default="")
    education_level: Mapped[str] = mapped_column(String(200), default="")

    # RAG embedding vector (384-dim, all-MiniLM-L6-v2)
    resume_embedding: Mapped[list | None] = mapped_column(JSON, nullable=True, default=None)

    # AI coaching memory — accumulated across sessions
    coaching_notes: Mapped[str] = mapped_column(Text, default="")      # AI summary of past sessions
    session_count: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class PasswordResetToken(Base):
    """One-time password reset token. Only the token hash is stored."""
    __tablename__ = "password_reset_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    __table_args__ = (
        Index("ix_password_reset_tokens_user", "user_id", "created_at"),
        Index("ix_password_reset_tokens_hash", "token_hash"),
    )


class EmailVerificationToken(Base):
    """One-time email verification token. Only the token hash is stored."""
    __tablename__ = "email_verification_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    __table_args__ = (
        Index("ix_email_verification_tokens_user", "user_id", "created_at"),
        Index("ix_email_verification_tokens_hash", "token_hash"),
    )


class PowerMatchSnapshot(Base):
    """
    Persisted Power Match result for a user resume + job corpus version.
    Keeps repeat visits off the expensive ranking path.
    """
    __tablename__ = "power_match_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    resume_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    corpus_marker: Mapped[str] = mapped_column(String(200), nullable=False)
    limit: Mapped[int] = mapped_column(Integer, default=8)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    __table_args__ = (
        Index("ix_power_match_snapshots_lookup", "user_id", "resume_hash", "corpus_marker", "limit"),
    )


class TailoredResume(Base):
    """
    Stores a structured resume tailoring session tied to a user and a job.
    Tracks pipeline progress, changes made, and before/after metrics.
    """
    __tablename__ = "tailored_resumes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    job_id: Mapped[int] = mapped_column(Integer, ForeignKey("scraped_jobs.id"), nullable=False)
    session_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)

    # Structured resume snapshots
    original_resume: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    tailored_resume: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Pipeline state
    pipeline_stage: Mapped[str] = mapped_column(String(50), default="init")
    pipeline_progress: Mapped[dict | None] = mapped_column(JSON, default=dict)

    # Change tracking
    changes: Mapped[list | None] = mapped_column(JSON, default=list)

    # Before/after metrics
    match_before: Mapped[int | None] = mapped_column(Integer, nullable=True)
    match_after: Mapped[int | None] = mapped_column(Integer, nullable=True)
    score_before: Mapped[int | None] = mapped_column(Integer, nullable=True)
    score_after: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class ResumeVersion(Base):
    """
    Saved resume versions - from uploads, tailoring pipeline, or manual edits.
    Users can label, compare, and attach versions to tracked jobs.
    """
    __tablename__ = "resume_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)

    # Identity
    label: Mapped[str] = mapped_column(String(200), nullable=False)  # "PM version", "Tailored for DBS"
    source: Mapped[str] = mapped_column(String(50), default="upload")  # upload, tailored, manual, import

    # Content
    resume_text: Mapped[str] = mapped_column(Text, default="")
    resume_structured: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # parsed sections/bullets

    # Linked job (optional - set when created via tailoring pipeline)
    job_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("scraped_jobs.id"), nullable=True)
    job_title: Mapped[str] = mapped_column(String(500), default="")  # denormalized for display
    job_company: Mapped[str] = mapped_column(String(500), default="")

    # Metrics snapshot
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    word_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Flags
    is_master: Mapped[bool] = mapped_column(default=False)  # user's primary/base resume
    is_active: Mapped[bool] = mapped_column(default=True)  # soft delete

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)

    __table_args__ = (
        Index("ix_resume_versions_user", "user_id"),
    )


class InterviewStory(Base):
    """
    STAR+R story bank for interview prep.
    Users build reusable stories tagged with behavioral categories.
    """
    __tablename__ = "interview_stories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)

    # Identity
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    project_name: Mapped[str] = mapped_column(String(300), default="")

    # STAR+R fields
    situation: Mapped[str] = mapped_column(Text, default="")
    task: Mapped[str] = mapped_column(Text, default="")
    action: Mapped[str] = mapped_column(Text, default="")
    result: Mapped[str] = mapped_column(Text, default="")
    reflection: Mapped[str] = mapped_column(Text, default="")

    # Tagging — JSON array from 8 behavioral categories:
    # motivation, proactiveness, ambiguity, perseverance,
    # conflict_resolution, empathy, growth, communication
    tags: Mapped[list | None] = mapped_column(JSON, default=list)

    # Target seniority level
    seniority: Mapped[str] = mapped_column(String(20), default="mid")  # junior|mid|senior|staff

    # Soft delete
    is_active: Mapped[bool] = mapped_column(Integer, default=1)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)

    __table_args__ = (
        Index("ix_interview_stories_user", "user_id"),
    )


class StoryUsage(Base):
    """Tracks which stories were used for which job interviews."""
    __tablename__ = "story_usages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    story_id: Mapped[int] = mapped_column(Integer, ForeignKey("interview_stories.id"), nullable=False)
    job_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("scraped_jobs.id"), nullable=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    question_asked: Mapped[str] = mapped_column(Text, default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class JobAlertPreference(Base):
    """Per-user opt-in settings for matched job email digests."""
    __tablename__ = "job_alert_preferences"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    enabled: Mapped[bool] = mapped_column(Integer, default=0, nullable=False)
    min_score: Mapped[int] = mapped_column(Integer, default=75, nullable=False)
    direct_employers_only: Mapped[bool] = mapped_column(Integer, default=1, nullable=False)
    frequency: Mapped[str] = mapped_column(String(20), default="daily", nullable=False)
    keywords: Mapped[str] = mapped_column(Text, default="", nullable=False)
    max_jobs: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    consented_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    unsubscribed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)

    __table_args__ = (
        Index("ix_job_alert_preferences_user", "user_id", unique=True),
        Index("ix_job_alert_preferences_enabled", "enabled"),
    )


class JobAlertDelivery(Base):
    """Records alerted or user-suppressed jobs so digests do not repeat them."""
    __tablename__ = "job_alert_deliveries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    preference_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("job_alert_preferences.id"), nullable=True
    )
    scraped_job_id: Mapped[int] = mapped_column(Integer, ForeignKey("scraped_jobs.id"), nullable=False)
    resume_hash: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    match_score: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    action: Mapped[str] = mapped_column(String(30), default="sent", nullable=False)
    sent_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_job_alert_deliveries_lookup", "user_id", "scraped_job_id"),
        Index("ix_job_alert_deliveries_action", "user_id", "action"),
    )


class UsageLog(Base):
    __tablename__ = "usage_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    __table_args__ = (
        Index("ix_usage_logs_user_action_created", "user_id", "action", "created_at"),
        Index("ix_usage_logs_action_created", "action", "created_at"),
    )
