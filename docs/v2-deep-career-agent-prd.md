# Job Hunter SG V2 Deep Career Agent PRD

Status: ready-for-agent
Date: 2026-07-04

## Problem Statement

The user wants Job Hunter SG to become a highly capable job-seeking system, not just a job board, resume editor, or application tracker. The system should understand the candidate from historical resumes, projects, dev work, LinkedIn/profile context, and direct interview answers. It should then help the candidate pursue a specific job with accurate, evidence-bound positioning.

Today, the candidate has many historical resumes and application variants, but no single trusted model of "who I am, what I can do, what evidence supports it, and which positioning has worked." Existing resume tailoring can improve text, but the advanced product needs to connect candidate understanding, job research, ATS matching, agent debate, resume generation, interview preparation, application tracking, and outcome learning.

The key risk is fabrication. The system must never optimize a resume by inventing unsupported claims, metrics, credentials, employers, tools, dates, or outcomes. It should improve match quality by finding the strongest truthful evidence and asking the candidate when evidence is missing.

## Solution

Build **Job Hunter SG Advanced**, also described as the **Deep Career Agent**, inside the existing Job Hunter SG product.

The product centers on one application at a time:

1. The user creates or selects an application from a job description.
2. The system builds or updates a candidate capability model from past resumes, saved resume versions, profile context, projects, and candidate answers.
3. The system researches the target role, title, company language, similar job posts, likely ATS keywords, and market expectations.
4. The deep agent creates a tailored application workspace containing a role brief, claim ledger, resume draft, debate round, final application pack, and interview prep.
5. Specialist agents critique and improve the work through a shared application workspace rather than a rigid linear handoff.
6. The final resume is approved by the user and saved as both structured text and the exact submitted DOCX/PDF artifact.
7. The application is tracked through append-only stages and outcomes so the system can later learn which positioning, role families, keywords, and resume versions are getting traction.

The first version should be powerful but not broad. It should prioritize one excellent end-to-end application workflow before broad automation.

### Phased Delivery

**Phase 1: Application Workspace V1**

Start with one job description and one application. The user can create a tracked application, attach resume/profile context, run the existing deep-agent foundation, and receive a role brief, tailored resume draft, agent debate summary, and append-only stage history.

This phase proves the core loop:

```text
job description
-> tracked application
-> candidate context
-> deep agent review
-> role brief
-> tailored draft
-> debate metadata
-> saved status history
```

**Phase 2: Candidate Evidence Graph**

Ingest historical resumes and saved resume versions, deduplicate variants, extract recurring claims, and build a candidate capability model. This becomes the evidence source behind the claim ledger.

**Phase 3: Web Auto-Research**

Add controlled research for similar job titles, role expectations, public job posts, ATS language, company signals, and safe interview-question sources. Research should enrich the role brief, not bypass user approval.

**Phase 4: Outcome Learning**

Use application outcomes to compare which role angles, resume versions, keywords, bullets, and company types correlate with interviews, rejections, offers, or no response. Treat these as signals, not causal proof.

## Issue Plan

- [#32 Create Application Workspace V1](https://github.com/haomingkoo/job-hunter-sg/issues/32)
- [#33 Create Application From Pasted Job Description](https://github.com/haomingkoo/job-hunter-sg/issues/33)
- [#34 Workspace Detail View](https://github.com/haomingkoo/job-hunter-sg/issues/34)
- [#35 Run Deep Agent Review](https://github.com/haomingkoo/job-hunter-sg/issues/35)
- [#36 Persist Debate Summary](https://github.com/haomingkoo/job-hunter-sg/issues/36)
- [#37 Save Tailored Resume Draft](https://github.com/haomingkoo/job-hunter-sg/issues/37)
- [#38 Submitted Resume Artifact](https://github.com/haomingkoo/job-hunter-sg/issues/38)
- [#39 Pipeline Board View](https://github.com/haomingkoo/job-hunter-sg/issues/39)
- [#40 SEA-LION Live Smoke Test](https://github.com/haomingkoo/job-hunter-sg/issues/40)
- [#41 MCP Tool Loader](https://github.com/haomingkoo/job-hunter-sg/issues/41)
- [#42 Web Auto-Research Role Brief](https://github.com/haomingkoo/job-hunter-sg/issues/42)
- [#43 Graphify Resume And Dev Evidence Search](https://github.com/haomingkoo/job-hunter-sg/issues/43)
- [#44 Interview Prep Pack](https://github.com/haomingkoo/job-hunter-sg/issues/44)
- [#45 Outcome Learning Signals](https://github.com/haomingkoo/job-hunter-sg/issues/45)

## User Stories

1. As a candidate, I want the system to ingest my past resumes, so that it can understand my actual experience instead of asking me to start from scratch.
2. As a candidate, I want the system to deduplicate similar resume variants, so that repeated files do not distort my capability model.
3. As a candidate, I want the system to identify recurring skills, industries, tools, responsibilities, and outcomes across my resumes, so that I can see my strongest positioning.
4. As a candidate, I want the system to flag weak or unsupported claims, so that I do not accidentally submit inflated resume content.
5. As a candidate, I want the system to interview me about missing evidence, so that important accomplishments, metrics, constraints, and tradeoffs are not lost.
6. As a candidate, I want the system to keep a claim ledger, so that every resume bullet can be traced back to evidence.
7. As a candidate, I want to paste one job description and create one application workspace, so that the agent can focus deeply on that opportunity.
8. As a candidate, I want the system to research similar job titles and role expectations, so that I understand what the market calls this job.
9. As a candidate, I want the system to extract ATS keywords from the job description and similar roles, so that my resume uses relevant language without keyword stuffing.
10. As a candidate, I want the system to compare my evidence against the target role, so that I can see matched strengths, gaps, and risks.
11. As a candidate, I want the system to generate a tailored professional summary, so that my resume opens with a confident but natural positioning statement.
12. As a candidate, I want the system to rewrite bullets using my real experience, so that the final resume is stronger but still defensible.
13. As a candidate, I want the system to preserve exact metrics and reject invented numbers, so that the resume remains accurate.
14. As a candidate, I want the system to ask before using uncertain evidence, so that I can confirm or correct the claim.
15. As a candidate, I want an orchestrator agent to coordinate specialist agents, so that the work feels coherent instead of fragmented.
16. As a candidate, I want a Scout agent to research the role, title, company, job description, and market language, so that the application is grounded in the target opportunity.
17. As a candidate, I want a Strategist agent to propose positioning, so that the resume tells a focused story for the role.
18. As a candidate, I want a Surgeon agent to cut filler and improve bullet clarity, so that the resume is sharper and more readable.
19. As a candidate, I want an ATS agent to check keywords and formatting, so that the resume is parsable and aligned.
20. As a candidate, I want a Skeptic agent to attack vague or inflated claims, so that weak claims are caught before submission.
21. As a candidate, I want an Interview Coach agent to test whether I can defend each claim, so that the resume prepares me for interviews instead of creating risk.
22. As a candidate, I want an Auditor agent to approve or reject the final application pack, so that final output has a clear quality gate.
23. As a candidate, I want agent disagreements to be saved per application, so that I can understand why the system recommended changes.
24. As a candidate, I want debate metadata linked to the exact resume draft being reviewed, so that I can inspect the decision trail later.
25. As a candidate, I want the debate summarized instead of dumped as raw chatter, so that I can read useful disagreements without noise.
26. As a candidate, I want to approve, reject, or edit proposed changes, so that I stay in control of the final resume.
27. As a candidate, I want the final submitted resume saved as structured text, so that the system can analyze what worked.
28. As a candidate, I want the final submitted DOCX/PDF saved, so that I know exactly what was sent.
29. As a candidate, I want a table view of all applications, so that I can track company, role, status, dates, source, follow-up, notes, and outcome.
30. As a candidate, I want a pipeline board view, so that I can see applications moving through saved, applied, screening, interview, assessment, final round, offer, accepted, rejected, withdrawn, and no response.
31. As a candidate, I want status changes to be append-only, so that the system remembers the actual timeline rather than overwriting history.
32. As a candidate, I want stage dates and notes, so that I can prepare follow-ups and interviews on time.
33. As a candidate, I want each application to link to its role brief, resume version, debate round, claim ledger, and interview prep, so that every artifact stays connected.
34. As a candidate, I want interview questions prepared from the job description and my resume, so that I can answer with relevant stories.
35. As a candidate, I want STAR, CAR, and accomplishment-story guidance, so that answers are structured but still natural.
36. As a candidate, I want the system to track which applications got interviews, rejections, offers, or no response, so that it can learn which positioning works.
37. As a candidate, I want the system to rank outcome signals cautiously, so that it does not overclaim that one keyword caused an interview.
38. As a candidate, I want the system to compare successful and unsuccessful applications, so that I can improve future targeting.
39. As a candidate, I want to see which role families are getting traction, so that I can focus my search.
40. As a candidate, I want the system to avoid automatic submission, so that no application is sent without my approval.

## Implementation Decisions

- Build this inside Job Hunter SG, not as a separate product. The existing product already has job search, resume scoring, resume tailoring, application tracking, resume versions, SEA-LION integration, and a Resume Agent v2 foundation.
- Keep `career-kit` as a private evidence workspace if needed. It is not the product home.
- Use a shared application workspace model rather than a rigid conveyor-belt pipeline. Agents collaborate by reading and writing shared artifacts: candidate model, role brief, claim ledger, resume draft, debate board, application pack, interview prep, and status history.
- Use one orchestrator agent. Specialist agents should not run as an unstructured group chat. The orchestrator coordinates tasks, merges critiques, asks the user when evidence is missing, and produces user-visible recommendations.
- Save debate metadata per application. Each debate round must link to the exact resume draft it reviewed.
- Use a claim ledger as the source of truth for resume accuracy. Each claim should be linked to evidence or flagged as needing user confirmation.
- Store final submitted resumes as both structured text and the exact submitted file artifact.
- Track application stages as append-only history. Updating the current status should add a stage event rather than erase prior status movement.
- Preserve the existing table tracker and add a pipeline board as an additional view.
- Build the pipeline board natively using the existing React drag-and-drop dependency already in the product. Focalboard and Taskcafe can be used for product inspiration only, not as embedded dependencies.
- Use official APIs, public pages, or documented job-board endpoints for research where possible. Do not rely on brittle or legally risky automation as the first version.
- Keep user approval boundaries clear. The agent may research, draft, compare, score, critique, and prepare. It must not submit applications, send messages, invent claims, change unsupported metrics, or save a final submitted version without user approval.
- Use SEA-LION through the existing OpenAI-compatible model adapter. Local development must start the backend with the environment file loaded so the model keys are present.
- Keep the first advanced slice focused on one excellent application end-to-end before adding large-scale automation.
- Use the codebase-design vocabulary for architecture work. The key first seam is the application workspace: one module should hide the details of tracked application records, role briefs, resume drafts, debate metadata, claim ledger entries, and stage history behind a small interface. This gives callers leverage and keeps workflow changes local.
- Use the improve-codebase-architecture skill before expanding beyond Phase 1. The target is to avoid a shallow layer that spreads application-workspace behavior across tracker, resume, and agent callers.
- Refactoring the current codebase is allowed when it increases locality for the Application Workspace V1 slice. The refactor should concentrate application-specific behavior that is currently spread across tracker endpoints, resume-version endpoints, and the resume-agent session.

### Architecture Refactor Direction

The first deepening opportunity is an **Application Workspace module**.

Current friction:

- Tracker endpoints manage application status and stage history directly.
- Resume-version endpoints save drafts independently from tracked applications.
- Resume Agent v2 streams critique and pending diffs through in-memory session state.
- Future debate metadata, role briefs, claim ledgers, and submitted artifacts would become scattered if added directly to each caller.

Target module:

```text
ApplicationWorkspace
  create from job description or scraped job
  attach candidate context
  run or record deep-agent review
  save role brief
  save resume draft
  save debate round
  append stage event
  link final submitted resume artifact
```

The module's interface should be small and application-centered. It should hide whether data is stored on tracked jobs, resume versions, JSON fields, future tables, or files. That gives callers leverage and keeps changes local.

Phase 1 can start with the existing tables and JSON fields. New tables should be added only when a JSON field becomes too awkward to query or validate.

## Testing Decisions

- Test behavior at the application workflow level where possible: creating an application, researching a role, generating drafts, saving debate metadata, approving output, and updating status history.
- Existing Resume Agent v2 tests are prior art for deep-agent wiring, tool calls, persona configuration, missing credentials, owner-bound sessions, pending diffs, anti-fabrication gates, and endpoint streaming.
- Existing tracker endpoint tests are prior art for authenticated application tracking.
- Tests should verify that the backend accepts every status shown by the frontend.
- Tests should verify that status movement appends to stage history instead of replacing it.
- Tests should verify that every final submitted resume has both structured content and a linked file artifact.
- Tests should verify that unsupported metrics introduced during rewriting are rejected.
- Tests should verify that debate metadata is saved under the application and linked to the reviewed draft.
- Tests should verify that claim-ledger validation blocks unsupported resume claims from final approval.
- Tests should verify that pipeline-board drag updates the application status through the same backend API as table edits.
- Tests should verify that missing SEA-LION credentials produce a clear user-facing error.
- Tests should avoid asserting internal agent reasoning text. They should assert stable artifacts: role brief, claim ledger entries, debate findings, final verdicts, status history, and saved resume versions.

## Out of Scope

- Automatic job application submission.
- Sending LinkedIn messages, recruiter emails, or cover notes without user approval.
- Private LinkedIn scraping, login bypassing, CAPTCHA bypassing, or scraping behind access controls.
- Full Glassdoor scraping in the first version. Interview question research should start with public and safe sources.
- Replacing the existing tracker with Focalboard, Taskcafe, or another full project-management app.
- Building a full statistical attribution engine that claims exact causality between keywords and interviews.
- Large-scale autonomous application campaigns.
- A polished marketing landing page. The first screen should be a working job-search command center.

## Further Notes

- The current Resume Agent v2 foundation already maps well to the proposed product roles: Scout, Strategist, Surgeon, ATS/Auditor, Skeptic, Interview Coach, and Tracker.
- The immediate technical next step is not another architecture rewrite. It is a vertical slice that proves one application can move from job description to researched role brief, tailored evidence-bound resume, saved debate, approved final artifact, and tracked stage history.
- The existing tracker stage-history change already supports the append-only stage requirement.
- The live deep-agent path needs the backend process to load the SEA-LION environment variables. The keys exist locally, but the process must be started with the environment file.
- The architecture-review skill should be used as a checkpoint before Phase 2, when the candidate evidence graph and web research could otherwise become scattered across unrelated modules.
