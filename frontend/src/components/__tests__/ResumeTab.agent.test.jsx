import React from "react";
import { act } from "react-dom/test-utils";
import { createRoot } from "react-dom/client";
import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";

import ResumeTab, { applyAgentDiffDecision, consumeSseEvents, parseSseEvents } from "../ResumeTab.jsx";

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
      .find((button) => button.textContent.includes("Agent review"));
    const classicEditor = container.querySelector("[data-testid='classic-resume-editor']");

    expect(classicButton).toBeTruthy();
    expect(agentButton).toBeTruthy();
    expect(classicEditor.className).not.toContain("hidden");

    await act(async () => {
      agentButton.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    expect(container.querySelector("[data-testid='resume-agent-v2-panel']")).toBeTruthy();
    expect(classicEditor.className).toContain("hidden");
    expect(container.textContent).toContain("Add LinkedIn or profile context");

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

  it("scores a first upload once", async () => {
    sessionStorage.clear();
    global.fetch = vi.fn((url) => {
      const target = String(url);
      if (target.includes("/api/resume/upload")) {
        return responseJson({
          text: "Jane Doe\nPROFESSIONAL EXPERIENCE\n• Built a reporting pipeline used by 50 finance users every month.",
          name: "Jane Doe",
          parse_quality: { warnings: [] },
        });
      }
      if (target.includes("/api/resume/score")) {
        return responseJson({ overall_score: 78, checks: {} });
      }
      if (target.includes("/api/ai/status")) {
        return responseJson({ healthy: true });
      }
      return responseJson([]);
    });

    await act(async () => {
      root.render(<ResumeTab selectedJob={null} user={null} setActiveTab={() => {}} />);
    });
    const input = container.querySelector('input[type="file"]');
    Object.defineProperty(input, "files", {
      value: [new File(["resume"], "resume.pdf", { type: "application/pdf" })],
    });

    await act(async () => {
      input.dispatchEvent(new Event("change", { bubbles: true }));
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(global.fetch.mock.calls.filter(([url]) => String(url).includes("/api/resume/score"))).toHaveLength(1);
  });

  it("parses agent error events from SSE", () => {
    const events = parseSseEvents(
      'event: error\ndata: {"event":"error","session_id":"sid-1","message":"Agent v2 needs SEALION_API configured before it can run."}\n\n',
    );

    expect(events).toEqual([
      {
        event: "error",
        session_id: "sid-1",
        message: "Agent v2 needs SEALION_API configured before it can run.",
      },
    ]);
  });

  it("consumes agent SSE events as chunks arrive", async () => {
    const encoder = new TextEncoder();
    const response = {
      body: new ReadableStream({
        start(controller) {
          controller.enqueue(encoder.encode('event: session\ndata: {"event":"session","session_id":"sid-1"}\n\n'));
          controller.enqueue(encoder.encode(': keepalive\n\nevent: token\ndata: {"event":"token","session_id":"sid-1","content":"Review ready"}\n\n'));
          controller.close();
        },
      }),
    };
    const events = [];

    await consumeSseEvents(response, (event) => events.push(event));

    expect(events).toEqual([
      { event: "session", session_id: "sid-1" },
      { event: "token", session_id: "sid-1", content: "Review ready" },
    ]);
  });
});
