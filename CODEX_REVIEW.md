# CODEX REVIEW — Resume Tailoring Pipeline

## Your Mission

A new multi-pass resume tailoring pipeline was built in one session. You are the second pair of eyes. Your job is to **find bugs, edge cases, and reliability issues** before this ships.

Do NOT just read the code. Run it. Test it. Break it. Use agents to parallelize if needed.

## Priority: RELIABILITY over features. No hidden fallbacks. No silent failures.

---

## Phase 1: Verify everything compiles and imports

Run these in `backend/`:

```bash
python3 -c "from jd_preparser import preparse_job_description; print('OK')"
python3 -c "from resume_structurer import structure_resume, get_all_bullets, flatten_to_text; print('OK')"
python3 -c "from ai_phrases import clean_ai_phrases, AI_PHRASE_REPLACEMENTS; print(f'OK: {len(AI_PHRASE_REPLACEMENTS)} phrases')"
python3 -c "from validation_gates import run_all_gates, validate_and_fix; print('OK')"
python3 -c "from tailoring_pipeline import run_pipeline, get_pipeline_state, STAGES; print(f'OK: {len(STAGES)} stages')"
python3 -c "from models import ScrapedJob, TailoredResume; print('OK')"
```

If ANY of these fail, fix the import error before proceeding.

---

## Phase 2: Unit test the validation gates

Write and run tests for `validation_gates.py`. These are the safety net -- if gates are broken, hallucinated resumes ship.

### Test cases to write:

```python
# test_validation_gates.py

from validation_gates import (
    gate_fact_preservation,
    gate_ai_phrases,
    gate_keyword_verbatim,
    gate_length_sanity,
    gate_hallucination,
    validate_and_fix,
)

# Gate 1: Fact preservation
def test_fact_preserved():
    r = gate_fact_preservation(
        "Led team of 12 engineers saving $3M",
        "Directed team of 12 engineers achieving $3M in cost savings"
    )
    assert r.passed  # both facts present

def test_fact_altered():
    r = gate_fact_preservation(
        "Led team of 12 engineers saving $3M",
        "Directed team of 15 engineers achieving $5M in cost savings"
    )
    assert not r.passed  # $3M and 12 are missing

def test_fact_removed():
    r = gate_fact_preservation(
        "Reduced costs by 25%",
        "Significantly reduced operational costs"
    )
    assert not r.passed  # 25% is gone

# Gate 2: AI phrases
def test_ai_phrase_replaced():
    r = gate_ai_phrases("Spearheaded a transformative initiative")
    assert r.auto_fixed
    assert "spearheaded" not in r.fixed_text.lower()

def test_ai_phrase_protected_by_jd():
    r = gate_ai_phrases(
        "Spearheaded the cloud migration",
        jd_text="Looking for someone who has spearheaded large migrations"
    )
    # "spearheaded" is in the JD, so it should be protected
    assert "spearheaded" in (r.fixed_text or "Spearheaded").lower()

# Gate 3: Keyword verbatim
def test_keyword_present():
    r = gate_keyword_verbatim(
        "Built machine learning pipeline for real-time data",
        ["machine learning"]
    )
    assert r.passed

def test_keyword_missing():
    r = gate_keyword_verbatim(
        "Built ML pipeline for real-time data",
        ["machine learning"]
    )
    assert not r.passed  # "ML" != "machine learning"

# Gate 4: Length sanity
def test_length_too_long():
    original = "Led a team"
    tailored = " ".join(["word"] * 45)
    r = gate_length_sanity(original, tailored)
    assert not r.passed  # > 40 words

def test_length_bloated():
    original = "Led team of 5"
    tailored = " ".join(["word"] * 30)  # 30 words from 4 = 7.5x
    r = gate_length_sanity(original, tailored)
    assert not r.passed  # > 1.8x

# Gate 5: Hallucination
def test_no_hallucination():
    r = gate_hallucination(
        "Led Python team to deploy ML models",
        "Directed Python team to deploy ML models on AWS",
        injectable_keywords={"AWS"}
    )
    assert r.passed  # AWS is injectable

def test_hallucination_detected():
    r = gate_hallucination(
        "Managed team schedule",
        "Managed Kubernetes Docker Terraform CI/CD pipeline orchestration",
        injectable_keywords=set()
    )
    assert not r.passed  # 4+ new domain terms invented

# Full pipeline: validate_and_fix
def test_critical_failure_reverts():
    original = "Saved $3M through process optimization"
    tailored = "Revolutionized process optimization achieving unprecedented results"
    final, results = validate_and_fix(original, tailored)
    assert final == original  # should revert: $3M fact lost

def test_auto_fix_applied():
    original = "Led team"
    tailored = "Spearheaded a cutting-edge team"
    final, results = validate_and_fix(original, tailored, jd_text="")
    assert "spearheaded" not in final.lower()  # AI phrases cleaned
    assert final != original  # but not fully reverted
```

Run with: `python3 -m pytest test_validation_gates.py -v`

---

## Phase 3: Integration test the pipeline stages

Test each stage in isolation, then the full pipeline.

### Test jd_preparser with real DB jobs:

```python
# Pick a real job from the DB and verify pre-parsing works
from database import init_db, SessionLocal
from models import ScrapedJob
from jd_preparser import preparse_job_description

init_db()
db = SessionLocal()
job = db.query(ScrapedJob).filter(ScrapedJob.description != "").first()
if job:
    result = preparse_job_description(job.description, job.skills or [])
    assert isinstance(result["required_skills"], list)
    assert isinstance(result["single_word_skills"], list)
    assert result["parsed_at"]  # timestamp present
    print(f"Job: {job.title}")
    print(f"Required: {result['required_skills'][:5]}")
    print(f"Tech: {result['single_word_skills'][:5]}")
    print(f"Experience: {result['experience_years']}")
db.close()
```

### Test resume_structurer with a real resume:

```python
from resume_structurer import structure_resume, get_all_bullets, flatten_to_text

sample = """
Jane Doe
jane@example.com | +65 9876 5432

EXPERIENCE
Google - Singapore
Senior Engineer | Jan 2020 - Present
- Built scalable data pipeline processing 10M events daily
- Led team of 8 to migrate legacy systems to cloud

EDUCATION
NUS - BSc Computer Science | 2016 - 2020

SKILLS
Python, Java, Kubernetes, AWS, SQL
"""

result = structure_resume(sample)
assert result["contact"]["email"] == "jane@example.com"
assert len(result["sections"]) >= 3
bullets = get_all_bullets(result)
assert len(bullets) >= 2

# Round-trip test: flatten and re-parse should not lose content
flat = flatten_to_text(result)
assert "10M events" in flat
assert "Google" in flat
```

### Test the full pipeline WITHOUT LLM calls (nudge mode):

```python
from tailoring_pipeline import run_pipeline, get_pipeline_state
import time

state = run_pipeline(
    resume_text=sample,  # from above
    job_description="Looking for a Senior Engineer with 5+ years experience in Python, data pipelines, and cloud infrastructure. Kubernetes preferred.",
    parsed_jd=None,  # will be parsed on the fly
    intensity="nudge",  # local only, no LLM
)

# Wait for completion (nudge is fast, ~2s)
for _ in range(20):
    status = state.to_dict()
    if status["complete"]:
        break
    time.sleep(0.5)

assert status["complete"], f"Pipeline stuck at: {status['stage']} - {status['message']}"
assert state.result is not None
assert state.result["tailored_text"]  # not empty
assert state.result["score"]["before"] > 0
assert state.result["score"]["after"] > 0
assert isinstance(state.result["ats_gaps"], list)
assert state.result["skill_match"]["after"] >= 0  # real re-scan, not fake
assert not state.result.get("degraded", False) or state.result.get("pipeline_notes")  # if degraded, must explain why
print(f"Score: {state.result['score']['before']} -> {state.result['score']['after']}")
print(f"Skills: {state.result['skill_match']['before']} -> {state.result['skill_match']['after']}")
print(f"ATS gaps: {len(state.result['ats_gaps'])}")
```

---

## Phase 4: Error path audit

For each of these scenarios, trace through the code and verify the behavior is EXPLICIT (no silent swallowing):

1. **LLM returns None for Stage 1 strategy**: Should log warning, use fallback priorities with `_degraded: True`, and pipeline_notes must explain.

2. **LLM returns garbage for Stage 3 rewrites**: JSON parse fails, numbered-line fallback also fails. Should log warning with bullet count, continue with originals, NOT crash.

3. **All validation gates fail for a rewrite**: `validate_and_fix` should return original text. The change should NOT appear in the changes list.

4. **Job has no description**: `preparse_job_description("")` should return empty structure, not crash.

5. **Resume has no bullets**: `get_all_bullets` returns empty list. Stage 3 should skip gracefully.

6. **Rate limiter exhausted**: `_call_sealion` returns None after 30s timeout. Pipeline should degrade gracefully with pipeline_notes.

7. **Concurrent pipelines**: Two users start pipelines simultaneously. Verify `_active_pipelines` dict doesn't corrupt.

---

## Phase 5: Check for these specific bugs

1. **`_stage_6_validate` signature**: Verify ALL call sites pass `parsed_jd` (4 args before, now 5). Search for `_stage_6_validate(` and confirm.

2. **`skill_match.after` is real**: In the result builder, verify `matched_after` comes from `final.get("matched_after")` which is a real re-scan of `tailored_text`, NOT an estimate.

3. **`call_sealion_json` actually parses JSON**: Verify `json.loads(candidate)` is called inside the retry loop, not just bracket matching.

4. **Stage 3 uses `call_sealion_json`**: Verify it's not using `_call_sealion` (which has no retry logic for JSON).

5. **`_cleanup_expired_pipelines` is called**: Verify it runs on `get_pipeline_state()` reads.

6. **`lifespan` replaces `on_event("startup")`**: Verify the old `@app.on_event("startup")` is removed and `app = FastAPI(..., lifespan=lifespan)` is set.

7. **`auth.py` JWT_SECRET**: Verify no hardcoded fallback string. Local dev generates ephemeral key with explicit warning log.

---

## Phase 6: Write a summary

After completing all phases, write a `REVIEW_RESULTS.md` with:
- Total issues found (critical / medium / low)
- Each issue: file, line, description, fix applied or recommended
- Confirmation that all Phase 2 tests pass
- Confirmation that the nudge pipeline runs end-to-end
- Any remaining concerns

---

## Rules
- No hidden fallbacks. If something fails, it must be visible to the user or logged explicitly.
- Do NOT modify the pipeline architecture or add features. This review is about reliability, not new functionality.
- If you find a bug, fix it AND add a test for it.
- If you find something you're unsure about, flag it in the summary rather than silently ignoring it.
