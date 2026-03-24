"""
Pydantic v2 request / response schemas.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator


# ── Auth ─────────────────────────────────────────────────────────────────────

# Allowed email domains for signup (set via ALLOWED_EMAIL_DOMAINS env var)
# Default: aisg.sg (AI Singapore). Comma-separated for multiple domains.
import os as _os
_ALLOWED_DOMAINS = [
    d.strip().lower()
    for d in _os.environ.get("ALLOWED_EMAIL_DOMAINS", "aisg.sg").split(",")
    if d.strip()
]


class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    name: str = Field(..., min_length=1, max_length=255)

    @field_validator("email")
    @classmethod
    def email_domain_check(cls, v: str) -> str:
        domain = v.split("@")[-1].lower()
        if _ALLOWED_DOMAINS and domain not in _ALLOWED_DOMAINS:
            allowed = ", ".join(f"@{d}" for d in _ALLOWED_DOMAINS)
            raise ValueError(f"Signup restricted to {allowed} emails")
        return v

    @field_validator("password")
    @classmethod
    def password_min_length(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., max_length=128)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    name: str
    tier: str
    api_key: Optional[str] = None
    created_at: datetime

    @model_validator(mode="after")
    def mask_api_key(self):
        if self.api_key and len(self.api_key) > 4:
            self.api_key = f"...{self.api_key[-4:]}"
        return self


class AuthResponse(BaseModel):
    token: str
    user: UserOut


# ── Jobs ─────────────────────────────────────────────────────────────────────

class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    company: str
    location: str
    salary: str
    source: str
    url: str
    posted_date: str
    employment_type: str
    seniority: str
    description: str
    skills: Any
    agency: str
    scraped_at: str


class SearchResponse(BaseModel):
    keyword: str
    searched_at: str
    total_raw: int
    total_deduped: int
    duplicates_removed: int
    ssg_recommended_skills: list[str]
    by_source: dict[str, int]
    jobs: list[JobOut]


# ── Tracker ──────────────────────────────────────────────────────────────────

_STATUS = Literal["applied", "interview", "offer", "rejected", "withdrawn"]


class TrackedJobCreate(BaseModel):
    company: str = Field(..., min_length=1, max_length=500)
    role: str = Field(..., min_length=1, max_length=500)
    date_applied: Optional[str] = Field(None, max_length=50)
    status: _STATUS = "applied"
    source: str = Field("", max_length=200)
    follow_up_date: Optional[str] = Field(None, max_length=50)
    notes: str = Field("", max_length=5000)
    scraped_job_id: Optional[int] = None


class TrackedJobUpdate(BaseModel):
    company: Optional[str] = Field(None, max_length=500)
    role: Optional[str] = Field(None, max_length=500)
    date_applied: Optional[str] = Field(None, max_length=50)
    status: Optional[_STATUS] = None
    source: Optional[str] = Field(None, max_length=200)
    follow_up_date: Optional[str] = Field(None, max_length=50)
    notes: Optional[str] = Field(None, max_length=5000)


class TrackedJobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    company: str
    role: str
    date_applied: Optional[str]
    status: str
    source: str
    follow_up_date: Optional[str]
    notes: str
    scraped_job_id: Optional[int]
    created_at: datetime
    updated_at: datetime


# ── Utility ──────────────────────────────────────────────────────────────────

class ContactRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    email: EmailStr
    message: str = Field(..., min_length=1, max_length=5000)


class TierInfo(BaseModel):
    name: str
    price: str
    limits: dict[str, Any]
    features: list[str]


class ResumeScoreRequest(BaseModel):
    resume_text: str = Field(..., min_length=50, max_length=10000)
    job_description: str = Field("", max_length=10000)


class RewriteBulletRequest(BaseModel):
    bullet: str = Field(..., min_length=1, max_length=1000)
    job_title: str = Field("", max_length=200)
    session_id: str = Field("", max_length=64)
    used_verbs: str = Field("", max_length=500)


class IntegrateKeywordsRequest(BaseModel):
    resume_text: str = Field(..., min_length=50, max_length=10000)
    missing_keywords: list[str] = Field(..., min_length=1, max_length=20)
    job_title: str = Field("", max_length=200)
    session_id: str = Field("", max_length=64)
