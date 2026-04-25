import json
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import company_taxonomy
from company_taxonomy import (
    apply_company_taxonomy,
    normalize_company_name,
    ssic_section_from_code,
)


def test_normalize_company_name_strips_common_legal_suffixes():
    assert normalize_company_name("THE SUPREME HR ADVISORY PTE. LTD.") == "the supreme hr advisory"
    assert normalize_company_name("DBS Bank Ltd") == "dbs bank"


def test_ssic_section_from_code_maps_to_official_section_range():
    assert ssic_section_from_code("62011") == "Information & Communications"
    assert ssic_section_from_code("64120") == "Financial & Insurance"
    assert ssic_section_from_code("41001") == "Construction"


def test_apply_company_taxonomy_prefers_cached_acra_ssic(tmp_path, monkeypatch):
    cache_path = tmp_path / "company_ssic_cache.json"
    cache_path.write_text(
        json.dumps(
            {
                "dbs bank": {
                    "company_ssic_code": "64120",
                    "company_ssic_description": "FULL BANKS",
                    "company_ssic_source": "acra",
                    "entity_name": "DBS BANK LTD",
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(company_taxonomy, "CACHE_PATH", cache_path)
    monkeypatch.setattr(company_taxonomy, "_COMPANY_CACHE", None)
    monkeypatch.setattr(company_taxonomy, "LIVE_LOOKUP_ENABLED", False)

    job_data = {"company": "DBS Bank Ltd", "sector": "Finance & Accounting"}
    apply_company_taxonomy(job_data)

    assert job_data["company_ssic_code"] == "64120"
    assert job_data["company_ssic_description"] == "FULL BANKS"
    assert job_data["company_ssic_source"] == "acra"
    assert job_data["sector"] == "Financial & Insurance"


def test_analytics_sector_label_strips_legacy_ssic_letter_prefix():
    from main import _analytics_sector_label

    assert _analytics_sector_label("K Financial & Insurance") == "Financial & Insurance"
    assert _analytics_sector_label("N Administrative & Support Services") == "Administrative & Support Services"
    # Already-clean labels are returned unchanged.
    assert _analytics_sector_label("Engineering") == "Engineering"
    assert _analytics_sector_label("Financial & Insurance") == "Financial & Insurance"


def test_apply_company_taxonomy_labels_fallback_without_fake_code(tmp_path, monkeypatch):
    cache_path = tmp_path / "company_ssic_cache.json"
    monkeypatch.setattr(company_taxonomy, "CACHE_PATH", cache_path)
    monkeypatch.setattr(company_taxonomy, "_COMPANY_CACHE", None)
    monkeypatch.setattr(company_taxonomy, "LIVE_LOOKUP_ENABLED", False)

    job_data = {"company": "Unknown Employer", "sector": "IT / Tech"}
    apply_company_taxonomy(job_data)

    assert job_data["company_ssic_code"] == ""
    assert job_data["company_ssic_description"] == ""
    assert job_data["company_ssic_source"] == "inferred"
    assert job_data["sector"] == "IT / Tech"
