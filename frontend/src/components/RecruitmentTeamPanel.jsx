import { useEffect, useMemo, useState } from "react";
import { Activity, Bot, CheckCircle2, ChevronDown, Loader2, Send, Users, XCircle } from "lucide-react";

const EVIDENCE_PAGE_SIZE = 25;

const STATUS_STYLE = {
  running: { icon: Loader2, color: "text-[#88BDF2]" },
  completed: { icon: CheckCircle2, color: "text-emerald-600" },
  failed: { icon: XCircle, color: "text-amber-700" },
  quality_blocked: { icon: XCircle, color: "text-amber-700" },
};

function StatusIcon({ status }) {
  const { icon: Icon, color } = STATUS_STYLE[status] || { icon: Loader2, color: "text-[#6A89A7]" };
  return <Icon size={14} className={`${color} ${status === "running" ? "animate-spin" : ""}`} />;
}

function groupActivityByRun(events) {
  const groups = [];
  const byRunId = new Map();
  for (const item of events) {
    let group = byRunId.get(item.run_id);
    if (!group) {
      group = { runId: item.run_id, coordinatorEvents: [], memberEvents: [] };
      byRunId.set(item.run_id, group);
      groups.push(group);
    }
    if (item.team_member === "coordinator") {
      group.coordinatorEvents.push(item);
    } else {
      group.memberEvents.push(item);
    }
  }
  return groups;
}

import { apiFetch } from "../lib/api.js";
import { streamRecruitmentCommand } from "../lib/recruitmentTeamApi.js";


function storedThreadKey(userId) {
  return `jobhunter:recruitment-thread:${userId}`;
}


export default function RecruitmentTeamPanel({ user }) {
  const [resumeVersions, setResumeVersions] = useState([]);
  const [resumeVersionId, setResumeVersionId] = useState("");
  const [threadId, setThreadId] = useState(
    () => localStorage.getItem(storedThreadKey(user.id)) || "",
  );
  const [snapshot, setSnapshot] = useState(null);
  const [events, setEvents] = useState([]);
  const [candidateProfile, setCandidateProfile] = useState(null);
  const [targetAssessment, setTargetAssessment] = useState(null);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [visibleProfileCount, setVisibleProfileCount] = useState(EVIDENCE_PAGE_SIZE);
  const [visibleCriteriaCount, setVisibleCriteriaCount] = useState(EVIDENCE_PAGE_SIZE);

  const selectedResume = useMemo(
    () => resumeVersions.find((resume) => String(resume.id) === String(resumeVersionId)),
    [resumeVersionId, resumeVersions],
  );
  const recommendations = snapshot?.case_facts?.recommendations || [];
  const shortlistedJobs = snapshot?.case_facts?.shortlisted_jobs || [];
  const displayedJobs = [
    ...recommendations,
    ...shortlistedJobs.filter(
      (savedJob) => !recommendations.some((job) => job.job_id === savedJob.job_id),
    ),
  ];
  const shortlistedJobIds = new Set(snapshot?.case_facts?.shortlisted_job_ids || []);
  const selectedTargetId = snapshot?.case_facts?.selected_target?.job_id;
  const roleProfile = snapshot?.case_facts?.role_success_profile;
  const candidateProfileFields = useMemo(
    () => [...(candidateProfile?.profile?.fields || [])].sort(
      (a, b) => (b.evidence_support_score ?? 0) - (a.evidence_support_score ?? 0),
    ),
    [candidateProfile],
  );
  const visibleProfileFields = candidateProfileFields.slice(0, visibleProfileCount);
  const roleSources = new Map(
    (roleProfile?.sources || []).map((source) => [source.source_id, source]),
  );
  const candidateEvidence = new Map(
    (roleProfile?.candidate_evidence || []).map((item) => [item.criterion_id, item]),
  );
  const resumeEvidence = new Map(
    (roleProfile?.cited_resume_evidence || []).map((item) => [item.evidence_id, item]),
  );

  function appendActivity(activityEvent) {
    setEvents((current) => (
      current.some((item) => item.sequence === activityEvent.sequence)
        ? current
        : [...current, activityEvent]
    ));
  }

  async function refreshThread(id) {
    const [snapshotResponse, eventResponse] = await Promise.all([
      apiFetch(`/api/recruitment-team/threads/${id}`),
      apiFetch(`/api/recruitment-team/threads/${id}/events`),
    ]);
    const [nextSnapshot, nextEvents] = await Promise.all([
      snapshotResponse.json(),
      eventResponse.json(),
    ]);
    setSnapshot(nextSnapshot);
    setEvents(nextEvents);
    if (nextSnapshot.case_facts?.candidate_profile_artifact_id) {
      const profileResponse = await apiFetch(
        `/api/recruitment-team/threads/${id}/candidate-profile`,
      );
      setCandidateProfile(await profileResponse.json());
    } else {
      setCandidateProfile(null);
    }
    if (nextSnapshot.case_facts?.target_assessment_artifact_id) {
      const assessmentResponse = await apiFetch(
        `/api/recruitment-team/threads/${id}/assessment`,
      );
      setTargetAssessment(await assessmentResponse.json());
    } else {
      setTargetAssessment(null);
    }
  }

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const response = await apiFetch("/api/resume/versions");
        const versions = await response.json();
        if (cancelled) return;
        setResumeVersions(versions);
        const master = versions.find((resume) => resume.is_master) || versions[0];
        if (master) setResumeVersionId(String(master.id));
      } catch (loadError) {
        if (!cancelled) setError(loadError.message);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (!threadId) return undefined;
    let cancelled = false;
    refreshThread(threadId).catch((loadError) => {
      if (!cancelled) setError(loadError.message);
    });
    return () => { cancelled = true; };
  }, [threadId]);

  useEffect(() => {
    if (threadId) return undefined;
    let cancelled = false;
    (async () => {
      try {
        const response = await apiFetch("/api/recruitment-team/threads");
        const threads = await response.json();
        if (cancelled || !threads.length) return;
        const nextThreadId = threads[0].thread_id;
        localStorage.setItem(storedThreadKey(user.id), nextThreadId);
        setThreadId(nextThreadId);
      } catch (loadError) {
        if (!cancelled) setError(loadError.message);
      }
    })();
    return () => { cancelled = true; };
  }, [threadId, user.id]);

  async function submit(event) {
    event.preventDefault();
    const text = message.trim();
    if (!text || busy) return;
    if (!threadId && !resumeVersionId) {
      setError("Save or select a resume before starting the recruitment team.");
      return;
    }

    setBusy(true);
    setError("");
    try {
      const idempotencyKey = globalThis.crypto.randomUUID();
      const receipt = threadId
        ? await streamRecruitmentCommand(
          `/api/recruitment-team/threads/${threadId}/messages/stream`,
          { message: text, idempotency_key: idempotencyKey },
          appendActivity,
        )
        : await streamRecruitmentCommand(
          "/api/recruitment-team/threads/stream",
          {
            resume_version_id: Number(resumeVersionId),
            message: text,
            idempotency_key: idempotencyKey,
          },
          appendActivity,
        );
      const nextThreadId = receipt.thread_id;
      localStorage.setItem(storedThreadKey(user.id), nextThreadId);
      setMessage("");
      if (nextThreadId !== threadId) setThreadId(nextThreadId);
      await refreshThread(nextThreadId);
    } catch (submitError) {
      setError(submitError.message);
    } finally {
      setBusy(false);
    }
  }

  async function searchCurrentJobs() {
    const query = message.trim();
    if (!threadId || !query || busy) return;
    setBusy(true);
    setError("");
    try {
      await streamRecruitmentCommand(
        `/api/recruitment-team/threads/${threadId}/jobs/search/stream`,
        { query, idempotency_key: globalThis.crypto.randomUUID() },
        appendActivity,
      );
      setMessage("");
      await refreshThread(threadId);
    } catch (searchError) {
      setError(searchError.message);
    } finally {
      setBusy(false);
    }
  }

  async function studyResume() {
    if (!threadId || busy) return;
    setBusy(true);
    setError("");
    try {
      await streamRecruitmentCommand(
        `/api/recruitment-team/threads/${threadId}/candidate-profile/stream`,
        { idempotency_key: globalThis.crypto.randomUUID() },
        appendActivity,
      );
      await refreshThread(threadId);
    } catch (profileError) {
      setError(profileError.message);
      await refreshThread(threadId);
    } finally {
      setBusy(false);
    }
  }

  async function assessTarget() {
    if (!threadId || busy) return;
    setBusy(true);
    setError("");
    try {
      await streamRecruitmentCommand(
        `/api/recruitment-team/threads/${threadId}/assessment/stream`,
        { idempotency_key: globalThis.crypto.randomUUID() },
        appendActivity,
      );
      await refreshThread(threadId);
    } catch (assessmentError) {
      setError(assessmentError.message);
      await refreshThread(threadId);
    } finally {
      setBusy(false);
    }
  }

  async function updateJob(path) {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      await apiFetch(path, {
        method: "POST",
        body: JSON.stringify({ idempotency_key: globalThis.crypto.randomUUID() }),
      });
      await refreshThread(threadId);
    } catch (actionError) {
      setError(actionError.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section aria-labelledby="recruitment-team-title" className="space-y-5">
      <header className="rounded-3xl bg-[#384959] px-6 py-6 text-white sm:px-8">
        <div className="flex items-center gap-3">
          <div className="rounded-2xl bg-white/10 p-3"><Users size={22} /></div>
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-[#BDDDFC]">V3</p>
            <h1 id="recruitment-team-title" className="text-2xl font-semibold">AI Recruitment Team</h1>
          </div>
        </div>
        <p className="mt-4 max-w-2xl text-sm leading-relaxed text-[#dbeaf8]">
          Explore your next move with a persistent team that preserves evidence and shows real activity.
        </p>
      </header>

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_22rem]">
        <div className="rounded-3xl border border-[#BDDDFC]/40 bg-white p-5 shadow-sm">
          {!threadId && (
            <label className="mb-5 block text-sm font-medium text-[#384959]">
              Resume evidence
              <select
                value={resumeVersionId}
                onChange={(event) => setResumeVersionId(event.target.value)}
                className="mt-2 w-full rounded-xl border border-[#BDDDFC] bg-white px-3 py-2 text-sm"
              >
                {resumeVersions.length === 0 && <option value="">No saved resumes</option>}
                {resumeVersions.map((resume) => (
                  <option key={resume.id} value={resume.id}>{resume.label}</option>
                ))}
              </select>
            </label>
          )}

          <div className="min-h-72 space-y-3" aria-live="polite">
            {snapshot?.messages?.map((item, index) => (
              <div
                key={`${item.run_id || index}:${item.role}`}
                className={`max-w-[90%] whitespace-pre-wrap rounded-2xl px-4 py-3 text-sm leading-relaxed ${
                  item.role === "user"
                    ? "ml-auto bg-[#384959] text-white"
                    : "bg-[#f0f5fa] text-[#384959]"
                }`}
              >
                {item.content}
              </div>
            ))}
            {!snapshot?.messages?.length && (
              <div className="flex min-h-56 flex-col items-center justify-center text-center text-[#6A89A7]">
                <Bot size={28} />
                <p className="mt-3 text-sm">Tell the team what kind of work you want next.</p>
                {selectedResume && <p className="mt-1 text-xs">Starting from {selectedResume.label}</p>}
              </div>
            )}
          </div>

          {error && <p role="alert" className="mt-3 text-sm text-red-700">{error}</p>}
          <form onSubmit={submit} className="mt-4 flex items-end gap-2">
            <textarea
              value={message}
              onChange={(event) => setMessage(event.target.value)}
              rows={2}
              placeholder="Describe your target role, constraints, or follow-up..."
              className="min-h-12 flex-1 resize-y rounded-2xl border border-[#BDDDFC] px-4 py-3 text-sm text-[#384959] focus:outline-none focus:ring-2 focus:ring-[#88BDF2]"
            />
            <button
              type="submit"
              disabled={busy || !message.trim()}
              className="inline-flex h-12 items-center gap-2 rounded-2xl bg-[#384959] px-4 text-sm font-semibold text-white disabled:opacity-40"
            >
              <Send size={15} />
              {busy ? "Working" : "Send"}
            </button>
            {threadId && (
              <button
                type="button"
                onClick={searchCurrentJobs}
                disabled={busy || !message.trim()}
                className="h-12 rounded-2xl border border-[#384959] px-4 text-sm font-semibold text-[#384959] disabled:opacity-40"
              >
                Search jobs
              </button>
            )}
            {threadId && (
              <button
                type="button"
                onClick={studyResume}
                disabled={busy || candidateProfile?.status === "completed"}
                className="h-12 rounded-2xl border border-[#384959] px-4 text-sm font-semibold text-[#384959] disabled:opacity-40"
              >
                {candidateProfile?.status === "failed" ? "Resume profile" : "Study resume"}
              </button>
            )}
          </form>

          {candidateProfile && (
            <section aria-labelledby="candidate-profile-title" className="mt-6 border-t border-[#BDDDFC]/50 pt-5">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <h2 id="candidate-profile-title" className="text-sm font-semibold text-[#384959]">
                    Candidate Evidence Profile
                  </h2>
                  <p className="mt-1 text-xs text-[#6A89A7]">
                    {candidateProfile.prompt_version} · {candidateProfile.decomposition_version}
                  </p>
                  {candidateProfile.execution_policy && (
                    <p className="mt-1 text-xs text-[#6A89A7]">
                      {candidateProfile.model_name} · {candidateProfile.execution_policy.model_timeout_seconds}s timeout ·{" "}
                      {candidateProfile.execution_policy.validation_attempts} validation attempts ·{" "}
                      {candidateProfile.execution_policy.transport_retries} transport retries
                    </p>
                  )}
                </div>
                <span className="rounded-full bg-[#f0f5fa] px-2 py-1 text-xs capitalize text-[#384959]">
                  {candidateProfile.status}
                </span>
              </div>
              {candidateProfile.status === "failed" && candidateProfile.error && (
                <div className="mt-3 rounded-2xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
                  Profile paused at {candidateProfile.error.failed_scope_id || "an unreported scope"}.
                  {candidateProfile.error.recovery ? ` ${candidateProfile.error.recovery}` : ""}
                </div>
              )}
              {candidateProfileFields.length > 0 && (
                <>
                  <p className="mt-3 text-xs text-[#6A89A7]">
                    Showing {visibleProfileFields.length} of {candidateProfileFields.length} fields, strongest evidence first.
                  </p>
                  <div className="mt-2 space-y-3">
                    {visibleProfileFields.map((field) => (
                      <article key={field.field_id} className="rounded-2xl border border-[#BDDDFC]/60 p-4">
                        <div className="flex flex-wrap items-start justify-between gap-2">
                          <p className="font-medium text-[#384959]">{field.statement}</p>
                          <span className="rounded-full bg-[#f0f5fa] px-2 py-1 text-xs capitalize text-[#384959]">
                            {field.category.replaceAll("_", " ")}
                          </span>
                        </div>
                        <p className="mt-1 text-xs text-[#6A89A7]">
                          Raw evidence support {field.evidence_support_score}/100 · {field.evidence_kind.replaceAll("_", " ")}
                        </p>
                        <p className="mt-2 text-sm text-[#6A89A7]">{field.score_reason}</p>
                        {(field.evidence_quotes || []).map((quote, index) => (
                          <blockquote key={`${field.field_id}:${index}`} className="mt-2 border-l-2 border-[#BDDDFC] pl-3 text-xs text-[#6A89A7]">
                            “{quote}”
                          </blockquote>
                        ))}
                      </article>
                    ))}
                  </div>
                  {visibleProfileCount < candidateProfileFields.length && (
                    <button
                      type="button"
                      onClick={() => setVisibleProfileCount((count) => count + EVIDENCE_PAGE_SIZE)}
                      className="mt-3 flex w-full items-center justify-center gap-1 rounded-xl border border-[#BDDDFC] py-2 text-xs font-medium text-[#384959] hover:bg-[#f0f5fa]"
                    >
                      <ChevronDown size={14} />
                      Show {Math.min(EVIDENCE_PAGE_SIZE, candidateProfileFields.length - visibleProfileCount)} more
                    </button>
                  )}
                </>
              )}
            </section>
          )}

          {displayedJobs.length > 0 && (
            <section aria-labelledby="recommended-jobs-title" className="mt-6 border-t border-[#BDDDFC]/50 pt-5">
              <h2 id="recommended-jobs-title" className="text-sm font-semibold text-[#384959]">
                Current source-backed matches
              </h2>
              <div className="mt-3 space-y-3">
                {displayedJobs.map((job) => {
                  const shortlisted = shortlistedJobIds.has(job.job_id);
                  const selected = selectedTargetId === job.job_id;
                  const variants = job.posting_variants || [];
                  return (
                    <article key={job.job_id} className="rounded-2xl border border-[#BDDDFC]/60 p-4">
                      <div className="flex flex-wrap items-start justify-between gap-3">
                        <div>
                          <h3 className="font-semibold text-[#384959]">{job.title}</h3>
                          <p className="text-sm text-[#6A89A7]">{job.company} · {job.location}</p>
                        </div>
                        <span className="rounded-full bg-[#f0f5fa] px-2 py-1 text-xs text-[#384959]">
                          {selected ? "Selected target" : shortlisted ? "Shortlisted" : job.source.availability}
                        </span>
                      </div>
                      <p className="mt-2 text-sm text-[#384959]">
                        {job.salary || "Salary not stated"} · {job.seniority || "Seniority not stated"}
                      </p>
                      <p className="mt-1 text-xs text-[#6A89A7]">
                        {job.source.source} · posted {job.source.posted_date || "date unavailable"}
                        {job.source.closing_date ? ` · closes ${job.source.closing_date}` : ""}
                        {variants.length > 1 ? ` · ${variants.length} posting variants retained` : ""}
                      </p>
                      <div className="mt-3 flex flex-wrap gap-2">
                        <a
                          href={job.source.url}
                          target="_blank"
                          rel="noreferrer"
                          className="rounded-xl border border-[#BDDDFC] px-3 py-2 text-xs font-medium text-[#384959]"
                        >
                          View source
                        </a>
                        {!shortlisted && (
                          <button
                            type="button"
                            onClick={() => updateJob(`/api/recruitment-team/threads/${threadId}/jobs/${job.job_id}/shortlist`)}
                            className="rounded-xl border border-[#BDDDFC] px-3 py-2 text-xs font-medium text-[#384959]"
                          >
                            Shortlist
                          </button>
                        )}
                        {!selected && (
                          <button
                            type="button"
                            onClick={() => updateJob(`/api/recruitment-team/threads/${threadId}/jobs/${job.job_id}/select`)}
                            className="rounded-xl bg-[#384959] px-3 py-2 text-xs font-medium text-white"
                          >
                            Select target
                          </button>
                        )}
                      </div>
                    </article>
                  );
                })}
              </div>
            </section>
          )}

          {roleProfile && (
            <section aria-labelledby="role-success-title" className="mt-6 border-t border-[#BDDDFC]/50 pt-5">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <h2 id="role-success-title" className="text-sm font-semibold text-[#384959]">
                    Role Success Profile
                  </h2>
                  <p className="mt-1 text-xs text-[#6A89A7]">
                    Selected job: primary evidence · taxonomy match: {roleProfile.source_coverage.taxonomy_match_quality}
                    {roleProfile.assessment_disposition ? ` · assessment ${roleProfile.assessment_disposition.replaceAll("_", " ")}` : ""}
                  </p>
                </div>
                <span className="rounded-full bg-[#f0f5fa] px-2 py-1 text-xs text-[#384959]">
                  {roleProfile.criteria.length} criteria
                </span>
              </div>
              {roleProfile.criteria.length > visibleCriteriaCount && (
                <p className="mt-3 text-xs text-[#6A89A7]">
                  Showing {Math.min(visibleCriteriaCount, roleProfile.criteria.length)} of {roleProfile.criteria.length} criteria.
                </p>
              )}
              <div className="mt-3 space-y-3">
                {roleProfile.criteria.slice(0, visibleCriteriaCount).map((criterion) => {
                  const evidence = candidateEvidence.get(criterion.criterion_id);
                  return (
                    <article key={criterion.criterion_id} className="rounded-2xl border border-[#BDDDFC]/60 p-4">
                      <div className="flex flex-wrap items-start justify-between gap-2">
                        <p className="font-medium text-[#384959]">{criterion.statement}</p>
                        <span className="rounded-full bg-[#f0f5fa] px-2 py-1 text-xs capitalize text-[#384959]">
                          {evidence?.alignment || "unknown"}
                        </span>
                      </div>
                      <p className="mt-1 text-xs capitalize text-[#6A89A7]">
                        {criterion.category.replaceAll("_", " ")} · {criterion.requirement_level}
                        {criterion.alternative_group_id ? " · alternative requirement" : ""}
                        {evidence?.evidence_support_score != null
                          ? ` · raw evidence support ${evidence.evidence_support_score}/100`
                          : evidence ? ` · raw evidence confidence ${Math.round(evidence.confidence * 100)}%` : ""}
                      </p>
                      {evidence?.supported_strength ? (
                        <p className="mt-2 text-sm text-[#384959]">
                          <span className="font-medium">Strength: </span>{evidence.supported_strength}
                        </p>
                      ) : evidence && <p className="mt-2 text-sm text-[#384959]">{evidence.explanation}</p>}
                      {evidence?.remaining_gap && !["none", "none.", "n/a", "not applicable"].includes(evidence.remaining_gap.toLowerCase()) && (
                        <p className="mt-1 text-sm text-[#6A89A7]">
                          <span className="font-medium">Gap: </span>{evidence.remaining_gap}
                        </p>
                      )}
                      {(criterion.source_citations || []).map((citation) => (
                        <blockquote key={`${criterion.criterion_id}-${citation.source_id}`} className="mt-2 border-l-2 border-[#88BDF2] pl-3 text-xs text-[#6A89A7]">
                          {citation.source_path}: “{citation.relevant_excerpt}”
                        </blockquote>
                      ))}
                      {(evidence?.resume_evidence_ids || []).map((evidenceId) => {
                        const record = resumeEvidence.get(evidenceId);
                        return record ? (
                          <blockquote key={evidenceId} className="mt-2 border-l-2 border-[#BDDDFC] pl-3 text-xs text-[#6A89A7]">
                            Resume {record.source_locator}: “{record.text}”
                          </blockquote>
                        ) : null;
                      })}
                      <div className="mt-2 flex flex-wrap gap-2 text-xs">
                        {criterion.source_ids.map((sourceId) => {
                          const source = roleSources.get(sourceId);
                          if (!source) return <span key={sourceId}>{sourceId}</span>;
                          return source.url ? (
                            <a
                              key={sourceId}
                              href={source.url}
                              target="_blank"
                              rel="noreferrer"
                              className="text-[#384959] underline decoration-[#88BDF2] underline-offset-2"
                            >
                              {source.title} ({source.evidence_strength})
                            </a>
                          ) : <span key={sourceId}>{source.title} ({source.evidence_strength})</span>;
                        })}
                      </div>
                    </article>
                  );
                })}
              </div>
              {visibleCriteriaCount < roleProfile.criteria.length && (
                <button
                  type="button"
                  onClick={() => setVisibleCriteriaCount((count) => count + EVIDENCE_PAGE_SIZE)}
                  className="mt-3 flex w-full items-center justify-center gap-1 rounded-xl border border-[#BDDDFC] py-2 text-xs font-medium text-[#384959] hover:bg-[#f0f5fa]"
                >
                  <ChevronDown size={14} />
                  Show {Math.min(EVIDENCE_PAGE_SIZE, roleProfile.criteria.length - visibleCriteriaCount)} more
                </button>
              )}
              {roleProfile.clarification_question && (
                <div className="mt-3 rounded-2xl bg-[#f0f5fa] p-4 text-sm text-[#384959]">
                  <span className="font-semibold">Focused clarification: </span>
                  {roleProfile.clarification_question}
                </div>
              )}
              {(roleProfile.validation_notes || []).length > 0 && (
                <div className="mt-3 text-xs text-[#6A89A7]">
                  Citation validation: {roleProfile.validation_notes.join(" ")}
                </div>
              )}
              {(roleProfile.policy_constraints || []).length > 0 && (
                <div className="mt-3 text-xs text-[#6A89A7]">
                  Assessment policy: {roleProfile.policy_constraints.map((item) => item.statement).join(" ")}
                </div>
              )}
            </section>
          )}

          {roleProfile && (
            <section aria-labelledby="target-assessment-title" className="mt-6 border-t border-[#BDDDFC]/50 pt-5">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <h2 id="target-assessment-title" className="text-sm font-semibold text-[#384959]">
                    Target assessment
                  </h2>
                  <p className="mt-1 text-xs text-[#6A89A7]">
                    Five isolated evidence reviews, synthesis, then an independent quality judgment.
                  </p>
                </div>
                <button
                  type="button"
                  onClick={assessTarget}
                  disabled={busy || targetAssessment?.status === "completed"}
                  className="rounded-xl bg-[#384959] px-3 py-2 text-xs font-medium text-white disabled:opacity-40"
                >
                  {targetAssessment?.status === "completed" ? "Assessment complete" : targetAssessment ? "Run assessment again" : "Run assessment"}
                </button>
              </div>
              {targetAssessment && (
                <div className="mt-4 space-y-3">
                  <div className="rounded-2xl border border-[#BDDDFC]/60 p-4 text-xs text-[#6A89A7]">
                    <p className="font-medium capitalize text-[#384959]">{targetAssessment.status.replaceAll("_", " ")}</p>
                    <p className="mt-1">
                      {targetAssessment.execution_policy.persona_pack_version} ·{" "}
                      {targetAssessment.execution_policy.specialist_max_concurrency} max concurrent specialists ·{" "}
                      {targetAssessment.execution_policy.specialist_validation_attempts} specialist validation attempts ·{" "}
                      {targetAssessment.execution_policy.synthesis_validation_attempts} synthesis validation attempts ·{" "}
                      {targetAssessment.execution_policy.judge_validation_attempts} judge validation attempts ·{" "}
                      {targetAssessment.execution_policy.transport_retries} transport retries · no fallback model · no content truncation
                    </p>
                  </div>
                  {(targetAssessment.specialist_runs || []).map((run) => (
                    <article key={run.persona_id} className="rounded-2xl border border-[#BDDDFC]/60 p-4">
                      <div className="flex items-center justify-between gap-2">
                        <h3 className="text-sm font-semibold capitalize text-[#384959]">
                          {run.persona_id.replaceAll("_", " ")}
                        </h3>
                        <span className="rounded-full bg-[#f0f5fa] px-2 py-1 text-xs capitalize text-[#384959]">
                          {run.status}
                        </span>
                      </div>
                      {run.submission ? (
                        <>
                          <p className="mt-2 text-sm text-[#384959]">{run.submission.summary}</p>
                          <p className="mt-2 text-xs text-[#6A89A7]">
                            Raw evidence support {run.submission.score}/100 · {run.submission.score_reason}
                          </p>
                        </>
                      ) : (
                        <p className="mt-2 text-xs text-amber-800">
                          {run.failure_type || "unknown"} failure · attempts {run.attempt_count || 0}
                        </p>
                      )}
                    </article>
                  ))}
                  {targetAssessment.synthesis && (
                    <article className="whitespace-pre-wrap rounded-2xl border border-[#BDDDFC]/60 p-4 text-sm text-[#384959]">
                      {targetAssessment.synthesis}
                    </article>
                  )}
                  {targetAssessment.judge && (
                    <article className="rounded-2xl border border-[#BDDDFC]/60 p-4">
                      <h3 className="text-sm font-semibold text-[#384959]">Independent quality judge</h3>
                      <p className="mt-2 text-sm text-[#384959]">
                        {targetAssessment.judge.disposition} · output quality {targetAssessment.judge.score}/100 · confidence {targetAssessment.judge.confidence}/100
                      </p>
                      <p className="mt-2 text-xs text-[#6A89A7]">
                        Score reason: {targetAssessment.judge.score_reason}
                      </p>
                      <p className="mt-1 text-xs text-[#6A89A7]">
                        Confidence basis: {targetAssessment.judge.confidence_reason}
                      </p>
                      {(targetAssessment.judge.strengths || []).map((strength) => (
                        <p key={strength} className="mt-2 text-xs text-emerald-800">Strength: {strength}</p>
                      ))}
                      {(targetAssessment.judge.weaknesses || []).map((weakness) => (
                        <p key={weakness} className="mt-2 text-xs text-amber-800">Weakness: {weakness}</p>
                      ))}
                      {(targetAssessment.judge.evidence_gaps || []).map((gap) => (
                        <p key={gap} className="mt-2 text-xs text-amber-800">Evidence gap: {gap}</p>
                      ))}
                      {targetAssessment.judge.rubric_scores && (
                        <dl className="mt-3 grid gap-2 sm:grid-cols-2">
                          {Object.entries(targetAssessment.judge.rubric_scores).map(([rubric, score]) => (
                            <div key={rubric} className="rounded-xl bg-[#f0f5fa] px-3 py-2">
                              <dt className="text-xs capitalize text-[#6A89A7]">{rubric.replaceAll("_", " ")}</dt>
                              <dd className="text-sm font-semibold text-[#384959]">{score}/100</dd>
                            </div>
                          ))}
                        </dl>
                      )}
                      {(targetAssessment.judge.deductions || []).map((deduction) => (
                        <p key={`${deduction.rubric}:${deduction.reason}`} className="mt-2 text-xs text-amber-800">
                          Deduction · {deduction.rubric.replaceAll("_", " ")} · {deduction.points} points: {deduction.reason}
                        </p>
                      ))}
                    </article>
                  )}
                  {targetAssessment.correction?.attempted && (
                    <p className="rounded-2xl border border-[#BDDDFC]/60 p-4 text-xs text-[#6A89A7]">
                      The first synthesis was rejected and one targeted correction was judged independently.
                    </p>
                  )}
                  {targetAssessment.error && (
                    <p className="rounded-2xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
                      {targetAssessment.error.message || targetAssessment.error.error_type}
                    </p>
                  )}
                </div>
              )}
            </section>
          )}
        </div>

        <aside className="rounded-3xl border border-[#BDDDFC]/40 bg-[#f5f8fb] p-5">
          <div className="flex items-center gap-2 text-sm font-semibold text-[#384959]">
            <Activity size={16} /> Team activity
          </div>
          <p className="mt-1 text-xs text-[#6A89A7]">
            Real workflow events, not hidden reasoning.
          </p>
          <ol className="mt-4 space-y-3">
            {groupActivityByRun(events).map((group) => {
              const trunk = group.coordinatorEvents[group.coordinatorEvents.length - 1];
              const branches = group.memberEvents;
              return (
                <li key={group.runId} className="rounded-2xl bg-white p-3 text-sm shadow-sm">
                  {trunk && (
                    <div className="flex items-center justify-between gap-2">
                      <span className="flex items-center gap-1.5 font-medium capitalize text-[#384959]">
                        <StatusIcon status={trunk.status} /> {trunk.team_member}
                      </span>
                      <span className="text-xs capitalize text-[#6A89A7]">{trunk.status}</span>
                    </div>
                  )}
                  {trunk && <p className="mt-1 leading-relaxed text-[#6A89A7]">{trunk.summary}</p>}
                  {branches.length > 0 && (
                    <ol className={`space-y-2 ${trunk ? "mt-3 border-l-2 border-[#BDDDFC]/70 pl-3" : ""}`}>
                      {branches.map((branch) => (
                        <li key={branch.sequence} className="rounded-xl bg-[#f5f8fb] px-3 py-2">
                          <div className="flex items-center justify-between gap-2">
                            <span className="flex items-center gap-1.5 text-xs font-semibold capitalize text-[#384959]">
                              <StatusIcon status={branch.status} /> {branch.team_member.replaceAll("_", " ")}
                            </span>
                            <span className="text-[11px] capitalize text-[#6A89A7]">{branch.status}</span>
                          </div>
                          <p className="mt-1 text-xs leading-relaxed text-[#6A89A7]">{branch.summary}</p>
                        </li>
                      ))}
                    </ol>
                  )}
                </li>
              );
            })}
            {events.length === 0 && (
              <li className="text-sm text-[#6A89A7]">Activity will appear after your first message.</li>
            )}
          </ol>
        </aside>
      </div>
    </section>
  );
}
