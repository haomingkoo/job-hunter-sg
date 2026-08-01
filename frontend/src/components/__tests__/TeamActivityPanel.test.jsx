import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import TeamActivityPanel from "../TeamActivityPanel.jsx";

/**
 * Tool names are an implementation detail. `humanize` maps them through
 * TOOL_PHRASES, and when it finds no phrase it falls back to stripping the
 * subject, so an unmapped tool renders to a candidate as "Called read_shortlist."
 *
 * The three `it.fails` cases below are the #146 coordinator tools. They fail
 * today because TOOL_PHRASES does not know them. Flip them to `it` in the same
 * change that adds the phrases (docs/v4-146-coordinator-loop.md §7).
 */

const activity = (toolName) => ({
  sequence: 1,
  run_id: "run-1",
  event_type: "conversation",
  status: "running",
  team_member: "coordinator",
  attempt: 1,
  trace_key: "trace-1",
  summary: `coordinator called ${toolName}.`,
  detail: { tool_name: toolName },
  created_at: "2026-08-02T00:00:00Z",
});

describe("TeamActivityPanel tool phrasing", () => {
  let container;
  let root;

  beforeEach(() => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  const render = (toolName) => {
    act(() => root.render(<TeamActivityPanel events={[activity(toolName)]} busy />));
    return container.textContent;
  };

  it("renders a candidate-facing phrase for a mapped tool", () => {
    const text = render("read_target_job");

    expect(text).toContain("Reading the job posting");
    expect(text).not.toContain("read_target_job");
  });

  it.fails("read_shortlist has no phrase yet", () => {
    expect(render("read_shortlist")).not.toContain("read_shortlist");
  });

  it.fails("search_jobs has no phrase yet", () => {
    expect(render("search_jobs")).not.toContain("search_jobs");
  });

  it.fails("the structured-reply tool has no phrase yet", () => {
    expect(render("ConversationReply")).not.toContain("ConversationReply");
  });
});
