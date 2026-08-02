# V4 slice 4: automatic resume study (#141)

Current implementation and acceptance record for issue #141. The executable contract is
in `backend/tests/test_study_first.py`.

## Implemented behavior

- `StartThread` dispatches a background candidate-profile study after the new thread is
  durable.
- The study is keyed by user, resume version, checkpoint, prompt version, and model. It
  does not hold the conversation's thread lock while model work runs.
- A second thread using the same unchanged resume resolves the completed artifact and
  makes zero additional profiler calls.
- Running, completed, and failed study events are persisted. The active streaming request
  also receives those events, so the activity panel shows the profiler while it works.
- The thread records `candidate_profile_status` and the completed artifact ID. While the
  study runs, the manual study action is disabled and labelled `Studying resume`.
- The coordinator can continue working while the profile is unavailable. Once complete,
  `read_candidate_evidence` resolves the resume-version artifact.

The artifact belongs to a resume version, not a conversation. A thread holds only the
status and artifact pointer needed by its snapshot and read endpoints.

## Product boundary

The automatic study is one evidence profiler, not a second persona-orchestration system.
Recruiter, hiring-manager, ATS, skeptic, and judge roles remain part of target assessment
when that workflow requires them. The empty-state copy must not claim that those roles run
on every first message.

Studying every uploaded or saved resume is intentionally outside this slice. The trigger
is attaching a resume to a recruitment-team thread, avoiding model work for unused
versions.

## Acceptance evidence

Observed in the local browser against the real API on 2026-08-03:

1. On a fresh thread, `Candidate profiler is working` appeared in about one second without
   pressing a separate study control.
2. The composer remained enabled while the study ran. The coordinator completed its own
   first turn independently.
3. The study completed and stored artifact
   `ca5c66a2-45bc-45e7-bc6c-8da8daf8ac0f` for the acceptance fixture.
4. A second thread using the same resume immediately linked that artifact, added no study
   run, and emitted no candidate-profiler event.

The artifact identifier above belongs only to the local acceptance database; correctness
does not depend on that value.

## Regression coverage

- A study can build an artifact without a thread in model scope.
- Repeating a completed resume-version study makes zero profiler calls.
- `StartThread` dispatches only after the thread is durable.
- Another thread resolves the existing resume-version artifact.
- Background events are routed to the active stream publisher.
- The automatic study does not take the long-running conversation lock.
- The frontend disables the manual study action while automatic study is running.
