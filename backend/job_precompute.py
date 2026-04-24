"""
Precomputed job metadata used to keep request-time filters cheap.
"""

from __future__ import annotations

import re
from collections.abc import Iterable


SECTOR_KEYWORDS: dict[str, list[str]] = {
    "Data & AI": [
        "data", "machine learning", "ml ", "ai ", "artificial intelligence",
        "analytics", "business intelligence", "bi ", "data scientist",
        "data engineer", "data analyst", "nlp", "deep learning",
        "data science", "data governance", "data visualization",
    ],
    "IT / Tech": [
        "software", "software engineer", "developer", "devops", "sre",
        "cloud", "fullstack", "full-stack", "full stack", "frontend",
        "front-end", "backend", "back-end", "programmer", "sysadmin",
        "it ", "information technology", "cybersecurity", "cyber security",
        "infrastructure", "platform", "solutions architect", "tech lead",
        "technical lead", "application engineer", "systems analyst",
        "network engineer", "database administrator",
    ],
    "Engineering": [
        "engineer", "engineering", "mechanical", "electrical", "civil",
        "structural", "chemical", "hardware", "firmware", "embedded",
        "technician", "maintenance engineer", "quality engineer",
    ],
    "Built Environment & Construction": [
        "quantity surveyor", "surveyor", "construction", "site supervisor",
        "site engineer", "site manager", "project coordinator construction",
        "bim", "architectural", "architecture", "m&e", "facilities",
        "property management", "estate management", "building services",
    ],
    "Food & Hospitality": [
        "cook", "chef", "kitchen", "culinary", "restaurant", "f&b",
        "food and beverage", "food service", "barista", "service crew",
        "banquet", "hotel", "hospitality", "waiter", "waitress",
        "housekeeping", "catering",
    ],
    "Finance & Accounting": [
        "finance", "financial", "accountant", "accounting", "audit",
        "tax", "treasury", "credit", "banking", "investment", "fund",
        "compliance", "risk", "actuary", "actuarial", "accounts executive",
        "accounts assistant", "bookkeeping", "payables", "receivables",
    ],
    "Healthcare": [
        "nurse", "nursing", "doctor", "medical", "healthcare",
        "health care", "clinical", "pharmacy", "pharmacist",
        "physiotherapist", "dental", "dentist", "radiographer",
        "diagnostic imaging", "patient care",
    ],
    "Beauty & Wellness": [
        "beautician", "beauty", "aesthetic", "esthetician", "spa",
        "wellness", "massage", "masseur", "hair stylist", "nail",
        "therapist",
    ],
    "Sales & Marketing": [
        "sales", "marketing", "business development", "account manager",
        "brand", "digital marketing", "seo", "sem ", "content",
        "communications", "public relations", "pr ", "advertising",
        "growth", "partnership", "customer success", "retail associate",
        "merchandising", "ecommerce", "e-commerce",
    ],
    "Admin & Operations": [
        "admin", "administrator", "operations", "coordinator",
        "executive assistant", "office", "receptionist", "clerk",
        "procurement", "supply chain", "logistics", "warehouse",
        "inventory", "purchasing", "shipping", "driver", "delivery",
        "transport", "fleet",
    ],
    "Customer Service": [
        "customer service", "customer care", "call centre", "call center",
        "contact centre", "contact center", "service ambassador",
        "client service", "guest relations", "helpdesk",
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
    "Public Sector & Policy": [
        "policy", "governance", "public service", "public sector",
        "ministry", "statutory board", "land acquisition", "urban planning",
        "strategic planning", "manpower policy",
    ],
    "Product & Project Management": [
        "product manager", "project manager", "scrum", "agile",
        "program manager", "product owner", "delivery manager",
    ],
}


def _normalize_match_text(value: str) -> str:
    return f" {re.sub(r'[^a-z0-9+#./&-]+', ' ', (value or '').lower())} "


def _skill_text(skills) -> str:
    if skills is None:
        return ""
    if isinstance(skills, str):
        return skills
    if isinstance(skills, dict):
        return " ".join(_skill_text(child) for child in skills.values())
    if isinstance(skills, Iterable):
        return " ".join(_skill_text(child) for child in skills)
    return str(skills)


def _keyword_hits(text: str, keyword: str) -> int:
    needle = _normalize_match_text(keyword)
    return 1 if needle.strip() and needle in text else 0


def classify_sector(title: str, skills=None, description: str = "") -> str:
    """
    Infer a market sector from cheap, already-extracted fields.

    Title carries the most weight, but skill terms help classify generic titles
    like "Manager", "Executive", or "Specialist" without pulling large job
    descriptions into request-time analytics.
    """
    title_text = _normalize_match_text(title)
    skills_text = _normalize_match_text(_skill_text(skills))
    description_text = _normalize_match_text((description or "")[:2000])
    scores: dict[str, int] = {}
    for sector, keywords in SECTOR_KEYWORDS.items():
        score = 0
        for keyword in keywords:
            score += _keyword_hits(title_text, keyword) * 4
            score += _keyword_hits(skills_text, keyword) * 3
            score += _keyword_hits(description_text, keyword)
        if score:
            scores[sector] = score
    if scores:
        return max(scores.items(), key=lambda item: item[1])[0]
    return "Other"


def salary_floor_from_text(value: str) -> int:
    numbers = [
        int(part.replace(",", ""))
        for part in re.findall(r"\d[\d,]*", value or "")
    ]
    return numbers[0] if numbers else 0


def salary_bounds_from_text(value: str) -> tuple[int, int, int]:
    numbers = [
        int(part.replace(",", ""))
        for part in re.findall(r"\d[\d,]*", value or "")
    ]
    plausible = [number for number in numbers if 0 < number < 1_000_000]
    if not plausible:
        return 0, 0, 0
    low = plausible[0]
    high = plausible[1] if len(plausible) > 1 else plausible[0]
    if high < low:
        low, high = high, low
    midpoint = round((low + high) / 2)
    return low, high, midpoint


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
    job_data["sector"] = classify_sector(
        job_data.get("title", "") or "",
        job_data.get("skills"),
        job_data.get("description", "") or "",
    )
    job_data["salary_floor"] = salary_floor_from_text(job_data.get("salary", "") or "")
    job_data["skills_flat"] = skills_flat_text(job_data.get("skills"))
    return job_data
