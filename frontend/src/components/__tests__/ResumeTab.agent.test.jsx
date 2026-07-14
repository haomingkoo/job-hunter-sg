import React from "react";
import { act } from "react-dom/test-utils";
import { createRoot } from "react-dom/client";
import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";

import ResumeTab from "../ResumeTab.jsx";

function responseJson(data, ok = true) {
  return Promise.resolve({
    ok,
    status: ok ? 200 : 500,
    json: () => Promise.resolve(data),
    text: () => Promise.resolve(typeof data === "string" ? data : JSON.stringify(data)),
    headers: { get: () => "" },
  });
}

function setField(field, value) {
  const setter = Object.getOwnPropertyDescriptor(field.constructor.prototype, "value")?.set;
  setter.call(field, value);
  field.dispatchEvent(new Event("input", { bubbles: true }));
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

  it("starts a detached review and reconnects through session state", async () => {
    global.fetch = vi.fn((url) => {
      const target = String(url);
      if (target.includes("/api/resume/agent/start")) {
        return responseJson({ session_id: "detached-1", status: "queued" });
      }
      if (target.includes("/api/resume/agent/detached-1/state")) {
        return responseJson({
          session_id: "detached-1",
          status: "completed",
          progress: "Review complete",
          response: "Evidence-bound review ready.",
          todos: [],
          persona_findings: [],
          pending_diffs: [],
          document: null,
        });
      }
      if (target.includes("/api/resume/score")) return responseJson({ overall_score: 78, checks: {} });
      if (target.includes("/api/ai/status")) return responseJson({ healthy: true });
      return responseJson([]);
    });
    await act(async () => {
      root.render(<ResumeTab selectedJob={null} user={{ id: 1 }} setActiveTab={() => {}} />);
    });
    const agentButton = Array.from(container.querySelectorAll("button"))
      .find((button) => button.textContent.includes("Agent review"));
    await act(async () => agentButton.dispatchEvent(new MouseEvent("click", { bubbles: true })));
    const prompt = container.querySelector('textarea[placeholder^="Ask for ATS gaps"]');
    await act(async () => setField(prompt, "Review this resume"));
    const send = container.querySelector('button[title="Send to Agent Review"]');

    await act(async () => {
      send.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(global.fetch.mock.calls.some(([url]) => String(url).includes("/api/resume/agent/start"))).toBe(true);
    expect(sessionStorage.getItem("jh_resume_agent_session")).toBe("detached-1");
    expect(container.textContent).toContain("Evidence-bound review ready.");
  });

});
