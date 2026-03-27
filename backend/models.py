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


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    tier: Mapped[str] = mapped_column(String(20), default="free", nullable=False)
    api_key: Mapped[str] = mapped_column(
        String(64), unique=True, default=_generate_api_key, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    last_login: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

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
    source: Mapped[str] = mapped_column(String(200), default="")
    url: Mapped[str] = mapped_column(Text, default="")
    posted_date: Mapped[str] = mapped_column(String(100), default="")
    closing_date: Mapped[str] = mapped_column(String(100), default="")
    employment_type: Mapped[str] = mapped_column(String(100), default="")
    seniority: Mapped[str] = mapped_column(String(100), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    skills: Mapped[dict | list | None] = mapped_column(JSON, default=list)
    agency: Mapped[str] = mapped_column(String(300), default="")
    dedup_key: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    search_keyword: Mapped[str] = mapped_column(String(300), default="")
    scraped_at: Mapped[str] = mapped_column(String(50), default="")
    posted_at_sort: Mapped[str] = mapped_column(String(50), default="")

    # Pre-parsed JD data for instant resume tailoring (populated at scrape time)
    parsed_jd: Mapped[dict | None] = mapped_column(JSON, nullable=True, default=None)
    jd_summary: Mapped[str] = mapped_column(Text, default="")
    jd_summary_generated_at: Mapped[str] = mapped_column(String(50), default="")
    jd_summary_status: Mapped[str] = mapped_column(String(100), default="")

    # Cached skill term labels for fast list-page rendering (JSON array of strings)
    job_terms_preview: Mapped[list | None] = mapped_column(JSON, nullable=True, default=None)

    # RAG embedding vector (384-dim, all-MiniLM-L6-v2)
    embedding_vector: Mapped[list | None] = mapped_column(JSON, nullable=True, default=None)

    __table_args__ = (
        Index("ix_scraped_jobs_keyword", "search_keyword"),
        Index("ix_scraped_jobs_posted_sort", "posted_at_sort"),
        Index("ix_scraped_jobs_source", "source"),
        Index("ix_scraped_jobs_location", "location"),
        Index("ix_scraped_jobs_seniority", "seniority"),
        Index("ix_scraped_jobs_emp_type", "employment_type"),
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


class UsageLog(Base):
    __tablename__ = "usage_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
