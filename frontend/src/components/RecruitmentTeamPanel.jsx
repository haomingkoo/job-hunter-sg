import { useEffect, useMemo, useRef, useState } from "react";
import { Archive, Bot, ChevronDown, MessageSquare, Pencil, RotateCcw, Send, Trash2, Users, X } from "lucide-react";

const EVIDENCE_PAGE_SIZE = 25;
const THREAD_REFRESH_POLL_INTERVAL_MS = 1500;
const THREAD_TITLE_MAX_CHARS = 120;
const JOB_FEEDBACK_REASON_MAX_CHARS = 500;

import TeamActivityPanel from "./TeamActivityPanel.jsx";
import SpecialistReport from "./SpecialistReport.jsx";
import ProposedEditsPanel from "./ProposedEditsPanel.jsx";
import AiServiceStatus from "./AiServiceStatus.jsx";
import { apiFetch } from "../lib/api.js";
import { normalizeActivityEvents } from "../lib/recruitmentActivity.js";
import { streamRecruitmentCommand } from "../lib/recruitmentTeamApi.js";


function storedThreadKey(userId) {
  return `jobhunter:recruitment-thread:${userId}`;
}

function pendingResumeKey(userId) {
  return `jobhunter:pending-resume-version:${userId}`;
}


function formatMetricNumber(value) {
  return new Intl.NumberFormat("en-SG").format(Number(value) || 0);
}


function metricCount(value, singular) {
  const count = Number(value) || 0;
  return `${formatMetricNumber(count)} ${count === 1 ? singular : `${singular}s`}`;
}


export function ExecutionDetails({ metrics }) {
  if (!metrics || Object.keys(metrics).length === 0) return null;

  const roleMetrics = Object.entries(metrics.transport_by_role || {});
  const models = metrics.models || [];
  const validationCodes = metrics.validation_codes || [];
  const hasSeparateUsageMetrics = Object.hasOwn(metrics, "reported_model_call_count");
  const transportCallCountAvailable = Object.hasOwn(metrics, "transport_call_count");
  const transportTokenUsageAvailable = metrics.transport_token_usage_available === true;
  const transportRetryCountAvailable = Object.hasOwn(metrics, "transport_retry_count");
  const transportErrorCountAvailable = Object.hasOwn(metrics, "transport_error_count");

  return (
    <details className="rounded-xl border border-[#DCE7F2] bg-[#FAFCFE] px-3 py-2 text-xs text-[#4A6785]">
      <summary className="cursor-pointer font-medium text-[#384959] focus:outline-none focus-visible:ring-2 focus-visible:ring-[#88BDF2]">
        Execution details
      </summary>
      <dl className="mt-3 grid gap-x-4 gap-y-2 sm:grid-cols-2">
        {hasSeparateUsageMetrics ? (
          <>
            <div>
              <dt>Workflow-reported calls</dt>
              <dd className="font-semibold text-[#384959]">{formatMetricNumber(metrics.reported_model_call_count)}</dd>
            </div>
            <div>
              <dt>Transport-observed calls</dt>
              <dd className="font-semibold text-[#384959]">
                {transportCallCountAvailable
                  ? formatMetricNumber(metrics.transport_call_count)
                  : "Unavailable"}
              </dd>
            </div>
          </>
        ) : (
          <div>
            <dt>Model calls</dt>
            <dd className="font-semibold text-[#384959]">{formatMetricNumber(metrics.model_call_count)}</dd>
          </div>
        )}
        <div>
          <dt>Run time</dt>
          <dd className="font-semibold text-[#384959]">
            {formatMetricNumber(Math.round((Number(metrics.latency_ms) || 0) / 1000))} seconds
          </dd>
        </div>
        {hasSeparateUsageMetrics ? (
          <>
            <div>
              <dt>Workflow-reported input tokens</dt>
              <dd className="font-semibold text-[#384959]">{formatMetricNumber(metrics.reported_input_tokens)}</dd>
            </div>
            <div>
              <dt>Transport-observed input tokens</dt>
              <dd className="font-semibold text-[#384959]">
                {transportTokenUsageAvailable
                  ? formatMetricNumber(metrics.transport_input_tokens)
                  : "Unavailable"}
              </dd>
            </div>
            <div>
              <dt>Workflow-reported output tokens</dt>
              <dd className="font-semibold text-[#384959]">{formatMetricNumber(metrics.reported_output_tokens)}</dd>
            </div>
            <div>
              <dt>Transport-observed output tokens</dt>
              <dd className="font-semibold text-[#384959]">
                {transportTokenUsageAvailable
                  ? formatMetricNumber(metrics.transport_output_tokens)
                  : "Unavailable"}
              </dd>
            </div>
          </>
        ) : (
          <>
            <div>
              <dt>Input tokens</dt>
              <dd className="font-semibold text-[#384959]">{formatMetricNumber(metrics.input_tokens)}</dd>
            </div>
            <div>
              <dt>Output tokens</dt>
              <dd className="font-semibold text-[#384959]">{formatMetricNumber(metrics.output_tokens)}</dd>
            </div>
          </>
        )}
        <div>
          <dt>Transport retries</dt>
          <dd className="font-semibold text-[#384959]">
            {transportRetryCountAvailable
              ? formatMetricNumber(metrics.transport_retry_count)
              : "Unavailable"}
          </dd>
        </div>
        <div>
          <dt>Transport errors</dt>
          <dd className="font-semibold text-[#384959]">
            {transportErrorCountAvailable
              ? formatMetricNumber(metrics.transport_error_count)
              : "Unavailable"}
          </dd>
        </div>
      </dl>
      {models.length > 0 && (
        <p className="mt-3">
          <span className="font-medium text-[#384959]">Models: </span>
          {models.join(", ")}
        </p>
      )}
      {roleMetrics.length > 0 && (
        <div className="mt-3">
          <p className="font-medium text-[#384959]">Calls by team member</p>
          <ul className="mt-1 space-y-1">
            {roleMetrics.map(([role, values]) => (
              <li key={role}>
                <span className="capitalize">{role.replaceAll("_", " ")}</span>: {metricCount(values.call_count, "call")}
                {Number(values.retry_count) > 0 ? `, ${metricCount(values.retry_count, "retry")}` : ""}
                {Number(values.error_count) > 0 ? `, ${metricCount(values.error_count, "error")}` : ""}
              </li>
            ))}
          </ul>
        </div>
      )}
      {validationCodes.length > 0 && (
        <p className="mt-3">
          <span className="font-medium text-[#384959]">Validation flags: </span>
          {validationCodes.join(", ")}
        </p>
      )}
    </details>
  );
}


export default function RecruitmentTeamPanel({
  user,
  setActiveTab,
  onOpenApplication,
  onTailorJob,
  initialRequest = null,
  onInitialRequestHandled,
}) {
  const [resumeVersions, setResumeVersions] = useState([]);
  const [resumeVersionId, setResumeVersionId] = useState(
    () => localStorage.getItem(pendingResumeKey(user.id)) || "",
  );
  const [threadId, setThreadId] = useState(
    () => (
      localStorage.getItem(pendingResumeKey(user.id))
        ? ""
        : localStorage.getItem(storedThreadKey(user.id)) || ""
    ),
  );
  const [snapshot, setSnapshot] = useState(null);
  const [events, setEvents] = useState([]);
  const [foregroundRunId, setForegroundRunId] = useState("");
  const [candidateProfile, setCandidateProfile] = useState(null);
  const [targetAssessment, setTargetAssessment] = useState(null);
  const [proposedEdits, setProposedEdits] = useState([]);
  const [editResult, setEditResult] = useState(null);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const queuedMessagesRef = useRef([]);
  const [queuedMessages, setQueuedMessages] = useState([]);
  const [error, setError] = useState("");
  const [visibleProfileCount, setVisibleProfileCount] = useState(EVIDENCE_PAGE_SIZE);
  const [visibleCriteriaCount, setVisibleCriteriaCount] = useState(EVIDENCE_PAGE_SIZE);
  const [feedbackJobId, setFeedbackJobId] = useState(null);
  const [feedbackScope, setFeedbackScope] = useState("role");
  const [feedbackReason, setFeedbackReason] = useState("");
  const [suppressAutoResume, setSuppressAutoResume] = useState(false);
  const [threadSummaries, setThreadSummaries] = useState(null);
  const [showConversations, setShowConversations] = useState(false);
  const [renamingThreadId, setRenamingThreadId] = useState("");
  const [renameTitle, setRenameTitle] = useState("");
  const [deletionTarget, setDeletionTarget] = useState(null);
  const [retention, setRetention] = useState(null);
  const [lifecycleNotice, setLifecycleNotice] = useState("");
  const [loadingEarlierMessages, setLoadingEarlierMessages] = useState(false);
  const handledInitialRequestRef = useRef("");

  const selectedResume = useMemo(
    () => resumeVersions.find((resume) => String(resume.id) === String(resumeVersionId)),
    [resumeVersionId, resumeVersions],
  );
  const archived = snapshot?.status === "archived";
  const bindingMismatch = snapshot?.case_facts?.resume_binding_status === "mismatch";
  const persistedAwaitingAnswer = snapshot?.workflow_state === "awaiting_candidate_answer";
  const answerResuming = persistedAwaitingAnswer && busy;
  const awaitingAnswer = persistedAwaitingAnswer && !busy;
  const candidateStudyRunning = snapshot?.case_facts?.candidate_profile_status === "running";
  const candidateProfileReady = snapshot?.case_facts?.candidate_profile_status === "completed";
  const persistedRunActive = !busy && events.at(-1)?.status === "running";
  const latestRunEvent = events.findLast((item) => item.event_type === "run");
  const failedConversationTurn = latestRunEvent?.status === "failed"
    && ["start_thread", "send_message", "answer_assessment_question"]
      .includes(latestRunEvent.detail?.command_type)
    ? latestRunEvent
    : null;
  const reviewedTargetSpecialistRuns = targetAssessment?.status === "completed"
    ? (targetAssessment.specialist_runs || [])
    : [];
  const targetSpecialistCount = new Set(
    reviewedTargetSpecialistRuns.map((run) => run.persona_id),
  ).size;
  const plan = snapshot?.case_facts?.plan || [];
  const recommendations = snapshot?.case_facts?.recommendations || [];
  const shortlistedJobs = snapshot?.case_facts?.shortlisted_jobs || [];
  const displayedJobs = [
    ...recommendations,
    ...shortlistedJobs.filter(
      (savedJob) => !recommendations.some((job) => job.job_id === savedJob.job_id),
    ),
  ];
  const shortlistedJobIds = new Set(snapshot?.case_facts?.shortlisted_job_ids || []);
  const matchRationales = new Map(
    (snapshot?.case_facts?.match_rationales || []).map((item) => [item.job_id, item]),
  );
  const allDisplayedJobsRanked = displayedJobs.every((job) => matchRationales.has(job.job_id));
  const profileRankingUsed = snapshot?.case_facts?.latest_ranking_receipt?.candidate_profile_used === true;
  const rankingReceipt = snapshot?.case_facts?.latest_ranking_receipt;
  const selectedTargetId = snapshot?.case_facts?.selected_target?.job_id;
  const selectedTarget = snapshot?.case_facts?.selected_target;
  const selectedTrackedJobId = snapshot?.case_facts?.tracked_job_ids?.[String(selectedTargetId)];
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
    setEvents((current) => normalizeActivityEvents([...current, activityEvent]));
  }

  function streamForegroundCommand(path, body) {
    let runId = "";
    setForegroundRunId("");
    return streamRecruitmentCommand(path, body, (activityEvent) => {
      if (!runId && activityEvent.run_id) {
        runId = activityEvent.run_id;
        setForegroundRunId(activityEvent.run_id);
      }
      appendActivity(activityEvent);
    });
  }

  async function loadThreads() {
    const response = await apiFetch("/api/recruitment-team/threads");
    const threads = await response.json();
    setThreadSummaries(threads);
    return threads;
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
    setEvents(normalizeActivityEvents(nextEvents));
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
    const editsResponse = await apiFetch(`/api/recruitment-team/threads/${id}/proposed-edits`);
    setProposedEdits(await editsResponse.json());
  }

  async function loadEarlierMessages() {
    const beforeMessageId = snapshot?.oldest_message_id;
    if (!threadId || !snapshot?.message_history_has_more || !beforeMessageId) return;
    setLoadingEarlierMessages(true);
    setError("");
    try {
      const response = await apiFetch(
        `/api/recruitment-team/threads/${threadId}?before_message_id=${beforeMessageId}`,
      );
      const page = await response.json();
      setSnapshot((current) => ({
        ...current,
        messages: [...(page.messages || []), ...(current?.messages || [])],
        message_history_has_more: page.message_history_has_more,
        oldest_message_id: page.oldest_message_id,
      }));
    } catch (historyError) {
      setError(historyError.message || "Could not load earlier messages.");
    } finally {
      setLoadingEarlierMessages(false);
    }
  }

  async function runTurn(action, { clearMessage = false, refreshOnError = false, fallbackError = "" } = {}) {
    setBusy(true);
    setError("");
    try {
      await action();
      if (clearMessage) setMessage("");
      await refreshThread(threadId);
      return true;
    } catch (turnError) {
      setError(turnError.message || fallbackError);
      if (refreshOnError || turnError.detail?.code === "resume_binding_mismatch") {
        await refreshThread(threadId);
      }
      return false;
    } finally {
      setBusy(false);
    }
  }

  async function retryFailedConversationTurn() {
    if (!threadId || !failedConversationTurn?.detail?.retryable || busy) return;
    setBusy(true);
    setError("");
    try {
      await streamForegroundCommand(
        `/api/recruitment-team/threads/${threadId}/runs/${failedConversationTurn.run_id}/retry/stream`,
        {},
      );
      await refreshThread(threadId);
    } catch (retryError) {
      setError(retryError.message || "Could not retry this turn.");
      await refreshThread(threadId);
    } finally {
      setBusy(false);
    }
  }

  function acceptEdits(editIds) {
    return runTurn(async () => {
      const response = await apiFetch(
        `/api/recruitment-team/threads/${threadId}/proposed-edits/accept`,
        {
          method: "POST",
          body: JSON.stringify({ edit_ids: editIds, idempotency_key: crypto.randomUUID() }),
        },
      );
      setEditResult(await response.json());
    }, { fallbackError: "Could not save those edits." });
  }

  async function rejectEdits(editIds) {
    try {
      await apiFetch(`/api/recruitment-team/threads/${threadId}/proposed-edits/reject`, {
        method: "POST",
        body: JSON.stringify({ edit_ids: editIds, idempotency_key: crypto.randomUUID() }),
      });
      await refreshThread(threadId);
    } catch (rejectError) {
      setError(rejectError.message || "Could not dismiss that edit.");
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
    if (!threadId || (!candidateStudyRunning && !persistedRunActive)) {
      return undefined;
    }
    const interval = setInterval(() => {
      refreshThread(threadId).catch((loadError) => setError(loadError.message));
    }, THREAD_REFRESH_POLL_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [threadId, candidateStudyRunning, persistedRunActive]);

  useEffect(() => {
    if (
      threadId
      || suppressAutoResume
      || initialRequest
      || localStorage.getItem(pendingResumeKey(user.id))
    ) return undefined;
    let cancelled = false;
    loadThreads().then((threads) => {
      if (cancelled) return;
      const nextThread = threads.find((thread) => thread.status === "active");
      if (!nextThread) return;
      localStorage.setItem(storedThreadKey(user.id), nextThread.thread_id);
      setThreadId(nextThread.thread_id);
    }).catch((loadError) => {
      if (!cancelled) setError(loadError.message);
    });
    return () => { cancelled = true; };
  }, [initialRequest, threadId, suppressAutoResume, user.id]);

  useEffect(() => {
    if (
      !initialRequest
      || !resumeVersions.length
      || handledInitialRequestRef.current === initialRequest.id
      || (threadId && !snapshot)
    ) return undefined;

    const requestedVersionId = Number(initialRequest.resumeVersionId);
    if (!resumeVersions.some((resume) => Number(resume.id) === requestedVersionId)) return undefined;

    handledInitialRequestRef.current = initialRequest.id;
    (async () => {
      setBusy(true);
      setError("");
      try {
        setResumeVersionId(String(requestedVersionId));
        const currentVersionId = Number(snapshot?.case_facts?.resume_version_id);
        const receipt = threadId
          && snapshot?.status !== "archived"
          && currentVersionId === requestedVersionId
          ? await streamForegroundCommand(
            `/api/recruitment-team/threads/${threadId}/messages/stream`,
            {
              message: initialRequest.message,
              idempotency_key: globalThis.crypto.randomUUID(),
            },
          )
          : await streamForegroundCommand(
            "/api/recruitment-team/threads/stream",
            {
              resume_version_id: requestedVersionId,
              message: initialRequest.message,
              idempotency_key: globalThis.crypto.randomUUID(),
            },
          );
        const nextThreadId = receipt.thread_id;
        localStorage.removeItem(pendingResumeKey(user.id));
        localStorage.setItem(storedThreadKey(user.id), nextThreadId);
        await refreshThread(nextThreadId);
        await loadThreads();
        if (nextThreadId !== threadId) setThreadId(nextThreadId);
      } catch (requestError) {
        setError(requestError.message || "Could not search with this resume.");
      } finally {
        setBusy(false);
        onInitialRequestHandled?.(initialRequest.id);
      }
    })();
    return undefined;
  }, [initialRequest, onInitialRequestHandled, resumeVersions, snapshot, threadId, user.id]);

  function clearConversation() {
    localStorage.removeItem(storedThreadKey(user.id));
    setSuppressAutoResume(true);
    setThreadId("");
    setSnapshot(null);
    setEvents([]);
    setCandidateProfile(null);
    setTargetAssessment(null);
    setMessage("");
    queuedMessagesRef.current = [];
    setQueuedMessages([]);
    setError("");
    setVisibleProfileCount(EVIDENCE_PAGE_SIZE);
    setVisibleCriteriaCount(EVIDENCE_PAGE_SIZE);
  }

  function startNewConversation() {
    if (busy) return;
    clearConversation();
    setResumeVersionId("");
  }

  function startConversationWithResume(versionId) {
    if (busy || !versionId) return;
    clearConversation();
    localStorage.setItem(pendingResumeKey(user.id), String(versionId));
    setResumeVersionId(String(versionId));
    setEditResult(null);
  }

  function selectConversation(id) {
    if (busy) return;
    localStorage.setItem(storedThreadKey(user.id), id);
    setSuppressAutoResume(false);
    setSnapshot(null);
    setThreadId(id);
    setShowConversations(false);
    setLifecycleNotice("");
  }

  async function toggleConversationManager() {
    const nextVisible = !showConversations;
    setShowConversations(nextVisible);
    if (!nextVisible) return;
    setError("");
    try {
      await loadThreads();
    } catch (loadError) {
      setError(loadError.message);
    }
  }

  async function renameConversation(event) {
    event.preventDefault();
    const title = renameTitle.trim();
    if (!renamingThreadId || !title || busy) return;
    setBusy(true);
    setError("");
    try {
      await apiFetch(`/api/recruitment-team/threads/${renamingThreadId}`, {
        method: "PATCH",
        body: JSON.stringify({ title }),
      });
      await loadThreads();
      if (renamingThreadId === threadId) await refreshThread(threadId);
      setRenamingThreadId("");
      setRenameTitle("");
      setLifecycleNotice("Conversation renamed.");
    } catch (renameError) {
      setError(renameError.message);
    } finally {
      setBusy(false);
    }
  }

  async function setConversationArchived(summary, shouldArchive) {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      const action = shouldArchive ? "archive" : "restore";
      await apiFetch(`/api/recruitment-team/threads/${summary.thread_id}/${action}`, {
        method: "POST",
      });
      await loadThreads();
      if (summary.thread_id === threadId) await refreshThread(threadId);
      setLifecycleNotice(shouldArchive ? "Conversation archived." : "Conversation restored.");
    } catch (archiveError) {
      setError(archiveError.message);
    } finally {
      setBusy(false);
    }
  }

  async function beginDeleteConversation(summary) {
    if (busy) return;
    setError("");
    try {
      const response = await apiFetch("/api/recruitment-team/retention");
      setRetention(await response.json());
      setDeletionTarget(summary);
    } catch (retentionError) {
      setError(retentionError.message);
    }
  }

  async function deleteConversation() {
    if (!deletionTarget || busy) return;
    const deletedId = deletionTarget.thread_id;
    setBusy(true);
    setError("");
    try {
      const response = await apiFetch(`/api/recruitment-team/threads/${deletedId}`, {
        method: "DELETE",
        body: JSON.stringify({ idempotency_key: globalThis.crypto.randomUUID() }),
      });
      const result = await response.json();
      const remaining = await loadThreads();
      if (deletedId === threadId) {
        const nextThread = remaining.find((thread) => thread.status === "active");
        if (nextThread) {
          localStorage.setItem(storedThreadKey(user.id), nextThread.thread_id);
          setSnapshot(null);
          setThreadId(nextThread.thread_id);
        } else {
          clearConversation();
        }
      }
      setDeletionTarget(null);
      setRetention(null);
      setLifecycleNotice(`${result.retention.live_data} ${result.retention.backups}`);
    } catch (deleteError) {
      setError(deleteError.message);
    } finally {
      setBusy(false);
    }
  }

  async function startAutopilot() {
    if (busy || !resumeVersionId) return;
    setBusy(true);
    setError("");
    try {
      const receipt = await streamForegroundCommand(
        "/api/recruitment-team/threads/stream",
        {
          resume_version_id: Number(resumeVersionId),
          message: "Find roles for me.",
          idempotency_key: globalThis.crypto.randomUUID(),
        },
      );
      const nextThreadId = receipt.thread_id;
      localStorage.removeItem(pendingResumeKey(user.id));
      setThreadId(nextThreadId);
      localStorage.setItem(storedThreadKey(user.id), nextThreadId);
      await refreshThread(nextThreadId);
      await loadThreads();
    } catch (autopilotError) {
      setError(autopilotError.message || "Could not read your resume.");
    } finally {
      setBusy(false);
    }
  }

  async function submit(event) {
    event.preventDefault();
    const text = message.trim();
    if (!text || archived) return;
    if (busy) {
      queuedMessagesRef.current = [...queuedMessagesRef.current, text];
      setQueuedMessages(queuedMessagesRef.current);
      setMessage("");
      return;
    }
    if (!threadId && !resumeVersionId) {
      setError("Save or select a resume before starting the recruitment team.");
      return;
    }

    setBusy(true);
    setMessage("");
    setError("");
    try {
      const idempotencyKey = globalThis.crypto.randomUUID();
      const receipt = threadId
        ? await streamForegroundCommand(
          `/api/recruitment-team/threads/${threadId}/messages/stream`,
          { message: text, idempotency_key: idempotencyKey },
        )
        : await streamForegroundCommand(
          "/api/recruitment-team/threads/stream",
          {
            resume_version_id: Number(resumeVersionId),
            message: text,
            idempotency_key: idempotencyKey,
          },
        );
      const nextThreadId = receipt.thread_id;
      localStorage.removeItem(pendingResumeKey(user.id));
      localStorage.setItem(storedThreadKey(user.id), nextThreadId);
      const createdThread = nextThreadId !== threadId;
      if (createdThread) setThreadId(nextThreadId);
      await refreshThread(nextThreadId);
      if (createdThread) await loadThreads();
      while (queuedMessagesRef.current.length) {
        const [queuedMessage, ...remaining] = queuedMessagesRef.current;
        const queuedReceipt = await streamForegroundCommand(
          `/api/recruitment-team/threads/${nextThreadId}/messages/stream`,
          {
            message: queuedMessage,
            idempotency_key: globalThis.crypto.randomUUID(),
          },
        );
        queuedMessagesRef.current = remaining;
        setQueuedMessages(remaining);
        await refreshThread(queuedReceipt.thread_id);
      }
    } catch (submitError) {
      setError(submitError.message);
      if (threadId && submitError.detail?.code === "resume_binding_mismatch") {
        await refreshThread(threadId);
      }
    } finally {
      setBusy(false);
    }
  }

  function searchCurrentJobs() {
    const query = message.trim();
    if (!threadId || busy || archived) return undefined;
    return runTurn(
      () => streamForegroundCommand(
        `/api/recruitment-team/threads/${threadId}/jobs/search/stream`,
        { query, idempotency_key: globalThis.crypto.randomUUID() },
      ),
      { clearMessage: true },
    );
  }

  function studyResume() {
    if (!threadId || busy || archived) return undefined;
    return runTurn(
      () => streamForegroundCommand(
        `/api/recruitment-team/threads/${threadId}/candidate-profile/stream`,
        { idempotency_key: globalThis.crypto.randomUUID() },
      ),
      { refreshOnError: true },
    );
  }

  function assessTarget() {
    if (!threadId || busy || archived) return undefined;
    return runTurn(
      () => streamForegroundCommand(
        `/api/recruitment-team/threads/${threadId}/assessment/stream`,
        { idempotency_key: globalThis.crypto.randomUUID() },
      ),
      { refreshOnError: true },
    );
  }

  function answerAssessmentQuestion(event) {
    event.preventDefault();
    const answer = message.trim();
    if (!threadId || !answer || busy || archived) return undefined;
    setMessage("");
    return runTurn(
      () => streamForegroundCommand(
        `/api/recruitment-team/threads/${threadId}/assessment/answer/stream`,
        { answer, idempotency_key: globalThis.crypto.randomUUID() },
      ),
      { refreshOnError: true },
    ).then((completed) => {
      if (!completed) setMessage(answer);
      return completed;
    });
  }

  async function handoffToResumeAgent() {
    if (!threadId || busy || archived) return;
    setBusy(true);
    setError("");
    try {
      const response = await apiFetch(
        `/api/recruitment-team/threads/${threadId}/resume-agent-handoff`,
        { method: "POST" },
      );
      const { session_id } = await response.json();
      sessionStorage.setItem("jh_resume_agent_session", session_id);
      sessionStorage.setItem("jh_resume_agent_autoopen", "1");
      setActiveTab?.("resume");
    } catch (handoffError) {
      setError(handoffError.message);
    } finally {
      setBusy(false);
    }
  }

  function updateJob(path) {
    if (busy || archived) return undefined;
    return runTurn(() => streamForegroundCommand(
      `${path}/stream`,
      { idempotency_key: globalThis.crypto.randomUUID() },
    ), { refreshOnError: true });
  }

  async function submitJobFeedback(event, jobId) {
    event.preventDefault();
    if (busy || archived) return;
    const saved = await runTurn(
      () => streamForegroundCommand(
        `/api/recruitment-team/threads/${threadId}/jobs/${jobId}/feedback/stream`,
        {
          scope: feedbackScope,
          reason: feedbackReason.trim(),
          idempotency_key: globalThis.crypto.randomUUID(),
        },
      ),
      { refreshOnError: true },
    );
    if (saved) {
      setFeedbackJobId(null);
      setFeedbackScope("role");
      setFeedbackReason("");
    }
  }

  return (
    <section aria-labelledby="recruitment-team-title" className="space-y-5">
      {/* Once a conversation exists the pitch is dead weight above every reply,
          so the header collapses to a title bar and the explanation stays where
          it is still doing a job: the empty state. */}
      <header
        className={`rounded-3xl bg-[#384959] text-white ${
          threadId ? "px-5 py-3 sm:px-6" : "px-6 py-6 sm:px-8"
        }`}
      >
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <div className={`rounded-2xl bg-white/10 ${threadId ? "p-2" : "p-3"}`}>
              <Users size={threadId ? 18 : 22} />
            </div>
            <div>
              {!threadId && (
                <p className="text-xs font-semibold uppercase tracking-[0.18em] text-[#BDDDFC]">V3</p>
              )}
              <h1
                id="recruitment-team-title"
                className={threadId ? "text-base font-semibold" : "text-2xl font-semibold"}
              >
                {threadId ? snapshot?.title || "Recruitment conversation" : "AI Recruitment Team"}
              </h1>
              {archived && <p className="text-xs text-[#BDDDFC]">Archived · read only</p>}
              {threadId && snapshot?.case_facts && (
                <p className="mt-1 text-xs text-[#BDDDFC]">
                  Resume: {snapshot.case_facts.resume_label} · v{snapshot.case_facts.resume_version_id}
                  {snapshot.case_facts.resume_sha256
                    ? ` · ${snapshot.case_facts.resume_sha256.slice(0, 10)}`
                    : ""}
                  {snapshot.case_facts.resume_word_count
                    ? ` · ${snapshot.case_facts.resume_word_count} words`
                    : ""}
                  {snapshot.case_facts.resume_created_at
                    ? ` · saved ${new Date(snapshot.case_facts.resume_created_at).toLocaleDateString()}`
                    : ""}
                </p>
              )}
            </div>
          </div>
          {(threadId || threadSummaries?.length > 0) && (
            <div className="flex flex-wrap justify-end gap-2">
              <button
                type="button"
                onClick={toggleConversationManager}
                className="inline-flex items-center gap-2 rounded-xl border border-white/30 px-3 py-2 text-xs font-semibold text-white"
                aria-expanded={showConversations}
              >
                <MessageSquare size={14} />
                Conversations
              </button>
              {threadId && (
                <button
                  type="button"
                  onClick={startNewConversation}
                  disabled={busy}
                  className="rounded-xl border border-white/30 px-3 py-2 text-xs font-semibold text-white disabled:opacity-40"
                >
                  Start new conversation
                </button>
              )}
            </div>
          )}
        </div>
        {!threadId && (
          <p className="mt-4 max-w-2xl text-sm leading-relaxed text-[#dbeaf8]">
            Explore your next move with a persistent team that preserves evidence and shows real activity.
          </p>
        )}
      </header>

      {showConversations && (
        <section
          aria-labelledby="conversation-manager-title"
          className="rounded-3xl border border-[#BDDDFC]/60 bg-white p-5 shadow-sm"
        >
          <div className="flex items-start justify-between gap-3">
            <div>
              <h2 id="conversation-manager-title" className="font-semibold text-[#384959]">
                Conversations
              </h2>
              <p className="mt-1 text-xs text-[#6A89A7]">
                Switch, rename, archive, restore, or permanently delete your conversations.
              </p>
            </div>
            <button
              type="button"
              onClick={() => setShowConversations(false)}
              aria-label="Close conversation manager"
              className="rounded-lg p-2 text-[#4A6785] hover:bg-[#f0f5fa]"
            >
              <X size={16} />
            </button>
          </div>

          {lifecycleNotice && (
            <p role="status" className="mt-3 rounded-xl bg-[#f0f5fa] px-3 py-2 text-xs text-[#384959]">
              {lifecycleNotice}
            </p>
          )}

          <div className="mt-4 space-y-2">
            {threadSummaries?.map((summary) => (
              <article
                key={summary.thread_id}
                className={`rounded-2xl border p-3 ${
                  summary.thread_id === threadId ? "border-[#88BDF2] bg-[#f7fafc]" : "border-[#DCE7F2]"
                }`}
              >
                {renamingThreadId === summary.thread_id ? (
                  <form onSubmit={renameConversation} className="flex flex-wrap gap-2">
                    <label className="min-w-48 flex-1 text-xs font-medium text-[#384959]">
                      Conversation title
                      <input
                        autoFocus
                        value={renameTitle}
                        onChange={(event) => setRenameTitle(event.target.value)}
                        maxLength={THREAD_TITLE_MAX_CHARS}
                        className="mt-1 w-full rounded-xl border border-[#BDDDFC] px-3 py-2 text-sm"
                      />
                    </label>
                    <button
                      type="submit"
                      disabled={!renameTitle.trim() || busy}
                      className="self-end rounded-xl bg-[#384959] px-3 py-2 text-xs font-semibold text-white disabled:opacity-40"
                    >
                      Save name
                    </button>
                    <button
                      type="button"
                      onClick={() => setRenamingThreadId("")}
                      className="self-end rounded-xl border border-[#BDDDFC] px-3 py-2 text-xs text-[#384959]"
                    >
                      Cancel
                    </button>
                  </form>
                ) : (
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <button
                      type="button"
                      onClick={() => selectConversation(summary.thread_id)}
                      disabled={busy}
                      className="min-w-0 flex-1 text-left disabled:opacity-40"
                    >
                      <span className="block truncate text-sm font-semibold text-[#384959]">{summary.title}</span>
                      <span className="mt-1 block truncate text-xs text-[#6A89A7]">
                        {summary.last_message || summary.resume_label}
                      </span>
                      <span className="mt-1 block truncate text-[11px] text-[#6A89A7]">
                        {summary.resume_label} · v{summary.resume_version_id}
                        {summary.resume_sha256 ? ` · ${summary.resume_sha256.slice(0, 10)}` : ""}
                        {summary.resume_word_count ? ` · ${summary.resume_word_count} words` : ""}
                        {summary.resume_created_at
                          ? ` · saved ${new Date(summary.resume_created_at).toLocaleDateString()}`
                          : ""}
                      </span>
                    </button>
                    <span className="rounded-full bg-[#f0f5fa] px-2 py-1 text-xs capitalize text-[#384959]">
                      {summary.status}
                    </span>
                    <div className="flex gap-1">
                      <button
                        type="button"
                        onClick={() => {
                          setRenamingThreadId(summary.thread_id);
                          setRenameTitle(summary.title);
                        }}
                        aria-label={`Rename ${summary.title}`}
                        className="rounded-lg p-2 text-[#4A6785] hover:bg-[#f0f5fa]"
                      >
                        <Pencil size={15} />
                      </button>
                      <button
                        type="button"
                        onClick={() => setConversationArchived(summary, summary.status === "active")}
                        aria-label={`${summary.status === "active" ? "Archive" : "Restore"} ${summary.title}`}
                        className="rounded-lg p-2 text-[#4A6785] hover:bg-[#f0f5fa]"
                      >
                        {summary.status === "active" ? <Archive size={15} /> : <RotateCcw size={15} />}
                      </button>
                      <button
                        type="button"
                        onClick={() => beginDeleteConversation(summary)}
                        aria-label={`Delete ${summary.title}`}
                        className="rounded-lg p-2 text-red-700 hover:bg-red-50"
                      >
                        <Trash2 size={15} />
                      </button>
                    </div>
                  </div>
                )}
              </article>
            ))}
            {threadSummaries?.length === 0 && (
              <p className="py-6 text-center text-sm text-[#6A89A7]">No saved conversations yet.</p>
            )}
          </div>

          {deletionTarget && retention && (
            <div role="dialog" aria-modal="true" aria-labelledby="delete-conversation-title" className="mt-4 rounded-2xl border border-red-200 bg-red-50 p-4">
              <h3 id="delete-conversation-title" className="font-semibold text-red-900">
                Permanently delete “{deletionTarget.title}”?
              </h3>
              <p className="mt-2 text-sm text-red-900">{retention.live_data}</p>
              <p className="mt-1 text-xs text-red-800">Backups: {retention.backups}</p>
              <p className="mt-1 text-xs text-red-800">Telemetry: {retention.telemetry}</p>
              <div className="mt-4 flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={deleteConversation}
                  disabled={busy}
                  className="rounded-xl bg-red-700 px-3 py-2 text-xs font-semibold text-white disabled:opacity-40"
                >
                  Delete permanently
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setDeletionTarget(null);
                    setRetention(null);
                  }}
                  disabled={busy}
                  className="rounded-xl border border-red-300 px-3 py-2 text-xs font-semibold text-red-900 disabled:opacity-40"
                >
                  Keep conversation
                </button>
              </div>
            </div>
          )}
        </section>
      )}

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_22rem]">
        <div className="rounded-3xl border border-[#BDDDFC]/40 bg-white p-5 shadow-sm">
          {bindingMismatch && (
            <div className="mb-5 rounded-2xl border border-amber-300 bg-amber-50 p-4 text-sm text-amber-950">
              This conversation's saved resume no longer matches its evidence receipt. Its history is
              still readable, but new analysis is blocked.
              <button
                type="button"
                onClick={startNewConversation}
                className="ml-2 rounded-lg border border-amber-700 px-2.5 py-1 text-xs font-semibold"
              >
                Start a new conversation
              </button>
            </div>
          )}
          {!threadId && (
            <label className="mb-5 block text-sm font-medium text-[#384959]">
              Resume evidence
              <select
                value={resumeVersionId}
                onChange={(event) => setResumeVersionId(event.target.value)}
                className="mt-2 w-full rounded-xl border border-[#BDDDFC] bg-white px-3 py-2 text-sm"
              >
                <option value="">
                  {resumeVersions.length === 0 ? "No saved resumes" : "Choose a resume…"}
                </option>
                {resumeVersions.map((resume) => (
                  <option key={resume.id} value={resume.id}>
                    {resume.label} · v{resume.id} · {resume.word_count || 0} words
                  </option>
                ))}
              </select>
              {selectedResume && (
                <span className="mt-2 block text-xs font-normal text-[#6A89A7]">
                  v{selectedResume.id} · {selectedResume.word_count || 0} words
                  {selectedResume.created_at
                    ? ` · saved ${new Date(selectedResume.created_at).toLocaleString()}`
                    : ""}
                  {selectedResume.content_sha256
                    ? ` · ${selectedResume.content_sha256.slice(0, 10)}`
                    : ""}
                </span>
              )}
            </label>
          )}

          <div className="min-h-72 space-y-3" aria-live="polite">
            {profileRankingUsed && rankingReceipt && (
              <p className="rounded-xl bg-[#f0f5fa] px-3 py-2 text-xs text-[#4A6785]">
                Recommendations use resume v{rankingReceipt.resume_version_id}
                {rankingReceipt.resume_sha256 ? ` · ${rankingReceipt.resume_sha256.slice(0, 10)}` : ""}
                {rankingReceipt.candidate_profile_artifact_id
                  ? ` · profile ${rankingReceipt.candidate_profile_artifact_id.slice(0, 8)}`
                  : ""}
              </p>
            )}
            {snapshot?.message_history_has_more && (
              <div className="flex justify-center">
                <button
                  type="button"
                  onClick={loadEarlierMessages}
                  disabled={loadingEarlierMessages}
                  className="rounded-full border border-[#BDDDFC] px-3 py-1.5 text-xs font-medium text-[#384959] disabled:opacity-60"
                >
                  {loadingEarlierMessages ? "Loading…" : "Load earlier messages"}
                </button>
              </div>
            )}
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
              <div className="flex min-h-56 flex-col items-center justify-center px-6 text-center">
                <Bot size={28} className="text-[#6A89A7]" />
                {selectedResume ? (
                  <>
                    <p className="mt-3 text-sm font-medium text-[#384959]">
                      Working from {selectedResume.label}
                    </p>
                    <p className="mt-1 max-w-md text-xs leading-relaxed text-[#4A6785]">
                      The candidate profiler resolves your resume evidence first. The coordinator
                      then searches current Singapore roles and explains its work.
                    </p>
                    {/* Two doors, because a candidate who knows what they want should not
                        have to answer questions first, and one who does not should not face
                        an empty box. */}
                    <div className="mt-4 flex flex-wrap items-center justify-center gap-2">
                      <button
                        type="button"
                        onClick={startAutopilot}
                        disabled={busy}
                        className="rounded-2xl bg-[#384959] px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-40"
                      >
                        {busy ? "Reading your resume" : "Find roles for me"}
                      </button>
                      <span className="text-xs text-[#4A6785]">or tell them what you want below</span>
                    </div>
                  </>
                ) : (
                  <>
                    <p className="mt-3 text-sm font-medium text-[#384959]">
                      The team works from a saved resume
                    </p>
                    <p className="mt-1 text-xs text-[#4A6785]">
                      Add one and they can start reading it straight away.
                    </p>
                    <button
                      type="button"
                      onClick={() => setActiveTab?.("resume")}
                      className="mt-4 rounded-2xl bg-[#384959] px-4 py-2.5 text-sm font-semibold text-white"
                    >
                      Add a resume
                    </button>
                  </>
                )}
              </div>
            )}
          </div>

          {error && <p role="alert" className="mt-3 text-sm text-red-700">{error}</p>}
          {failedConversationTurn && (
            <div className="mt-3 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
              <span>
                This turn stopped. Next step: {String(
                  failedConversationTurn.detail?.recovery_action || "review the failure",
                ).replaceAll("_", " ")}.
              </span>
              {failedConversationTurn.detail?.retryable && (
                <button
                  type="button"
                  onClick={retryFailedConversationTurn}
                  disabled={busy || archived}
                  className="rounded-xl border border-amber-700 px-3 py-2 text-xs font-semibold disabled:opacity-40"
                >
                  Retry this turn
                </button>
              )}
            </div>
          )}
          <AiServiceStatus />
          {awaitingAnswer && (
            <p className="mt-3 rounded-xl border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900">
              The assessment paused on a question above -- answer it below to continue.
            </p>
          )}
          {archived && (
            <div className="mt-3 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-[#BDDDFC] bg-[#f7fafc] px-3 py-2 text-sm text-[#384959]">
              <span>This conversation is archived. Restore it before continuing the workflow.</span>
              <button
                type="button"
                onClick={() => setConversationArchived(
                  threadSummaries?.find((thread) => thread.thread_id === threadId) || {
                    thread_id: threadId,
                    title: snapshot?.title || "Recruitment conversation",
                    status: "archived",
                  },
                  false,
                )}
                disabled={busy}
                className="rounded-xl border border-[#384959] px-3 py-2 text-xs font-semibold disabled:opacity-40"
              >
                Restore conversation
              </button>
            </div>
          )}
          <form onSubmit={awaitingAnswer ? answerAssessmentQuestion : submit} className="mt-4 flex items-end gap-2">
            <textarea
              value={message}
              onChange={(event) => setMessage(event.target.value)}
              disabled={archived || answerResuming}
              rows={2}
              placeholder={
                answerResuming
                  ? "Continuing the assessment..."
                  : awaitingAnswer
                  ? "Answer the assessment's question..."
                  : "Describe your target role, constraints, or follow-up..."
              }
              className="min-h-12 flex-1 resize-y rounded-2xl border border-[#BDDDFC] px-4 py-3 text-sm text-[#384959] focus:outline-none focus:ring-2 focus:ring-[#88BDF2]"
            />
            <button
              type="submit"
              disabled={!message.trim() || archived || answerResuming}
              className="inline-flex h-12 items-center gap-2 rounded-2xl bg-[#384959] px-4 text-sm font-semibold text-white disabled:opacity-40"
            >
              <Send size={15} />
              {answerResuming ? "Continuing" : busy ? "Queue message" : awaitingAnswer ? "Send answer" : "Send"}
            </button>
            {!awaitingAnswer && threadId && (
              <button
                type="button"
                onClick={searchCurrentJobs}
                disabled={busy || archived}
                title="Search using what you have already told the team, or type to narrow it"
                className="h-12 rounded-2xl border border-[#384959] px-4 text-sm font-semibold text-[#384959] disabled:opacity-40"
              >
                Search jobs
              </button>
            )}
            {!awaitingAnswer && threadId && (
              <button
                type="button"
                onClick={studyResume}
                disabled={busy || archived || candidateStudyRunning || candidateProfile?.status === "completed"}
                className="h-12 rounded-2xl border border-[#384959] px-4 text-sm font-semibold text-[#384959] disabled:opacity-40"
              >
                {candidateStudyRunning
                  ? "Studying resume"
                  : candidateProfile?.status === "failed"
                    ? "Resume profile"
                    : "Study resume"}
              </button>
            )}
          </form>
          {queuedMessages.length > 0 && (
            <div className="mt-2 rounded-xl border border-[#BDDDFC] bg-[#f7fafc] px-3 py-2 text-xs text-[#384959]">
              <p className="font-medium">Queued for the team</p>
              {queuedMessages.map((queuedMessage, index) => (
                <p key={`${index}-${queuedMessage}`} className="mt-1">{queuedMessage}</p>
              ))}
            </div>
          )}

          {plan.length > 0 && (
            <section aria-labelledby="recruitment-plan-title" className="mt-6 border-t border-[#BDDDFC]/50 pt-5">
              <h2 id="recruitment-plan-title" className="text-sm font-semibold text-[#384959]">
                Recruitment plan
              </h2>
              <p className="mt-1 text-xs text-[#6A89A7]">
                The coordinator updates this when your direction or the work changes.
              </p>
              <ol className="mt-3 space-y-2">
                {plan.map((item, index) => (
                  <li
                    key={`${index}-${item.step}`}
                    className="flex items-start justify-between gap-3 rounded-xl border border-[#BDDDFC]/60 px-3 py-2"
                  >
                    <span className="text-sm text-[#384959]">{item.step}</span>
                    <span className="shrink-0 rounded-full bg-[#f0f5fa] px-2 py-1 text-xs capitalize text-[#384959]">
                      {item.status.replaceAll("_", " ")}
                    </span>
                  </li>
                ))}
              </ol>
            </section>
          )}

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
              {candidateProfile.execution_metrics
                && Object.keys(candidateProfile.execution_metrics).length > 0 && (
                  <div className="mt-3">
                    <ExecutionDetails metrics={candidateProfile.execution_metrics} />
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
                {allDisplayedJobsRanked ? "Current source-backed matches" : "Current search results"}
              </h2>
              <div className="mt-3 space-y-3">
                {displayedJobs.map((job) => {
                  const shortlisted = shortlistedJobIds.has(job.job_id);
                  const selected = selectedTargetId === job.job_id;
                  const variants = job.posting_variants || [];
                  const rationale = matchRationales.get(job.job_id);
                  return (
                    <article key={job.job_id} className="rounded-2xl border border-[#BDDDFC]/60 p-4">
                      <div className="flex flex-wrap items-start justify-between gap-3">
                        <div>
                          <h3 className="font-semibold text-[#384959]">{job.title}</h3>
                          <p className="text-sm text-[#6A89A7]">{job.company} · {job.location}</p>
                        </div>
                        <span className="rounded-full bg-[#f0f5fa] px-2 py-1 text-xs text-[#384959]">
                          {selected
                            ? "Selected target"
                            : shortlisted
                              ? "Shortlisted"
                              : rationale && profileRankingUsed
                                ? "Profile-ranked match"
                                : "Search result"}
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
                      <p className="mt-1 text-xs text-[#6A89A7]">
                        Employer relationship: {job.employer_relationship === "direct"
                          ? "verified direct"
                          : job.employer_relationship === "intermediary"
                            ? "intermediary"
                            : "unverified"}
                      </p>
                      {rationale && (
                        <div className="mt-3 rounded-xl bg-[#f7fafc] p-3 text-xs text-[#384959]">
                          <p className="font-medium">
                            Level: {rationale.level_fit.replaceAll("_", " ")} · Pay: {rationale.pay_position.replaceAll("_", " ")}
                          </p>
                          <div className="mt-2">
                            <p className="font-medium">Matched</p>
                            {rationale.matched.map((point) => (
                              <div key={`${job.job_id}-matched-${point.statement}`} className="mt-1">
                                <p>{point.statement}</p>
                                <blockquote className="mt-1 border-l-2 border-[#88BDF2] pl-2 text-[#6A89A7]">
                                  Resume: “{point.resume_quote}”
                                </blockquote>
                              </div>
                            ))}
                          </div>
                          <div className="mt-2">
                            <p className="font-medium">Stretch</p>
                            {rationale.stretch.length ? rationale.stretch.map((point) => (
                              <div key={`${job.job_id}-stretch-${point.statement}`} className="mt-1">
                                <p>{point.statement}</p>
                                <blockquote className="mt-1 border-l-2 border-[#BDDDFC] pl-2 text-[#6A89A7]">
                                  Resume: “{point.resume_quote}”
                                </blockquote>
                              </div>
                            )) : <p className="mt-1 text-[#6A89A7]">None identified.</p>}
                          </div>
                          <div className="mt-2">
                            <p className="font-medium">Missing</p>
                            <p className="mt-1 text-[#6A89A7]">
                              {rationale.missing.length ? rationale.missing.join(" · ") : "None identified."}
                            </p>
                          </div>
                        </div>
                      )}
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
                            disabled={busy || archived}
                            className="rounded-xl border border-[#BDDDFC] px-3 py-2 text-xs font-medium text-[#384959] disabled:opacity-40"
                          >
                            Shortlist
                          </button>
                        )}
                        {!selected && (
                          <button
                            type="button"
                            onClick={() => updateJob(`/api/recruitment-team/threads/${threadId}/jobs/${job.job_id}/select`)}
                            disabled={busy || archived || !candidateProfileReady}
                            className="rounded-xl bg-[#384959] px-3 py-2 text-xs font-medium text-white disabled:opacity-40"
                          >
                            {candidateProfileReady ? "Select target" : "Preparing resume profile"}
                          </button>
                        )}
                        {!shortlisted && !selected && (
                          <button
                            type="button"
                            onClick={() => {
                              setFeedbackJobId(job.job_id);
                              setFeedbackScope("role");
                              setFeedbackReason("");
                            }}
                            disabled={busy || archived}
                            className="rounded-xl px-3 py-2 text-xs font-medium text-[#6A89A7] hover:bg-[#f0f5fa] disabled:opacity-40"
                          >
                            Not for me
                          </button>
                        )}
                      </div>
                      {feedbackJobId === job.job_id && (
                        <form onSubmit={(event) => submitJobFeedback(event, job.job_id)} className="mt-3 rounded-xl border border-[#BDDDFC]/60 bg-[#f7fafc] p-3">
                          <p className="text-xs font-medium text-[#384959]">Hide this result and save private feedback</p>
                          <div className="mt-2 flex flex-wrap gap-3 text-xs text-[#384959]">
                            <label className="flex items-center gap-1.5">
                              <input type="radio" name={`feedback-scope-${job.job_id}`} checked={feedbackScope === "role"} onChange={() => setFeedbackScope("role")} />
                              This role
                            </label>
                            <label className="flex items-center gap-1.5">
                              <input type="radio" name={`feedback-scope-${job.job_id}`} checked={feedbackScope === "company"} onChange={() => setFeedbackScope("company")} />
                              This company
                            </label>
                          </div>
                          <input
                            type="text"
                            value={feedbackReason}
                            maxLength={JOB_FEEDBACK_REASON_MAX_CHARS}
                            onChange={(event) => setFeedbackReason(event.target.value)}
                            placeholder="Reason (optional)"
                            className="mt-2 w-full rounded-lg border border-[#BDDDFC] bg-white px-3 py-2 text-xs text-[#384959]"
                          />
                          <p className="mt-1 text-xs text-[#6A89A7]">This guides your conversation only; it does not change the role’s relevance for everyone.</p>
                          <div className="mt-2 flex gap-2">
                            <button type="submit" disabled={busy} className="rounded-lg bg-[#384959] px-3 py-2 text-xs font-medium text-white disabled:opacity-40">Save feedback</button>
                            <button type="button" onClick={() => setFeedbackJobId(null)} className="rounded-lg px-3 py-2 text-xs text-[#6A89A7]">Cancel</button>
                          </div>
                        </form>
                      )}
                    </article>
                  );
                })}
              </div>
            </section>
          )}

          {selectedTarget && selectedTrackedJobId && (
            <section aria-labelledby="selected-next-action-title" className="mt-6 rounded-2xl border border-[#88BDF2]/60 bg-[#f7fafc] p-4">
              <p className="text-xs font-semibold uppercase tracking-[0.14em] text-[#6A89A7]">Selected target</p>
              <h2 id="selected-next-action-title" className="mt-1 font-semibold text-[#384959]">
                Next action: review the evidence, tailor your resume, then manage the application
              </h2>
              <p className="mt-1 text-sm text-[#6A89A7]">{selectedTarget.title} at {selectedTarget.company} is saved as one durable application.</p>
              <div className="mt-3 flex flex-wrap gap-2">
                <a href="#role-success-title" className="rounded-xl border border-[#BDDDFC] px-3 py-2 text-xs font-medium text-[#384959]">Review evidence</a>
                <button type="button" onClick={() => onTailorJob?.(selectedTarget, snapshot.case_facts.resume_version_id)} className="rounded-xl border border-[#BDDDFC] px-3 py-2 text-xs font-medium text-[#384959]">Tailor resume</button>
                <button type="button" onClick={() => onOpenApplication?.(selectedTrackedJobId)} className="rounded-xl bg-[#384959] px-3 py-2 text-xs font-medium text-white">Open application workspace</button>
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
                <div className="flex flex-wrap items-center gap-2">
                  {targetAssessment?.status === "completed" && (
                    <button
                      type="button"
                      onClick={handoffToResumeAgent}
                      disabled={busy || archived}
                      className="rounded-xl border border-[#384959] px-3 py-2 text-xs font-medium text-[#384959] disabled:opacity-40"
                    >
                      Draft resume edits for this job
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={assessTarget}
                    disabled={busy || archived || targetAssessment?.status === "completed"}
                    className="rounded-xl bg-[#384959] px-3 py-2 text-xs font-medium text-white disabled:opacity-40"
                  >
                    {targetAssessment?.status === "completed" ? "Assessment complete" : targetAssessment ? "Run assessment again" : "Run assessment"}
                  </button>
                </div>
              </div>
              {targetAssessment && (
                <div className="mt-4 space-y-3">
                  <div className="rounded-2xl border border-[#DCE7F2] p-4 text-xs">
                    <p className="font-medium capitalize text-[#384959]">{targetAssessment.status.replaceAll("_", " ")}</p>
                    <p className="mt-1 text-[#4A6785]">
                      {targetAssessment.status === "completed"
                        ? `${targetSpecialistCount} ${targetSpecialistCount === 1 ? "specialist" : "specialists"} reviewed this role against your evidence, then an independent judge reviewed their verdict.`
                        : "Specialist findings remain private until the independent review completes."}
                    </p>
                  </div>
                  <ExecutionDetails metrics={targetAssessment.execution_metrics} />
                  {reviewedTargetSpecialistRuns.map((run, index) => (
                    <SpecialistReport key={`${run.persona_id}-${index}`} run={run} />
                  ))}
                  {targetAssessment.status === "completed" && targetAssessment.synthesis && (
                    <article className="whitespace-pre-wrap rounded-2xl border border-[#BDDDFC]/60 p-4 text-sm text-[#384959]">
                      {targetAssessment.synthesis}
                      {(targetAssessment.synthesis_claims || []).length > 0 && (
                        <div className="mt-4 space-y-2 border-t border-[#EDF3F9] pt-3">
                          {(targetAssessment.synthesis_claims || []).map((claim, index) => (
                            <div key={`${claim.kind}-${index}`} className="whitespace-normal text-xs text-[#4A6785]">
                              <p>{claim.statement}</p>
                              <p className="mt-1 font-mono text-[10px] text-[#6A89A7]">
                                {[...(claim.criterion_ids || []), ...(claim.candidate_profile_field_ids || []), ...(claim.resume_evidence_ids || []), ...(claim.candidate_evidence_ids || [])].join(" · ")}
                              </p>
                            </div>
                          ))}
                        </div>
                      )}
                    </article>
                  )}
                  {targetAssessment.status === "completed" && targetAssessment.judge && (
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

          <ProposedEditsPanel
            edits={proposedEdits}
            onAccept={acceptEdits}
            onReject={rejectEdits}
            onStartConversation={startConversationWithResume}
            busy={busy || archived}
            result={editResult}
          />
        </div>

        <TeamActivityPanel
          events={events}
          busy={busy || persistedRunActive}
          awaitingAnswer={awaitingAnswer}
          foregroundRunId={busy ? foregroundRunId : ""}
        />
      </div>
    </section>
  );
}
