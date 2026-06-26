import React from "react";
import { act } from "react-dom/test-utils";
import { createRoot } from "react-dom/client";
import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";

import ResumeTab, { applyAgentDiffDecision } from "../ResumeTab.jsx";

function responseJson(data, ok = true) {
  return Promise.resolve({
    ok,
    status: ok ? 200 : 500,
    json: () => Promise.resolve(data),
    text: () => Promise.resolve(typeof data === "string" ? data : JSON.stringify(data)),
    headers: { get: () => "" },
  });
}

describe("ResumeTab Agent v2", () => {
  let container;
  let root;

  beforeEach(() => {
    sessionStorage.clear();
    sessionStorage.setItem(
      "jh_resume_text",
      "Jane Doe\njane@example.com\n\nEXPERIENCE\n- Built data pipeline processing 10M events daily",
    );
    sessionStorage.setItem("jh_wizard_step", "3");
    global.fetch = vi.fn((url) => {
      const target = String(url);
      if (target.includes("/api/resume/score")) {
        return responseJson({ overall_score: 78, checks: {} });
      }
      if (target.includes("/api/ai/status")) {
        return responseJson({ healthy: true });
      }
      return responseJson([]);
    });
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    vi.restoreAllMocks();
    sessionStorage.clear();
  });

  it("v2 toggle renders and does not affect the classic editor", async () => {
    await act(async () => {
      root.render(<ResumeTab selectedJob={null} user={null} setActiveTab={() => {}} />);
    });

    const classicButton = Array.from(container.querySelectorAll("button"))
      .find((button) => button.textContent.includes("Classic"));
    const agentButton = Array.from(container.querySelectorAll("button"))
      .find((button) => button.textContent.includes("Agent v2"));
    const classicEditor = container.querySelector("[data-testid='classic-resume-editor']");

    expect(classicButton).toBeTruthy();
    expect(agentButton).toBeTruthy();
    expect(classicEditor.className).not.toContain("hidden");

    await act(async () => {
      agentButton.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    expect(container.querySelector("[data-testid='resume-agent-v2-panel']")).toBeTruthy();
    expect(classicEditor.className).toContain("hidden");

    await act(async () => {
      classicButton.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    expect(container.querySelector("[data-testid='resume-agent-v2-panel']")).toBeFalsy();
    expect(classicEditor.className).not.toContain("hidden");
  });

  it("accepting a bullet diff applies it; rejecting discards it", () => {
    const resumeText = "EXPERIENCE\n- Built data pipeline processing 10M events daily";
    const pendingDiffs = [
      {
        bullet_id: "exp-0-b0",
        original: "Built data pipeline processing 10M events daily",
        rewrite: "Built reliable data pipeline processing 10M events daily",
      },
    ];

    const accepted = applyAgentDiffDecision(resumeText, pendingDiffs, "exp-0-b0", "accept");
    const rejected = applyAgentDiffDecision(resumeText, pendingDiffs, "exp-0-b0", "reject");

    expect(accepted.resumeText).toContain("Built reliable data pipeline processing 10M events daily");
    expect(accepted.pendingDiffs).toEqual([]);
    expect(rejected.resumeText).toBe(resumeText);
    expect(rejected.pendingDiffs).toEqual([]);
  });
});
