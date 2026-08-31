import { useEffect, useMemo, useState } from "react";
import { ChevronDown } from "lucide-react";

import { activityDetail } from "../lib/recruitmentActivity.js";

/**
 * Renders the specialists as persistent identities rather than as a log. Every member
 * keeps its row for the whole run: waiting, working, then reported with its own findings.
 *
 * Only tool steps and submitted conclusions are shown. Private reasoning never reaches
 * this component, per the never-leak-reasoning invariant.
 */

// display_name values come from recruitment_team/persona_packs/v1/personas.json.
const MEMBERS = {
  coordinator: { name: "Coordinator", remit: "Runs the brief and decides who works next" },
  job_search: { name: "Job search", remit: "Runs the deterministic posting search and profile-aware ranking" },
  candidate_profiler: { name: "Candidate profiler", remit: "Builds your evidence profile from the resume" },
  role_profiler: { name: "Role profiler", remit: "Builds the target role's source-backed success profile" },
  recruiter: { name: "Recruiter screen", remit: "Judges it the way a first-pass screen would" },
  hiring_manager: { name: "Hiring manager", remit: "Checks the work against what the team needs" },
  ats: { name: "ATS and parsing", remit: "Reads it as the applicant tracking system will" },
  skeptic: { name: "Evidence skeptic", remit: "Attacks every claim that lacks proof" },
  market_researcher: { name: "Target-market analyst", remit: "Places the role in the current market" },
  quality_judge: { name: "Independent judge", remit: "Reviews the team's verdict before you see it" },
};

const SPECIALIST_IDS = new Set([
  "recruiter",
  "hiring_manager",
  "ats",
  "skeptic",
  "market_researcher",
]);

// Phrased for a candidate, not a job runner.
const STATUS = {
  running: { label: "Working", dot: "bg-[#88BDF2]", pulse: true, text: "text-[#2F6FAE]" },
  paused: { label: "Waiting on you", dot: "bg-amber-500", pulse: true, text: "text-amber-800" },
  completed: { label: "Reported", dot: "bg-emerald-600", pulse: false, text: "text-emerald-800" },
  failed: { label: "Stopped", dot: "bg-[#94A9BE]", pulse: false, text: "text-[#4A6785]" },
  quality_blocked: { label: "Held back", dot: "bg-amber-600", pulse: false, text: "text-amber-800" },
};

function statusOf(key) {
  return STATUS[key] || { label: "Waiting", dot: "bg-[#C6D4E1]", pulse: false, text: "text-[#4A6785]" };
}

function monogram(id) {
  const name = MEMBERS[id]?.name || id.replaceAll("_", " ");
  const words = name.split(/\s+/).filter(Boolean);
  return (words.length > 1 ? words[0][0] + words[1][0] : name.slice(0, 2)).toUpperCase();
}

function useElapsed(active, startedAt) {
  const [now, setNow] = useState(() => Date.now());
  const startedAtMs = Date.parse(startedAt || "");
  useEffect(() => {
    if (!active || !Number.isFinite(startedAtMs)) return undefined;
    setNow(Date.now());
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [active, startedAtMs]);
  if (!active || !Number.isFinite(startedAtMs)) return null;
  const total = Math.max(0, Math.floor((now - startedAtMs) / 1000));
  return `${String(Math.floor(total / 60)).padStart(2, "0")}:${String(total % 60).padStart(2, "0")}`;
}

// Tool names are an implementation detail. Say what the specialist is doing instead.
const TOOL_PHRASES = {
  write_todos: "planning its checks",
  read_candidate_evidence: "reading your evidence profile",
  read_target_job: "reading the job posting",
  read_shortlist: "reading your shortlist",
  search_jobs: "searching current postings",
  ask_candidate: "asking you a question",
  propose_resume_edit: "drafting a resume edit",
  task: "delegating a specialist review",
  submit_target_specialist_assessment: "writing up its assessment",
  ConversationReply: "writing your reply",
};

/**
 * The same tool is bound under two names: the assessment runner wraps search as
 * `guarded_search_jobs`, the coordinator binds `search_jobs`. Keying on the raw
 * bound name meant the most common tool in a run fell through to generic
 * wording on whichever path was not spelled here.
 */
function normalizeTool(toolName) {
  return String(toolName || "").replace(/^guarded_/, "");
}

function capitalize(text) {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function humanize(item) {
  const summary = item.summary;
  if (!summary) return summary;
  const detail = activityDetail(item);

  // What came back. Counts and named outcomes only: no tool ever returns its
  // raw payload to this panel.
  if (detail.stage === "result" && detail.outcome) return capitalize(detail.outcome);

  const tool = normalizeTool(detail.tool_name);
  const phrase = TOOL_PHRASES[tool];
  if (phrase) return capitalize(phrase);

  // The row already names the agent, so drop a leading "ats ..." / "hiring_manager ..." subject.
  const memberPrefix = `${item.team_member} `;
  return capitalize(summary.startsWith(memberPrefix) ? summary.slice(memberPrefix.length) : summary);
}

function profileStage(scopeId) {
  if (scopeId === "__global_semantic_merge__" || scopeId === "__global_correction__") {
    return { key: "combine", label: "Combining overlapping resume evidence" };
  }
  if (scopeId === "__independent_evaluation__") {
    return { key: "evaluate", label: "Checking evidence support" };
  }
  return { key: "evidence", label: "Reading resume evidence" };
}

function profileRecoveryText(detail) {
  if (detail?.retryable !== true) return "Review the failure details before continuing.";
  if (["start_thread", "send_message", "answer_assessment_question"].includes(detail?.command_type)) {
    return "Use Retry this turn to continue from saved progress.";
  }
  if (detail?.command_type === "build_candidate_profile") {
    return "Use Resume profile to continue from saved progress.";
  }
  return "Try the available recovery action to continue from saved progress.";
}

function summarizeProfileProgress(step, terminalDetail) {
  const transition = step.detail?.transition;
  const stage = profileStage(step.detail?.scope_id);
  const completed = Number(step.detail?.completed_scope_count);
  const total = Number(step.detail?.scope_count);
  const progress = Number.isInteger(completed) && Number.isInteger(total) && total > 0
    ? ` · ${Math.min(completed, total)} of ${total} checks complete`
    : "";
  let summary = stage.label;
  if (transition === "correction") summary = `Rechecking ${stage.label.toLowerCase()}`;
  if (transition === "failure") {
    summary = `Stopped while ${stage.label.toLowerCase()} · ${profileRecoveryText(terminalDetail)}`;
  }
  return { ...step, profileStage: stage.key, summary: `${summary}${progress}` };
}

function projectCandidateProfilerSteps(steps) {
  const progressByStage = new Map();
  const terminal = [];
  const terminalFailure = [...steps].reverse().find((step) => step.status === "failed");
  for (const step of steps) {
    if (step.detail?.transition) {
      const summary = summarizeProfileProgress(step, terminalFailure?.detail);
      progressByStage.set(`${step.runId}:${summary.profileStage}`, summary);
    } else if (step.status !== "running") {
      terminal.push(step.status === "failed" ? {
        ...step,
        summary: `Profile stopped. ${profileRecoveryText(step.detail)}`,
      } : step);
    }
  }
  if (progressByStage.size === 0) return terminal.length ? terminal : steps;
  return [...progressByStage.values(), ...terminal].sort((a, b) => a.key - b.key);
}

/** Preserve the thread's completed work as later runs add new steps. */
function buildRoster(events) {
  if (!events.length) return [];
  const byMember = new Map();
  const lifecycleByRun = new Map();
  for (const item of events) {
    if (item.event_type === "run") {
      const current = lifecycleByRun.get(item.run_id);
      if (!current || Number(item.sequence) > Number(current.sequence)) {
        lifecycleByRun.set(item.run_id, item);
      }
    }
    const existing = byMember.get(item.team_member) || { id: item.team_member, steps: [] };
    // Keep every step. The old panel showed only the newest, which threw the tool loop away.
    existing.steps.push({
      key: item.sequence,
      runId: item.run_id,
      summary: humanize(item),
      status: item.status,
      detail: activityDetail(item),
    });
    byMember.set(item.team_member, existing);
  }
  const rows = [];
  for (const row of byMember.values()) {
    // Stream order is not arrival order, so sequence decides both trail order and status.
    row.steps.sort((a, b) => a.key - b.key);
    row.auditSteps = [...row.steps];
    // Collapse repeated narration, but never erase a state transition. A tool
    // call and its accepted result can intentionally share candidate-facing
    // wording while carrying different running/completed states.
    row.steps = row.steps.filter((step, i) => (
      i === 0
      || step.summary !== row.steps[i - 1].summary
      || step.status !== row.steps[i - 1].status
      || step.runId !== row.steps[i - 1].runId
    ));
    if (row.id === "candidate_profiler") {
      const latestByProfilerRun = new Map();
      for (const step of row.steps) latestByProfilerRun.set(step.runId, step);
      const activeProfilerStep = [...latestByProfilerRun.values()]
        .filter((step) => (
          step.status === "running" && !statusFromLifecycle(lifecycleByRun.get(step.runId))
        ))
        .reduce((latest, step) => (!latest || step.key > latest.key ? step : latest), null);
      const latestProfilerRunId = activeProfilerStep?.runId || row.steps.at(-1)?.runId;
      row.steps = projectCandidateProfilerSteps(
        row.steps.filter((step) => step.runId === latestProfilerRunId),
      );
    }
    const latestByRun = new Map();
    for (const step of row.steps) latestByRun.set(step.runId, step);
    const latestActiveStep = [...latestByRun.values()]
      .filter((step) => (
        step.status === "running" && !statusFromLifecycle(lifecycleByRun.get(step.runId))
      ))
      .reduce((latest, step) => (!latest || step.key > latest.key ? step : latest), null);
    const latestStep = latestActiveStep || row.steps.at(-1);
    const lifecycleStatus = statusFromLifecycle(lifecycleByRun.get(latestStep?.runId));
    row.status = lifecycleStatus && ["running", "failed"].includes(latestStep?.status)
      ? lifecycleStatus
      : latestStep?.status;
    // A specialist can submit and then be re-engaged, so its verdict is the last completed
    // step rather than the last step. Keep both: the verdict is what the candidate wants,
    // the live step is what reassures them something is still happening.
    row.conclusion = row.status === "failed"
      ? [...row.steps].reverse().find((step) => step.status === "failed")
      : [...row.steps].reverse().find((step) => step.status === "completed");
    row.liveStep = row.status === "running" ? latestStep : null;
    rows.push(row);
  }
  rows.sort((a, b) => (a.id === "coordinator" ? -1 : b.id === "coordinator" ? 1 : 0));
  return rows;
}

function statusFromLifecycle(lifecycle) {
  if (!lifecycle || lifecycle.status === "running") return null;
  if (lifecycle.detail?.failure_code === "quality_gate_blocked") return "quality_blocked";
  if (lifecycle.status === "failed") return "failed";
  if (lifecycle.status === "completed") {
    return lifecycle.detail?.reply_mode === "paused" ? "paused" : "completed";
  }
  return null;
}

function AgentRow({ agent, defaultOpen }) {
  const [open, setOpen] = useState(defaultOpen);
  const [auditOpen, setAuditOpen] = useState(false);
  const meta = MEMBERS[agent.id] || { name: agent.id.replaceAll("_", " "), remit: "" };
  const state = statusOf(agent.status);
  const panelId = `agent-steps-${agent.id}`;
  const { conclusion, liveStep, steps: trail, auditSteps = trail } = agent;
  const hasCondensedTrail = agent.id === "candidate_profiler" && auditSteps.length > trail.length;

  return (
    <li className="overflow-hidden rounded-2xl border border-[#DCE7F2] bg-white">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-controls={panelId}
        className="flex w-full items-start gap-3 p-3 text-left transition-colors hover:bg-[#F7FAFD] focus:outline-none focus-visible:ring-2 focus-visible:ring-[#88BDF2]"
      >
        <span
          aria-hidden="true"
          className="mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-xl bg-[#EDF3F9] text-[11px] font-bold tracking-wide text-[#384959]"
        >
          {monogram(agent.id)}
        </span>

        <span className="min-w-0 flex-1">
          <span className="flex items-center justify-between gap-2">
            <span className="truncate text-sm font-semibold text-[#384959]">{meta.name}</span>
            <span className={`flex shrink-0 items-center gap-1.5 text-[11px] font-medium ${state.text}`}>
              <span className={`h-1.5 w-1.5 rounded-full ${state.dot} ${state.pulse ? "animate-pulse" : ""}`} />
              {state.label}
            </span>
          </span>
          {meta.remit && <span className="mt-0.5 block truncate text-[11px] text-[#4A6785]">{meta.remit}</span>}

          {conclusion?.summary && (
            <span className="mt-1.5 block text-xs font-medium leading-relaxed text-[#33506B]">
              {conclusion.summary}
            </span>
          )}

          {liveStep?.summary && (
            <span className="mt-1.5 flex items-center gap-1.5 text-[11px] italic text-[#4A6785]">
              <span aria-hidden="true" className="h-1 w-1 shrink-0 animate-pulse rounded-full bg-[#88BDF2]" />
              {liveStep.summary}
            </span>
          )}
        </span>

        {(trail.length > 1 || hasCondensedTrail) && (
          <ChevronDown
            size={14}
            aria-hidden="true"
            className={`mt-1 shrink-0 text-[#6A89A7] transition-transform ${open ? "rotate-180" : ""}`}
          />
        )}
      </button>

      {open && (trail.length > 1 || hasCondensedTrail) && (
        <div id={panelId} className="border-t border-[#EDF3F9] bg-[#FAFCFE] px-3 py-2.5 pl-[3.25rem]">
          <ol className="space-y-1.5">
            {trail.map((step) => (
              <li key={`${step.runId}-${step.key}`} className="relative text-[11px] leading-relaxed text-[#4A6785]">
                <span
                  aria-hidden="true"
                  className={`absolute -left-3.5 top-1.5 h-1 w-1 rounded-full ${
                    step.status === "completed" ? "bg-emerald-500" : "bg-[#BDDDFC]"
                  }`}
                />
                {step.summary}
              </li>
            ))}
          </ol>
          {hasCondensedTrail && (
            <div className="mt-2 border-t border-[#EDF3F9] pt-2">
              <button
                type="button"
                onClick={() => setAuditOpen((value) => !value)}
                className="text-[11px] font-medium text-[#33506B] underline decoration-[#BDDDFC] underline-offset-2"
              >
                {auditOpen ? "Hide full activity" : `View full activity (${auditSteps.length} events)`}
              </button>
              {auditOpen && (
                <ol className="mt-2 space-y-1.5 border-l border-[#DCE7F2] pl-3">
                  {auditSteps.map((step) => (
                    <li key={`audit-${step.runId}-${step.key}`} className="text-[11px] leading-relaxed text-[#4A6785]">
                      {step.summary}
                    </li>
                  ))}
                </ol>
              )}
            </div>
          )}
        </div>
      )}
    </li>
  );
}

export default function TeamActivityPanel({ events, busy, awaitingAnswer, foregroundRunId = "" }) {
  // The parent keeps this collection deduplicated and ordered at its state boundary.
  const roster = useMemo(() => buildRoster(events), [events]);
  const latestRunId = foregroundRunId || events.at(-1)?.run_id;
  const latestRunEvents = useMemo(
    () => events.filter((item) => item.run_id === latestRunId),
    [events, latestRunId],
  );
  const elapsed = useElapsed(busy, latestRunEvents[0]?.created_at);
  // Only a full assessment runs specialists and a judge. A chat turn now streams
  // its own tool steps through this panel, and promising it several minutes of
  // specialists would be a lie on every message.
  const assessing = useMemo(() => {
    return latestRunEvents.some((item) => item.event_type === "assessment");
  }, [latestRunEvents]);

  const latestRunRoster = useMemo(
    () => buildRoster(latestRunEvents),
    [latestRunEvents],
  );
  const specialists = latestRunRoster.filter((agent) => SPECIALIST_IDS.has(agent.id));
  // "Reported" means it has produced a verdict, even if it was re-engaged afterwards.
  const reported = specialists.filter((a) => a.conclusion).length;
  const requiredSpecialistCount = latestRunEvents.reduce((known, item) => {
    const count = Number(item.detail?.required_specialist_count);
    return Number.isInteger(count) && count > 0 ? count : known;
  }, null);
  const latestRunActive = latestRunRoster.find((agent) => agent.status === "running");
  const active = roster.find((agent) => agent.status === "running");
  const latestRunStatus = statusFromLifecycle(
    latestRunEvents.findLast((item) => item.event_type === "run"),
  );

  let headline = "Idle";
  if (awaitingAnswer) headline = "Waiting on your answer";
  else if (busy && latestRunActive) {
    headline = `${MEMBERS[latestRunActive.id]?.name || latestRunActive.id} is working`;
  }
  else if (busy) headline = "Team is working";
  else if (active) headline = `${MEMBERS[active.id]?.name || active.id} is working`;
  else if (latestRunStatus === "quality_blocked") headline = "Assessment held back for review";
  else if (latestRunStatus === "failed") headline = "Run stopped before completion";
  else if (latestRunStatus === "completed") headline = "Run complete";

  return (
    <aside className="rounded-3xl border border-[#DCE7F2] bg-[#F5F8FB] p-4">
      <div className="flex items-baseline justify-between gap-2">
        <h2 className="text-sm font-semibold text-[#384959]">Your team</h2>
        {elapsed && (
          <span className="font-mono text-[11px] tabular-nums text-[#4A6785]" aria-label={`Elapsed ${elapsed}`}>
            {elapsed}
          </span>
        )}
      </div>

      <p className="mt-0.5 text-[11px] text-[#4A6785]" aria-live="polite">
        {headline}
        {assessing && specialists.length > 0 && (
          requiredSpecialistCount
            ? ` · ${reported} of ${requiredSpecialistCount} reported`
            : ` · ${reported} reported`
        )}
      </p>

      {busy && assessing && (
        <p className="mt-2 rounded-xl bg-[#EDF3F9] px-3 py-2 text-[11px] leading-relaxed text-[#33506B]">
          A full assessment runs several specialists and an independent judge. This usually takes a few
          minutes.
        </p>
      )}

      {roster.length === 0 ? (
        <p className="mt-4 text-xs leading-relaxed text-[#4A6785]">
          The candidate profiler checks your evidence first; the coordinator follows with that profile.
        </p>
      ) : (
        <ol className="mt-3 space-y-2">
          {roster.map((agent) => (
            <AgentRow key={agent.id} agent={agent} defaultOpen={agent.status === "running"} />
          ))}
        </ol>
      )}
    </aside>
  );
}
