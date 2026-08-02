# V4 slice 4: the study runs first, automatically (#141)

Design for issue #141. Companion to `docs/v4-study-first-recruitment.md`, slice **V4**,
and the next item in that PRD's sequencing after the coordinator loop (#146, merged in
PR 151).

This document is the contract the tests in `backend/tests/test_study_first.py` assert
against.

## The state today

Every piece exists and nothing connects them.

| piece | state |
|---|---|
| `CandidateProfileArtifact` | keyed `(user_id, resume_version_id, checkpoint_id)`, holds validated scopes and the finished profile |
| `SQLAlchemyCandidateProfileStore` | resumes validated scopes, abandons a checkpoint whose prompt or model version moved on |
| `LangChainCandidateProfilerFactory` | produces the evidence-cited profile |
| `ConversationContext.candidate_profile` | already populated on every coordinator turn, `recruitment_team.py:563` |
| `read_candidate_evidence` | already bound to the coordinator loop |

So the profile reaches the agent the moment one exists. The only missing link is that
**nothing ever builds it unless the candidate finds the "Study resume" button and presses
it.** `BuildCandidateProfile` is reachable from two endpoints and from no automatic path.

Observed on 2026-08-02, live, on the first turn of a fresh thread:

```
read_candidate_evidence -> {"ok": false, "failure_type": "business",
                            "reason": "No evidence profile exists for this thread yet"}
```

The coordinator then wrote its search query from raw resume text. Its own reply named the
candidate's semiconductor background as the differentiator, and neither query it ran
contained a domain term. That is slice V2's failure (#139) with the study as its cause.

## The conflict this slice has to resolve

Issue #141 states two acceptance criteria that pull against each other:

> 3. The composer is enabled the whole time
> 5. Parallel specialists writing to one thread must go through that lock, not around it

`execute()` takes a blocking process-local `_thread_lock(thread_id)` for the whole
command (`recruitment_team.py:230-234`). A study is one model call per resume scope, so
30 to 60 seconds on the AGENT tier. Start it as a thread-scoped command and the
candidate's first `SendMessage` blocks on that lock until it finishes. The composer is
enabled and the Send button spins. Criterion 3 would be satisfied in the DOM and violated
in the product.

**Resolution: the study is a property of a resume version, not of a conversation.**

The artifact table already says so. `CandidateProfileArtifact` is keyed by
`(user_id, resume_version_id)`; the thread only holds a pointer in
`case_facts["candidate_profile_artifact_id"]`. Building the study needs no thread, so it
takes no thread lock, and criteria 3 and 5 stop competing: there is no thread write to
serialise during the model work.

What follows from that:

- The study runs against `(user_id, resume_version_id)` with no thread in scope.
- A thread **resolves** its profile by looking the artifact up on that key, rather than
  requiring that this particular thread is the one that built it. Two threads on one
  resume then share a study, which is what "cached per resume version" has to mean.
- Activity events are the one genuine thread write, and they are short. They take the
  lock to allocate `thread.next_event_sequence` and release it. A held-for-milliseconds
  lock is not the held-for-a-minute lock criterion 3 is about.

## 1. The entry point

New module `backend/recruitment_team/study.py`.

```python
def study_resume_version(
    db: Session,
    *,
    owner_id: int,
    resume_version_id: int,
    profiler_factory: CandidateProfilerFactory,
    telemetry: RecruitmentTelemetry,
) -> CandidateProfileArtifact: ...
```

No `thread_id` parameter, and that absence is the design. It is a guard against the next
person reaching for `thread.case_facts` from inside the study and quietly reintroducing
the lock.

It is idempotent by construction rather than by a flag: `_profile_checkpoint_id` derives
from the resume document plus the configured model, and the store loads validated scopes
under that id, so a second call over a completed artifact makes **zero model calls** and
returns the same record. Acceptance criterion 5 is a property of the checkpoint, not a
new short-circuit, and the test asserts on the model-call count rather than on wall time.

## 2. Where it is triggered

`StartThread` is the resume-attach point for the recruitment team, and it is the only
trigger this slice adds. After `_start_thread` commits, the study is dispatched to a
background worker that builds its own `Session` and its own team, the way
`activity_stream.stream_command` already spawns `recruitment-team-command`
(`activity_stream.py:45-81`). The request returns without waiting.

Not triggered on resume upload or on resume save. Those are outside the recruitment team
and would study resumes the candidate never brings to it, at one model call per scope
each. If the study should follow every saved resume, that is a decision about cost and
belongs in its own issue.

## 3. Resolving the profile from a thread

`recruitment_team.py:557` currently gates on
`facts["candidate_profile_status"] == "completed"` and
`facts["candidate_profile_artifact_id"]`. Both are written only by
`_build_candidate_profile`, so a thread whose study ran through the new path would report
no profile while a completed artifact sat in the table.

The gate becomes a lookup on `(owner_id, thread.resume_version_id)` for a `completed`
artifact under the current checkpoint identity. `case_facts` keeps its two keys, written
whenever a lookup succeeds, so `snapshot()` and the existing endpoints keep working and
the frontend needs no change to read them.

## 4. Visibility

Acceptance criterion 2 is that the panel names specialists working within seconds, with
nothing pressed. The study publishes activity events on the thread that dispatched it,
through `RecruitmentTeam._event` and the existing publisher, with
`team_member="candidate_profiler"` and one event per resume scope as it completes.

`TOOL_PHRASES` and `humanize` in `TeamActivityPanel.jsx` already render
`"{member} called {tool}."`. The scope events use the same shape, so the panel needs a
phrase entry and nothing else.

**Within seconds** is the part worth testing. The first event must be published when the
study starts, not when the first scope completes, because the first scope is a model call
and the criterion is about what the candidate sees while waiting.

## 5. What the coordinator sees while the study runs

Nothing blocks, so the candidate can send a message during the study. `read_candidate_evidence`
returns the same refusal it returns today, with the reason changed to say a study is in
progress rather than that none exists. The live trace of 2026-08-02 shows the coordinator
handling that refusal correctly on the first try: it read the reason, dropped the tool,
and searched instead.

This is #148's principle applied. The agent is given the fact that a study is running and
decides what to do about it. It is not blocked, and it is not lied to.

## 6. Acceptance

Driven in a browser against a real backend, asserting on rendered text, with the
before-state recorded first.

1. Attach a resume and press nothing. The activity panel names the candidate profiler
   working within seconds.
2. The composer accepts a message and sends it while the study is still running. The
   reply arrives without waiting for the study.
3. A profile artifact exists when it finishes, and the coordinator's next turn calls
   `read_candidate_evidence` and gets fields back.
4. Start a second thread on the same resume version. The study does not re-run: no
   candidate-profiler model call, and the profile is available immediately.

### Unit tests

| test | what would otherwise pass while broken |
|---|---|
| `study_resume_version` builds an artifact with no thread in scope | a study that still needs a thread, and with it the lock |
| a second study on the same resume version makes zero model calls | criterion 5, asserted on model calls rather than on elapsed time |
| `StartThread` dispatches the study | the trigger forgotten, which is the whole slice |
| a thread resolves a profile built by another thread | the `case_facts` gate left in place, so the study runs and no turn can see it |
| a message sent during a running study is not blocked | the lock reintroduced by a later refactor |
| the first activity event is published before the first scope completes | "within seconds" satisfied only for a fast model |
| `read_candidate_evidence` says a study is running | the coordinator told a profile will never exist, and giving up on it |

## 7. What is NOT built

- **The persona-pack rewrite.** Issue #141's scope says five specialists should produce
  their own read of the person with no job in scope. Today's profiler is decomposed by
  resume scope, not by persona, and rewriting it changes what the artifact means, what
  validates it, and every checkpoint in the table. This slice connects the study that
  exists. Re-aiming the personas is worth its own issue and its own before-state.
- **Studying on resume upload or save.** See §2.
- **Queued messages.** A message sent during a study is answered immediately, not
  queued. Stacking is slice V7 (#144).
- **Any change to the per-thread lock.** The point of §1 is that this slice does not
  need one.
