import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import TeamActivityPanel from "../TeamActivityPanel.jsx";

/**
 * Tool names are an implementation detail. `humanize` maps them through
 * TOOL_PHRASES, and when it finds no phrase it falls back to stripping the
 * subject, so an unmapped tool renders to a candidate as "Called read_shortlist."
 *
 * A candidate can see which tool ran and a content-free outcome. Inputs stay
 * out of durable activity even when they look harmless.
 */

let sequence = 0;

const activity = (toolName, detail = {}, overrides = {}) => ({
  sequence: (sequence += 1),
  run_id: "run-1",
  event_type: "conversation",
  status: "running",
  team_member: "coordinator",
  attempt: 1,
  trace_key: "trace-1",
  summary: `coordinator called ${toolName}.`,
  detail: { tool_name: toolName, stage: "call", ...detail },
  created_at: "2026-08-02T00:00:00Z",
  ...overrides,
});

describe("TeamActivityPanel tool phrasing", () => {
  let container;
  let root;

  beforeEach(() => {
    sequence = 0;
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  const renderEvents = (events) => {
    act(() => root.render(<TeamActivityPanel events={events} busy />));
    return container.textContent;
  };

  const render = (toolName, detail) => renderEvents([activity(toolName, detail)]);

  it("renders a candidate-facing phrase for a mapped tool", () => {
    const text = render("read_target_job");

    expect(text).toContain("Reading the job posting");
    expect(text).not.toContain("read_target_job");
  });

  it("phrases read_shortlist", () => {
    const text = render("read_shortlist");

    expect(text).toContain("Reading your shortlist");
    expect(text).not.toContain("read_shortlist");
  });

  it("phrases search_jobs", () => {
    const text = render("search_jobs");

    expect(text).toContain("Searching current postings");
    expect(text).not.toContain("search_jobs");
  });

  it("phrases the structured-reply tool", () => {
    const text = render("ConversationReply");

    expect(text).toContain("Writing your reply");
    expect(text).not.toContain("ConversationReply");
  });

  it("phrases a real specialist delegation", () => {
    const text = render("task");

    expect(text).toContain("Delegating a specialist review");
    expect(text).not.toContain("called task");
  });

  it("phrases the wrapped search tool the same as the unwrapped one", () => {
    // The assessment runner binds `guarded_search_jobs`; the coordinator binds
    // `search_jobs`. Keying on one bound name left the other unphrased.
    const text = render("guarded_search_jobs");

    expect(text).toContain("Searching current postings");
    expect(text).not.toContain("guarded_search_jobs");
  });

  it("falls back to the summary for a tool it has no phrase for", () => {
    const text = renderEvents([
      activity("some_new_tool", {}, { summary: "coordinator called some_new_tool." }),
    ]);

    expect(text).toContain("Called some_new_tool.");
  });
});

describe("TeamActivityPanel step content", () => {
  let container;
  let root;

  beforeEach(() => {
    sequence = 0;
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  const renderEvents = (events, props = {}) => {
    act(() => root.render(<TeamActivityPanel events={events} busy {...props} />));
    return container.textContent;
  };

  it("does not show a search input from legacy activity", () => {
    const text = renderEvents([
      activity("search_jobs", { query: "semiconductor yield analytics engineer" }),
    ]);

    expect(text).toContain("Searching current postings");
    expect(text).not.toContain("semiconductor yield analytics engineer");
  });

  it("shows what came back", () => {
    const text = renderEvents([
      activity("search_jobs", { query: "yield engineer" }),
      activity("search_jobs", { stage: "result", outcome: "2 matching postings" }, {
        summary: "coordinator finished search_jobs.",
      }),
    ]);

    expect(text).toContain("2 matching postings");
    expect(text).not.toContain("finished search_jobs");
  });

  it("preserves completion when a tool call and result have the same wording", () => {
    const text = renderEvents([
      activity("submit_target_specialist_assessment", {}, {
        event_type: "assessment",
        team_member: "ats",
      }),
      activity("submit_target_specialist_assessment", {}, {
        event_type: "assessment",
        status: "completed",
        team_member: "ats",
        detail: {
          tool_name: "submit_target_specialist_assessment",
          stage: "result",
        },
      }),
    ]);

    expect(text).toContain("1 reported");
    expect(text).not.toContain("1 of 1 reported");
    expect(text).toContain("Reported");
  });

  it("collapses repeated content-free search steps", () => {
    const text = renderEvents([
      activity("search_jobs", { query: "computer vision engineer" }),
      activity("search_jobs", { query: "semiconductor yield engineer" }),
    ]);

    expect(text).not.toContain("computer vision engineer");
    expect(text).not.toContain("semiconductor yield engineer");
    expect(text.match(/Searching current postings/g)).toHaveLength(1);
  });

  it("summarizes profiler checkpoints and keeps the full activity opt-in", () => {
    const events = [];
    const scopes = [
      ...Array.from({ length: 10 }, (_, index) => `experience_${String(index + 1).padStart(2, "0")}`),
      "__global_semantic_merge__",
      "__independent_evaluation__",
    ];
    scopes.forEach((scopeId, index) => {
      for (const transition of ["start", "checkpoint", "completion"]) {
        events.push(activity("", {
          transition,
          scope_id: scopeId,
          scope_count: scopes.length,
          completed_scope_count: transition === "completion" ? index + 1 : index,
        }, {
          event_type: "candidate_profile",
          team_member: "candidate_profiler",
          summary: `The candidate profiler ${transition} a resume scope.`,
        }));
      }
    });
    events.push(activity("", {
      transition: "failure",
      scope_id: "__independent_evaluation__",
      scope_count: scopes.length,
      completed_scope_count: scopes.length - 1,
    }, {
      event_type: "candidate_profile",
      status: "failed",
      team_member: "candidate_profiler",
      summary: "The candidate profiler stopped on a resume scope.",
    }));

    renderEvents(events, { busy: false });
    const profiler = [...container.querySelectorAll("button")]
      .find((button) => button.textContent.includes("Candidate profiler"));
    act(() => profiler.click());

    expect(container.textContent).toContain("Reading resume evidence");
    expect(container.textContent).toContain("Combining overlapping resume evidence");
    expect(container.textContent).toContain("Stopped while checking evidence support");
    expect(container.textContent).toContain(`View full activity (${events.length} events)`);
    expect(container.textContent).not.toContain("started a resume scope");
    expect(container.textContent).not.toContain("experience_01");

    const fullActivity = [...container.querySelectorAll("button")]
      .find((button) => button.textContent.includes("View full activity"));
    act(() => fullActivity.click());

    expect(container.textContent.match(/resume scope/g)).toHaveLength(events.length);
  });

  it("shows the newest profiler run instead of historical completed progress", () => {
    const events = [
      activity("", {
        transition: "completion",
        scope_id: "experience_01",
        scope_count: 3,
        completed_scope_count: 1,
      }, {
        event_type: "candidate_profile",
        status: "running",
        team_member: "candidate_profiler",
        summary: "The candidate profiler completed a resume scope.",
      }),
      activity("", {}, {
        event_type: "candidate_profile",
        status: "completed",
        team_member: "candidate_profiler",
        summary: "The candidate profiler completed the resume profile.",
      }),
      activity("", {}, {
        run_id: "run-2",
        event_type: "candidate_profile",
        status: "running",
        team_member: "candidate_profiler",
        summary: "The candidate profiler is checking the current resume evidence profile.",
      }),
    ];

    renderEvents(events);

    const profiler = [...container.querySelectorAll("button")]
      .find((button) => button.textContent.includes("Candidate profiler"));
    expect(profiler.textContent).toContain("Working");
    expect(profiler.textContent).not.toContain("Reported");
    expect(container.textContent).not.toContain("Reading resume evidence");
    expect(container.textContent).toContain(`View full activity (${events.length} events)`);
  });

  it("keeps identical durable profiler events in the opt-in audit", () => {
    const events = ["start", "start"].map((transition) => activity("", {
      transition,
      scope_id: "experience_01",
      scope_count: 3,
      completed_scope_count: 0,
    }, {
      event_type: "candidate_profile",
      team_member: "candidate_profiler",
      summary: "The candidate profiler started a resume scope.",
    }));

    renderEvents(events, { busy: false });
    const fullActivity = [...container.querySelectorAll("button")]
      .find((button) => button.textContent.includes("View full activity"));
    expect(fullActivity.textContent).toContain(`${events.length} events`);
    act(() => fullActivity.click());
    expect(container.textContent.match(/started a resume scope/g)).toHaveLength(events.length);
  });

  it("uses the durable profile recovery control and respects retryability", () => {
    const progress = activity("", {
      transition: "start",
      scope_id: "experience_01",
      scope_count: 3,
      completed_scope_count: 0,
    }, {
      event_type: "candidate_profile",
      team_member: "candidate_profiler",
      summary: "The candidate profiler started a resume scope.",
    });
    const retryableFailure = activity("", {
      command_type: "build_candidate_profile",
      retryable: true,
      recovery_action: "retry_incomplete_stage",
    }, {
      event_type: "run",
      status: "failed",
      team_member: "candidate_profiler",
      summary: "The candidate profiler could not complete the resume study.",
    });

    let text = renderEvents([progress, retryableFailure], { busy: false });
    expect(text).toContain("Use Resume profile to continue from saved progress");
    expect(text).not.toContain("Use Retry this turn");

    act(() => root.unmount());
    root = createRoot(container);
    const terminalFailure = {
      ...retryableFailure,
      sequence: retryableFailure.sequence + 1,
      detail: { ...retryableFailure.detail, retryable: false },
    };
    text = renderEvents([progress, terminalFailure], { busy: false });
    expect(text).toContain("Review the failure details before continuing");
    expect(text).not.toContain("continue from saved progress");
  });

  it("makes a terminal-only profile failure actionable after reload", () => {
    const events = [
      activity("", {}, {
        event_type: "run",
        team_member: "candidate_profiler",
        summary: "The candidate profiler started.",
      }),
      activity("", {
        command_type: "build_candidate_profile",
        retryable: true,
        recovery_action: "retry_incomplete_stage",
      }, {
        event_type: "run",
        status: "failed",
        team_member: "candidate_profiler",
        summary: "The candidate profiler could not complete the resume study.",
      }),
    ];

    const text = renderEvents(events, { busy: false });

    expect(text).toContain("Profile stopped. Use Resume profile to continue from saved progress.");
    expect(text).not.toContain("could not complete the resume study");
  });

  it("keeps completed steps when a later run starts", () => {
    const text = renderEvents([
      activity("search_jobs", { query: "manufacturing manager" }),
      activity("ConversationReply", {}, { status: "completed" }),
      activity("search_jobs", { query: "operations manager" }, { run_id: "run-2" }),
    ]);

    expect(text).not.toContain("manufacturing manager");
    expect(text).toContain("Writing your reply");
    expect(text).not.toContain("operations manager");
  });

  it("promises specialists and a judge only while an assessment is running", () => {
    const chatting = renderEvents([activity("search_jobs", { query: "yield engineer" })]);
    expect(chatting).not.toContain("independent judge");

    act(() => root.unmount());
    root = createRoot(container);

    const assessing = renderEvents([
      activity("read_target_job", {}, { event_type: "assessment" }),
    ]);
    expect(assessing).toContain("independent judge");
  });

  it("does not label a failed latest run complete", () => {
    const text = renderEvents([
      activity("read_target_job", {}, {
        event_type: "run",
        status: "failed",
        summary: "The coordinator reached its bounded execution limit.",
      }),
    ], { busy: false });

    expect(text).toContain("Run stopped before completion");
    expect(text).not.toContain("Run complete");
  });

  it("stops stale working rows from the failed run", () => {
    renderEvents([
      activity("read_candidate_evidence", {}, {
        team_member: "candidate_profiler",
        summary: "The candidate profiler is studying this resume.",
      }),
      activity("search_jobs", {}, { team_member: "coordinator" }),
      activity("search_jobs", {}, {
        sequence: 3,
        event_type: "run",
        status: "failed",
        team_member: "coordinator",
        summary: "The coordinator stopped before completion.",
      }),
    ], { busy: false });

    const profiler = [...container.querySelectorAll("button")]
      .find((button) => button.textContent.includes("Candidate profiler"));
    expect(profiler.textContent).toContain("Stopped");
    expect(profiler.textContent).not.toContain("Working");
  });

  it("keeps a separate profiler run working when the foreground run fails", () => {
    const text = renderEvents([
      activity("read_candidate_evidence", {}, {
        run_id: "profile-run",
        team_member: "candidate_profiler",
        summary: "The candidate profiler is studying this resume.",
      }),
      activity("search_jobs", {}, {
        sequence: 2,
        run_id: "foreground-run",
        team_member: "coordinator",
      }),
      activity("search_jobs", {}, {
        sequence: 3,
        run_id: "foreground-run",
        event_type: "run",
        status: "failed",
        team_member: "coordinator",
        summary: "The coordinator stopped before completion.",
      }),
    ], { busy: false });

    expect(text).toContain("Candidate profiler is working");
    const profiler = [...container.querySelectorAll("button")]
      .find((button) => button.textContent.includes("Candidate profiler"));
    expect(profiler.textContent).toContain("Working");
    expect(profiler.textContent).not.toContain("Stopped");
  });

  it("reconciles an older terminal run after a newer background run starts", () => {
    renderEvents([
      activity("submit_target_assessment_synthesis", {}, {
        sequence: 1,
        run_id: "assessment-run",
        event_type: "assessment",
        team_member: "coordinator",
      }),
      activity("submit_target_assessment_judgment", {}, {
        sequence: 2,
        run_id: "assessment-run",
        event_type: "run",
        status: "completed",
        team_member: "quality_judge",
      }),
      activity("read_candidate_evidence", {}, {
        sequence: 3,
        run_id: "profile-run",
        event_type: "candidate_profile",
        team_member: "candidate_profiler",
      }),
    ], { busy: false });

    const coordinator = [...container.querySelectorAll("button")]
      .find((button) => button.textContent.includes("Coordinator"));
    expect(coordinator.textContent).toContain("Reported");
    expect(coordinator.textContent).not.toContain("Working");
  });

  it("keeps an older same-member run visible while it is genuinely active", () => {
    renderEvents([
      activity("read_candidate_evidence", {}, {
        sequence: 1,
        run_id: "background-profile",
        event_type: "candidate_profile",
        team_member: "candidate_profiler",
      }),
      activity("read_candidate_evidence", {}, {
        sequence: 2,
        run_id: "foreground-profile",
        event_type: "run",
        status: "running",
        team_member: "candidate_profiler",
      }),
      activity("read_candidate_evidence", {}, {
        sequence: 3,
        run_id: "foreground-profile",
        event_type: "run",
        status: "completed",
        team_member: "candidate_profiler",
      }),
    ], { busy: false });

    const profiler = [...container.querySelectorAll("button")]
      .find((button) => button.textContent.includes("Candidate profiler"));
    expect(profiler.textContent).toContain("Working");
    expect(profiler.textContent).not.toContain("Reported");
  });

  it("keeps a newer same-member run visible when the older run finishes", () => {
    renderEvents([
      activity("read_candidate_evidence", {}, {
        sequence: 1,
        run_id: "background-profile",
        event_type: "candidate_profile",
        team_member: "candidate_profiler",
        summary: "The candidate profiler is studying this resume.",
      }),
      activity("read_candidate_evidence", {}, {
        sequence: 2,
        run_id: "foreground-profile",
        event_type: "run",
        status: "running",
        team_member: "candidate_profiler",
        summary: "The candidate profiler is studying this resume.",
      }),
      activity("read_candidate_evidence", {}, {
        sequence: 3,
        run_id: "background-profile",
        event_type: "candidate_profile",
        status: "completed",
        team_member: "candidate_profiler",
      }),
    ], { busy: false });

    const profiler = [...container.querySelectorAll("button")]
      .find((button) => button.textContent.includes("Candidate profiler"));
    expect(profiler.textContent).toContain("Working");
    expect(profiler.textContent).not.toContain("Reported");
  });

  it("shows the highest-sequence live step across active same-member runs", () => {
    const text = renderEvents([
      activity("read_candidate_evidence", {}, {
        sequence: 1,
        run_id: "profile-a",
        event_type: "candidate_profile",
        team_member: "candidate_profiler",
      }),
      activity("read_candidate_evidence", {}, {
        sequence: 2,
        run_id: "profile-b",
        event_type: "candidate_profile",
        team_member: "candidate_profiler",
      }),
      activity("candidate_profile_progress", {}, {
        sequence: 3,
        run_id: "profile-a",
        event_type: "candidate_profile",
        team_member: "candidate_profiler",
        summary: "candidate_profiler resumed the older study.",
      }),
    ], { busy: false });

    expect(text).toContain("Resumed the older study.");
  });

  it("uses the latest lifecycle event when a failed run is retried", () => {
    const text = renderEvents([
      activity("search_jobs", {}, { event_type: "run" }),
      activity("search_jobs", {}, { event_type: "run", status: "failed" }),
      activity("search_jobs", {}, { event_type: "run", status: "running" }),
    ], { busy: true });

    expect(text).toContain("Coordinator is working");
    expect(text).not.toContain("Run stopped before completion");
    const coordinator = [...container.querySelectorAll("button")]
      .find((button) => button.textContent.includes("Coordinator"));
    expect(coordinator.textContent).toContain("Working");
  });

  it("shows completion when a failed run succeeds on retry", () => {
    const text = renderEvents([
      activity("search_jobs", {}, { event_type: "run" }),
      activity("search_jobs", {}, { event_type: "run", status: "failed" }),
      activity("search_jobs", {}, { event_type: "run", status: "running" }),
      activity("search_jobs", {}, { event_type: "run", status: "completed" }),
    ], { busy: false });

    expect(text).toContain("Run complete");
    expect(text).not.toContain("Run stopped before completion");
  });

  it("keeps paused work out of a terminal reported state", () => {
    const text = renderEvents([
      activity("read_target_job", {}, {
        event_type: "assessment",
        team_member: "role_profiler",
      }),
      activity("ask_candidate", {}, {
        event_type: "run",
        status: "completed",
        team_member: "coordinator",
        detail: { reply_mode: "paused" },
      }),
    ], { busy: false, awaitingAnswer: true });

    expect(text).toContain("Waiting on your answer");
    const roleProfiler = [...container.querySelectorAll("button")]
      .find((button) => button.textContent.includes("Role profiler"));
    expect(roleProfiler.textContent).toContain("Waiting on you");
    expect(roleProfiler.textContent).not.toContain("Reported");
  });

  it("does not leave the coordinator working after the judge completes the run", () => {
    const text = renderEvents([
      activity("submit_target_assessment_synthesis", {}, {
        event_type: "assessment",
        team_member: "coordinator",
      }),
      activity("submit_target_assessment_judgment", {}, {
        event_type: "run",
        status: "completed",
        team_member: "quality_judge",
        summary: "The independent quality judge completed this turn.",
      }),
    ], { busy: false });

    expect(text).toContain("Run complete");
    const coordinator = [...container.querySelectorAll("button")]
      .find((button) => button.textContent.includes("Coordinator"));
    expect(coordinator.textContent).toContain("Reported");
    expect(coordinator.textContent).not.toContain("Working");
  });

  it("preserves held-back status through the terminal failure wrapper", () => {
    const text = renderEvents([
      activity("submit_target_assessment_synthesis", {}, {
        event_type: "assessment",
        team_member: "coordinator",
      }),
      activity("submit_target_assessment_judgment", {}, {
        event_type: "assessment",
        status: "quality_blocked",
        team_member: "quality_judge",
      }),
      activity("submit_target_assessment_judgment", {}, {
        event_type: "run",
        status: "failed",
        team_member: "coordinator",
        detail: { failure_code: "quality_gate_blocked" },
      }),
    ], { busy: false });

    expect(text).toContain("Assessment held back for review");
    expect(text).not.toContain("Run stopped before completion");
    const coordinator = [...container.querySelectorAll("button")]
      .find((button) => button.textContent.includes("Coordinator"));
    expect(coordinator.textContent).toContain("Held back");
  });

  it("counts only specialist reports from the active assessment", () => {
    const text = renderEvents([
      activity("submit_target_specialist_assessment", {}, {
        run_id: "old-assessment",
        event_type: "assessment",
        status: "completed",
        team_member: "recruiter",
        summary: "Recruiter submitted its assessment.",
      }),
      activity("read_candidate_evidence", {}, {
        run_id: "active-assessment",
        event_type: "assessment",
        status: "completed",
        team_member: "candidate_profiler",
        summary: "Candidate profile completed.",
      }),
      activity("submit_target_specialist_assessment", {}, {
        run_id: "active-assessment",
        event_type: "assessment",
        status: "running",
        team_member: "recruiter",
        summary: "Recruiter revisited the evidence.",
      }),
      activity("submit_target_assessment_judgment", {}, {
        run_id: "active-assessment",
        event_type: "assessment",
        status: "running",
        team_member: "quality_judge",
        summary: "The independent judge started review.",
      }),
    ]);

    expect(text).toContain("0 reported");
    expect(text).not.toContain("0 of 1 reported");
    expect(text).not.toContain("2 of 3 reported");
  });

  it("uses an authoritative required-specialist count when an event supplies it", () => {
    const text = renderEvents([
      activity("read_target_job", { required_specialist_count: 5 }, {
        run_id: "assessment-run",
        event_type: "assessment",
      }),
      activity("submit_target_specialist_assessment", {}, {
        run_id: "assessment-run",
        event_type: "assessment",
        status: "completed",
        team_member: "recruiter",
      }),
    ]);

    expect(text).toContain("1 of 5 reported");
  });

  it("keeps the explicit foreground run visible when a background profiler reports later", () => {
    const text = renderEvents([
      activity("read_target_job", {}, {
        sequence: 10,
        run_id: "assessment-run",
        event_type: "assessment",
        team_member: "coordinator",
      }),
      activity("read_candidate_evidence", {}, {
        sequence: 11,
        run_id: "profile-run",
        event_type: "candidate_profile",
        team_member: "candidate_profiler",
      }),
    ], { foregroundRunId: "assessment-run" });

    expect(text).toContain("Coordinator is working");
    expect(text).toContain("independent judge");
    expect(text).not.toContain("Candidate profiler is working");
  });

  it("deduplicates and orders reconnect events before choosing lifecycle state", () => {
    const completed = activity("ConversationReply", {}, {
      sequence: 3,
      event_type: "run",
      status: "completed",
    });
    const text = renderEvents([
      completed,
      activity("search_jobs", {}, { sequence: 1, event_type: "run" }),
      activity("search_jobs", {}, { sequence: 2 }),
      { ...completed },
    ], { busy: false });

    expect(text).toContain("Run complete");
    expect(text).not.toContain("Coordinator is working");
  });

  it("derives elapsed time from the durable run timestamp", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-08-02T00:02:05Z"));
    try {
      renderEvents([
        activity("search_jobs", {}, {
          sequence: 1,
          event_type: "run",
          created_at: "2026-08-02T00:00:00Z",
        }),
      ]);

      expect(container.querySelector('[aria-label="Elapsed 02:05"]')).not.toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  it("does not carry an old assessment count into the active conversation", () => {
    const text = renderEvents([
      activity("submit_target_specialist_assessment", {}, {
        run_id: "old-assessment",
        event_type: "assessment",
        status: "completed",
        team_member: "recruiter",
        summary: "Recruiter submitted its assessment.",
      }),
      activity("search_jobs", {}, {
        run_id: "active-conversation",
        event_type: "conversation",
        status: "running",
      }),
    ]);

    expect(text).not.toContain("reported");
  });

  it("names target profiling as role-profiler work", () => {
    const text = renderEvents([
      activity("select_target", {}, {
        event_type: "run",
        status: "completed",
        team_member: "role_profiler",
        summary: "The role profiler completed this turn.",
      }),
    ], { busy: false });

    expect(text).toContain("Role profiler");
    expect(text).toContain("Builds the target role's source-backed success profile");
    expect(text).toContain("Reported");
  });
});
