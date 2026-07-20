# Resume Agent Reference Benchmark — 2026-07-19

## Labelled case

Resume evidence:

- AI Project Lead at GovTech, Jan 2022–Present.
- Led delivery of an internal document assistant for operations teams.
- Coordinated engineers, policy users, and QA reviewers across rollout.

Target evidence:

- AI Project Lead at Example Agency.
- Own document automation delivery and stakeholder rollout.

The business policy excludes candidate location from scoring.

## Independent reference panel

Three isolated Codex reviewers evaluated the same evidence without seeing each
other's work. Each scored the candidate 78/100 and identified the same three
material gaps:

1. No quantified outcome, adoption, or scale evidence.
2. “Led delivery” does not prove end-to-end ownership.
3. “Document assistant” is related to, but does not prove, “document automation.”

One reviewer also mentioned missing Singapore location. That finding was rejected
because the product's explicit fairness policy prohibits location scoring.

The comparator is an independent Codex panel. The runtime did not expose a model
selector, so this is not represented as a verified GPT-5.6 comparison.

## Product results

| Measurement | Baseline | Optimized clean run | Final gated recovery run |
|---|---:|---:|---:|
| Model calls | 14 | 7 | 9 |
| Total tokens | 53,664 | 28,386 | 45,610 |
| Product median candidate score | 72 | 72 | 72 |
| Reviewer score range | 20 | 20 | 13 |
| Reference-panel score | 78 | 78 | 78 |
| Valid reference gaps found | 3/3 | 3/3 | 3/3 |
| Quality judge | 88, consensus-only | 88, raw-evidence grounded | 88, structured tool verdict |
| End-to-end elapsed time | not comparable | 45.0 s | 92.9 s |

The optimized clean run contained five parallel reviewer calls, one synthesis
call, one judge call, and five local `submit_assessment` tool calls. Reviewer
latencies ranged from 1.0 s to 19.4 s. Synthesis took 15.4 s and the judge took
9.5 s. Synthesis and judging remain the main token and latency consumers.

An earlier recovery run demonstrated the bounded feedback loop: the judge
requested a synthesis revision, the synthesis was corrected, and the result was
re-judged. A judge timeout added 60 seconds and was preserved as an error span;
it was not converted into an empty result or hidden success.

The final gated run used five reviewer calls, one read-only synthesis, one native
LangChain structured judge call, one synthesis revision, and one structured
re-judge. The initial synthesis included hypothetical examples, so the judge
correctly required revision. The final output had no edit-tool calls, hidden
fallbacks, placeholders, example markers, reviewer-mechanism leakage, or other
presentation-contract violations. The quality judge scored the final write-up
88/100 and returned evidence-cited strengths, weaknesses, deductions, confidence
bases, and evidence gaps through `submit_quality_judgment`.

## Output evaluation

The optimized product and reference panel agree on all three material gaps. The
product adds useful role-specific perspectives and an explicit median, but its
72 score is six points below the unanimous reference score. That score delta is
rubric weighting, not missed evidence.

The live evaluations found and drove fixes for these output defects:

- Treating “document assistant” as equivalent to automation.
- Treating “led delivery” as proof of end-to-end ownership.
- Penalizing an unrequested technology stack.
- Combining different findings under an inaccurate unanimous-consensus claim.
- Printing internal claim IDs in user-facing prose.
- Suggesting placeholder metrics or hypothetical capabilities.

The judge now receives raw resume and target-job evidence, uses a native
LangChain structured tool schema with
blocking/non-blocking weaknesses, and triggers one visible synthesis revision for
blocking evidence defects.

## Architecture finding

The deployed review path is a bounded hybrid:

- The session coordinator launches independent, isolated reviewer model calls in
  parallel and passes each reviewer explicit evidence and a specialist prompt.
- A separate LLM synthesizes their validated outputs.
- A fresh LLM instance judges the synthesis against raw evidence.

This is genuinely multi-model and iterative, but reviewer selection and assignment
remain deterministic rather than LLM-decomposed. The generic DeepAgents factory
supports native delegation, while the production path favors explicit coverage,
validation, and bounded cost. Dynamic LLM task decomposition should only replace
this after a labelled benchmark shows better output per token.

## Deployment gate

Run locally first:

```bash
cd backend
.venv/bin/pytest -q
RUN_LIVE_SEALION=1 .venv/bin/pytest -q tests/test_resume_agent_live.py
.venv/bin/python scripts/benchmark_resume_agent_reference.py
```

Run the authenticated staging canary after deployment:

```bash
cd backend
JOB_HUNTER_E2E_BASE_URL=https://staging.example \
JOB_HUNTER_E2E_TOKEN=... \
.venv/bin/python scripts/validate_resume_agent_deployment.py
```

The canary fails unless every required reviewer completes, every reviewer uses
the structured submission contract, synthesis and judge spans are present in
matched pairs, the final judge no longer requests revision, the target context
survives a follow-up turn, and the terminal output is non-empty. HTTP 200 alone
does not pass the gate.
