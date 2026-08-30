import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import ProposedEditsPanel from "../ProposedEditsPanel.jsx";

const APPLICABLE = {
  id: "edit-1",
  section_key: "experience",
  original: "Ran vLLM inference clusters on AMD MI300X.",
  rewrite: "Operated vLLM inference clusters on AMD MI300X GPUs.",
  applicable: true,
  evidence_refs: [
    {
      evidence_id: "candidate-1",
      evidence_quote: "I operated the MI300X clusters in production.",
    },
  ],
};

const STALE = {
  id: "edit-2",
  section_key: "experience",
  original: "Text the resume no longer contains.",
  rewrite: "Never applied.",
  applicable: false,
};

describe("ProposedEditsPanel", () => {
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

  const mount = (props) =>
    act(() =>
      root.render(
        <ProposedEditsPanel onAccept={vi.fn()} onReject={vi.fn()} {...props} />,
      ),
    );

  const buttonLabelled = (text) =>
    [...container.querySelectorAll("button")].find((b) => b.textContent.trim() === text);

  it("renders nothing when there is nothing to review", () => {
    mount({ edits: [] });
    expect(container.textContent).toBe("");
  });

  it("survives a null payload instead of throwing", () => {
    mount({ edits: null });
    expect(container.textContent).toBe("");
  });

  it("offers accept-all only for edits that still apply", () => {
    mount({ edits: [APPLICABLE, STALE] });

    expect(buttonLabelled("Accept all 1")).toBeTruthy();
    expect(container.textContent).not.toContain("Never applied.");
    expect(container.textContent).toContain("drafted against wording your resume no longer contains");
    expect(container.textContent).toContain(
      "Candidate confirmed: “I operated the MI300X clusters in production.”",
    );
  });

  it("accepts everything with no argument and one edit by id", () => {
    const onAccept = vi.fn();
    mount({ edits: [APPLICABLE], onAccept });

    act(() => buttonLabelled("Accept all 1").click());
    expect(onAccept).toHaveBeenCalledWith(null);

    act(() => buttonLabelled("Accept").click());
    expect(onAccept).toHaveBeenCalledWith(["edit-1"]);
  });

  it("tells the candidate which version was saved and what was skipped", () => {
    mount({
      edits: [APPLICABLE],
      result: { label: "Tailored for Platform Operations Engineer", stale_edit_ids: ["edit-2"] },
    });

    const status = container.querySelector('[role="status"]');
    expect(status.textContent).toContain("Tailored for Platform Operations Engineer");
    expect(status.textContent).toContain("1 edit(s) were skipped");
  });

  it("keeps the derived-version handoff visible after every edit is accepted", () => {
    const onStartConversation = vi.fn();
    mount({
      edits: [],
      result: { resume_version_id: 19, label: "Hui Shan tailored", stale_edit_ids: [] },
      onStartConversation,
    });

    act(() => buttonLabelled("Start conversation with this version").click());
    expect(onStartConversation).toHaveBeenCalledWith(19);
  });
});
