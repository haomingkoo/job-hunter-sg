import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from job_precompute import classify_sector, salary_bounds_from_text


def test_classify_sector_uses_title_and_skill_signals():
    assert classify_sector("Quantity Surveyor") == "Built Environment & Construction"
    assert classify_sector("Chef de Partie") == "Food & Hospitality"
    assert classify_sector("Manager", ["Risk Management", "Banking", "Compliance"]) == "Finance & Accounting"
    assert classify_sector("Digital Forensics Incident Responder", ["Cyber Security"]) == "IT / Tech"


def test_classify_sector_keeps_unknown_as_other():
    assert classify_sector("Principal Manager", ["Stakeholder Management"]) == "Other"


def test_salary_bounds_from_text_extracts_floor_ceiling_and_midpoint():
    assert salary_bounds_from_text("S$6,000 - S$8,500 monthly") == (6000, 8500, 7250)
    assert salary_bounds_from_text("up to $8,500") == (8500, 8500, 8500)
    assert salary_bounds_from_text("salary undisclosed") == (0, 0, 0)
