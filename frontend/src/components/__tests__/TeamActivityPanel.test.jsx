import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

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

    expect(text).toContain("1 of 1 reported");
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
        status: "failed",
        summary: "The coordinator reached its bounded execution limit.",
      }),
    ], { busy: false });

    expect(text).toContain("Run stopped before completion");
    expect(text).not.toContain("Run complete");
  });

  it("stops every stale working row when the latest run fails", () => {
    renderEvents([
      activity("read_candidate_evidence", {}, {
        team_member: "candidate_profiler",
        summary: "The candidate profiler is studying this resume.",
      }),
      activity("search_jobs", {}, { team_member: "coordinator" }),
      activity("search_jobs", {}, {
        sequence: 3,
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

  it("shows a held-back assessment and names the quality judge", () => {
    const text = renderEvents([
      activity("submit_target_assessment_judgment", {}, {
        event_type: "assessment",
        status: "quality_blocked",
        team_member: "quality_judge",
        summary: "The independent judge held this assessment back from the candidate.",
      }),
    ], { busy: false });

    expect(text).toContain("Assessment held back for review");
    expect(text).toContain("Independent judge");
    expect(text).toContain("Held back");
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

    expect(text).toContain("0 of 1 reported");
    expect(text).not.toContain("2 of 3 reported");
  });

  it("uses durable sequence order when reconnect events arrive out of order", () => {
    const completed = ["recruiter", "hiring_manager", "ats", "skeptic", "market_researcher"]
      .map((team_member, index) => activity("submit_target_specialist_assessment", {}, {
        sequence: 200 + index,
        run_id: "active-assessment",
        event_type: "assessment",
        status: "completed",
        team_member,
        summary: `${team_member} submitted its assessment.`,
      }));
    const lateOlderEvent = activity("search_jobs", {}, {
      sequence: 99,
      run_id: "older-conversation",
      event_type: "conversation",
    });

    const text = renderEvents([...completed, lateOlderEvent]);

    expect(text).toContain("5 of 5 reported");
    expect(text.match(/Reported/g)).toHaveLength(5);
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
