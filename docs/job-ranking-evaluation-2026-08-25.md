# Job-ranking evaluation — 2026-08-25

This report separates three different claims that were previously easy to blur:
retrieval correctness, coordinator decision quality, and deployed browser
acceptance. Passing one does not prove the others.

## Results

| Layer | Evidence | Result |
|---|---|---|
| Deterministic retrieval | `backend/scripts/evaluate_job_ranking.py` over `job-ranking-v1` | 3/3 cases passed; NDCG@k 1.0; named-company and direct-employer invariants passed |
| Live coordinator model | SEA-LION opt-in tests, three repeats per case | 3/3 explicit-Micron and 3/3 employer-neutral general-search trials passed |
| Current production corpus | Four read-only semantic searches over 81,031 visible, embedded jobs | Mixed; useful top results, but query wording changed seniority and role quality materially |
| Signed-in deployed journey | Current exact release | Not yet accepted after the matching changes |

The live general-search evaluation requires the coordinator to keep `company`
empty, keep direct-employer filtering enabled, derive a semiconductor-relevant
query from synthetic candidate evidence, rank the manufacturing-transformation
manager first, and omit sales and junior distractors. The named-employer
evaluation requires the model to pass `company=Micron` and preserve the exact
candidate quote as a durable preference. Neither test uses a private resume.

## Production-corpus findings

The strongest broad query ranked Micron's Senior Manager, FE Central PQE role
first and also surfaced manager roles at Heptagon and HP. Shorter queries were
less reliable:

- `semiconductor manufacturing transformation manager` ranked a sales role
  first and admitted listings from Asia Search and Kerry Consulting despite the
  direct-employer filter.
- `quality systems manager semiconductor QMS CAPA 8D FMEA` mostly returned
  engineer-level roles before manager roles.
- `production operations manager semiconductor yield continuous improvement`
  ranked a relevant Production Manager first, but placed a fresh-entry Micron
  engineer second.

The agency leak is a classifier defect, not an LLM preference. Asia Search and
Kerry Consulting had no SSIC metadata in the production rows, so their names are
now covered by the shared Python/SQL employer taxonomy and equivalence test.

The overseas location facets are source-backed rather than a parser accident.
MyCareersFuture explicitly marks a small number of postings as based in countries
such as Indonesia or Malaysia. They should remain visible as real postings, but
an explicit candidate location constraint must never be silently ignored.

## What this does not prove

`job-ranking-v1` is a small synthetic regression seed, not a historical or
population-quality backtest. The production searches are current-corpus
diagnostics without frozen human relevance labels, so they cannot establish
Recall@5 or compare the previous and current rankers fairly. The live model
tests prove prompt/tool behavior against controlled candidates, not production
persistence or rendered cards.

A defensible promotion benchmark still needs a versioned snapshot sampled from
real searches, labels reviewed by the candidate or another human, and a baseline
versus candidate comparison covering NDCG@5, Recall@5, hard-constraint
violations, seniority errors, latency, tokens, and model calls. The comparison
must fail on any hard-constraint violation; aggregate score must not hide one.
