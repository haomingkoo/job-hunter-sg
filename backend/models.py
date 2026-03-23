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
    employment_type: Mapped[str] = mapped_column(String(100), default="")
    seniority: Mapped[str] = mapped_column(String(100), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    skills: Mapped[dict | list | None] = mapped_column(JSON, default=list)
    agency: Mapped[str] = mapped_column(String(300), default="")
    dedup_key: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    search_keyword: Mapped[str] = mapped_column(String(300), default="")
    scraped_at: Mapped[str] = mapped_column(String(50), default="")

    __table_args__ = (
        Index("ix_scraped_jobs_keyword", "search_keyword"),
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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)

    user: Mapped[User] = relationship("User", back_populates="tracked_jobs")


class UsageLog(Base):
    __tablename__ = "usage_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
