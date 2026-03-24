# CODEX REVIEW — Resume Tailoring Pipeline

## INSTRUCTION TO CODEX

You MUST run every test below. Not read. RUN. Write actual test files, execute them, report pass/fail. If you find a bug, fix it AND add a test. Write results to `REVIEW_RESULTS.md`.

Use agents in parallel where possible to speed this up.

---

## TASK 1: Import check (run these, report pass/fail)

```bash
cd backend
python3 -c "from jd_preparser import preparse_job_description; print('PASS')"
python3 -c "from resume_structurer import structure_resume, get_all_bullets, flatten_to_text; print('PASS')"
python3 -c "from ai_phrases import clean_ai_phrases, AI_PHRASE_REPLACEMENTS; print(f'PASS: {len(AI_PHRASE_REPLACEMENTS)} phrases')"
python3 -c "from validation_gates import run_all_gates, validate_and_fix; print('PASS')"
python3 -c "from tailoring_pipeline import run_pipeline, get_pipeline_state, STAGES; print(f'PASS: {len(STAGES)} stages')"
python3 -c "from models import ScrapedJob, TailoredResume; print('PASS')"
```

---

## TASK 2: Write and run validation gate tests

Create `backend/tests/test_validation_gates.py` with these EXACT tests:

```python
from validation_gates import gate_fact_preservation, gate_ai_phrases, gate_keyword_verbatim, gate_length_sanity, gate_hallucination, validate_and_fix

def test_fact_preserved():
    """$3M in original must appear in rewrite."""
    r = gate_fact_preservation("Led team of 12 engineers saving $3M", "Directed team of 12 engineers achieving $3M in savings")
    assert r.passed, f"Should pass: {r.message}"

def test_fact_altered():
    """Changed $3M to $5M must FAIL."""
    r = gate_fact_preservation("Led team of 12 engineers saving $3M", "Directed team of 15 engineers achieving $5M")
    assert not r.passed, "Should fail: facts were altered"

def test_fact_removed():
    """Removing 25% must FAIL."""
    r = gate_fact_preservation("Reduced costs by 25%", "Significantly reduced operational costs")
    assert not r.passed, "Should fail: 25% was removed"

def test_ai_phrase_replaced():
    """'Spearheaded' should be auto-replaced."""
    r = gate_ai_phrases("Spearheaded a transformative initiative")
    assert r.auto_fixed, "Should auto-fix AI phrases"
    assert "spearheaded" not in r.fixed_text.lower(), "spearheaded should be replaced"

def test_ai_phrase_protected_by_jd():
    """If JD uses 'spearheaded', don't replace it."""
    r = gate_ai_phrases("Spearheaded the migration", jd_text="Must have spearheaded large projects")
    # spearheaded is in JD, should be protected
    if r.fixed_text:
        assert "spearhead" in r.fixed_text.lower(), "Protected phrase was wrongly replaced"

def test_keyword_present():
    r = gate_keyword_verbatim("Built machine learning pipeline", ["machine learning"])
    assert r.passed

def test_keyword_missing():
    r = gate_keyword_verbatim("Built ML pipeline", ["machine learning"])
    assert not r.passed, "'ML' is not 'machine learning'"

def test_length_too_long():
    r = gate_length_sanity("Led a team", " ".join(["word"] * 45))
    assert not r.passed, "45 words exceeds 40 max"

def test_length_bloated():
    r = gate_length_sanity("Led team", " ".join(["word"] * 20))
    assert not r.passed, "20 words from 2 = 10x, exceeds 1.8x"

def test_hallucination_with_injectable():
    r = gate_hallucination("Led Python team", "Led Python team to deploy on AWS", injectable_keywords={"AWS"})
    assert r.passed, "AWS is injectable, should pass"

def test_hallucination_detected():
    r = gate_hallucination("Managed schedule", "Managed Kubernetes Docker Terraform CI/CD pipeline", injectable_keywords=set())
    assert not r.passed, "4+ new terms invented"

def test_critical_failure_reverts():
    """If fact is lost, validate_and_fix must return ORIGINAL text."""
    original = "Saved $3M through process optimization"
    tailored = "Revolutionized process optimization achieving unprecedented results"
    final, _ = validate_and_fix(original, tailored)
    assert final == original, f"Should revert to original, got: {final}"
```

Run: `cd backend && python3 -m pytest tests/test_validation_gates.py -v`

Report: how many pass, how many fail. Fix any failures.

---

## TASK 3: Run nudge pipeline end-to-end (no LLM needed)

```python
# Save as backend/tests/test_pipeline_nudge.py and RUN it
import sys, time
sys.path.insert(0, ".")
from tailoring_pipeline import run_pipeline, get_pipeline_state

sample_resume = """
Jane Doe
jane@example.com | +65 9876 5432

EXPERIENCE
Google - Singapore
Senior Engineer | Jan 2020 - Present
- Built scalable data pipeline processing 10M events daily
- Led team of 8 to migrate legacy systems to cloud
- Responsible for managing cross-team dependencies

EDUCATION
NUS - BSc Computer Science | 2016 - 2020

SKILLS
Python, Java, Kubernetes, AWS, SQL
"""

sample_jd = "Senior Engineer with 5+ years in Python, data pipelines, cloud infrastructure. Kubernetes preferred."

state = run_pipeline(
    resume_text=sample_resume,
    job_description=sample_jd,
    parsed_jd=None,
    intensity="nudge",
)

for _ in range(30):
    status = state.to_dict()
    print(f"  Stage {status['stage_number']}/{status['total_stages']}: {status['stage']} - {status['message']}")
    if status["complete"]:
        break
    if status.get("error"):
        print(f"  ERROR: {status['error']}")
        break
    time.sleep(0.5)

assert status["complete"], f"Pipeline stuck at: {status['stage']}"
result = state.result
assert result, "No result"
assert result["tailored_text"], "Empty tailored text"
assert result["score"]["before"] > 0, "No baseline score"
assert result["score"]["after"] > 0, "No final score"
assert isinstance(result["ats_gaps"], list), "No ATS gaps"
assert isinstance(result["skill_match"]["matched_after"], list), "skill_match.after should be a real list"
assert not result.get("degraded") or result.get("pipeline_notes"), "If degraded, must explain why"

print(f"\nPASS: Score {result['score']['before']} -> {result['score']['after']}")
print(f"Skills matched: {result['skill_match']['before']} -> {result['skill_match']['after']}")
print(f"ATS gaps: {len(result['ats_gaps'])}")
print(f"Changes: {result['total_changes']}")
```

Run: `cd backend && python3 tests/test_pipeline_nudge.py`

---

## TASK 4: Check error paths (trace through code, verify no silent failures)

For each scenario, trace the code path and confirm it either raises an error or adds to pipeline_notes:

1. `_stage_1_strategize` returns None -> should use fallback with `_degraded: True`
2. Stage 3 LLM returns empty string -> should log warning, keep originals
3. `validate_and_fix` gets a rewrite where $3M became $5M -> should return original text
4. `preparse_job_description("")` -> should return empty structure, not crash
5. `structure_resume("")` -> should not crash

Run each case manually in Python and report.

---

## TASK 5: Check the live deployment works

After Railway deploys, test:
```bash
curl -s 'https://jobhunter.kooexperience.com/api/jobs/1/parsed' | python3 -m json.tool
```

Verify it returns `{job_id, title, company, parsed_jd, has_parsed_jd}`.

---

## TASK 6: Write REVIEW_RESULTS.md

Format:
```
# Review Results

## Import check: X/6 pass
## Validation gate tests: X/13 pass
## Nudge pipeline: PASS/FAIL
## Error paths: X/5 verified
## Live deployment: PASS/FAIL

## Issues found:
1. [CRITICAL/MEDIUM/LOW] file:line - description - fix applied: yes/no
2. ...

## Conclusion: SHIP / NEEDS FIXES
```
