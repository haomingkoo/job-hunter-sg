"""
Resume tailoring pipeline -- multi-pass AI + local processing.

Orchestrates 7 stages to transform a raw resume into a JD-tailored version:
  Stage 0: Local  -- structure resume + load parsed JD + baseline score
  Stage 1: 70B    -- strategic analysis (priorities, keyword placement)
  Stage 2: Local  -- AI phrase cleanup + simple local fixes
  Stage 3: 32B    -- per-bullet rewrites (batched)
  Stage 4: Local  -- section coherence (verb dedup, keyword verify, tense)
  Stage 5: 70B    -- executive summary + full-resume polish
  Stage 6: Local  -- validation gates + final metrics
"""

from __future__ import annotations

import json
import logging
import re
import secrets
import threading
import time
from datetime import datetime, timezone
from typing import Optional

from ai_phrases import clean_ai_phrases
from ats_terms import build_job_ats_terms, match_resume_against_job_terms
from config import (
    PIPELINE_REWRITE_TOKENS_PER_BULLET,
    PIPELINE_STRATEGY_MAX_TOKENS,
    PIPELINE_SUMMARY_MAX_TOKENS,
    SEALION_PIPELINE_MODEL,
    VALIDATION_REWRITE_MAX_EXPANSION_RATIO,
)
from ai_service import _call_sealion, call_sealion_json
from jd_preparser import preparse_job_description
from prompt_safety import UNTRUSTED_DATA_RULE, xml_data_block
from resume_scorer import ResumeScorer
from resume_structurer import flatten_to_text, get_all_bullets, structure_resume
from validation_gates import validate_and_fix

log = logging.getLogger("jobhunter.pipeline")

# ── Pipeline state ──────────────────────────────────────────────────────────

STAGES = [
    "analyze",        # 0: local structure + baseline
    "strategize",     # 1: 70B strategic analysis
    "local_cleanup",  # 2: AI phrase cleanup
    "bullet_rewrite", # 3: 32B per-bullet rewrites
    "section_polish", # 4: local section coherence
    "full_polish",    # 5: 70B summary + full review
    "validate",       # 6: local validation + final metrics
    "complete",       # 7: done
]


class PipelineState:
    """Thread-safe pipeline progress tracker."""

    def __init__(self, session_id: str, owner_key: str | None = None):
        self.session_id = session_id
        self.owner_key = owner_key
        self.stage_index = 0
        self.stage_name = STAGES[0]
        self.progress = {"completed": 0, "total": 0}
        self.message = "Initializing..."
        self.error: str | None = None
        self.result: dict | None = None
        self._lock = threading.Lock()
        self._created_at = time.monotonic()

    def advance(self, message: str = "") -> None:
        with self._lock:
            self.stage_index = min(self.stage_index + 1, len(STAGES) - 1)
            self.stage_name = STAGES[self.stage_index]
            self.progress = {"completed": 0, "total": 0}
            self.message = message or f"Stage: {self.stage_name}"

    def update_progress(self, completed: int, total: int, message: str = "") -> None:
        with self._lock:
            self.progress = {"completed": completed, "total": total}
            if message:
                self.message = message

    def set_error(self, error: str) -> None:
        with self._lock:
            self.error = error
            self.message = f"Error: {error}"
            self._completed_at = time.monotonic()

    def set_result(self, result: dict) -> None:
        with self._lock:
            self.result = result
            self.stage_name = "complete"
            self.stage_index = len(STAGES) - 1
            self.message = "Tailoring complete."
            self._completed_at = time.monotonic()

    def to_dict(self) -> dict:
        with self._lock:
            return {
                "session_id": self.session_id,
                "stage": self.stage_name,
                "stage_number": self.stage_index,
                "total_stages": len(STAGES) - 1,
                "progress": self.progress,
                "message": self.message,
                "error": self.error,
                "complete": self.stage_name == "complete",
            }


# Active pipelines (in-memory, cleared on restart)
_active_pipelines: dict[str, PipelineState] = {}
_pipelines_lock = threading.Lock()
_PIPELINE_TTL_SECONDS = 1800  # 30 minutes
_MAX_ACTIVE_PIPELINES = 4
_MAX_RETAINED_PIPELINES = 32


class PipelineCapacityError(RuntimeError):
    """Raised when another tailoring pipeline cannot be admitted."""


def _trim_terminal_pipelines_locked(max_total: int) -> None:
    """Evict the oldest finished sessions until the registry fits."""
    overflow = len(_active_pipelines) - max_total
    if overflow <= 0:
        return

    terminal = sorted(
        (
            (session_id, state)
            for session_id, state in _active_pipelines.items()
            if state.stage_name == "complete" or state.error is not None
        ),
        key=lambda item: (
            getattr(item[1], "_completed_at", item[1]._created_at),
            item[1]._created_at,
            item[0],
        ),
    )
    for session_id, _state in terminal[:overflow]:
        _active_pipelines.pop(session_id, None)


def get_pipeline_state(
    session_id: str,
    owner_key: str | None = None,
) -> PipelineState | None:
    # Piggyback cleanup on reads (cheap, no extra thread needed)
    _cleanup_expired_pipelines()
    with _pipelines_lock:
        state = _active_pipelines.get(session_id)
        if state and state.owner_key and state.owner_key != owner_key:
            return None
        return state


def owner_has_active_pipelines(owner_key: str) -> bool:
    with _pipelines_lock:
        return any(
            state.owner_key == owner_key
            and state.stage_name != "complete"
            and state.error is None
            for state in _active_pipelines.values()
        )


def purge_owner_pipelines(owner_key: str) -> None:
    with _pipelines_lock:
        session_ids = [
            session_id
            for session_id, state in _active_pipelines.items()
            if state.owner_key == owner_key
        ]
        for session_id in session_ids:
            _active_pipelines.pop(session_id, None)


def _cleanup_expired_pipelines() -> None:
    """Remove pipelines older than TTL, whether completed, errored, or stuck mid-run.

    Uses _completed_at when set (normal completion or error); otherwise falls back
    to _created_at so genuinely-stuck-in-progress sessions still get evicted.
    """
    now = time.monotonic()
    with _pipelines_lock:
        expired = [
            sid for sid, state in _active_pipelines.items()
            if now - getattr(state, "_completed_at", state._created_at) > _PIPELINE_TTL_SECONDS
        ]
        for sid in expired:
            del _active_pipelines[sid]
        _trim_terminal_pipelines_locked(_MAX_RETAINED_PIPELINES)
        if expired:
            log.info(f"[PIPELINE] Cleaned up {len(expired)} expired sessions")


# ── Verb synonym map for section-level dedup ────────────────────────────────

_VERB_SYNONYMS: dict[str, list[str]] = {
    "led": ["directed", "guided", "headed", "managed"],
    "managed": ["oversaw", "supervised", "administered", "coordinated"],
    "developed": ["created", "built", "designed", "engineered"],
    "implemented": ["deployed", "executed", "launched", "rolled out"],
    "improved": ["enhanced", "optimized", "strengthened", "refined"],
    "created": ["built", "developed", "established", "designed"],
    "analyzed": ["evaluated", "assessed", "examined", "reviewed"],
    "coordinated": ["organized", "arranged", "facilitated", "synchronized"],
    "delivered": ["shipped", "produced", "completed", "provided"],
    "reduced": ["decreased", "minimized", "cut", "lowered"],
    "increased": ["grew", "expanded", "boosted", "raised"],
    "designed": ["architected", "crafted", "planned", "structured"],
    "built": ["constructed", "developed", "assembled", "created"],
    "launched": ["introduced", "initiated", "started", "rolled out"],
    "established": ["founded", "set up", "instituted", "created"],
}


def _find_synonym(verb: str, used_verbs: set[str]) -> str:
    """Find an unused synonym for a verb."""
    lower = verb.lower()
    synonyms = _VERB_SYNONYMS.get(lower, [])
    for syn in synonyms:
        if syn not in used_verbs:
            return syn
    return verb  # no synonym available


def _issue_guidance_for_bullet(issues: list[str]) -> str:
    """Convert local bullet issues into rewrite guidance for the LLM."""
    guidance = []
    issue_set = set(issues or [])

    if {"no_action_verb", "weak_verb"} & issue_set:
        guidance.append("Open with a sharper action verb.")
    if {"no_metric", "weak_metric"} & issue_set:
        guidance.append("Preserve or foreground concrete metrics, scale, scope, or outcome.")
    if {"too_long", "wordy"} & issue_set:
        guidance.append("Tighten the bullet so the result lands earlier.")
    if {"overused_language", "filler_language"} & issue_set:
        guidance.append("Reduce repeated generic wording and choose more specific nouns or verbs.")
    if {"tense_mismatch"} & issue_set:
        guidance.append("Keep tense consistent with the rest of the section.")

    return " ".join(guidance) or "Improve clarity while preserving the original facts."


# ── Stage implementations ───────────────────────────────────────────────────


def _stage_0_analyze(
    resume_text: str,
    parsed_jd: dict,
    jd_text: str,
    state: PipelineState,
) -> dict:
    """Stage 0: Local -- structure resume + baseline score + skill gap."""
    state.update_progress(0, 3, "Parsing resume structure...")

    structured = structure_resume(resume_text)
    state.update_progress(1, 3, "Scoring resume...")

    scorer = ResumeScorer()
    score_result = scorer.analyze(resume_text, jd_text, parsed_jd=parsed_jd)
    state.update_progress(2, 3, "Analyzing skill gaps...")

    all_jd_skills = (
        parsed_jd.get("required_skills", [])
        + parsed_jd.get("preferred_skills", [])
        + parsed_jd.get("single_word_skills", [])
    )
    resume_lower = resume_text.lower()
    matched_skills = [s for s in all_jd_skills if s.lower() in resume_lower]
    missing_skills = [s for s in all_jd_skills if s.lower() not in resume_lower]

    # Classify missing as injectable vs non-injectable
    # Injectable: resume has adjacent experience (fuzzy match)
    injectable = []
    non_injectable = []
    for skill in missing_skills:
        words = skill.lower().split()
        if any(w in resume_lower for w in words if len(w) > 3):
            injectable.append(skill)
        else:
            non_injectable.append(skill)

    state.update_progress(3, 3, "Analysis complete.")

    return {
        "structured": structured,
        "score_result": score_result,
        "matched_skills": matched_skills,
        "missing_skills": missing_skills,
        "injectable_keywords": injectable,
        "non_injectable_keywords": non_injectable,
        "baseline_score": score_result.get("overall_score", 0),
    }


def _stage_1_strategize(
    analysis: dict,
    parsed_jd: dict,
    jd_text: str,
    state: PipelineState,
) -> dict | None:
    """Stage 1: 70B -- strategic analysis of what to prioritize."""
    bullets = get_all_bullets(analysis["structured"])
    if not bullets:
        return None

    state.update_progress(0, 1, "AI analyzing resume strategy (70B)...")

    # Build compact bullet summary for the LLM
    bullet_summary = []
    for b in bullets:
        issues = ", ".join(b.get("issues", [])) or "none"
        bullet_summary.append(
            f"[{b['id']}] ({b['section_key']}) "
            f"issues={issues}: {b['text'][:80]}"
        )

    system = """You are a resume strategy expert. Given a resume's bullets with their issues, a job description summary, and skill gaps, create a tailoring strategy.

Return ONLY valid JSON with this structure:
{
  "bullet_priorities": [
    {"id": "exp-0-b2", "priority": "high", "reason": "weak verb + relevant to JD"}
  ],
  "keyword_placements": [
    {"keyword": "machine learning", "target_bullet_id": "exp-0-b1", "reason": "already discusses ML work"}
  ],
  "summary_direction": "Emphasize ML engineering leadership and production deployment experience"
}

Priority levels: "high" (rewrite needed + JD relevant), "medium" (fixable issues), "low" (minor), "skip" (already strong or irrelevant).
Only include bullets that need work in bullet_priorities. Skip strong bullets."""
    system += f"\n\nSECURITY: {UNTRUSTED_DATA_RULE}"

    user_msg = "Create the strategy from this context:\n" + xml_data_block(
        "strategy_context_data",
        json.dumps(
            {
                "bullets": bullet_summary[:25],
                "required_skills": parsed_jd.get("required_skills", [])[:10],
                "preferred_skills": parsed_jd.get("preferred_skills", [])[:5],
                "injectable_keywords": analysis["injectable_keywords"][:8],
                "job_experience_requirement": parsed_jd.get(
                    "experience_years", "not specified"
                ),
            },
            ensure_ascii=False,
        ),
    )

    content = call_sealion_json(
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_msg},
        ],
        max_tokens=PIPELINE_STRATEGY_MAX_TOKENS,
        model=SEALION_PIPELINE_MODEL,
    )

    fallback = {
        "bullet_priorities": [
            {"id": b["id"], "priority": "high" if b.get("issues") else "skip", "reason": "auto"}
            for b in bullets
        ],
        "keyword_placements": [],
        "summary_direction": "Tailor to match the job description.",
        "_degraded": True,
        "_degraded_reason": "AI strategy planning was unavailable, so the pipeline used local issue-based prioritization instead.",
    }

    if not content:
        log.warning("[PIPELINE] Stage 1 failed, using fallback priorities")
        state.update_progress(1, 1, "Strategy fallback ready.")
        return fallback

    try:
        start = content.find("{")
        end = content.rfind("}") + 1
        if start >= 0 and end > start:
            strategy = json.loads(content[start:end])
            strategy["_degraded"] = False
            state.update_progress(1, 1, "Strategy ready.")
            return strategy
    except (json.JSONDecodeError, ValueError) as e:
        log.warning(f"[PIPELINE] Stage 1 JSON parse error: {e}")

    state.update_progress(1, 1, "Strategy fallback ready.")
    return fallback


def _stage_2_local_cleanup(
    analysis: dict,
    jd_text: str,
    state: PipelineState,
) -> dict:
    """Stage 2: Local -- AI phrase cleanup + simple fixes."""
    structured = analysis["structured"]
    bullets = get_all_bullets(structured)
    changes = []

    state.update_progress(0, len(bullets), "Cleaning AI phrases...")

    for i, bullet in enumerate(bullets):
        cleaned, phrase_changes = clean_ai_phrases(bullet["text"], jd_text)
        if phrase_changes:
            _update_bullet_text(structured, bullet["id"], cleaned)
            changes.append({
                "bullet_id": bullet["id"],
                "type": "ai_phrase_cleanup",
                "original": bullet["text"],
                "tailored": cleaned,
                "details": phrase_changes,
            })
        state.update_progress(i + 1, len(bullets))

    return {"changes": changes, "structured": structured}


def _stage_3_bullet_rewrite(
    structured: dict,
    strategy: dict | None,
    parsed_jd: dict,
    jd_text: str,
    injectable_keywords: list[str],
    state: PipelineState,
) -> list[dict]:
    """Stage 3: 32B -- per-bullet rewrites for priority bullets."""
    bullets = get_all_bullets(structured)
    changes = []

    priority_map = {}
    if strategy and "bullet_priorities" in strategy:
        for p in strategy["bullet_priorities"]:
            priority_map[p["id"]] = p

    keyword_map: dict[str, list[str]] = {}
    if strategy and "keyword_placements" in strategy:
        for kp in strategy["keyword_placements"]:
            bid = kp.get("target_bullet_id", "")
            kw = kp.get("keyword", "")
            if bid and kw:
                keyword_map.setdefault(bid, []).append(kw)

    rewrite_bullets = []
    for bullet in bullets:
        priority_info = priority_map.get(bullet["id"])
        if priority_info and priority_info.get("priority") in ("high", "medium"):
            rewrite_bullets.append(bullet)
        elif bullet.get("issues") and any(
            i in ("no_action_verb", "weak_verb") for i in bullet["issues"]
        ):
            rewrite_bullets.append(bullet)

    if not rewrite_bullets:
        state.update_progress(0, 0, "No bullets need rewriting.")
        return changes

    # Batch bullets into groups of 4 for efficiency
    batch_size = 4
    total = len(rewrite_bullets)
    completed = 0

    for batch_start in range(0, total, batch_size):
        batch = rewrite_bullets[batch_start:batch_start + batch_size]
        state.update_progress(
            completed, total,
            f"Rewriting bullets {completed + 1}-{min(completed + len(batch), total)} of {total}...",
        )

        # Build sibling context per bullet (other bullets in same entry)
        # so the LLM knows what's already said and avoids duplication
        sibling_map: dict[str, list[str]] = {}
        entry_context_map: dict[str, str] = {}
        for section in structured.get("sections", []):
            for entry in section.get("entries", []):
                entry_label = f"{entry.get('heading', '')} | {entry.get('subheading', '')}"
                for bullet in entry.get("bullets", []):
                    bid = bullet.get("id", "")
                    siblings = [
                        sib["text"][:60]
                        for sib in entry.get("bullets", [])
                        if sib.get("id") != bid
                    ]
                    sibling_map[bid] = siblings
                    entry_context_map[bid] = entry_label

        bullet_lines = []
        for idx, b in enumerate(batch):
            keywords_for_bullet = keyword_map.get(b["id"], [])
            kw_hint = f" [inject: {', '.join(keywords_for_bullet)}]" if keywords_for_bullet else ""
            issues = ", ".join(b.get("issues", []))
            guidance = _issue_guidance_for_bullet(b.get("issues", []))
            entry_ctx = entry_context_map.get(b["id"], "")
            siblings = sibling_map.get(b["id"], [])
            sibling_hint = ""
            if siblings:
                sibling_hint = f" [siblings already cover: {'; '.join(siblings[:3])}]"
            bullet_lines.append(
                f"{idx + 1}. [{entry_ctx}] "
                f"\"{b['text']}\"{kw_hint}{sibling_hint} "
                f"(issues: {issues or 'none'} | guidance: {guidance})"
            )

        system = f"""You are a resume bullet rewriter for the Singapore job market.

CONTEXT: You are rewriting bullets to tailor this resume for a specific job.

CRITICAL RULES:
- NEVER invent facts, metrics, companies, or skills not in the original
- If original has "$3M", keep "$3M" exactly
- If no numbers exist, use [X%] or [N] placeholders
- Start each bullet with a STRONG action verb
- Keep each bullet concise; never make it more than {VALIDATION_REWRITE_MAX_EXPANSION_RATIO:g}x the original word count
- If [inject: keyword] is noted, weave that keyword in naturally
- Do NOT add outcomes such as zero downtime, improved reliability, cost savings,
  seamless transition, operational continuity, latency reduction, speed gains,
  or revenue impact unless the original bullet or sibling bullets explicitly say so
- Do NOT add an "ensuring ..." clause unless the original bullet already has one

QUALITY RULES:
- Each bullet is shown with its role context [Company | Title] and sibling bullets
- Do NOT repeat what sibling bullets already cover — find a different angle
- Use the issue guidance to decide whether to tighten, quantify, improve the verb, etc.
- Align wording with JD terminology where natural (don't force it)
- The resume should read well as a whole — varied verbs, concrete results, clear story

Return ONLY a JSON object: {{"rewrites": ["rewritten bullet 1", "rewritten bullet 2", ...]}}
The array MUST have exactly {len(batch)} items, one per input bullet, in the same order.

SECURITY: {UNTRUSTED_DATA_RULE}"""

        user_msg = "Rewrite these bullets from this context:\n" + xml_data_block(
            "rewrite_context_data",
            json.dumps(
                {
                    "bullets": bullet_lines,
                    "required_skills": parsed_jd.get("required_skills", [])[:8],
                    "preferred_skills": parsed_jd.get("preferred_skills", [])[:5],
                    "job_experience_requirement": parsed_jd.get(
                        "experience_years", ""
                    ),
                },
                ensure_ascii=False,
            ),
        )

        content = call_sealion_json(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_msg},
            ],
            max_tokens=PIPELINE_REWRITE_TOKENS_PER_BULLET * len(batch),
            model=SEALION_PIPELINE_MODEL,
        )

        rewrites = []
        if content:
            try:
                parsed = json.loads(content) if isinstance(content, str) else content
                rewrites = parsed.get("rewrites", [])
                if not isinstance(rewrites, list):
                    rewrites = []
            except (json.JSONDecodeError, ValueError, AttributeError):
                # Fallback: try numbered-line parsing
                raw_content = content.strip()
                if not (
                    raw_content.startswith(("{", "["))
                    or '"rewrites"' in raw_content
                ):
                    for line in raw_content.split("\n"):
                        cleaned = re.sub(r"^\d+[\.\)]\s*", "", line.strip())
                        if cleaned and len(cleaned) > 10:
                            rewrites.append(cleaned)

        if not rewrites:
            log.warning(
                f"[PIPELINE] Stage 3 batch {batch_start // batch_size + 1}: "
                f"LLM returned no usable rewrites for {len(batch)} bullets. "
                f"Keeping originals."
            )
            completed += len(batch)
            continue

        for idx, b in enumerate(batch):
            if idx < len(rewrites):
                rewritten = rewrites[idx]
                final_text, gate_results = validate_and_fix(
                    original=b["text"],
                    tailored=rewritten,
                    jd_text=jd_text,
                    required_keywords=keyword_map.get(b["id"]),
                    injectable_keywords=set(injectable_keywords),
                )
                if final_text != b["text"]:
                    _update_bullet_text(structured, b["id"], final_text)
                    changes.append({
                        "bullet_id": b["id"],
                        "type": "bullet_rewrite",
                        "original": b["text"],
                        "tailored": final_text,
                        "gate_results": [
                            {"gate": g.gate_name, "passed": g.passed, "message": g.message}
                            for g in gate_results
                        ],
                        "user_status": "pending",
                    })

        completed += len(batch)

    state.update_progress(total, total, f"Rewrote {len(changes)} bullets.")
    return changes


def _stage_4_section_coherence(
    structured: dict,
    state: PipelineState,
) -> list[dict]:
    """Stage 4: Local -- verb dedup, keyword check, tense consistency."""
    changes = []
    sections = structured.get("sections", [])
    state.update_progress(0, len(sections), "Checking section coherence...")

    for sec_idx, section in enumerate(sections):
        if section.get("type") != "entries":
            continue

        for entry in section.get("entries", []):
            used_verbs: set[str] = set()
            for bullet in entry.get("bullets", []):
                text = bullet.get("text", "")
                first_word = text.split()[0].lower().rstrip(",:;.") if text.split() else ""

                # Verb dedup within same entry
                if first_word in used_verbs and first_word in _VERB_SYNONYMS:
                    synonym = _find_synonym(first_word, used_verbs)
                    if synonym != first_word:
                        new_text = synonym.capitalize() + text[len(first_word):]
                        _update_bullet_text(structured, bullet["id"], new_text)
                        changes.append({
                            "bullet_id": bullet["id"],
                            "type": "verb_dedup",
                            "original": text,
                            "tailored": new_text,
                            "reason": f"Replaced duplicate verb '{first_word}' with '{synonym}'",
                        })
                        text = new_text

                used_verbs.add(first_word)

        state.update_progress(sec_idx + 1, len(sections))

    return changes


def _find_section(structured: dict, key: str) -> dict | None:
    """Return the first section with the given key."""
    for section in structured.get("sections", []):
        if section.get("key") == key:
            return section
    return None


def _ensure_summary_section(structured: dict) -> dict:
    """Ensure the structured resume has a summary section and return it."""
    existing = _find_section(structured, "summary")
    if existing:
        return existing

    sections = structured.setdefault("sections", [])
    summary_section = {
        "key": "summary",
        "display_name": "PROFESSIONAL SUMMARY",
        "type": "text",
        "content": "",
        "entries": [],
    }

    insert_at = 0
    if sections and sections[0].get("key") == "personal":
        insert_at = 1
    sections.insert(insert_at, summary_section)
    return summary_section


_YEARS_EXPERIENCE_RE = re.compile(
    r"\b\d+(?:\.\d+)?\+?\s*(?:years?|yrs?)\s+(?:of\s+)?experience\b",
    re.IGNORECASE,
)


def _summary_has_unsupported_years(source_text: str, summary_text: str) -> bool:
    source_claims = {m.group(0).lower() for m in _YEARS_EXPERIENCE_RE.finditer(source_text)}
    for match in _YEARS_EXPERIENCE_RE.finditer(summary_text):
        if match.group(0).lower() not in source_claims:
            return True
    return False


def _summary_needs_refresh(summary_section: dict | None) -> bool:
    """Heuristic for whether the summary should be regenerated in a full pass."""
    if not summary_section:
        return True

    content = (summary_section.get("content") or "").strip()
    if len(content) < 40:
        return True

    words = content.split()
    if len(words) < 8:
        return True

    # Resume imports sometimes shout the whole summary or leave it as a title-like fragment.
    alpha_chars = [char for char in content if char.isalpha()]
    if alpha_chars:
        uppercase_ratio = sum(1 for char in alpha_chars if char.isupper()) / len(alpha_chars)
        if uppercase_ratio >= 0.78:
            return True

    # If the summary does not look sentence-like, treat it as weak and regenerate.
    if not re.search(r"[.!?]", content) and len(words) >= 12:
        return True

    return False


def _stage_5_full_polish(
    structured: dict,
    strategy: dict | None,
    parsed_jd: dict,
    jd_text: str,
    state: PipelineState,
) -> dict:
    """Stage 5: 70B -- executive summary generation + full review."""
    state.update_progress(0, 1, "AI polishing executive summary (70B)...")

    summary_section = _find_section(structured, "summary")
    summary_was_missing = summary_section is None
    if summary_was_missing:
        summary_section = _ensure_summary_section(structured)

    # Build context from the polished bullets
    bullet_context = []
    for b in get_all_bullets(structured)[:12]:
        bullet_context.append(f"- {b['text']}")

    summary_direction = ""
    if strategy:
        summary_direction = strategy.get("summary_direction", "")

    system = """You are an expert resume writer specializing in Singapore's job market.

Generate a compelling professional summary (2-4 sentences, ~40-60 words) that:
1. Opens with core expertise; mention years of experience only if the source bullets explicitly state it
2. Highlights 2-3 key strengths relevant to the target role
3. Mentions a quantified achievement if possible
4. Sounds natural, not AI-generated

CRITICAL RULES:
- Only reference achievements and skills that appear in the bullet points below. Do NOT invent.
- The target job's required experience is not the candidate's experience.
- If the source bullets do not explicitly say "years of experience", do not mention years.
- Do NOT add outcomes such as zero downtime, improved reliability, cost savings,
  seamless transition, operational continuity, latency reduction, speed gains,
  or revenue impact unless the bullets explicitly say so.
- Do NOT add an "ensuring ..." clause unless the bullets explicitly have one.
- NEVER change numbers, years of experience, dollar amounts, or metrics from the original resume.
  If the resume says "7+ years", keep "7+ years". Do NOT calculate, infer, or import different numbers.
- Preserve all factual claims exactly as stated in the resume.

Return ONLY the summary text, nothing else."""
    system += f"\n\nSECURITY: {UNTRUSTED_DATA_RULE}"

    user_msg = "Write the summary from this context:\n" + xml_data_block(
        "summary_context_data",
        json.dumps(
            {
                "target_role_skills": parsed_jd.get("required_skills", [])[:5],
                "summary_direction": summary_direction,
                "resume_bullets": bullet_context,
            },
            ensure_ascii=False,
        ),
    )

    content = _call_sealion(
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_msg},
        ],
        max_tokens=PIPELINE_SUMMARY_MAX_TOKENS,
        model=SEALION_PIPELINE_MODEL,
        temperature=0.3,
    )

    result = {
        "summary_rewritten": False,
        "summary_created": summary_was_missing,
        "original_summary": "",
        "new_summary": "",
        "_degraded": False,
        "_degraded_reason": "",
    }

    if not content:
        result["_degraded"] = True
        result["_degraded_reason"] = (
            "AI summary polishing was unavailable, so the pipeline kept the current summary content."
        )
    elif summary_section is not None and _summary_needs_refresh(summary_section):
        new_summary = content.strip().strip('"')
        source_text = "\n".join(bullet_context)
        if _summary_has_unsupported_years(source_text, new_summary):
            result["_degraded"] = True
            result["_degraded_reason"] = (
                "AI summary polishing added unsupported years of experience, so the pipeline kept the current summary."
            )
        elif len(new_summary) > 30:
            result["original_summary"] = summary_section.get("content", "")
            result["new_summary"] = new_summary
            result["summary_rewritten"] = True
            summary_section["content"] = new_summary
        else:
            result["_degraded"] = True
            result["_degraded_reason"] = (
                "AI summary polishing returned unusable content, so the pipeline kept the current summary."
            )
    elif summary_was_missing and summary_section is not None and not summary_section.get("content", "").strip():
        result["_degraded"] = True
        result["_degraded_reason"] = (
            "The resume did not contain enough structured content to generate a professional summary."
        )

    if summary_was_missing and not result["summary_rewritten"]:
        sections = structured.get("sections", [])
        if summary_section in sections:
            sections.remove(summary_section)

    state.update_progress(1, 1, "Full polish complete.")
    return result


def _stage_6_validate(
    structured: dict,
    original_text: str,
    jd_text: str,
    parsed_jd: dict,
    state: PipelineState,
) -> dict:
    """Stage 6: Local -- final metrics + real skill re-scan + ATS gap report."""
    state.update_progress(0, 4, "Running final score...")

    tailored_text = flatten_to_text(structured)
    scorer = ResumeScorer()
    final_score = scorer.analyze(tailored_text, jd_text, parsed_jd=parsed_jd)

    state.update_progress(1, 4, "Re-scanning skill match...")

    # REAL skill match re-scan against tailored text using the same canonical
    # ATS term builder used by score + job match.
    canonical_terms = build_job_ats_terms(
        jd_text=jd_text,
        parsed_jd=parsed_jd,
    )
    rescan = match_resume_against_job_terms(
        resume_text=tailored_text,
        job_terms=canonical_terms,
        jd_text=jd_text,
    )
    matched_after = [item.get("skill", "") for item in rescan.get("matched", []) if item.get("skill")]
    missing_after = [item.get("skill", "") for item in rescan.get("missing", []) if item.get("skill")]

    state.update_progress(2, 4, "Building ATS gap report...")

    ats_gaps = _build_ats_gap_report(structured, missing_after, parsed_jd)

    skills_reordered = _reorder_skills_section(structured, matched_after)

    state.update_progress(4, 4, "Validation complete.")

    return {
        "final_score": final_score.get("overall_score", 0),
        "tailored_text": flatten_to_text(structured),  # re-flatten after skills reorder
        "matched_after": matched_after,
        "missing_after": missing_after,
        "ats_gaps": ats_gaps,
        "skills_reordered": skills_reordered,
    }


# ── ATS gap report builder ──────────────────────────────────────────────────


def _build_ats_gap_report(
    structured: dict,
    missing_skills: list[str],
    parsed_jd: dict,
) -> list[dict]:
    """Build actionable ATS gap report: what's missing and WHERE to add it.

    For each missing skill, suggests the best section and entry to insert it,
    or flags it as needing user input.
    """
    if not missing_skills:
        return []

    gaps = []
    required_set = {s.lower() for s in parsed_jd.get("required_skills", [])}
    sections = structured.get("sections", [])

    for skill in missing_skills:
        skill_lower = skill.lower()
        is_required = skill_lower in required_set
        words = skill_lower.split()

        best_section = None
        best_entry = None
        best_reason = ""

        # Check if it's a technical skill (belongs in Skills section)
        single_word_tech = parsed_jd.get("single_word_skills", [])
        is_tech_skill = skill_lower in {s.lower() for s in single_word_tech}

        if is_tech_skill or len(words) == 1:
            best_section = "skills"
            best_reason = f"Add '{skill}' to your Technical Skills list."
        else:
            # For multi-word skills, find the entry with most related context
            best_overlap = 0
            for section in sections:
                if section.get("key") not in ("experience", "projects"):
                    continue
                for entry in section.get("entries", []):
                    entry_text = " ".join(
                        b.get("text", "") for b in entry.get("bullets", [])
                    ).lower()
                    overlap = sum(1 for w in words if w in entry_text and len(w) > 3)
                    if overlap > best_overlap:
                        best_overlap = overlap
                        best_section = section.get("key")
                        best_entry = entry.get("id")
                        best_reason = (
                            f"Your {entry.get('heading', '')} role has related context. "
                            f"Weave '{skill}' into an existing bullet or add a new one."
                        )

            if not best_section:
                best_section = "skills"
                best_reason = (
                    f"No existing bullets relate to '{skill}'. "
                    f"Add to Skills if you have this skill, or skip if you don't."
                )

        gaps.append({
            "skill": skill,
            "required": is_required,
            "suggested_section": best_section,
            "suggested_entry_id": best_entry,
            "action": best_reason,
            "needs_user_input": best_section == "skills" or best_entry is None,
        })

    # Sort: required first, then by whether user input is needed
    gaps.sort(key=lambda g: (not g["required"], g["needs_user_input"]))
    return gaps


def _reorder_skills_section(
    structured: dict,
    matched_skills: list[str],
) -> bool:
    """Reorder Skills section to front-load JD-matched skills. Returns True if reordered."""
    matched_lower = {s.lower() for s in matched_skills}

    for section in structured.get("sections", []):
        if section.get("key") != "skills":
            continue
        skill_list = section.get("skill_list", [])
        if not skill_list:
            content = section.get("content", "")
            if content:
                skill_list = [s.strip() for s in re.split(r"[,;|]", content) if s.strip()]

        if not skill_list:
            return False

        front = [s for s in skill_list if s.lower() in matched_lower]
        back = [s for s in skill_list if s.lower() not in matched_lower]
        reordered = front + back

        if reordered != skill_list:
            section["skill_list"] = reordered
            section["content"] = ", ".join(reordered)
            return True

    return False


def _update_bullet_text(structured: dict, bullet_id: str, new_text: str) -> bool:
    """Update a bullet's text in the structured resume by its ID."""
    for section in structured.get("sections", []):
        for entry in section.get("entries", []):
            for bullet in entry.get("bullets", []):
                if bullet.get("id") == bullet_id:
                    bullet["text"] = new_text
                    return True
    return False


# ── Main pipeline runner ────────────────────────────────────────────────────


def run_pipeline(
    resume_text: str,
    job_description: str,
    parsed_jd: dict | None,
    intensity: str = "full",
    session_id: str | None = None,
    owner_key: str | None = None,
) -> PipelineState:
    """Start the tailoring pipeline in a background thread.

    intensity is "nudge" (local only), "keywords" (+ keyword injection) or
    "full" (every stage). parsed_jd may be None to parse the JD on the fly.
    Returns a PipelineState that can be polled for progress.
    """
    if not session_id:
        session_id = secrets.token_hex(16)

    state = PipelineState(session_id, owner_key=owner_key)

    # Sweep before inserting so the dict can't grow without bound even if
    # nobody polls get_pipeline_state (the only other cleanup trigger).
    _cleanup_expired_pipelines()

    with _pipelines_lock:
        active = [
            existing
            for existing in _active_pipelines.values()
            if existing.stage_name != "complete" and existing.error is None
        ]
        if owner_key is not None and any(
            existing.owner_key == owner_key for existing in active
        ):
            raise PipelineCapacityError(
                "A tailoring pipeline is already running for this account."
            )
        if len(active) >= _MAX_ACTIVE_PIPELINES:
            raise PipelineCapacityError("Tailoring is busy. Try again shortly.")
        _trim_terminal_pipelines_locked(_MAX_RETAINED_PIPELINES - 1)
        _active_pipelines[session_id] = state

    def _run() -> None:
        try:
            _execute_pipeline(resume_text, job_description, parsed_jd, intensity, state)
        except Exception as e:
            log.exception(f"[PIPELINE] Unhandled error in session {session_id}")
            state.set_error(str(e))

    thread = threading.Thread(target=_run, daemon=True, name=f"pipeline-{session_id[:8]}")
    thread.start()

    return state


def _execute_pipeline(
    resume_text: str,
    jd_text: str,
    parsed_jd: dict | None,
    intensity: str,
    state: PipelineState,
) -> None:
    """Execute all pipeline stages sequentially."""
    start_time = time.monotonic()

    if not parsed_jd:
        parsed_jd = preparse_job_description(jd_text)

    state.update_progress(0, 0, "Analyzing resume and job description...")
    analysis = _stage_0_analyze(resume_text, parsed_jd, jd_text, state)
    state.advance("Analysis complete. Planning strategy...")

    all_changes: list[dict] = []
    pipeline_notes: list[dict] = []

    if intensity == "nudge":
        # Nudge: only local cleanup, skip LLM stages
        cleanup = _stage_2_local_cleanup(analysis, jd_text, state)
        all_changes.extend(cleanup["changes"])
        state.advance("Local cleanup done.")

        coherence_changes = _stage_4_section_coherence(analysis["structured"], state)
        all_changes.extend(coherence_changes)
        state.advance("Section coherence done.")

        final = _stage_6_validate(analysis["structured"], resume_text, jd_text, parsed_jd, state)
        state.advance("Validation done.")

    else:
        strategy = _stage_1_strategize(analysis, parsed_jd, jd_text, state)
        if strategy and strategy.get("_degraded"):
            pipeline_notes.append({
                "type": "strategy_fallback",
                "message": strategy.get("_degraded_reason", "The strategy stage fell back to local prioritization."),
            })
        state.advance("Strategy ready. Cleaning up...")

        cleanup = _stage_2_local_cleanup(analysis, jd_text, state)
        all_changes.extend(cleanup["changes"])
        state.advance("Cleanup done. Rewriting bullets...")

        bullet_changes = _stage_3_bullet_rewrite(
            analysis["structured"],
            strategy,
            parsed_jd,
            jd_text,
            analysis["injectable_keywords"],
            state,
        )
        all_changes.extend(bullet_changes)
        state.advance("Bullets rewritten. Polishing sections...")

        coherence_changes = _stage_4_section_coherence(analysis["structured"], state)
        all_changes.extend(coherence_changes)
        state.advance("Sections polished.")

        if intensity == "full":
            polish = _stage_5_full_polish(
                analysis["structured"], strategy, parsed_jd, jd_text, state,
            )
            if polish.get("_degraded"):
                pipeline_notes.append({
                    "type": "summary_fallback",
                    "message": polish.get("_degraded_reason", "The summary stage kept the current content because AI polishing was unavailable."),
                })
            if polish.get("summary_rewritten"):
                all_changes.append({
                    "type": "summary_rewrite",
                    "original": polish["original_summary"],
                    "tailored": polish["new_summary"],
                    "user_status": "pending",
                })
            state.advance("Full polish done. Validating...")

        final = _stage_6_validate(analysis["structured"], resume_text, jd_text, parsed_jd, state)

    elapsed = round(time.monotonic() - start_time, 1)

    result = {
        "session_id": state.session_id,
        "original_text": resume_text,
        "tailored_text": final["tailored_text"],
        "original_resume": analysis["structured"],
        "changes": all_changes,
        "skill_match": {
            "before": len(analysis["matched_skills"]),
            "after": len(final.get("matched_after", analysis["matched_skills"])),
            "matched_before": analysis["matched_skills"],
            "matched_after": final.get("matched_after", analysis["matched_skills"]),
            "missing_before": analysis["missing_skills"],
            "missing_after": final.get("missing_after", analysis["missing_skills"]),
            "injectable": analysis["injectable_keywords"],
            "non_injectable": analysis["non_injectable_keywords"],
        },
        "ats_gaps": final.get("ats_gaps", []),
        "skills_reordered": final.get("skills_reordered", False),
        "score": {
            "before": analysis["baseline_score"],
            "after": final["final_score"],
        },
        "pipeline_notes": pipeline_notes,
        "degraded": bool(pipeline_notes),
        "intensity": intensity,
        "elapsed_seconds": elapsed,
        "total_changes": len(all_changes),
    }

    log.info(
        f"[PIPELINE] Session {state.session_id[:8]} complete in {elapsed}s. "
        f"Score: {analysis['baseline_score']} -> {final['final_score']}, "
        f"Changes: {len(all_changes)}"
    )

    state.set_result(result)
