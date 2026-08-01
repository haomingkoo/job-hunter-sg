# V4: Study-first recruitment

Design captured 2026-08-01 after a full day of live testing against production with two
real resumes. Supersedes nothing; V3 stays, this changes the order its parts run in.

## The problem in one sentence

Every expensive component in V3 runs downstream of the cheapest one, so five cited
personas and a mandatory judge do careful work on whatever a bag-of-skills cosine
happened to return.

Three disconnects, all the same shape, all confirmed live:

| what is built | where it goes today |
|---|---|
| evidence-cited candidate profile | never reaches the job search |
| job search results | never reach the conversation model |
| the coordinator's own reasoning | never reaches the search query |

The third is why a coordinator that correctly described a candidate as "bridging
semiconductor manufacturing with AI implementation" then searched a query containing
no domain terms at all. The second is why, asked to improve a resume, it replied:

> "I cannot ... I do not have access to the 7 job postings mentioned in the previous
> turn. Could you please paste the text of one or two specific job postings?"

It had found, ranked and rendered those seven jobs one turn earlier.

## The target flow

```
attach resume
  -> STUDY (async, 5 specialists, cached per resume)
       recruiter | hiring manager | ATS reader | skeptic | market analyst
  -> profile: what transfers, what is rare, what is evidenced, what the market pays
  -> SEARCH using what the study concluded (not an alphabetised skill bag)
  -> DIFF each result structurally against the profile
  -> RANK on separate axes: level, pay, domain, gap
  -> EXPLAIN each match, citing the specialist who made the point
  -> PROPOSE resume edits that close the gaps just named
```

Each stage feeds the next. That is the whole change.

## User stories

**S1. Study my resume before recommending anything.**
As a candidate, when I attach a resume, the team studies it before suggesting roles,
so its advice is about me rather than about my keywords.
- Study starts automatically on resume attach, not behind an optional button
- Five specialists each produce their own read of the person, with no job in scope
- Output is cached per resume version (`candidate_profile_artifacts` already exists)

**S2. Let me watch it work, and keep talking.**
As a candidate, I can see which specialist is working and keep chatting while they do,
so depth costs me no waiting.
- Study runs as a background run, streaming into the activity panel
- The composer stays enabled during a run
- Questions asked mid-study are accepted, not blocked

**S3. Let me stack questions.**
As a candidate, I can ask several things without waiting for each answer.
- Queued messages persist immediately and are acknowledged on arrival
- Answerable-now questions get a thin answer, flagged as provisional
- The real answer follows once the study lands, and says so
- Constraints in queued messages still land as preferences

**S4. Search using what you learned about me.**
As a candidate, the job search reflects my actual differentiator.
- The query is composed from the study, and names the intersection I sit on
- Exclusions and level are filters, never text in a similarity query

**S5. Tell me why I am a fit.**
As a candidate, every match shows why, citing my own resume.
- Structured diff per job: matched / missing / stretch, each with an evidence quote
- Level: required years vs my career; seniority vs my target
- Pay: salary against the band for that level and sector
- The model explains the diff; it does not invent it

**S6. Rank on what makes a job good, not on text similarity.**
As a candidate, a $4,000 "Manager" role does not rank alongside a $12,500 one.
- Separate axes rather than one cosine
- Underpaying-for-level is surfaced, not silently ranked equal

**S7. Draft the edits that close the gaps you just named.**
As a candidate, the gaps identified become concrete proposed bullet rewrites.
- Uses the existing `propose_resume_edit`, gates and pending-until-accepted rules

## What already exists

Most of it. This is a wiring change more than a build.

| piece | state |
|---|---|
| `candidate_profile_artifacts` + `BuildCandidateProfile` | exists, optional, output unused |
| five persona packs, versioned | exists, written to judge against a target job |
| `read_target_job`, `read_candidate_evidence`, `propose_resume_edit` | exist in `open_agent/tools.py` |
| `ask_candidate` + LangGraph interrupt + SqliteSaver checkpoints | exists, works |
| SSE, `recruitment_runs`, `workflow_state`, activity panel | exists |
| `parsed_jd` requirements, `job_terms_preview` ATS labels | exist on 90k rows |
| per-thread lock serialising commands | exists |

## What has to change

1. **Personas re-aimed at the person.** Their prompts assume a posting is in scope.
   Rewrite what each is asked to produce. Versioned pack, so the seam is there.
2. **Study becomes the entry point**, running async on resume attach.
3. **Coordinator gets context and tools.** Today `ConversationModel.respond(messages,
   resume_text, current_preferences)` binds only a structured-output submission tool,
   so it cannot look anything up. It needs the shortlist and profile in context, plus
   `read_shortlist`, `read_target_job`, `read_candidate_evidence`, `search_jobs`,
   `propose_resume_edit`. Four of the five already exist.
4. **Conversation becomes a loop**, not a single `model.invoke()`.
5. **Structured diff + multi-axis ranking**, new.
6. **Match rationale carried in the payload**, new.

## Sequencing

1. Coordinator context + tools (closes all three disconnects; highest value)
2. Study-first, async, with the re-aimed personas
3. Structured diff and rationale in the payload
4. Multi-axis ranking
5. Queued messages
6. Edit drafting from named gaps

## Traps this repo has already paid for

- **A green suite is not evidence.** 851 tests passed while job search returned zero
  results for every user, and while the coordinator could not see the jobs it found.
  Acceptance is one real run on the real site, not a passing suite.
- **An optional field is a request.** `search_query` was added, merged, deployed and
  did nothing, because the model declines to fill optional fields. If the system needs
  it, the schema must fail without it. Same lesson as the question cap.
- **Prompt text is not a bound.** A limit the model may decline is a suggestion.
- **Terse is not shallow.** Four brevity rules in the conversation prompt made the
  model drop analysis along with padding. Cut padding, never cut reasoning.
- **Similarity cannot express "not".** Embedding "not computer vision" retrieves
  computer vision. Exclusions are filters.
- **Employers mis-tag seniority.** The corpus holds "Non-executive" roles at $18,000.
  Salary is the more honest signal.
- **Rank-then-filter starves.** Constrain candidates before ranking, or an ageing
  index silently empties every result.
- **A grep cannot see model-emitted values.** Verify against runtime data before
  deleting anything keyed on model output.

## Vertical slices

Each slice is shippable on its own and is accepted by driving the real frontend
against the real backend until a user story is observably true. Not a smoke test:
a smoke test asserts a 200, and every failure found on 2026-08-01 returned 200.

Acceptance rules for every slice:
- Drive the browser, not the API. The bug where seven found jobs never reached the
  coordinator was invisible from the endpoint and obvious in the UI.
- Assert on rendered content, never on status codes.
- Use a real resume with a real career, not a fixture sentence. The fixture resume
  is one line, and one line hid every parsing failure this repo has had.
- Record the observed before-state first, so an inert change cannot pass.

### V1 - The coordinator can see the thread

Story S5 (partial), unblocks everything else.

Accept: search returns matches, then ask "improve my resume for these roles".
The reply names at least one job from the shortlist by title. It must not ask the
candidate to paste a job description.

Before-state on 2026-08-01: *"I cannot ... I do not have access to the 7 job postings."*

### V2 - The query names the differentiator

Story S4.

Accept: run autopilot on a resume with a clear domain. The query rendered in the
transcript contains a domain term from the resume. Results include at least one
employer from that domain.

Before-state: query was `prompt engineering ... computer vision ... deep learning`,
results were HRNET Ventures and BOK SENG Logistics. The same corpus returns Micron,
NXP and Avago when the domain is named.

Guard: `search_query` must be required in the submission schema. It was optional,
merged, deployed, and never once populated.

### V3 - Exclusions are honoured

Story S4.

Accept: state "not computer vision, not entry level" in conversation, then search.
No result is a computer-vision role. No result is entry level unless its salary
contradicts its label.

Before-state: stating exclusions made results worse. 2 of 7 defensible, down from
the turn before any constraint was given.

### V4 - Study runs first, and is visible

Stories S1, S2.

Accept: attach a resume and do nothing else. The activity panel names specialists
working within seconds, without the candidate pressing anything. The composer stays
enabled throughout. A profile artifact exists when it finishes, and a second search
on the same resume does not re-run it.

### V5 - Every match says why

Story S5.

Accept: each result card shows matched, missing and stretch, and at least one item
quotes the resume. A quoted phrase must appear verbatim in the resume text.

### V6 - Ranking separates level and pay

Story S6.

Accept: given two postings with the same claimed title where one pays materially
less for the level, the better-paid one ranks higher, and the underpaying one is
labelled as such.

Before-state: a $4,000 "Manager, AI Transformation" and a $12,500 "IT Project
Manager" ranked as peers.

### V7 - Questions stack

Story S3.

Accept: send three messages during a running study. All three persist and appear.
Each is acknowledged. Constraints stated in them land as preferences. Nothing is
dropped and the composer never locks.

### V8 - Gaps become drafted edits

Story S7.

Accept: after a match names a missing requirement, proposed edits appear in the
table for that thread, pending. Accepting one changes the resume; declining leaves
it untouched.

Before-state: proposed edits have never been observed reaching the table on a live
run.
