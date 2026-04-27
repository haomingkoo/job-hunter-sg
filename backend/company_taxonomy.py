"""
Company-to-industry taxonomy helpers.

Official company industry is sourced from ACRA corporate entity records on
data.gov.sg, which expose primary SSIC codes and descriptions. Live lookups are
disabled by default so user-facing job searches do not block on public API rate
limits. Provide a local JSON cache or set ACRA_LIVE_LOOKUP=1 for explicit
backfills.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import requests

log = logging.getLogger(__name__)

ACRA_COLLECTION_ID = os.environ.get("ACRA_COLLECTION_ID", "2")
ACRA_COLLECTION_METADATA_URL = (
    "https://api-production.data.gov.sg/v2/public/api/collections/"
    f"{ACRA_COLLECTION_ID}/metadata?withDatasetMetadata=true"
)
DATASTORE_SEARCH_URL = "https://data.gov.sg/api/action/datastore_search"
DEFAULT_CACHE_PATH = Path(__file__).resolve().parent / "data" / "company_ssic_cache.json"
CACHE_PATH = Path(os.environ.get("COMPANY_SSIC_CACHE_PATH", str(DEFAULT_CACHE_PATH)))
LIVE_LOOKUP_ENABLED = os.environ.get("ACRA_LIVE_LOOKUP", "").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
LIVE_LOOKUP_MIN_INTERVAL_SECONDS = float(
    os.environ.get("ACRA_LIVE_LOOKUP_MIN_INTERVAL_SECONDS", "2.6")
)
LIVE_LOOKUP_MAX_ATTEMPTS = int(os.environ.get("ACRA_LIVE_LOOKUP_MAX_ATTEMPTS", "3"))
LIVE_LOOKUP_RETRY_SECONDS = float(os.environ.get("ACRA_LIVE_LOOKUP_RETRY_SECONDS", "12"))

_COMPANY_CACHE_LOCK = threading.Lock()
_COMPANY_CACHE: dict[str, dict[str, str]] | None = None
_DATASET_MAP_LOCK = threading.Lock()
_DATASET_MAP: dict[str, str] | None = None
_DATASET_MAP_FETCHED_AT = 0.0
_LAST_LIVE_LOOKUP_AT = 0.0

_LEGAL_SUFFIXES = {
    "PTE",
    "PRIVATE",
    "LTD",
    "LIMITED",
    "LLP",
    "LP",
    "LLC",
    "INC",
    "CO",
    "COMPANY",
    "CORP",
    "CORPORATION",
    "PLC",
}
_GENERIC_COMPANY_NAMES = {
    "",
    "confidential",
    "private advertiser",
    "undisclosed",
    "unknown",
    "singapore public service",
}


@dataclass(frozen=True)
class CompanyTaxonomyMatch:
    company_ssic_code: str
    company_ssic_description: str
    company_ssic_source: str = "acra"
    entity_name: str = ""


SSIC_SECTIONS: tuple[tuple[int, int, str], ...] = (
    (1, 3, "Agriculture & Fishing"),
    (5, 9, "Mining & Quarrying"),
    (10, 32, "Manufacturing"),
    (35, 35, "Electricity & Gas Supply"),
    (36, 39, "Water Supply, Sewerage & Waste Management"),
    (41, 43, "Construction"),
    (46, 47, "Wholesale & Retail Trade"),
    (49, 53, "Transportation & Storage"),
    (55, 56, "Accommodation & Food Service"),
    (58, 63, "Information & Communications"),
    (64, 66, "Financial & Insurance"),
    (68, 68, "Real Estate"),
    (69, 75, "Professional, Scientific & Technical"),
    (77, 82, "Administrative & Support Services"),
    (84, 84, "Public Administration & Defence"),
    (85, 85, "Education"),
    (86, 88, "Health & Social Services"),
    (90, 93, "Arts, Entertainment & Recreation"),
    (94, 96, "Other Service Activities"),
    (97, 98, "Household Employers"),
    (99, 99, "Extra-Territorial Organisations"),
)


def normalize_company_name(name: str) -> str:
    """Normalize employer names for ACRA cache lookup."""
    text = (name or "").upper().replace("&", " AND ")
    text = re.sub(r"\([^)]*\)", " ", text)
    text = re.sub(r"[^A-Z0-9]+", " ", text)
    words = [word for word in text.split() if word and word not in _LEGAL_SUFFIXES]
    return " ".join(words).lower()


def _is_generic_company(name: str) -> bool:
    return normalize_company_name(name) in _GENERIC_COMPANY_NAMES


def ssic_section_from_code(code: str) -> str:
    digits = re.sub(r"\D", "", code or "")
    if len(digits) < 2:
        return ""
    division = int(digits[:2])
    for start, end, label in SSIC_SECTIONS:
        if start <= division <= end:
            return label
    return ""


def _load_company_cache() -> dict[str, dict[str, str]]:
    global _COMPANY_CACHE
    with _COMPANY_CACHE_LOCK:
        if _COMPANY_CACHE is not None:
            return _COMPANY_CACHE
        if not CACHE_PATH.exists():
            _COMPANY_CACHE = {}
            return _COMPANY_CACHE
        try:
            with CACHE_PATH.open("r", encoding="utf-8") as fh:
                raw = json.load(fh)
            _COMPANY_CACHE = {
                normalize_company_name(key): value
                for key, value in raw.items()
                if isinstance(value, dict)
            }
        except Exception as exc:
            log.warning("Failed to load company SSIC cache: %s", type(exc).__name__)
            _COMPANY_CACHE = {}
        return _COMPANY_CACHE


def _write_company_cache(cache: dict[str, dict[str, str]]) -> None:
    with _COMPANY_CACHE_LOCK:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with CACHE_PATH.open("w", encoding="utf-8") as fh:
            json.dump(cache, fh, indent=2, sort_keys=True)


def cache_company_taxonomy(company_name: str, match: CompanyTaxonomyMatch) -> None:
    key = normalize_company_name(company_name or match.entity_name)
    if not key:
        return
    cache = _load_company_cache()
    cache[key] = asdict(match)
    _write_company_cache(cache)


def _dataset_letter_for_company(name: str) -> str:
    normalized = normalize_company_name(name)
    first = normalized[:1].upper()
    return first if first and "A" <= first <= "Z" else "OTHERS"


def _fetch_dataset_map() -> dict[str, str]:
    global _DATASET_MAP, _DATASET_MAP_FETCHED_AT
    with _DATASET_MAP_LOCK:
        now = time.monotonic()
        if _DATASET_MAP is not None and now - _DATASET_MAP_FETCHED_AT < 24 * 3600:
            return _DATASET_MAP
        resp = requests.get(ACRA_COLLECTION_METADATA_URL, timeout=15)
        resp.raise_for_status()
        payload = resp.json().get("data", {})
        datasets = payload.get("datasetMetadata") or []
        dataset_map: dict[str, str] = {}
        for dataset in datasets:
            name = str(dataset.get("name") or "")
            dataset_id = str(dataset.get("datasetId") or "")
            match = re.search(r"\('([^']+)'\)", name)
            if not match or not dataset_id:
                continue
            key = match.group(1).upper()
            dataset_map["OTHERS" if key == "OTHERS" else key] = dataset_id
        _DATASET_MAP = dataset_map
        _DATASET_MAP_FETCHED_AT = now
        return dataset_map


def _rate_limit_live_lookup() -> None:
    global _LAST_LIVE_LOOKUP_AT
    if LIVE_LOOKUP_MIN_INTERVAL_SECONDS <= 0:
        return
    elapsed = time.monotonic() - _LAST_LIVE_LOOKUP_AT
    if elapsed < LIVE_LOOKUP_MIN_INTERVAL_SECONDS:
        time.sleep(LIVE_LOOKUP_MIN_INTERVAL_SECONDS - elapsed)
    _LAST_LIVE_LOOKUP_AT = time.monotonic()


def _valid_ssic_value(value: Any) -> str:
    text = str(value or "").strip()
    return "" if text.lower() in {"", "na", "n.a.", "none", "null"} else text


def _score_record(record: dict, target_key: str) -> int:
    entity_key = normalize_company_name(str(record.get("entity_name") or ""))
    status = str(record.get("entity_status_description") or "").lower()
    score = 0
    if entity_key == target_key:
        score += 100
    elif target_key and (target_key in entity_key or entity_key in target_key):
        score += 45
    if any(word in status for word in ("live", "registered")):
        score += 20
    if _valid_ssic_value(record.get("primary_ssic_code")):
        score += 10
    return score


def _acra_retry_after(resp: requests.Response) -> float:
    retry_after = resp.headers.get("Retry-After", "")
    try:
        return min(60.0, max(1.0, float(retry_after)))
    except ValueError:
        pass
    try:
        message = str(resp.json().get("errorMsg") or "")
    except ValueError:
        message = ""
    match = re.search(r"try again in (\d+(?:\.\d+)?) seconds", message, re.I)
    if match:
        return min(60.0, max(1.0, float(match.group(1))))
    return LIVE_LOOKUP_RETRY_SECONDS


def _lookup_acra_live(company_name: str) -> CompanyTaxonomyMatch | None:
    if _is_generic_company(company_name):
        return None
    target_key = normalize_company_name(company_name)
    dataset_id = _fetch_dataset_map().get(_dataset_letter_for_company(company_name))
    if not dataset_id:
        return None

    params = {
        "resource_id": dataset_id,
        "limit": 10,
        "fields": "entity_name,entity_status_description,primary_ssic_code,primary_ssic_description",
        "q": target_key,
    }
    resp = None
    attempts = max(1, LIVE_LOOKUP_MAX_ATTEMPTS)
    for attempt in range(attempts):
        _rate_limit_live_lookup()
        resp = requests.get(DATASTORE_SEARCH_URL, params=params, timeout=15)
        if resp.status_code == 429 and attempt < attempts - 1:
            wait_seconds = _acra_retry_after(resp)
            log.info("ACRA lookup rate-limited for company=%r; retrying in %.1fs", company_name, wait_seconds)
            time.sleep(wait_seconds)
            continue
        resp.raise_for_status()
        break
    if resp is None:
        return None
    records = resp.json().get("result", {}).get("records", [])
    viable = [
        record for record in records
        if _valid_ssic_value(record.get("primary_ssic_code"))
    ]
    if not viable:
        return None
    best = max(viable, key=lambda record: _score_record(record, target_key))
    if _score_record(best, target_key) < 45:
        return None
    code = _valid_ssic_value(best.get("primary_ssic_code"))
    return CompanyTaxonomyMatch(
        company_ssic_code=code,
        company_ssic_description=_valid_ssic_value(best.get("primary_ssic_description")),
        entity_name=_valid_ssic_value(best.get("entity_name")),
    )


def lookup_company_ssic(
    company_name: str,
    *,
    allow_live: bool | None = None,
) -> CompanyTaxonomyMatch | None:
    if _is_generic_company(company_name):
        return None
    key = normalize_company_name(company_name)
    if not key:
        return None

    cached = _load_company_cache().get(key)
    if cached:
        code = _valid_ssic_value(cached.get("company_ssic_code"))
        if code:
            return CompanyTaxonomyMatch(
                company_ssic_code=code,
                company_ssic_description=_valid_ssic_value(cached.get("company_ssic_description")),
                company_ssic_source="acra",
                entity_name=_valid_ssic_value(cached.get("entity_name")),
            )

    use_live = LIVE_LOOKUP_ENABLED if allow_live is None else allow_live
    if not use_live:
        return None
    try:
        match = _lookup_acra_live(company_name)
    except Exception as exc:
        log.warning("ACRA lookup failed for company=%r: %s", company_name, type(exc).__name__)
        return None
    if match:
        cache_company_taxonomy(company_name, match)
    return match


def apply_company_taxonomy(job_data: dict) -> dict:
    """Populate company_ssic_* and prefer official SSIC section for sector."""
    existing_code = _valid_ssic_value(job_data.get("company_ssic_code"))
    existing_source = str(job_data.get("company_ssic_source") or "").strip().lower()
    if existing_code and existing_source == "acra":
        section = ssic_section_from_code(existing_code)
        if section:
            job_data["sector"] = section
        return job_data

    match = lookup_company_ssic(str(job_data.get("company") or ""))
    if match:
        job_data["company_ssic_code"] = match.company_ssic_code
        job_data["company_ssic_description"] = match.company_ssic_description
        job_data["company_ssic_source"] = "acra"
        section = ssic_section_from_code(match.company_ssic_code)
        if section:
            job_data["sector"] = section
        return job_data

    job_data["company_ssic_code"] = ""
    job_data["company_ssic_description"] = ""
    inferred_sector = str(job_data.get("sector") or "").strip()
    job_data["company_ssic_source"] = (
        "inferred" if inferred_sector and inferred_sector != "Other" else "unavailable"
    )
    return job_data
