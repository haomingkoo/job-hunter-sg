import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import TeamActivityPanel from "../TeamActivityPanel.jsx";

/**
 * Tool names are an implementation detail. `humanize` maps them through
 * TOOL_PHRASES, and when it finds no phrase it falls back to stripping the
 * subject, so an unmapped tool renders to a candidate as "Called read_shortlist."
 *
 * A candidate has to be able to read three things off this panel: which tool
 * ran, what it looked for, and what came back.
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

  it("shows what a search looked for", () => {
    const text = renderEvents([
      activity("search_jobs", { query: "semiconductor yield analytics engineer" }),
    ]);

    expect(text).toContain("semiconductor yield analytics engineer");
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

  it("keeps two searches with different queries as two steps", () => {
    // The consecutive-duplicate filter used to collapse them, because both
    // rendered to the same phrase. A re-query after reading the first results is
    // the behaviour a candidate most needs to see.
    const text = renderEvents([
      activity("search_jobs", { query: "computer vision engineer" }),
      activity("search_jobs", { query: "semiconductor yield engineer" }),
    ]);

    expect(text).toContain("computer vision engineer");
    expect(text).toContain("semiconductor yield engineer");
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
});
