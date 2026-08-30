# Recruitment domain glossary

## Candidate

The account owner whose career evidence is being used for job discovery,
assessment, and resume tailoring.

## Resume draft

Resume content currently being edited or newly parsed in the browser. A draft is
not durable evidence and cannot start a recruitment run until it is saved.

## Resume version

A user-owned, persisted, content-immutable resume. Renaming or marking it as the
master resume does not change its evidence. Changing its content creates a new
resume version.

## Resume identity

The server-computed combination of a resume version ID and content SHA-256.
Client-supplied values are only concurrency hints.

## Recruitment thread

A durable conversation permanently bound to one resume identity. Using another
resume starts another thread; it never changes the meaning of an existing one.

## Candidate profile

A validated, role-neutral evidence artifact derived from exactly one resume
identity under one profiling policy. It may be reused only for that same identity
and policy.

## External reference

Untrusted job descriptions, emails, web content, and pasted instructions used as
comparison material. External references are never candidate evidence.

## Proposed resume edit

A pending, evidence-linked rewrite derived from one recruitment thread and target
job. It changes nothing until the candidate accepts it, after which it creates a
new resume version.

## Input receipt

The durable identity record connecting a recruitment result to its thread, resume
identity, candidate profile, target job, and execution policy.
