"""
SkillsFuture course recommendations from the official MySkillsFuture dataset.

The source is the SSG MySkillsFuture Course Directory published on data.gov.sg.
It is downloaded lazily and cached in memory so Smart Match stays responsive.
"""

from __future__ import annotations

import html
import io
import math
import os
import re
import threading
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree as ET
from urllib.parse import quote

import requests


DATASET_ID = "d_b5802b76f409764c16dde4bf2feb19cd"
POLL_URL = f"https://api-open.data.gov.sg/v1/public/api/datasets/{DATASET_ID}/poll-download"
COURSE_URL = "https://www.myskillsfuture.gov.sg/content/portal/en/training-exchange/course-directory/course-detail.html?courseReferenceNumber={ref}"
HEADERS = {"User-Agent": "JobHunterSG/1.0 (+https://jobhunter.kooexperience.com)"}
CACHE_TTL_SECONDS = 24 * 3600
DISK_CACHE_PATH = Path(os.environ.get("SKILLSFUTURE_COURSE_CACHE", "/tmp/jobhunter_skillsfuture_courses.xlsx"))

_cache_lock = threading.Lock()
_refresh_lock = threading.Lock()
_course_cache: list[dict] = []
_course_cache_ts = 0.0
_last_error = ""


@dataclass
class CourseRecommendation:
    course_reference_number: str
    title: str
    provider: str
    course_rating_stars: float
    course_rating_respondents: int
    career_impact_stars: float
    career_impact_respondents: int
    full_course_fee: float
    net_course_fee: float
    hours: float
    conducted_in: str
    url: str
    reason: str
    score: float


def _clean_text(value: str) -> str:
    text = html.unescape(str(value or ""))
    text = text.replace("_x000D_", "\n")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _to_float(value: object) -> float:
    try:
        return float(str(value or "").replace(",", "").strip())
    except ValueError:
        return 0.0


def _to_int(value: object) -> int:
    try:
        return int(float(str(value or "").replace(",", "").strip()))
    except ValueError:
        return 0


def _cell_text(cell: ET.Element, shared_strings: list[str], ns: dict[str, str]) -> str:
    cell_type = cell.attrib.get("t", "")
    if cell_type == "inlineStr":
        return _clean_text("".join(node.text or "" for node in cell.findall(".//x:t", ns)))
    value_node = cell.find("x:v", ns)
    if value_node is None or value_node.text is None:
        return ""
    raw = value_node.text
    if cell_type == "s":
        index = _to_int(raw)
        return shared_strings[index] if 0 <= index < len(shared_strings) else ""
    return _clean_text(raw)


def _read_shared_strings(workbook: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in workbook.namelist():
        return []
    ns = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    shared_strings: list[str] = []
    with workbook.open("xl/sharedStrings.xml") as handle:
        for _event, elem in ET.iterparse(handle, events=("end",)):
            if elem.tag.endswith("}si"):
                shared_strings.append(_clean_text("".join(node.text or "" for node in elem.findall(".//x:t", ns))))
                elem.clear()
    return shared_strings


def _column_index(cell_ref: str) -> int:
    letters = re.sub(r"[^A-Z]", "", cell_ref.upper())
    index = 0
    for letter in letters:
        index = index * 26 + (ord(letter) - ord("A") + 1)
    return max(0, index - 1)


def _iter_sheet_rows(workbook: zipfile.ZipFile, shared_strings: list[str]):
    ns = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with workbook.open("xl/worksheets/sheet1.xml") as handle:
        for _event, row in ET.iterparse(handle, events=("end",)):
            if not row.tag.endswith("}row"):
                continue
            values: dict[int, str] = {}
            for cell in row.findall("x:c", ns):
                cell_ref = cell.attrib.get("r", "")
                values[_column_index(cell_ref)] = _cell_text(cell, shared_strings, ns)
            if values:
                max_index = max(values)
                yield [values.get(index, "") for index in range(max_index + 1)]
            row.clear()


def _get_with_retries(url: str, *, timeout: int, attempts: int = 2) -> requests.Response:
    last_exc: Exception | None = None
    for attempt in range(attempts):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=timeout)
            if resp.status_code not in {429, 500, 502, 503, 504}:
                resp.raise_for_status()
                return resp
            resp.raise_for_status()
        except requests.HTTPError as exc:
            last_exc = exc
            status = exc.response.status_code if exc.response is not None else 0
            if status not in {429, 500, 502, 503, 504} or attempt == attempts - 1:
                raise
            retry_after = exc.response.headers.get("Retry-After") if exc.response is not None else ""
            try:
                wait = min(2.0, max(0.25, float(retry_after)))
            except ValueError:
                wait = min(2.0, 0.5 * (attempt + 1))
            time.sleep(wait)
        except requests.RequestException as exc:
            last_exc = exc
            if attempt == attempts - 1:
                raise
            time.sleep(min(1.0, 0.5 * (attempt + 1)))
    raise RuntimeError(f"Request failed: {last_exc}")


def _parse_course_rows(xlsx_content: bytes) -> list[dict]:
    rows: list[dict] = []
    with zipfile.ZipFile(io.BytesIO(xlsx_content)) as workbook:
        shared_strings = _read_shared_strings(workbook)
        iterator = _iter_sheet_rows(workbook, shared_strings)
        headers = [value.strip().lower() for value in next(iterator, [])]
        index = {name: idx for idx, name in enumerate(headers)}
        for row in iterator:
            def get(name: str) -> str:
                idx = index.get(name, -1)
                return _clean_text(row[idx]) if 0 <= idx < len(row) else ""

            ref = get("coursereferencenumber")
            title = get("coursetitle")
            if not ref or not title:
                continue
            about = get("about_this_course")
            learn = get("what_you_learn")
            rows.append({
                "course_reference_number": ref,
                "title": title,
                "provider": get("trainingprovideralias"),
                "course_rating_stars": _to_float(get("courseratings_stars")),
                "course_rating_respondents": _to_int(get("courseratings_noofrespondents")),
                "career_impact_stars": _to_float(get("jobcareer_impact_stars")),
                "career_impact_respondents": _to_int(get("jobcareer_impact_noofrespondents")),
                "full_course_fee": _to_float(get("full_course_fee")),
                "net_course_fee": _to_float(get("course_fee_after_subsidies")),
                "hours": _to_float(get("number_of_hours")),
                "conducted_in": get("conducted_in"),
                "search_text": f"{title} {learn} {about}".lower(),
                "url": COURSE_URL.format(ref=quote(ref, safe="")),
            })
    return rows


def _download_course_rows() -> list[dict]:
    poll_resp = _get_with_retries(POLL_URL, timeout=10, attempts=3)
    payload = poll_resp.json()
    if payload.get("code") != 0:
        raise RuntimeError(payload.get("errMsg") or "SkillsFuture dataset unavailable")
    download_url = payload.get("data", {}).get("url")
    if not download_url:
        raise RuntimeError("SkillsFuture dataset download URL missing")

    xlsx_resp = _get_with_retries(download_url, timeout=35, attempts=2)
    content = xlsx_resp.content
    try:
        DISK_CACHE_PATH.write_bytes(content)
    except OSError:
        pass
    return _parse_course_rows(content)


def _load_disk_course_rows() -> list[dict]:
    if not DISK_CACHE_PATH.exists():
        return []
    return _parse_course_rows(DISK_CACHE_PATH.read_bytes())


def load_courses() -> tuple[list[dict], str]:
    global _course_cache, _course_cache_ts, _last_error
    now = time.time()
    with _cache_lock:
        if _course_cache and now - _course_cache_ts < CACHE_TTL_SECONDS:
            return _course_cache, _last_error

    with _refresh_lock:
        with _cache_lock:
            if _course_cache and time.time() - _course_cache_ts < CACHE_TTL_SECONDS:
                return _course_cache, _last_error

        try:
            courses = _download_course_rows()
        except Exception as exc:
            live_error = f"{exc.__class__.__name__}: {exc}"
            with _cache_lock:
                if _course_cache:
                    _last_error = f"Live refresh failed; showing cached official dataset. {live_error}"
                    return _course_cache, _last_error
            try:
                courses = _load_disk_course_rows()
            except Exception as cache_exc:
                with _cache_lock:
                    _last_error = f"{live_error}; disk cache failed: {cache_exc.__class__.__name__}: {cache_exc}"
                    return _course_cache, _last_error
            if not courses:
                with _cache_lock:
                    _last_error = live_error
                    return _course_cache, _last_error
            with _cache_lock:
                _course_cache = courses
                _course_cache_ts = time.time()
                _last_error = f"Live refresh failed; showing cached official dataset. {live_error}"
                return _course_cache, _last_error

        with _cache_lock:
            _course_cache = courses
            _course_cache_ts = time.time()
            _last_error = ""
            return _course_cache, _last_error


def _query_terms(skill: str) -> list[str]:
    normalized = re.sub(r"\s+", " ", skill.strip().lower())
    terms = [normalized]
    terms.extend(token for token in re.findall(r"[a-z0-9+#.]{3,}", normalized) if token not in {"and", "the", "for", "with"})
    return list(dict.fromkeys(terms))


def _score_course(course: dict, skill: str) -> tuple[float, str]:
    terms = _query_terms(skill)
    title = course["title"].lower()
    haystack = course["search_text"]

    score = 0.0
    reasons: list[str] = []
    exact = terms[0]
    if exact and exact in title:
        score += 70
        reasons.append("exact title match")
    elif exact and exact in haystack:
        score += 42
        reasons.append("matches course outcomes")

    token_hits = 0
    for term in terms[1:]:
        if term in title:
            score += 10
            token_hits += 1
        elif term in haystack:
            score += 4
            token_hits += 1
    if token_hits and not reasons:
        reasons.append(f"{token_hits} related term match{'' if token_hits == 1 else 'es'}")

    course_rating = course["course_rating_stars"]
    impact_rating = course["career_impact_stars"]
    rating_responses = course["course_rating_respondents"]
    impact_responses = course["career_impact_respondents"]
    if course_rating:
        score += course_rating * 4
        reasons.append(f"{course_rating:g}/5 course rating")
    if impact_rating:
        score += impact_rating * 5
        reasons.append(f"{impact_rating:g}/5 career impact")
    if rating_responses or impact_responses:
        score += min(10, math.log1p(rating_responses + impact_responses) * 2)

    if 0 < course["hours"] <= 80:
        score += 4
    if "English" in course["conducted_in"]:
        score += 2

    return score, "; ".join(reasons[:3]) or "related SkillsFuture course"


def recommend_courses_for_skills(skills: list[str], per_skill: int = 3) -> dict:
    courses, error = load_courses()
    cache_status = "live"
    if error and courses:
        cache_status = "cached"
    elif error:
        cache_status = "unavailable"
    clean_skills = [
        re.sub(r"\s+", " ", str(skill or "").strip())
        for skill in skills[:8]
        if str(skill or "").strip()
    ]
    recommendations: dict[str, list[dict]] = {}
    if not courses:
        return {
            "source": "data.gov.sg MySkillsFuture Course Directory",
            "course_count": 0,
            "cache_status": cache_status,
            "error": error,
            "recommendations": {skill: [] for skill in clean_skills},
        }

    for skill in clean_skills:
        scored: list[CourseRecommendation] = []
        for course in courses:
            score, reason = _score_course(course, skill)
            if score < 25:
                continue
            scored.append(CourseRecommendation(
                course_reference_number=course["course_reference_number"],
                title=course["title"],
                provider=course["provider"],
                course_rating_stars=course["course_rating_stars"],
                course_rating_respondents=course["course_rating_respondents"],
                career_impact_stars=course["career_impact_stars"],
                career_impact_respondents=course["career_impact_respondents"],
                full_course_fee=course["full_course_fee"],
                net_course_fee=course["net_course_fee"],
                hours=course["hours"],
                conducted_in=course["conducted_in"],
                url=course["url"],
                reason=reason,
                score=round(score, 1),
            ))
        scored.sort(
            key=lambda item: (
                item.score,
                item.career_impact_stars,
                item.course_rating_stars,
                item.course_rating_respondents + item.career_impact_respondents,
            ),
            reverse=True,
        )
        recommendations[skill] = [item.__dict__ for item in scored[:per_skill]]

    return {
        "source": "data.gov.sg MySkillsFuture Course Directory",
        "course_count": len(courses),
        "cache_status": cache_status,
        "error": error,
        "recommendations": recommendations,
    }
