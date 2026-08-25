# Job-ranking evaluation — 2026-08-25

This report separates retrieval regression, current-corpus diagnosis,
coordinator tool choice, and deployed browser acceptance. Passing one does not
prove the others.

## Evidence collected

| Layer | Evidence | Result |
|---|---|---|
| Offline regression | `backend/scripts/evaluate_job_ranking.py` over `job-ranking-v1` | 3/3 synthetic cases passed |
| Live coordinator | SEA-LION opt-in prompt evaluations, three repeats per case | 3/3 named-Micron and 3/3 explicit manager-search trials passed |
| Frozen production corpus | 81,031 public postings exported at `2026-08-25T11:38:00Z` and re-embedded from frozen text | Micron and other plausible manager roles were retrieved; the earlier numeric comparison is withdrawn because its post-hoc judged pool was incomplete |
| PostgreSQL policy parity | Read-only checks against the production PostgreSQL regex engine | EA markers, EA numbers, and punctuated agency names matched; direct-employer negative control did not |
| Signed-in deployed journey | Exact candidate release | Not yet accepted |

The frozen corpus SHA-256 is
`bfee51bf22c0d6dc2010efb10edd7d72de3a90c238895ecdedd4cbad31a5bfa4`.
The post-hoc development manifest SHA-256 is
`e5e7acf5ccf426bd257b02d007f8d0d9997f1ae960e6d008d977b5efdf183ded`.
The corpus is not checked into Git because it is 213 MB; the hashes bind the
local evaluation artifacts used for this report.

## Frozen-corpus development findings

The original four-case development table is deliberately not retained as
evidence. After the replay was corrected to reproduce released filtering order,
some returned jobs had no judgment. Reporting NDCG or recall for that incomplete
pool would be false precision. The replay now fails closed when any returned job
is unjudged.

For the rich query, the constrained retrieval ranked Micron's Senior Manager,
FE Central PQE role first, followed by manager roles at Heptagon, HP, New Toyo,
and Sys-Mac. The explicit-Micron case returned only Micron manager titles, again
with Senior Manager, FE Central PQE first. The short general case placed Micron
seventh in the seven-result retrieval set, so the coordinator can still select
it after comparing resume evidence rather than fame.

The policy now keeps direct employers, Singapore work locations, and explicit
title constraints inside pre-ranking eligibility. Overseas postings remain real
source rows and can be requested explicitly, but they are not returned by the
Recruitment Team's default Singapore search. Title evidence such as "Based in
Batam" overrides a misleading structured value such as "Islandwide".

## Live prompt evaluation

The named-employer evaluation requires the coordinator to pass `company=Micron`
instead of hoping semantic similarity recognises the employer. The manager
evaluation requires employer neutrality, direct-employer and Singapore
constraints, and an effective manager-level constraint. SEA-LION consistently
used `title_phrase=manager`; it did not redundantly add `exclude_junior` in that
case. It then published the strongest manufacturing-transformation role and
omitted the sales and technician distractors. The prompt tests use synthetic
candidate evidence, not a private resume.

## What this proves—and does not prove

This is a real frozen-corpus development replay, but it does not yet prove a
ranking improvement. It reproduces the Micron retrieval observation and checks
constraint mechanics on source-backed postings. It is not a
released-SHA-versus-candidate backtest: both diagnostic arms use the current
encoder and ranker, and the judgments were written after observing the
development pools. The machine-readable receipt therefore returns
`release_qualified: false`.

A release claim still requires a precommitted query set, arm-blinded pooled
judgments, captured outputs from the released checkout, and the candidate
outputs on the identical corpus. Retrieval evidence must then be combined with
an exact-SHA signed-in browser run and persisted trace evidence; neither one can
stand in for the other.
