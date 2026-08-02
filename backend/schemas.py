"""
Pydantic v2 request / response schemas.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator


# ── Auth ─────────────────────────────────────────────────────────────────────

# Allowed email domains for signup (set via ALLOWED_EMAIL_DOMAINS env var)
# Default: * (open signup). Set to "aisg.sg" to restrict, or comma-separated for multiple.
import os as _os
_raw_domains = _os.environ.get("ALLOWED_EMAIL_DOMAINS", "*").strip()
_ALLOWED_DOMAINS: list[str] = []
if _raw_domains and _raw_domains != "*":
    _ALLOWED_DOMAINS = [
        d.strip().lower()
        for d in _raw_domains.split(",")
        if d.strip()
    ]


class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    name: str = Field(..., min_length=1, max_length=255)
    accepted_terms: bool = Field(False, description="User accepted Terms of Service and Privacy Notice")

    @field_validator("email")
    @classmethod
    def email_domain_check(cls, v: str) -> str:
        domain = v.split("@")[-1].lower()
        if _ALLOWED_DOMAINS and domain not in _ALLOWED_DOMAINS:
            allowed = ", ".join(f"@{d}" for d in _ALLOWED_DOMAINS)
            raise ValueError(f"Signup restricted to {allowed} emails")
        return v

    @field_validator("accepted_terms")
    @classmethod
    def accepted_terms_required(cls, v: bool) -> bool:
        if not v:
            raise ValueError("You must accept the Terms of Service and Privacy Notice")
        return v


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., max_length=128)


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str = Field(..., min_length=20, max_length=300)
    password: str = Field(..., min_length=8, max_length=128)

class VerifyEmailRequest(BaseModel):
    token: str = Field(..., min_length=20, max_length=300)
    password: str = Field(..., min_length=8, max_length=128)
    name: str = Field(..., min_length=1, max_length=255)
    accepted_terms: bool = False

    @field_validator("accepted_terms")
    @classmethod
    def accepted_terms_required(cls, v: bool) -> bool:
        if not v:
            raise ValueError("You must accept the Terms of Service and Privacy Notice")
        return v


class ResendVerificationRequest(BaseModel):
    email: EmailStr


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(..., max_length=128)
    new_password: str = Field(..., min_length=8, max_length=128)


class DeleteAccountRequest(BaseModel):
    confirm_email: str = Field(..., min_length=3, max_length=255)
    current_password: Optional[str] = Field(None, max_length=128)


class CloudflareRegisterRequest(BaseModel):
    name: Optional[str] = Field(None, max_length=255)
    accepted_terms: bool = False

    @field_validator("accepted_terms")
    @classmethod
    def accepted_terms_required(cls, v: bool) -> bool:
        if not v:
            raise ValueError("You must accept the Terms of Service and Privacy Notice")
        return v


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    name: str
    tier: str
    api_key: Optional[str] = None
    created_at: datetime
    email_verified_at: Optional[datetime] = None
    terms_accepted_at: Optional[datetime] = None
    privacy_accepted_at: Optional[datetime] = None

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
    source_posting_id: str = ""
    openings: int = 1
    sector: str = ""
    company_ssic_code: str = ""
    company_ssic_description: str = ""
    company_ssic_source: str = ""
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

_STATUS = Literal[
    "saved",
    "applied",
    "screening",
    "interview",
    "assessment",
    "final_round",
    "offer",
    "accepted",
    "rejected",
    "withdrawn",
    "no_response",
]


class TrackedJobCreate(BaseModel):
    company: str = Field(..., min_length=1, max_length=500)
    role: str = Field(..., min_length=1, max_length=500)
    date_applied: Optional[str] = Field(None, max_length=50)
    status: _STATUS = "applied"
    source: str = Field("", max_length=200)
    source_url: str = Field("", max_length=2000)
    job_description: str = Field("", max_length=50000)
    role_metadata: dict[str, Any] = Field(default_factory=dict)
    follow_up_date: Optional[str] = Field(None, max_length=50)
    notes: str = Field("", max_length=5000)
    scraped_job_id: Optional[int] = None
    resume_version_id: Optional[int] = None


class TrackedJobUpdate(BaseModel):
    company: Optional[str] = Field(None, max_length=500)
    role: Optional[str] = Field(None, max_length=500)
    date_applied: Optional[str] = Field(None, max_length=50)
    status: Optional[_STATUS] = None
    source: Optional[str] = Field(None, max_length=200)
    source_url: Optional[str] = Field(None, max_length=2000)
    job_description: Optional[str] = Field(None, max_length=50000)
    role_metadata: Optional[dict[str, Any]] = None
    follow_up_date: Optional[str] = Field(None, max_length=50)
    notes: Optional[str] = Field(None, max_length=5000)
    resume_version_id: Optional[int] = None


class TrackedJobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    company: str
    role: str
    date_applied: Optional[str]
    status: str
    source: str
    source_url: str = ""
    job_description: str = ""
    role_metadata: Optional[dict[str, Any]] = None
    follow_up_date: Optional[str]
    notes: str
    scraped_job_id: Optional[int]
    resume_version_id: Optional[int] = None
    stage_history: Optional[list] = None
    created_at: datetime
    updated_at: datetime


class ApplicationWorkspaceCreate(BaseModel):
    company: str = Field(..., min_length=1, max_length=500)
    title: str = Field(..., min_length=1, max_length=500)
    job_description: str = Field(..., min_length=1, max_length=50000)
    source_url: str = Field("", max_length=2000)
    source: str = Field("", max_length=200)
    status: _STATUS = "saved"
    date_applied: Optional[str] = Field(None, max_length=50)
    follow_up_date: Optional[str] = Field(None, max_length=50)
    notes: str = Field("", max_length=5000)
    scraped_job_id: Optional[int] = None
    resume_version_id: Optional[int] = None
    role_metadata: dict[str, Any] = Field(default_factory=dict)


class ApplicationWorkspaceOut(BaseModel):
    id: int
    user_id: int
    company: str
    title: str
    role: str
    job_description: str
    source_url: str
    source: str
    status: str
    date_applied: Optional[str]
    follow_up_date: Optional[str]
    notes: str
    scraped_job_id: Optional[int]
    resume_version_id: Optional[int] = None
    role_metadata: dict[str, Any] = Field(default_factory=dict)
    stage_history: list = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


# ── Job Alerts ───────────────────────────────────────────────────────────────

_ALERT_FREQUENCY = Literal["daily", "weekly"]


class JobAlertPreferenceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    enabled: bool
    min_score: int
    direct_employers_only: bool
    frequency: str
    keywords: str
    max_jobs: int
    last_run_at: Optional[datetime]
    consented_at: Optional[datetime]
    unsubscribed_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime


class JobAlertPreferenceUpdate(BaseModel):
    enabled: Optional[bool] = None
    min_score: Optional[int] = Field(None, ge=35, le=95)
    direct_employers_only: Optional[bool] = None
    frequency: Optional[_ALERT_FREQUENCY] = None
    keywords: Optional[str] = Field(None, max_length=300)
    max_jobs: Optional[int] = Field(None, ge=1, le=10)

    @field_validator("keywords")
    @classmethod
    def clean_keywords(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return " ".join(value.split()).strip()


# ── Utility ──────────────────────────────────────────────────────────────────

class ContactRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    email: EmailStr
    message: str = Field(..., min_length=1, max_length=5000)


class ResumeScoreRequest(BaseModel):
    resume_text: str = Field(..., min_length=50, max_length=50000)
    job_description: str = Field("", max_length=10000)
    job_id: int | None = Field(None, description="Optional job ID to fetch parsed JD for ATS blending")
    template_id: str | None = Field(None, description="Template ID to check expected sections")


class ResumeAIRequest(ResumeScoreRequest):
    resume_text: str = Field(..., min_length=50, max_length=10000)


class RewriteBulletRequest(BaseModel):
    bullet: str = Field(..., min_length=1, max_length=1000)
    job_title: str = Field("", max_length=200)
    job_description: str = Field("", max_length=10000)
    job_id: int | None = Field(None, description="Target job ID for structured JD context")
    session_id: str = Field("", max_length=64)
    used_verbs: str = Field("", max_length=500)
    rewrite_focus: str = Field("", max_length=200)
    focused_feedback: str = Field("", max_length=2000)


class IntegrateKeywordsRequest(BaseModel):
    resume_text: str = Field(..., min_length=50, max_length=10000)
    missing_keywords: list[str] = Field(..., min_length=1, max_length=20)
    job_title: str = Field("", max_length=200)
    session_id: str = Field("", max_length=64)


class RegenerateSummaryRequest(BaseModel):
    resume_text: str = Field(..., min_length=50, max_length=10000)
    job_id: int | None = Field(None, description="Target job ID for JD context")
    user_direction: str | None = Field(None, max_length=500, description="User's custom instruction for summary style/focus")


class CoverLetterRequest(BaseModel):
    resume_text: str = Field(..., min_length=50, max_length=10000)
    job_id: int | None = Field(None)
    job_title: str = Field("", max_length=200)
    job_company: str = Field("", max_length=200)
    job_description: str = Field("", max_length=10000)
    user_direction: str | None = Field(None, max_length=500, description="Custom instruction like 'emphasize leadership' or 'keep it concise'")


class ApplicationPackRequest(BaseModel):
    resume_text: str = Field(..., min_length=50, max_length=15000)
    job_id: int | None = Field(None)
    job_title: str = Field("", max_length=200)
    job_company: str = Field("", max_length=200)
    job_description: str = Field("", max_length=15000)
    user_direction: str | None = Field(None, max_length=1000, description="Optional instruction for the application agent")


class SkillsFutureRecommendRequest(BaseModel):
    skills: list[str] = Field(..., min_length=1, max_length=8)
    per_skill: int = Field(3, ge=1, le=5)

    @field_validator("skills")
    @classmethod
    def clean_skills(cls, value: list[str]) -> list[str]:
        cleaned = []
        seen = set()
        for raw in value:
            skill = " ".join(str(raw or "").split()).strip()
            key = skill.lower()
            if not skill or key in seen:
                continue
            if len(skill) > 80:
                skill = skill[:80]
            cleaned.append(skill)
            seen.add(key)
        if not cleaned:
            raise ValueError("At least one skill is required")
        return cleaned[:8]


class ResumeChatRequest(BaseModel):
    messages: list = Field(..., description="Chat history: [{role: 'user'|'assistant', content: '...'}]")
    action: str = Field("chat", description="'chat' for next question, 'generate' to produce resume")


class ClientErrorReport(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    stack: str = Field(default="", max_length=4000)
    url: str = Field(default="", max_length=500)
    user_agent: str = Field(default="", max_length=300)
