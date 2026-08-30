# ADR 0001: Bind recruitment threads to immutable resume versions

Date: 2026-08-30

Status: Accepted

## Context

An authenticated upload currently produces a browser draft but not a saved resume
version. Recruitment Team may then restore an older active thread. Separately,
saved resume content can be overwritten while completed candidate profiles are
looked up mainly by resume-version ID. Together these behaviours can attach stale
career evidence to a new conversation.

The system already has user-owned `ResumeVersion` records, a
`RecruitmentThread.resume_version_id`, a server-computed `resume_sha256` in thread
facts, and revision-aware profile checkpoints.

## Decision

- Resume-version content is immutable. Content changes create a new version;
  metadata such as label and master status may still change.
- A new recruitment thread starts only after explicit resume selection and is
  permanently bound to that resume's server-computed ID and SHA-256.
- One private bound-resume resolver verifies ownership and identity before every
  recruitment workflow or evidence read.
- Candidate-profile reuse requires the bound document ID and revision as well as
  the existing profiling-policy checks.
- Accepting proposed edits creates a derived resume version and does not rebind the
  original thread.
- Legacy identity mismatches fail closed and ask the user to start a new thread.

## Consequences

The existing tables and public command model remain sufficient. We do not add a
snapshot table, global active-resume pointer, event bus, or generic evidence
framework. Some existing clients that overwrite resume content through `PUT` must
create a new version instead. Historical threads whose saved hash no longer
matches their version remain readable for audit but cannot run new work.

## Rejected alternatives

- Selecting the newest or master resume is ambiguous for multi-resume users.
- Clearing browser state or caches cannot prove server-side evidence identity.
- Rebuilding every profile still builds from the wrong resume if selection is
  wrong.
- Mutating a thread to use accepted edits changes the meaning of its history.
- A new snapshot subsystem duplicates an identity already expressible by an
  immutable resume version plus its existing hash.
