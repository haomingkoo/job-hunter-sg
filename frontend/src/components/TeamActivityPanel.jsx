import { useEffect, useMemo, useRef, useState } from "react";
import { ChevronDown } from "lucide-react";

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
  candidate_profiler: { name: "Candidate profiler", remit: "Builds your evidence profile from the resume" },
  recruiter: { name: "Recruiter screen", remit: "Judges it the way a first-pass screen would" },
  hiring_manager: { name: "Hiring manager", remit: "Checks the work against what the team needs" },
  ats: { name: "ATS and parsing", remit: "Reads it as the applicant tracking system will" },
  skeptic: { name: "Evidence skeptic", remit: "Attacks every claim that lacks proof" },
  market_researcher: { name: "Target-market analyst", remit: "Places the role in the current market" },
  judge: { name: "Independent judge", remit: "Reviews the team's verdict before you see it" },
};

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

function useElapsed(active) {
  const [now, setNow] = useState(() => Date.now());
  const startedAt = useRef(null);
  useEffect(() => {
    if (!active) {
      startedAt.current = null;
      return undefined;
    }
    startedAt.current = Date.now();
    setNow(Date.now());
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [active]);
  if (!active || !startedAt.current) return null;
  const total = Math.max(0, Math.floor((now - startedAt.current) / 1000));
  return `${String(Math.floor(total / 60)).padStart(2, "0")}:${String(total % 60).padStart(2, "0")}`;
}

// Tool names are an implementation detail. Say what the specialist is doing instead.
const TOOL_PHRASES = {
  write_todos: "planning its checks",
  read_candidate_evidence: "reading your evidence profile",
  read_target_job: "reading the job posting",
  ask_candidate: "asking you a question",
  propose_resume_edit: "drafting a resume edit",
  submit_target_specialist_assessment: "writing up its assessment",
  guarded_search_jobs: "searching current postings",
};

function humanize(summary, memberId) {
  if (!summary) return summary;
  const called = summary.match(/^(\w+) called (\w+)\.?$/);
  if (called) {
    const phrase = TOOL_PHRASES[called[2]];
    if (phrase) return phrase.charAt(0).toUpperCase() + phrase.slice(1);
  }
  // The row already names the agent, so drop a leading "ats ..." / "hiring_manager ..." subject.
  const withoutSubject = summary.replace(new RegExp(`^${memberId}\\s+`), "");
  return withoutSubject.charAt(0).toUpperCase() + withoutSubject.slice(1);
}

/** Latest run only: earlier runs are history, not live state. */
function buildRoster(events) {
  if (!events.length) return [];
  const latestRunId = events[events.length - 1].run_id;
  const byMember = new Map();
  for (const item of events) {
    if (item.run_id !== latestRunId) continue;
    const existing = byMember.get(item.team_member) || { id: item.team_member, steps: [] };
    // Keep every step. The old panel showed only the newest, which threw the tool loop away.
    existing.steps.push({
      key: item.sequence,
      summary: humanize(item.summary, item.team_member),
      status: item.status,
    });
    byMember.set(item.team_member, existing);
  }
  const rows = [];
  for (const row of byMember.values()) {
    // Stream order is not arrival order, so sequence decides both trail order and status.
    row.steps.sort((a, b) => a.key - b.key);
    // A repeated planning step is one step the user cares about, not five.
    row.steps = row.steps.filter((step, i) => i === 0 || step.summary !== row.steps[i - 1].summary);
    row.status = row.steps[row.steps.length - 1]?.status;
    // A specialist can submit and then be re-engaged, so its verdict is the last completed
    // step rather than the last step. Keep both: the verdict is what the candidate wants,
    // the live step is what reassures them something is still happening.
    row.conclusion = [...row.steps].reverse().find((step) => step.status === "completed");
    row.liveStep = row.status === "running" ? row.steps[row.steps.length - 1] : null;
    rows.push(row);
  }
  rows.sort((a, b) => (a.id === "coordinator" ? -1 : b.id === "coordinator" ? 1 : 0));
  return rows;
}

function AgentRow({ agent, defaultOpen }) {
  const [open, setOpen] = useState(defaultOpen);
  const meta = MEMBERS[agent.id] || { name: agent.id.replaceAll("_", " "), remit: "" };
  const state = statusOf(agent.status);
  const panelId = `agent-steps-${agent.id}`;
  const { conclusion, liveStep, steps: trail } = agent;

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

        {trail.length > 1 && (
          <ChevronDown
            size={14}
            aria-hidden="true"
            className={`mt-1 shrink-0 text-[#6A89A7] transition-transform ${open ? "rotate-180" : ""}`}
          />
        )}
      </button>

      {open && trail.length > 1 && (
        <ol id={panelId} className="space-y-1.5 border-t border-[#EDF3F9] bg-[#FAFCFE] px-3 py-2.5 pl-[3.25rem]">
          {trail.map((step) => (
            <li key={step.key} className="relative text-[11px] leading-relaxed text-[#4A6785]">
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
      )}
    </li>
  );
}

export default function TeamActivityPanel({ events, busy, awaitingAnswer }) {
  const roster = useMemo(() => buildRoster(events), [events]);
  const elapsed = useElapsed(busy);

  const specialists = roster.filter((a) => a.id !== "coordinator");
  // "Reported" means it has produced a verdict, even if it was re-engaged afterwards.
  const reported = specialists.filter((a) => a.conclusion).length;
  const active = roster.find((a) => a.status === "running");

  let headline = "Idle";
  if (awaitingAnswer) headline = "Waiting on your answer";
  else if (busy && active) headline = `${MEMBERS[active.id]?.name || active.id} is working`;
  else if (busy) headline = "Team is working";
  else if (roster.length) headline = "Run complete";

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
        {specialists.length > 0 && ` · ${reported} of ${specialists.length} reported`}
      </p>

      {busy && (
        <p className="mt-2 rounded-xl bg-[#EDF3F9] px-3 py-2 text-[11px] leading-relaxed text-[#33506B]">
          A full assessment runs several specialists and an independent judge. This usually takes a few
          minutes.
        </p>
      )}

      {roster.length === 0 ? (
        <p className="mt-4 text-xs leading-relaxed text-[#4A6785]">
          Your recruiter, hiring manager, ATS reader, evidence skeptic and market analyst start work
          after your first message.
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
