"""
Precomputed job metadata used to keep request-time filters cheap.
"""

from __future__ import annotations

import re


SECTOR_KEYWORDS: dict[str, list[str]] = {
    "Engineering": [
        "engineer", "engineering", "mechanical", "electrical", "civil",
        "structural", "chemical", "hardware", "firmware", "embedded",
    ],
    "IT / Tech": [
        "software", "developer", "devops", "sre", "cloud", "fullstack",
        "full-stack", "full stack", "frontend", "front-end", "backend",
        "back-end", "programmer", "sysadmin", "it ", "information technology",
        "cybersecurity", "cyber security", "infrastructure", "platform",
        "solutions architect", "tech lead", "technical lead",
    ],
    "Data & AI": [
        "data", "machine learning", "ml ", "ai ", "artificial intelligence",
        "analytics", "business intelligence", "bi ", "data scientist",
        "data engineer", "data analyst", "nlp", "deep learning",
    ],
    "Finance & Accounting": [
        "finance", "financial", "accountant", "accounting", "audit",
        "tax", "treasury", "credit", "banking", "investment", "fund",
        "compliance", "risk", "actuary", "actuarial",
    ],
    "Healthcare": [
        "nurse", "nursing", "doctor", "medical", "healthcare",
        "health care", "clinical", "pharmacy", "pharmacist",
        "therapist", "physiotherapist", "dental", "dentist",
    ],
    "Sales & Marketing": [
        "sales", "marketing", "business development", "account manager",
        "brand", "digital marketing", "seo", "sem ", "content",
        "communications", "public relations", "pr ", "advertising",
        "growth", "partnership",
    ],
    "Admin & Operations": [
        "admin", "administrator", "operations", "coordinator",
        "executive assistant", "office", "receptionist", "clerk",
        "procurement", "supply chain", "logistics", "warehouse",
    ],
    "Design & Creative": [
        "designer", "design", "ux", "ui ", "graphic", "creative",
        "art director", "visual", "illustrator", "copywriter",
    ],
    "HR & Recruitment": [
        "human resource", "hr ", "recruiter", "recruitment", "talent",
        "people", "compensation", "benefits", "payroll", "hrbp",
    ],
    "Education & Training": [
        "teacher", "lecturer", "professor", "trainer", "training",
        "education", "tutor", "curriculum", "instructor", "teaching",
    ],
    "Legal": [
        "lawyer", "legal", "counsel", "paralegal", "litigation",
        "contract", "regulatory",
    ],
    "Product & Project Management": [
        "product manager", "project manager", "scrum", "agile",
        "program manager", "product owner", "delivery manager",
    ],
}


def classify_sector(title: str) -> str:
    lower = f" {(title or '').lower()} "
    for sector, keywords in SECTOR_KEYWORDS.items():
        for keyword in keywords:
            if keyword in lower:
                return sector
    return "Other"


def salary_floor_from_text(value: str) -> int:
    numbers = [
        int(part.replace(",", ""))
        for part in re.findall(r"\d[\d,]*", value or "")
    ]
    return numbers[0] if numbers else 0


def _flatten_skill_values(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, dict):
        flattened: list[str] = []
        for child in value.values():
            flattened.extend(_flatten_skill_values(child))
        return flattened
    if isinstance(value, (list, tuple, set)):
        flattened: list[str] = []
        for child in value:
            flattened.extend(_flatten_skill_values(child))
        return flattened
    text_value = str(value).strip()
    return [text_value] if text_value else []


def skills_flat_text(skills) -> str:
    seen: set[str] = set()
    parts: list[str] = []
    for skill in _flatten_skill_values(skills):
        normalized = re.sub(r"\s+", " ", skill).strip()
        key = normalized.lower()
        if not normalized or key in seen:
            continue
        seen.add(key)
        parts.append(normalized)
    return " ".join(parts)[:5000]


def apply_job_precomputes(job_data: dict) -> dict:
    job_data["sector"] = classify_sector(job_data.get("title", "") or "")
    job_data["salary_floor"] = salary_floor_from_text(job_data.get("salary", "") or "")
    job_data["skills_flat"] = skills_flat_text(job_data.get("skills"))
    return job_data
