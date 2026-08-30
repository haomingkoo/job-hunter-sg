import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import RecruitmentTeamPanel, { ExecutionDetails } from "../RecruitmentTeamPanel.jsx";
import { apiFetch } from "../../lib/api.js";
import { streamRecruitmentCommand } from "../../lib/recruitmentTeamApi.js";

vi.mock("../../lib/api.js", () => ({ apiFetch: vi.fn() }));
vi.mock("../../lib/recruitmentTeamApi.js", () => ({
  streamRecruitmentCommand: vi.fn(),
}));

const response = (payload) => ({ json: async () => payload });

describe("RecruitmentTeamPanel", () => {
  let container;
  let root;

  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    vi.useRealTimers();
    container.remove();
  });

  it("separates workflow-reported and transport-observed execution usage", async () => {
    await act(async () => root.render(<ExecutionDetails metrics={{
      model_call_count: 2,
      reported_model_call_count: 2,
      transport_call_count: 1,
      input_tokens: 3300,
      reported_input_tokens: 3300,
      transport_input_tokens: 1300,
      output_tokens: 1300,
      reported_output_tokens: 1300,
      transport_output_tokens: 500,
      transport_token_usage_available: true,
    }} />));

    expect(container.textContent).toContain("Workflow-reported calls2");
    expect(container.textContent).toContain("Transport-observed calls1");
    expect(container.textContent).toContain("Workflow-reported input tokens3,300");
    expect(container.textContent).toContain("Transport-observed input tokens1,300");
    expect(container.textContent).toContain("Workflow-reported output tokens1,300");
    expect(container.textContent).toContain("Transport-observed output tokens500");
    expect(container.textContent).not.toContain("Model calls");
  });

  it.each([false, undefined])(
    "does not present unavailable transport tokens as totals (%s)",
    async (availability) => {
      const metrics = {
        reported_model_call_count: 2,
        transport_call_count: 1,
        reported_input_tokens: 3300,
        transport_input_tokens: 1300,
        reported_output_tokens: 1300,
        transport_output_tokens: 500,
      };
      if (availability !== undefined) {
        metrics.transport_token_usage_available = availability;
      }

      await act(async () => root.render(<ExecutionDetails metrics={metrics} />));

      expect(container.textContent).toContain("Transport-observed input tokensUnavailable");
      expect(container.textContent).toContain("Transport-observed output tokensUnavailable");
      expect(container.textContent).not.toContain("Transport-observed input tokens1,300");
      expect(container.textContent).not.toContain("Transport-observed output tokens500");
    },
  );

  it("does not present missing legacy transport counters as observed zeroes", async () => {
    await act(async () => root.render(<ExecutionDetails metrics={{
      reported_model_call_count: 2,
      reported_input_tokens: 3300,
      reported_output_tokens: 1300,
    }} />));

    expect(container.textContent).toContain("Transport-observed callsUnavailable");
    expect(container.textContent).toContain("Transport retriesUnavailable");
    expect(container.textContent).toContain("Transport errorsUnavailable");
    expect(container.textContent).not.toContain("Transport retries0");
    expect(container.textContent).not.toContain("Transport errors0");
  });

  it("distinguishes an explicitly observed zero from unavailable transport data", async () => {
    await act(async () => root.render(<ExecutionDetails metrics={{
      reported_model_call_count: 1,
      reported_input_tokens: 10,
      reported_output_tokens: 3,
      transport_call_count: 0,
      transport_retry_count: 0,
      transport_error_count: 0,
      transport_token_usage_available: false,
    }} />));

    expect(container.textContent).toContain("Transport-observed calls0");
    expect(container.textContent).toContain("Transport retries0");
    expect(container.textContent).toContain("Transport errors0");
    expect(container.textContent).toContain("Transport-observed input tokensUnavailable");
  });

  it("starts and continues one persisted recruitment conversation", async () => {
    let messageCount = 2;
    streamRecruitmentCommand.mockImplementation(async (path, body, onActivity) => {
      onActivity({
        sequence: messageCount === 2 ? 1 : 3,
        team_member: "coordinator",
        status: "running",
        summary: "Reviewing request.",
      });
      if (path.includes("/messages/stream")) {
        messageCount = 4;
        return { thread_id: "thread-1", run_id: "run-2", status: "completed" };
      }
      return { thread_id: "thread-1", run_id: "run-1", status: "completed" };
    });
    apiFetch.mockImplementation(async (path, options = {}) => {
      if (path === "/api/resume/versions") {
        return response([{ id: 7, label: "AI resume", is_master: true }]);
      }
      if (path === "/api/recruitment-team/threads" && !options.method) {
        return response([]);
      }
      if (path === "/api/recruitment-team/threads/thread-1") {
        const messages = [
          { role: "user", content: "Find roles for me." },
          { role: "assistant", content: "I will focus on evidence-backed matches." },
          { role: "user", content: "Keep it in Singapore." },
          { role: "assistant", content: "I will keep the search in Singapore." },
        ];
        return response({
          thread_id: "thread-1",
          workflow_state: "exploring",
          case_facts: {
            resume_version_id: 7,
            resume_label: "AI resume",
            plan: [
              { step: "Study resume evidence", status: "completed" },
              { step: "Rank current roles", status: "in_progress" },
            ],
          },
          messages: messages.slice(0, messageCount),
        });
      }
      if (path === "/api/recruitment-team/threads/thread-1/events") {
        return response([
          { sequence: 1, team_member: "coordinator", status: "running", summary: "Reviewing request." },
          { sequence: 2, team_member: "coordinator", status: "completed", summary: "Turn completed." },
        ]);
      }
      // refreshThread loads pending agent-drafted edits on every thread refresh.
      if (path.includes("/proposed-edits")) return response([]);
      throw new Error(`Unexpected request: ${path}`);
    });

    await act(async () => {
      root.render(<RecruitmentTeamPanel user={{ id: 42 }} />);
    });

    const resumeSelect = container.querySelector("select");
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value")
        .set.call(resumeSelect, "7");
      resumeSelect.dispatchEvent(new Event("change", { bubbles: true }));
    });

    const textarea = container.querySelector("textarea");
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")
        .set.call(textarea, "Find roles for me.");
      textarea.dispatchEvent(new Event("input", { bubbles: true }));
    });
    const form = textarea.closest("form");
    await act(async () => {
      form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    });

    expect(container.textContent).toContain("I will focus on evidence-backed matches.");
    expect(container.textContent).toContain("Turn completed.");
    expect(container.textContent).toContain("Recruitment plan");
    expect(container.textContent).toContain("Study resume evidence");
    expect(container.textContent).toContain("in progress");
    expect(localStorage.getItem("jobhunter:recruitment-thread:42")).toBe("thread-1");

    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")
        .set.call(textarea, "Keep it in Singapore.");
      textarea.dispatchEvent(new Event("input", { bubbles: true }));
      form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    });

    expect(container.textContent).toContain("I will keep the search in Singapore.");
    expect(streamRecruitmentCommand).toHaveBeenCalledWith(
      "/api/recruitment-team/threads/thread-1/messages/stream",
      expect.objectContaining({ message: "Keep it in Singapore." }),
      expect.any(Function),
    );
  });

  it("loads earlier conversation messages without making the initial snapshot unbounded", async () => {
    localStorage.setItem("jobhunter:recruitment-thread:42", "thread-history");
    apiFetch.mockImplementation(async (path) => {
      if (path === "/api/resume/versions") return response([]);
      if (path === "/api/recruitment-team/threads/thread-history") {
        return response({
          thread_id: "thread-history",
          workflow_state: "exploring",
          case_facts: {},
          messages: [{ message_id: 101, role: "assistant", content: "Recent reply." }],
          message_history_has_more: true,
          oldest_message_id: 101,
        });
      }
      if (path === "/api/recruitment-team/threads/thread-history?before_message_id=101") {
        return response({
          messages: [{ message_id: 1, role: "user", content: "Original request." }],
          message_history_has_more: false,
          oldest_message_id: 1,
        });
      }
      if (path === "/api/recruitment-team/threads/thread-history/events") return response([]);
      if (path === "/api/recruitment-team/threads") return response([]);
      if (path.includes("/proposed-edits")) return response([]);
      throw new Error(`Unexpected request: ${path}`);
    });

    await act(async () => root.render(<RecruitmentTeamPanel user={{ id: 42 }} />));
    expect(container.textContent).toContain("Recent reply.");
    expect(container.textContent).not.toContain("Original request.");

    const loadEarlier = [...container.querySelectorAll("button")]
      .find((button) => button.textContent === "Load earlier messages");
    await act(async () => loadEarlier.click());

    expect(container.textContent).toContain("Original request.");
    expect(container.textContent).toContain("Recent reply.");
    expect(container.textContent).not.toContain("Load earlier messages");
  });

  it("refreshes a detached running action until its committed result appears", async () => {
    vi.useFakeTimers();
    localStorage.setItem("jobhunter:recruitment-thread:42", "thread-detached");
    let completed = false;
    let threadReads = 0;
    apiFetch.mockImplementation(async (path) => {
      if (path === "/api/resume/versions") return response([]);
      if (path === "/api/recruitment-team/threads/thread-detached") {
        threadReads += 1;
        return response({
          thread_id: "thread-detached",
          workflow_state: completed ? "target_selected" : "exploring",
          case_facts: completed
            ? { selected_target: { job_id: 420181, title: "Quality Manager", company: "HME" } }
            : {},
          messages: completed
            ? [{ role: "assistant", content: "Selected target persisted." }]
            : [],
        });
      }
      if (path === "/api/recruitment-team/threads/thread-detached/events") {
        return response([
          {
            sequence: 1,
            run_id: "detached-run",
            event_type: "run",
            team_member: "coordinator",
            status: completed ? "completed" : "running",
            summary: completed ? "The coordinator completed this turn." : "Reviewing your request.",
          },
        ]);
      }
      if (path.includes("/proposed-edits")) return response([]);
      throw new Error(`Unexpected request: ${path}`);
    });

    await act(async () => root.render(<RecruitmentTeamPanel user={{ id: 42 }} />));
    expect(container.textContent).toContain("Coordinator is working");
    expect(container.textContent).not.toContain("Run complete");

    completed = true;
    await act(async () => {
      await vi.runOnlyPendingTimersAsync();
    });

    expect(threadReads).toBeGreaterThan(1);
    expect(container.textContent).toContain("Selected target");
    expect(container.textContent).toContain("Run complete");
  });

  it("runs autopilot once with the same request shown on its button", async () => {
    streamRecruitmentCommand.mockResolvedValue({
      thread_id: "thread-auto", run_id: "run-auto", status: "completed",
    });
    apiFetch.mockImplementation(async (path, options = {}) => {
      if (path === "/api/resume/versions") {
        return response([{ id: 7, label: "Manufacturing resume", is_master: true }]);
      }
      if (path === "/api/recruitment-team/threads" && !options.method) return response([]);
      if (path === "/api/recruitment-team/threads/thread-auto") {
        return response({
          thread_id: "thread-auto",
          workflow_state: "exploring",
          case_facts: {},
          messages: [
            { role: "user", content: "Find roles for me." },
            { role: "assistant", content: "I ranked the strongest current roles." },
          ],
        });
      }
      if (path === "/api/recruitment-team/threads/thread-auto/events") return response([]);
      if (path.includes("/proposed-edits")) return response([]);
      throw new Error(`Unexpected request: ${path}`);
    });

    await act(async () => root.render(<RecruitmentTeamPanel user={{ id: 42 }} />));
    const resumeSelect = container.querySelector("select");
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value")
        .set.call(resumeSelect, "7");
      resumeSelect.dispatchEvent(new Event("change", { bubbles: true }));
    });
    const autopilot = [...container.querySelectorAll("button")]
      .find((button) => button.textContent === "Find roles for me");
    await act(async () => autopilot.click());

    expect(streamRecruitmentCommand).toHaveBeenCalledTimes(1);
    expect(streamRecruitmentCommand).toHaveBeenCalledWith(
      "/api/recruitment-team/threads/stream",
      expect.objectContaining({ message: "Find roles for me." }),
      expect.any(Function),
    );
    expect(container.textContent).not.toContain("[autopilot]");
    expect(container.textContent).toContain("I ranked the strongest current roles.");
  });

  it("continues the existing conversation when post-export search uses its refined resume", async () => {
    localStorage.setItem("jobhunter:recruitment-thread:42", "thread-refined");
    const onInitialRequestHandled = vi.fn();
    streamRecruitmentCommand.mockResolvedValue({
      thread_id: "thread-refined", run_id: "run-next", status: "completed",
    });
    apiFetch.mockImplementation(async (path, options = {}) => {
      if (path === "/api/resume/versions") {
        return response([{ id: 19, label: "Recruitment team edits", is_master: false }]);
      }
      if (path === "/api/recruitment-team/threads" && !options.method) return response([]);
      if (path === "/api/recruitment-team/threads/thread-refined") {
        return response({
          thread_id: "thread-refined",
          workflow_state: "exploring",
          case_facts: { resume_version_id: 19, resume_label: "Recruitment team edits" },
          messages: [],
        });
      }
      if (path === "/api/recruitment-team/threads/thread-refined/events") return response([]);
      if (path.includes("/proposed-edits")) return response([]);
      throw new Error(`Unexpected request: ${path}`);
    });

    await act(async () => {
      root.render(
        <RecruitmentTeamPanel
          user={{ id: 42 }}
          initialRequest={{
            id: "next-jobs-1",
            resumeVersionId: 19,
            message: "Find more roles that match this refined resume.",
          }}
          onInitialRequestHandled={onInitialRequestHandled}
        />,
      );
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(streamRecruitmentCommand).toHaveBeenCalledTimes(1);
    expect(streamRecruitmentCommand).toHaveBeenCalledWith(
      "/api/recruitment-team/threads/thread-refined/messages/stream",
      expect.objectContaining({ message: "Find more roles that match this refined resume." }),
      expect.any(Function),
    );
    expect(onInitialRequestHandled).toHaveBeenCalledWith("next-jobs-1");
  });

  it("keeps the composer open and sends messages queued during a running turn", async () => {
    localStorage.setItem("jobhunter:recruitment-thread:42", "thread-queue");
    let releaseFirst;
    const firstTurn = new Promise((resolve) => { releaseFirst = resolve; });
    const sent = [];
    streamRecruitmentCommand.mockImplementation(async (_path, body) => {
      sent.push(body.message);
      if (sent.length === 1) await firstTurn;
      return { thread_id: "thread-queue", status: "completed" };
    });
    apiFetch.mockImplementation(async (path) => {
      if (path === "/api/resume/versions") return response([]);
      if (path === "/api/recruitment-team/threads/thread-queue") {
        return response({
          thread_id: "thread-queue",
          workflow_state: "exploring",
          case_facts: {},
          messages: sent.flatMap((content) => [
            { role: "user", content },
            { role: "assistant", content: `Answered: ${content}` },
          ]),
        });
      }
      if (path === "/api/recruitment-team/threads/thread-queue/events") return response([]);
      if (path.includes("/proposed-edits")) return response([]);
      throw new Error(`Unexpected request: ${path}`);
    });

    await act(async () => root.render(<RecruitmentTeamPanel user={{ id: 42 }} />));
    const textarea = container.querySelector("textarea");
    const form = textarea.closest("form");
    const enter = async (value) => {
      await act(async () => {
        Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")
          .set.call(textarea, value);
        textarea.dispatchEvent(new Event("input", { bubbles: true }));
        form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
      });
    };

    await enter("First question");
    expect(container.textContent).toContain("Queue message");
    await enter("Not entry level");
    await enter("Keep it in Singapore");
    await enter("Prefer senior individual contributor roles");

    expect(container.textContent).toContain("Queued for the team");
    expect(container.textContent).toContain("Not entry level");
    expect(container.textContent).toContain("Keep it in Singapore");
    expect(container.textContent).toContain("Prefer senior individual contributor roles");
    expect(container.querySelector("textarea").disabled).toBe(false);

    await act(async () => releaseFirst());

    expect(sent).toEqual([
      "First question",
      "Not entry level",
      "Keep it in Singapore",
      "Prefer senior individual contributor roles",
    ]);
    expect(container.textContent).not.toContain("Queued for the team");
    expect(container.textContent).toContain("Answered: Keep it in Singapore");
  });

  it("starts a new conversation without resurrecting the old thread on the next render", async () => {
    let threadsFetchCount = 0;
    streamRecruitmentCommand.mockImplementation(async () => (
      { thread_id: "thread-1", run_id: "run-1", status: "completed" }
    ));
    apiFetch.mockImplementation(async (path, options = {}) => {
      if (path === "/api/resume/versions") {
        return response([{ id: 7, label: "AI resume", is_master: true }]);
      }
      if (path === "/api/recruitment-team/threads" && !options.method) {
        threadsFetchCount += 1;
        return response([]);
      }
      if (path === "/api/recruitment-team/threads/thread-1") {
        return response({
          thread_id: "thread-1",
          workflow_state: "exploring",
          case_facts: { resume_label: "AI resume" },
          messages: [{ role: "assistant", content: "I will focus on evidence-backed matches." }],
        });
      }
      if (path === "/api/recruitment-team/threads/thread-1/events") return response([]);
      if (path.includes("/proposed-edits")) return response([]);
      throw new Error(`Unexpected request: ${path}`);
    });

    await act(async () => {
      root.render(<RecruitmentTeamPanel user={{ id: 42 }} />);
    });

    const resumeSelect = container.querySelector("select");
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value")
        .set.call(resumeSelect, "7");
      resumeSelect.dispatchEvent(new Event("change", { bubbles: true }));
    });

    const textarea = container.querySelector("textarea");
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")
        .set.call(textarea, "Find roles for me.");
      textarea.dispatchEvent(new Event("input", { bubbles: true }));
      textarea.closest("form").dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    });

    expect(container.textContent).toContain("I will focus on evidence-backed matches.");
    expect(localStorage.getItem("jobhunter:recruitment-thread:42")).toBe("thread-1");
    const fetchesBeforeReset = threadsFetchCount;

    const newConversationButton = [...container.querySelectorAll("button")]
      .find((button) => button.textContent === "Start new conversation");
    await act(async () => newConversationButton.click());

    expect(localStorage.getItem("jobhunter:recruitment-thread:42")).toBeNull();
    expect(container.textContent).not.toContain("I will focus on evidence-backed matches.");
    // A new conversation no longer inherits the previous resume selection.
    expect(container.textContent).toContain("Choose a resume…");
    expect(threadsFetchCount).toBe(fetchesBeforeReset);
  });

  it("discovers the latest owned thread without a browser pointer", async () => {
    apiFetch.mockImplementation(async (path) => {
      if (path === "/api/resume/versions") return response([]);
      if (path === "/api/recruitment-team/threads") {
        return response([{
          thread_id: "persisted-thread",
          title: "Saved conversation",
          status: "active",
          resume_label: "Saved resume",
          last_message: "Welcome back.",
        }]);
      }
      if (path === "/api/recruitment-team/threads/persisted-thread") {
        return response({
          thread_id: "persisted-thread",
          workflow_state: "exploring",
          case_facts: { resume_label: "Saved resume" },
          messages: [{ role: "assistant", content: "Welcome back." }],
        });
      }
      if (path === "/api/recruitment-team/threads/persisted-thread/events") {
        return response([]);
      }
      if (path.includes("/proposed-edits")) return response([]);
      throw new Error(`Unexpected request: ${path}`);
    });

    await act(async () => {
      root.render(<RecruitmentTeamPanel user={{ id: 42 }} />);
    });

    expect(container.textContent).toContain("Welcome back.");
    expect(localStorage.getItem("jobhunter:recruitment-thread:42"))
      .toBe("persisted-thread");
  });

  it("prefers a newly uploaded resume over silently restoring an older thread", async () => {
    localStorage.setItem("jobhunter:recruitment-thread:42", "old-semiconductor-thread");
    localStorage.setItem("jobhunter:pending-resume-version:42", "19");
    streamRecruitmentCommand.mockResolvedValue({
      thread_id: "hui-thread",
      run_id: "hui-run",
      status: "completed",
    });
    apiFetch.mockImplementation(async (path) => {
      if (path === "/api/resume/versions") {
        return response([{
          id: 19,
          label: "Hui Shan accounting resume",
          word_count: 800,
          content_sha256: "a".repeat(64),
        }]);
      }
      if (path === "/api/recruitment-team/threads") return response([]);
      if (path === "/api/recruitment-team/threads/hui-thread") {
        return response({
          thread_id: "hui-thread",
          workflow_state: "exploring",
          case_facts: {
            resume_version_id: 19,
            resume_label: "Hui Shan accounting resume",
            resume_sha256: "a".repeat(64),
          },
          messages: [],
        });
      }
      if (path === "/api/recruitment-team/threads/hui-thread/events") return response([]);
      if (path === "/api/recruitment-team/threads/hui-thread/proposed-edits") return response([]);
      throw new Error(`Unexpected request: ${path}`);
    });

    await act(async () => root.render(<RecruitmentTeamPanel user={{ id: 42 }} />));

    expect(container.textContent).toContain("Hui Shan accounting resume");
    expect(container.querySelector("select").value).toBe("19");
    expect(apiFetch).not.toHaveBeenCalledWith(
      "/api/recruitment-team/threads/old-semiconductor-thread",
    );

    const autopilot = [...container.querySelectorAll("button")]
      .find((button) => button.textContent === "Find roles for me");
    await act(async () => autopilot.click());

    expect(streamRecruitmentCommand).toHaveBeenCalledWith(
      "/api/recruitment-team/threads/stream",
      expect.objectContaining({ resume_version_id: 19 }),
      expect.any(Function),
    );
    expect(localStorage.getItem("jobhunter:pending-resume-version:42")).toBeNull();
  });

  it("keeps an accepted derived resume selected across reload", async () => {
    localStorage.setItem("jobhunter:recruitment-thread:42", "source-thread");
    apiFetch.mockImplementation(async (path, options = {}) => {
      if (path === "/api/resume/versions") {
        return response([
          { id: 7, label: "Hui Shan accounting resume" },
          { id: 19, label: "Hui Shan tailored for Senior Accountant" },
        ]);
      }
      if (path === "/api/recruitment-team/threads/source-thread") {
        return response({
          thread_id: "source-thread",
          status: "active",
          workflow_state: "target_selected",
          case_facts: { resume_version_id: 7, resume_label: "Hui Shan accounting resume" },
          messages: [],
        });
      }
      if (path === "/api/recruitment-team/threads/source-thread/events") return response([]);
      if (path === "/api/recruitment-team/threads/source-thread/proposed-edits") {
        return response([{
          id: "edit-1",
          applicable: true,
          section_key: "experience",
          original: "Prepared monthly accounts.",
          rewrite: "Prepared monthly accounts and reconciliations.",
          evidence_refs: [],
        }]);
      }
      if (
        path === "/api/recruitment-team/threads/source-thread/proposed-edits/accept"
        && options.method === "POST"
      ) {
        return response({
          resume_version_id: 19,
          label: "Hui Shan tailored for Senior Accountant",
          stale_edit_ids: [],
        });
      }
      if (path === "/api/recruitment-team/threads") return response([]);
      throw new Error(`Unexpected request: ${path}`);
    });

    await act(async () => root.render(<RecruitmentTeamPanel user={{ id: 42 }} />));
    await act(async () => {
      [...container.querySelectorAll("button")]
        .find((button) => button.textContent === "Accept all 1")
        .click();
    });
    await act(async () => {
      [...container.querySelectorAll("button")]
        .find((button) => button.textContent === "Start conversation with this version")
        .click();
    });

    expect(localStorage.getItem("jobhunter:recruitment-thread:42")).toBeNull();
    expect(localStorage.getItem("jobhunter:pending-resume-version:42")).toBe("19");
    expect(container.querySelector("select").value).toBe("19");

    await act(async () => root.unmount());
    root = createRoot(container);
    await act(async () => root.render(<RecruitmentTeamPanel user={{ id: 42 }} />));

    expect(container.querySelector("select").value).toBe("19");
    expect(container.textContent).toContain("Hui Shan tailored for Senior Accountant");
  });

  it("shows the exact resume and ranking provenance after reload and in history", async () => {
    const savedAt = "2026-08-30T01:02:03Z";
    const savedDate = new Date(savedAt).toLocaleDateString();
    const resumeHash = "a".repeat(64);
    localStorage.setItem("jobhunter:recruitment-thread:42", "accounting-thread");
    apiFetch.mockImplementation(async (path) => {
      if (path === "/api/resume/versions") {
        return response([{ id: 19, label: "Hui Shan accounting resume" }]);
      }
      if (path === "/api/recruitment-team/threads/accounting-thread") {
        return response({
          thread_id: "accounting-thread",
          title: "Senior accounting roles",
          status: "active",
          workflow_state: "exploring",
          case_facts: {
            resume_version_id: 19,
            resume_label: "Hui Shan accounting resume",
            resume_sha256: resumeHash,
            resume_word_count: 1258,
            resume_created_at: savedAt,
            latest_ranking_receipt: {
              candidate_profile_used: true,
              resume_version_id: 19,
              resume_sha256: resumeHash,
              candidate_profile_artifact_id: "profile-accounting-1234",
            },
          },
          messages: [{ role: "assistant", content: "I found accounting roles." }],
        });
      }
      if (path === "/api/recruitment-team/threads/accounting-thread/events") return response([]);
      if (path === "/api/recruitment-team/threads/accounting-thread/proposed-edits") return response([]);
      if (path === "/api/recruitment-team/threads") {
        return response([{
          thread_id: "accounting-thread",
          title: "Senior accounting roles",
          status: "active",
          last_message: "I found accounting roles.",
          resume_version_id: 19,
          resume_label: "Hui Shan accounting resume",
          resume_sha256: resumeHash,
          resume_word_count: 1258,
          resume_created_at: savedAt,
        }]);
      }
      throw new Error(`Unexpected request: ${path}`);
    });

    await act(async () => root.render(<RecruitmentTeamPanel user={{ id: 42 }} />));

    expect(container.textContent).toContain(
      `Resume: Hui Shan accounting resume · v19 · aaaaaaaaaa · 1258 words · saved ${savedDate}`,
    );
    expect(container.textContent).toContain("Recommendations use resume v19 · aaaaaaaaaa");
    expect(container.textContent).toContain("profile profile-");

    await act(async () => {
      [...container.querySelectorAll("button")]
        .find((button) => button.textContent.includes("Conversations"))
        .click();
    });
    expect(container.textContent).toContain(
      `Hui Shan accounting resume · v19 · aaaaaaaaaa · 1258 words · saved ${savedDate}`,
    );
  });

  it("recovers a streamed resume-binding conflict without exposing stale jobs", async () => {
    localStorage.setItem("jobhunter:recruitment-thread:42", "changed-resume-thread");
    let refreshCount = 0;
    streamRecruitmentCommand.mockRejectedValue(Object.assign(
      new Error("This conversation uses a changed resume."),
      { detail: { code: "resume_binding_mismatch" } },
    ));
    apiFetch.mockImplementation(async (path) => {
      if (path === "/api/resume/versions") {
        return response([{ id: 7, label: "Original resume" }]);
      }
      if (path === "/api/recruitment-team/threads/changed-resume-thread") {
        refreshCount += 1;
        return response({
          thread_id: "changed-resume-thread",
          title: "Original conversation",
          status: "active",
          workflow_state: "exploring",
          case_facts: refreshCount === 1 ? {
            resume_version_id: 7,
            resume_label: "Original resume",
            resume_binding_status: "verified",
            recommendations: [{
              job_id: 91,
              title: "Stale Semiconductor Engineer",
              company: "Old Employer",
              location: "Singapore",
              source: { source: "fixture", url: "https://example.test/91" },
            }],
          } : {
            resume_version_id: 7,
            resume_label: "Original resume",
            resume_binding_status: "mismatch",
            recommendations: [],
          },
          messages: [
            { role: "user", content: "Find accounting work." },
            { role: "assistant", content: "Earlier history remains readable." },
          ],
        });
      }
      if (path === "/api/recruitment-team/threads/changed-resume-thread/events") return response([]);
      if (path === "/api/recruitment-team/threads/changed-resume-thread/proposed-edits") return response([]);
      throw new Error(`Unexpected request: ${path}`);
    });

    await act(async () => root.render(<RecruitmentTeamPanel user={{ id: 42 }} />));
    expect(container.textContent).toContain("Stale Semiconductor Engineer");

    const textarea = container.querySelector("textarea");
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")
        .set.call(textarea, "Continue with accounting roles.");
      textarea.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await act(async () => container.querySelector("form").dispatchEvent(
      new Event("submit", { bubbles: true, cancelable: true }),
    ));

    expect(refreshCount).toBe(2);
    expect(container.textContent).toContain("saved resume no longer matches its evidence receipt");
    expect(container.textContent).toContain("Earlier history remains readable.");
    expect(container.textContent).not.toContain("Stale Semiconductor Engineer");
    expect(container.textContent).toContain("Start a new conversation");
  });

  it("renders every persisted candidate-profile field and resumes a failed profile", async () => {
    localStorage.setItem("jobhunter:recruitment-thread:42", "thread-profile");
    let completed = false;
    const fields = [
      {
        field_id: "credential_ca",
        category: "credential",
        statement: "Holds CA Singapore qualification.",
        evidence_support_score: 100,
        evidence_kind: "direct",
        score_reason: "The qualification is explicitly listed.",
        evidence_quotes: ["CA Singapore"],
      },
      {
        field_id: "stated_skill_python",
        category: "stated_skill",
        statement: "Lists Python as a skill.",
        evidence_support_score: 100,
        evidence_kind: "direct",
        score_reason: "The skills section lists Python; it does not prove use.",
        evidence_quotes: ["Python"],
      },
    ];
    streamRecruitmentCommand.mockImplementation(async (_path, _body, onActivity) => {
      onActivity({
        sequence: 3,
        team_member: "candidate_profiler",
        status: "running",
        summary: "Studying resume evidence.",
      });
      completed = true;
      return { thread_id: "thread-profile", status: "completed" };
    });
    apiFetch.mockImplementation(async (path) => {
      if (path === "/api/resume/versions") return response([]);
      if (path === "/api/recruitment-team/threads/thread-profile") {
        return response({
          thread_id: "thread-profile",
          workflow_state: completed ? "profile_ready" : "exploring",
          case_facts: {
            resume_label: "Finance and AI resume",
            candidate_profile_artifact_id: "artifact-1",
            candidate_profile_status: completed ? "completed" : "failed",
          },
          messages: [],
        });
      }
      if (path === "/api/recruitment-team/threads/thread-profile/events") {
        return response([]);
      }
      if (path === "/api/recruitment-team/threads/thread-profile/candidate-profile") {
        return response({
          artifact_id: "artifact-1",
          prompt_version: "candidate-evidence-profile-v3",
          decomposition_version: "semantic-section-record-v1",
          status: completed ? "completed" : "failed",
          profile: completed ? { fields } : null,
          error: completed ? null : {
            failed_scope_id: "experience_04",
            recovery: "Resume the candidate profile command.",
          },
        });
      }
      if (path.includes("/proposed-edits")) return response([]);
      throw new Error(`Unexpected request: ${path}`);
    });

    await act(async () => {
      root.render(<RecruitmentTeamPanel user={{ id: 42 }} />);
    });

    expect(container.textContent).toContain("Profile paused at experience_04");
    const resumeButton = [...container.querySelectorAll("button")]
      .find((button) => button.textContent.includes("Resume profile"));
    await act(async () => resumeButton.click());

    expect(streamRecruitmentCommand).toHaveBeenCalledWith(
      "/api/recruitment-team/threads/thread-profile/candidate-profile/stream",
      expect.objectContaining({ idempotency_key: expect.any(String) }),
      expect.any(Function),
    );
    expect(container.textContent).toContain("Holds CA Singapore qualification.");
    expect(container.textContent).toContain("Lists Python as a skill.");
    expect(container.textContent).toContain("it does not prove use");
  });

  it("does not offer a second study while the automatic study is running", async () => {
    localStorage.setItem("jobhunter:recruitment-thread:42", "thread-studying");
    apiFetch.mockImplementation(async (path) => {
      if (path === "/api/resume/versions") return response([]);
      if (path === "/api/recruitment-team/threads/thread-studying") {
        return response({
          thread_id: "thread-studying",
          workflow_state: "exploring",
          case_facts: { candidate_profile_status: "running" },
          messages: [],
        });
      }
      if (path === "/api/recruitment-team/threads/thread-studying/events") return response([]);
      if (path.includes("/proposed-edits")) return response([]);
      throw new Error(`Unexpected request: ${path}`);
    });

    await act(async () => root.render(<RecruitmentTeamPanel user={{ id: 42 }} />));

    const studyButton = [...container.querySelectorAll("button")]
      .find((button) => button.textContent === "Studying resume");
    expect(studyButton).toBeDefined();
    expect(studyButton.disabled).toBe(true);
  });

  it("paginates a large candidate profile, strongest evidence first", async () => {
    localStorage.setItem("jobhunter:recruitment-thread:42", "thread-paged");
    const fields = Array.from({ length: 30 }, (_, index) => ({
      field_id: `field_${index}`,
      category: "stated_skill",
      statement: `Field number ${index}.`,
      evidence_support_score: index,
      evidence_kind: "direct",
      score_reason: "reason",
      evidence_quotes: [],
    }));
    apiFetch.mockImplementation(async (path) => {
      if (path === "/api/resume/versions") return response([]);
      if (path === "/api/recruitment-team/threads/thread-paged") {
        return response({
          thread_id: "thread-paged",
          workflow_state: "profile_ready",
          case_facts: {
            candidate_profile_artifact_id: "artifact-paged",
            candidate_profile_status: "completed",
          },
          messages: [],
        });
      }
      if (path === "/api/recruitment-team/threads/thread-paged/events") return response([]);
      if (path === "/api/recruitment-team/threads/thread-paged/candidate-profile") {
        return response({ artifact_id: "artifact-paged", status: "completed", profile: { fields } });
      }
      if (path.includes("/proposed-edits")) return response([]);
      throw new Error(`Unexpected request: ${path}`);
    });

    await act(async () => root.render(<RecruitmentTeamPanel user={{ id: 42 }} />));

    expect(container.textContent).toContain("Showing 25 of 30 fields");
    expect(container.textContent).toContain("Field number 29.");
    expect(container.textContent).not.toContain("Field number 4.");

    const showMoreButton = [...container.querySelectorAll("button")]
      .find((button) => button.textContent.includes("Show 5 more"));
    await act(async () => showMoreButton.click());

    expect(container.textContent).toContain("Field number 4.");
  });

  it("shows why target selection is unavailable while the resume profile is running", async () => {
    localStorage.setItem("jobhunter:recruitment-thread:42", "thread-profile-running");
    apiFetch.mockImplementation(async (path) => {
      if (path === "/api/resume/versions") return response([]);
      if (path === "/api/recruitment-team/threads/thread-profile-running") {
        return response({
          thread_id: "thread-profile-running",
          workflow_state: "exploring",
          case_facts: {
            candidate_profile_status: "running",
            recommendations: [{
              job_id: 101,
              title: "Manufacturing Manager",
              company: "Example Employer",
              location: "Singapore",
              source: { source: "MyCareersFuture", url: "https://example.test/jobs/101" },
            }],
          },
          messages: [],
        });
      }
      if (path === "/api/recruitment-team/threads/thread-profile-running/events") return response([]);
      if (path.includes("/proposed-edits")) return response([]);
      throw new Error(`Unexpected request: ${path}`);
    });

    await act(async () => root.render(<RecruitmentTeamPanel user={{ id: 42 }} />));

    const selectButton = [...container.querySelectorAll("button")]
      .find((button) => button.textContent === "Preparing resume profile");
    expect(selectButton.disabled).toBe(true);
    expect(streamRecruitmentCommand).not.toHaveBeenCalled();
  });

  it("searches current jobs and renders source-backed target actions", async () => {
    localStorage.setItem("jobhunter:recruitment-thread:42", "thread-jobs");
    let shortlisted = false;
    let selected = false;
    const onOpenApplication = vi.fn();
    const onTailorJob = vi.fn();
    const job = {
      job_id: 101,
      title: "Applied AI Solution Architect",
      company: "Example Employer",
      location: "Singapore",
      salary: "$10,000 - $15,000",
      seniority: "Professional",
      employer_relationship: "unknown",
      employer_relationship_evidence: "mcf_no_relationship_signal",
      source: {
        source: "MyCareersFuture",
        url: "https://example.test/jobs/101",
        posted_date: "2026-07-03",
        closing_date: "2026-08-03",
        availability: "current",
      },
      posting_variants: [{ job_id: 101 }],
    };
    const roleProfile = {
      profile_version: "role-success-v1",
      target_job_id: 101,
      sources: [{
        source_id: "target_job:101",
        source_type: "target_job",
        title: "Applied AI Solution Architect — Example Employer",
        url: "https://example.test/jobs/101",
        evidence_strength: "primary",
      }],
      criteria: [{
        criterion_id: "agent_reliability",
        category: "technical_skills",
        requirement_level: "required",
        statement: "Build and evaluate reliable agent systems.",
        source_ids: ["target_job:101"],
      }],
      candidate_evidence: [{
        criterion_id: "agent_reliability",
        alignment: "direct",
        resume_evidence_ids: ["block-1"],
        explanation: "The resume explicitly describes production agent evaluation.",
        confidence: 0.93,
        confidence_basis: "Directly cited resume evidence.",
      }],
      source_coverage: { taxonomy_match_quality: "unmatched" },
      clarification_question: "Which production reliability outcomes matter most?",
    };
    streamRecruitmentCommand.mockImplementation(async (path, _body, onActivity) => {
      onActivity({
        sequence: 3,
        team_member: "job_researcher",
        status: "running",
        summary: "Searching current jobs.",
      });
      if (path.endsWith("/jobs/101/shortlist/stream")) shortlisted = true;
      if (path.endsWith("/jobs/101/select/stream")) selected = true;
      return { thread_id: "thread-jobs", status: "completed" };
    });
    apiFetch.mockImplementation(async (path, options = {}) => {
      if (path === "/api/resume/versions") return response([]);
      if (path === "/api/recruitment-team/threads/thread-jobs") {
        return response({
          thread_id: "thread-jobs",
          workflow_state: selected ? "target_selected" : "exploring",
          case_facts: {
            resume_version_id: 7,
            resume_label: "AI resume",
            candidate_profile_status: "completed",
            latest_ranking_receipt: { candidate_profile_used: true },
            recommendations: [job],
            match_rationales: [{
              job_id: 101,
              matched: [{
                statement: "Production agent reliability is directly relevant.",
                resume_quote: "Built reliable Python agent platforms",
              }],
              stretch: [],
              missing: ["Named cloud platform"],
              level_fit: "aligned",
              pay_position: "above_peer_median",
            }],
            shortlisted_job_ids: shortlisted || selected ? [101] : [],
            selected_target: selected ? job : null,
            tracked_job_ids: selected ? { "101": 7001 } : {},
            role_success_profile: selected ? roleProfile : null,
          },
          messages: [],
        });
      }
      if (path === "/api/recruitment-team/threads/thread-jobs/events") {
        return response([]);
      }
      if (path.includes("/proposed-edits")) return response([]);
      throw new Error(`Unexpected request: ${path}`);
    });

    await act(async () => {
      root.render(
        <RecruitmentTeamPanel
          user={{ id: 42 }}
          onOpenApplication={onOpenApplication}
          onTailorJob={onTailorJob}
        />,
      );
    });

    expect(container.textContent).toContain("Applied AI Solution Architect");
    expect(container.textContent).toContain("MyCareersFuture");
    expect(container.textContent).toContain("Level: aligned · Pay: above peer median");
    expect(container.textContent).toContain("Production agent reliability is directly relevant.");
    expect(container.textContent).toContain("Built reliable Python agent platforms");
    expect(container.textContent).toContain("Named cloud platform");
    expect(container.textContent).toContain("Profile-ranked match");
    expect(container.textContent).toContain("Employer relationship: unverified");
    expect(container.textContent).toContain("StretchNone identified.");
    expect(container.textContent).not.toContain("Role Success Profile");
    expect(container.querySelector('a[href="https://example.test/jobs/101"]')).not.toBeNull();

    const textarea = container.querySelector("textarea");
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")
        .set.call(textarea, "senior agentic AI Singapore");
      textarea.dispatchEvent(new Event("input", { bubbles: true }));
    });
    const searchButton = [...container.querySelectorAll("button")]
      .find((button) => button.textContent.includes("Search jobs"));
    await act(async () => searchButton.click());
    expect(streamRecruitmentCommand).toHaveBeenCalledWith(
      "/api/recruitment-team/threads/thread-jobs/jobs/search/stream",
      expect.objectContaining({ query: "senior agentic AI Singapore" }),
      expect.any(Function),
    );

    const shortlistButton = [...container.querySelectorAll("button")]
      .find((button) => button.textContent.includes("Shortlist"));
    await act(async () => shortlistButton.click());
    expect(streamRecruitmentCommand).toHaveBeenCalledWith(
      "/api/recruitment-team/threads/thread-jobs/jobs/101/shortlist/stream",
      expect.objectContaining({ idempotency_key: expect.any(String) }),
      expect.any(Function),
    );
    expect(container.textContent).toContain("Shortlisted");

    const selectButton = [...container.querySelectorAll("button")]
      .find((button) => button.textContent.includes("Select target"));
    await act(async () => {
      selectButton.click();
      await Promise.resolve();
    });
    expect(streamRecruitmentCommand).toHaveBeenCalledWith(
      "/api/recruitment-team/threads/thread-jobs/jobs/101/select/stream",
      expect.objectContaining({ idempotency_key: expect.any(String) }),
      expect.any(Function),
    );
    expect(container.textContent).toContain("Selected target");
    expect(container.textContent).toContain("Role Success Profile");
    expect(container.textContent).toContain("Build and evaluate reliable agent systems.");
    expect(container.textContent).toContain("raw evidence confidence 93%");
    expect(container.textContent).toContain("Which production reliability outcomes matter most?");
    expect(container.textContent).toContain("Next action: review the evidence, tailor your resume, then manage the application");

    const tailorButton = [...container.querySelectorAll("button")]
      .find((button) => button.textContent.includes("Tailor resume"));
    const workspaceButton = [...container.querySelectorAll("button")]
      .find((button) => button.textContent.includes("Open application workspace"));
    await act(async () => {
      tailorButton.click();
      workspaceButton.click();
    });
    expect(onTailorJob).toHaveBeenCalledWith(job, 7);
    expect(onOpenApplication).toHaveBeenCalledWith(7001);
  });

  it("records optional role feedback and removes the committed result after refresh", async () => {
    localStorage.setItem("jobhunter:recruitment-thread:42", "thread-feedback");
    let hidden = false;
    const job = {
      job_id: 301,
      title: "Sales Manager",
      company: "Example Equipment",
      location: "Singapore",
      salary: "$6,000 - $8,000",
      seniority: "Manager",
      source: { source: "MyCareersFuture", url: "https://example.test/jobs/301", availability: "current" },
      posting_variants: [],
    };
    streamRecruitmentCommand.mockImplementation(async (path, body) => {
      expect(path).toBe("/api/recruitment-team/threads/thread-feedback/jobs/301/feedback/stream");
      expect(body).toEqual(expect.objectContaining({
        scope: "role",
        reason: "Wrong function",
        idempotency_key: expect.any(String),
      }));
      hidden = true;
      return { thread_id: "thread-feedback", status: "completed" };
    });
    apiFetch.mockImplementation(async (path) => {
      if (path === "/api/resume/versions") return response([]);
      if (path === "/api/recruitment-team/threads/thread-feedback") {
        return response({
          thread_id: "thread-feedback",
          workflow_state: "exploring",
          case_facts: { recommendations: hidden ? [] : [job], match_rationales: [] },
          messages: [],
        });
      }
      if (path.endsWith("/events") || path.endsWith("/proposed-edits")) return response([]);
      throw new Error(`Unexpected request: ${path}`);
    });

    await act(async () => root.render(<RecruitmentTeamPanel user={{ id: 42 }} />));
    const hideButton = [...container.querySelectorAll("button")]
      .find((button) => button.textContent.includes("Not for me"));
    await act(async () => hideButton.click());
    const reasonInput = container.querySelector('input[placeholder="Reason (optional)"]');
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")
        .set.call(reasonInput, "Wrong function");
      reasonInput.dispatchEvent(new Event("input", { bubbles: true }));
    });
    const saveButton = [...container.querySelectorAll("button")]
      .find((button) => button.textContent.includes("Save feedback"));
    await act(async () => saveButton.click());

    expect(container.textContent).not.toContain("Sales Manager");
  });

  it("labels unranked retrieval as search results rather than matches", async () => {
    localStorage.setItem("jobhunter:recruitment-thread:42", "thread-raw-search");
    const job = {
      job_id: 202,
      title: "Production Operator",
      company: "Example Employer",
      location: "Singapore",
      salary: "$1,800 - $2,300",
      seniority: "Junior Executive",
      source: { source: "MyCareersFuture", url: "https://example.test/jobs/202", availability: "current" },
      posting_variants: [],
    };
    apiFetch.mockImplementation(async (path) => {
      if (path === "/api/resume/versions") return response([]);
      if (path === "/api/recruitment-team/threads/thread-raw-search") {
        return response({
          thread_id: "thread-raw-search",
          workflow_state: "exploring",
          case_facts: { recommendations: [job], match_rationales: [] },
          messages: [],
        });
      }
      if (path === "/api/recruitment-team/threads/thread-raw-search/events") return response([]);
      if (path.includes("/proposed-edits")) return response([]);
      throw new Error(`Unexpected request: ${path}`);
    });

    await act(async () => root.render(<RecruitmentTeamPanel user={{ id: 42 }} />));

    expect(container.textContent).toContain("Current search results");
    expect(container.textContent).not.toContain("Current source-backed matches");
  });

  it("runs and renders the judged multi-agent target assessment", async () => {
    localStorage.setItem("jobhunter:recruitment-thread:42", "thread-assessment");
    let assessed = false;
    const roleProfile = {
      criteria: [],
      candidate_evidence: [],
      cited_resume_evidence: [],
      sources: [],
      source_coverage: { taxonomy_match_quality: "unmatched" },
    };
    streamRecruitmentCommand.mockImplementation(async (path, _body, onActivity) => {
      expect(path).toBe("/api/recruitment-team/threads/thread-assessment/assessment/stream");
      onActivity({
        sequence: 4,
        team_member: "recruiter",
        status: "completed",
        summary: "Recruiter screen completed.",
      });
      assessed = true;
      return { thread_id: "thread-assessment", status: "completed" };
    });
    apiFetch.mockImplementation(async (path) => {
      if (path === "/api/resume/versions") return response([]);
      if (path === "/api/recruitment-team/threads/thread-assessment") {
        return response({
          thread_id: "thread-assessment",
          workflow_state: assessed ? "assessment_ready" : "target_selected",
          case_facts: {
            selected_target: { job_id: 101 },
            role_success_profile: roleProfile,
            target_assessment_artifact_id: assessed ? "assessment-1" : null,
          },
          messages: [],
        });
      }
      if (path === "/api/recruitment-team/threads/thread-assessment/events") {
        return response(assessed ? [{
          sequence: 4,
          team_member: "recruiter",
          status: "completed",
          summary: "Recruiter screen completed.",
        }] : []);
      }
      if (path === "/api/recruitment-team/threads/thread-assessment/assessment") {
        return response({
          artifact_id: "assessment-1",
          status: "completed",
          specialist_runs: [{
            persona_id: "recruiter",
            status: "completed",
            attempt_count: 1,
            submission: {
              summary: "The role has directly cited evidence.",
              score: 88,
              score_reason: "The cited field supports the role criterion.",
            },
          }],
          synthesis: "Evidence-grounded target assessment.",
          judge: {
            disposition: "pass",
            score: 92,
            confidence: 90,
            score_reason: "Claims retain provenance and boundaries.",
            confidence_reason: "Every cited artifact was available to the judge.",
            strengths: ["The synthesis preserves canonical evidence IDs."],
            weaknesses: ["One interview validation step could be more specific."],
            evidence_gaps: ["Production ownership scope remains unverified."],
            rubric_scores: {
              evidence_grounding: 96,
              role_coverage: 90,
              decision_usefulness: 88,
              fairness_and_boundaries: 100,
            },
            deductions: [{
              rubric: "decision_usefulness",
              points: 8,
              reason: "The validation step is broad.",
            }],
          },
          correction: { attempted: true },
          execution_metrics: {
            model_call_count: 12,
            input_tokens: 53021,
            output_tokens: 7612,
            latency_ms: 125000,
            models: ["aisingapore/Gemma-SEA-LION-v4-27B-IT"],
            validation_codes: ["synthesis:corrected"],
            transport_retry_count: 2,
            transport_error_count: 1,
            transport_by_role: {
              recruiter: { call_count: 2, retry_count: 1, error_count: 0 },
              quality_judge: { call_count: 2, retry_count: 1, error_count: 1 },
            },
          },
          execution_policy: {
            persona_pack_version: "recruitment-personas-v1",
            specialist_max_concurrency: 5,
            specialist_validation_attempts: 2,
            synthesis_validation_attempts: 2,
            judge_validation_attempts: 2,
            transport_retries: 0,
          },
        });
      }
      if (path.includes("/proposed-edits")) return response([]);
      throw new Error(`Unexpected request: ${path}`);
    });

    await act(async () => root.render(<RecruitmentTeamPanel user={{ id: 42 }} />));
    const assessButton = [...container.querySelectorAll("button")]
      .find((button) => button.textContent === "Run assessment");
    await act(async () => assessButton.click());

    expect(container.textContent).toContain("Recruiter screen completed.");
    expect(container.textContent).toContain("The role has directly cited evidence.");
    expect(container.textContent).toContain("Evidence-grounded target assessment.");
    expect(container.textContent).toContain("output quality 92/100");
    expect(container.textContent).toContain("Score reason: Claims retain provenance and boundaries.");
    expect(container.textContent).toContain("Confidence basis: Every cited artifact was available");
    expect(container.textContent).toContain("Strength: The synthesis preserves canonical evidence IDs.");
    expect(container.textContent).toContain("Weakness: One interview validation step could be more specific.");
    expect(container.textContent).toContain("Evidence gap: Production ownership scope remains unverified.");
    expect(container.textContent).toContain("evidence grounding96/100");
    expect(container.textContent).toContain("Deduction · decision usefulness · 8 points");
    expect(container.textContent).toContain("one targeted correction was judged independently");
    const executionDetails = [...container.querySelectorAll("details")]
      .find((element) => element.textContent.includes("Execution details"));
    expect(executionDetails.open).toBe(false);
    expect(executionDetails.textContent).toContain("Model calls12");
    expect(executionDetails.textContent).not.toContain("Workflow-reported calls");
    expect(executionDetails.textContent).not.toContain("Transport-observed calls");
    expect(executionDetails.textContent).toContain("Run time125 seconds");
    expect(executionDetails.textContent).toContain("Input tokens53,021");
    expect(executionDetails.textContent).toContain("Output tokens7,612");
    expect(executionDetails.textContent).toContain("Transport retries2");
    expect(executionDetails.textContent).toContain("recruiter: 2 calls, 1 retry");
    expect(executionDetails.textContent).toContain("quality judge: 2 calls, 1 retry, 1 error");
    expect(executionDetails.textContent).toContain("aisingapore/Gemma-SEA-LION-v4-27B-IT");
    expect(executionDetails.textContent).not.toContain("trace");
    // The execution-policy dump (validation attempts, transport retries, "no fallback
    // model") described knobs the runner does not enforce and meant nothing to a
    // candidate, so the panel now states what actually happened instead.
    expect(container.textContent).toContain("1 specialist reviewed this role against your evidence");
    expect(container.textContent).not.toContain("no fallback model");
  });

  it("keeps pre-judge specialist content private while an assessment is paused", async () => {
    localStorage.setItem("jobhunter:recruitment-thread:42", "thread-paused-assessment");
    apiFetch.mockImplementation(async (path) => {
      if (path === "/api/resume/versions") return response([]);
      if (path === "/api/recruitment-team/threads/thread-paused-assessment") {
        return response({
          thread_id: "thread-paused-assessment",
          workflow_state: "awaiting_candidate_answer",
          case_facts: {
            selected_target: { job_id: 101 },
            role_success_profile: {
              criteria: [],
              candidate_evidence: [],
              cited_resume_evidence: [],
              sources: [],
              source_coverage: { taxonomy_match_quality: "unmatched" },
            },
            target_assessment_artifact_id: "assessment-paused",
          },
          messages: [],
        });
      }
      if (path === "/api/recruitment-team/threads/thread-paused-assessment/events") {
        return response([]);
      }
      if (path === "/api/recruitment-team/threads/thread-paused-assessment/assessment") {
        return response({
          artifact_id: "assessment-paused",
          status: "paused",
          specialist_runs: [
            {
              persona_id: "recruiter",
              status: "completed",
              submission: { summary: "Initial recruiter report.", score: 80, score_reason: "Grounded." },
            },
            {
              persona_id: "recruiter",
              status: "completed",
              submission: { summary: "Revisited recruiter report.", score: 82, score_reason: "Grounded." },
            },
          ],
          synthesis: "",
          judge: null,
          correction: null,
          execution_policy: {},
        });
      }
      if (path.endsWith("/proposed-edits")) return response([]);
      throw new Error(`Unexpected request: ${path}`);
    });

    await act(async () => root.render(<RecruitmentTeamPanel user={{ id: 42 }} />));

    expect(container.textContent).toContain(
      "Specialist findings remain private until the independent review completes.",
    );
    expect(container.textContent).not.toContain("then an independent judge reviewed their verdict");
    expect(container.textContent).not.toContain("Initial recruiter report.");
    expect(container.textContent).not.toContain("Revisited recruiter report.");
  });

  it("shows that a submitted assessment answer is being processed", async () => {
    localStorage.setItem("jobhunter:recruitment-thread:42", "thread-answering");
    let releaseAnswer;
    let answerFinished = false;
    const pendingAnswer = new Promise((resolve) => { releaseAnswer = resolve; });
    streamRecruitmentCommand.mockImplementation(async () => {
      await pendingAnswer;
      answerFinished = true;
      return { thread_id: "thread-answering", status: "completed" };
    });
    apiFetch.mockImplementation(async (path) => {
      if (path === "/api/resume/versions") return response([]);
      if (path === "/api/recruitment-team/threads/thread-answering") {
        return response({
          thread_id: "thread-answering",
          workflow_state: answerFinished ? "assessment_ready" : "awaiting_candidate_answer",
          case_facts: answerFinished ? {} : { target_assessment_artifact_id: "assessment-paused" },
          messages: [],
        });
      }
      if (path === "/api/recruitment-team/threads/thread-answering/events") return response([]);
      if (path === "/api/recruitment-team/threads/thread-answering/assessment") {
        return response({
          artifact_id: "assessment-paused",
          status: "paused",
          specialist_runs: [],
          synthesis: "",
          judge: null,
          correction: null,
          execution_policy: {},
        });
      }
      if (path.endsWith("/proposed-edits")) return response([]);
      throw new Error(`Unexpected request: ${path}`);
    });

    await act(async () => root.render(<RecruitmentTeamPanel user={{ id: 42 }} />));
    const textarea = container.querySelector("textarea");
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")
        .set.call(textarea, "The synthetic role was full-time in Singapore.");
      textarea.dispatchEvent(new Event("input", { bubbles: true }));
      textarea.closest("form").dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    });

    expect(textarea.disabled).toBe(true);
    expect(textarea.value).toBe("");
    expect(textarea.placeholder).toBe("Continuing the assessment...");
    expect(container.textContent).toContain("Continuing");
    expect(container.textContent).not.toContain("Queue message");
    expect(container.textContent).not.toContain("Waiting on your answer");

    await act(async () => releaseAnswer());
  });

  it("hands off a completed target assessment to a resume-agent session", async () => {
    sessionStorage.clear();
    localStorage.setItem("jobhunter:recruitment-thread:42", "thread-handoff");
    let assessed = false;
    const roleProfile = {
      criteria: [],
      candidate_evidence: [],
      cited_resume_evidence: [],
      sources: [],
      source_coverage: { taxonomy_match_quality: "unmatched" },
    };
    streamRecruitmentCommand.mockImplementation(async (_path, _body, onActivity) => {
      onActivity({
        sequence: 4,
        team_member: "recruiter",
        status: "completed",
        summary: "Recruiter screen completed.",
      });
      assessed = true;
      return { thread_id: "thread-handoff", status: "completed" };
    });
    const handoffCalls = [];
    apiFetch.mockImplementation(async (path, options = {}) => {
      if (path === "/api/resume/versions") return response([]);
      if (path === "/api/recruitment-team/threads/thread-handoff") {
        return response({
          thread_id: "thread-handoff",
          workflow_state: assessed ? "assessment_ready" : "target_selected",
          case_facts: {
            selected_target: { job_id: 101 },
            role_success_profile: roleProfile,
            target_assessment_artifact_id: assessed ? "assessment-1" : null,
          },
          messages: [],
        });
      }
      if (path === "/api/recruitment-team/threads/thread-handoff/events") {
        return response([]);
      }
      if (path === "/api/recruitment-team/threads/thread-handoff/assessment") {
        return response({
          artifact_id: "assessment-1",
          status: "completed",
          specialist_runs: [],
          synthesis: "Evidence-grounded target assessment.",
          judge: {
            disposition: "pass",
            score: 92,
            confidence: 90,
            score_reason: "reason",
            confidence_reason: "reason",
            strengths: [],
            weaknesses: [],
            evidence_gaps: [],
            rubric_scores: {},
            deductions: [],
          },
          correction: { attempted: false },
          execution_policy: {
            persona_pack_version: "recruitment-personas-v1",
            specialist_max_concurrency: 5,
            specialist_validation_attempts: 2,
            synthesis_validation_attempts: 2,
            judge_validation_attempts: 2,
            transport_retries: 0,
          },
        });
      }
      if (
        path === "/api/recruitment-team/threads/thread-handoff/resume-agent-handoff" &&
        options.method === "POST"
      ) {
        handoffCalls.push({ path, options });
        return response({ session_id: "resume-agent-session-9", status: "queued" });
      }
      if (path.includes("/proposed-edits")) return response([]);
      throw new Error(`Unexpected request: ${path}`);
    });

    const setActiveTab = vi.fn();
    await act(async () => {
      root.render(<RecruitmentTeamPanel user={{ id: 42 }} setActiveTab={setActiveTab} />);
    });

    expect(
      [...container.querySelectorAll("button")].some((button) =>
        button.textContent.includes("Draft resume edits for this job"),
      ),
    ).toBe(false);

    const assessButton = [...container.querySelectorAll("button")]
      .find((button) => button.textContent === "Run assessment");
    await act(async () => assessButton.click());

    const handoffButton = [...container.querySelectorAll("button")]
      .find((button) => button.textContent.includes("Draft resume edits for this job"));
    expect(handoffButton).not.toBeUndefined();

    await act(async () => handoffButton.click());

    expect(handoffCalls).toHaveLength(1);
    expect(sessionStorage.getItem("jh_resume_agent_session")).toBe("resume-agent-session-9");
    expect(sessionStorage.getItem("jh_resume_agent_autoopen")).toBe("1");
    expect(setActiveTab).toHaveBeenCalledWith("resume");
  });

  it("shows a durable failed turn after reload and retries it by run id", async () => {
    localStorage.setItem("jobhunter:recruitment-thread:42", "thread-retry");
    let recovered = false;
    const retryCalls = [];
    streamRecruitmentCommand.mockImplementation(async (path, body, onActivity) => {
      retryCalls.push({ path, body });
      recovered = true;
      onActivity({ sequence: 3, run_id: "run-retry", event_type: "run", status: "running", team_member: "coordinator", summary: "Retrying turn." });
      return { run_id: "run-retry", thread_id: "thread-retry", status: "completed" };
    });
    apiFetch.mockImplementation(async (path, options = {}) => {
      if (path === "/api/resume/versions") {
        return response([{ id: 7, label: "AI resume", is_master: true }]);
      }
      if (path === "/api/recruitment-team/threads/thread-retry") {
        return response({
          thread_id: "thread-retry",
          status: "active",
          workflow_state: "exploring",
          case_facts: { resume_version_id: 7, resume_label: "AI resume" },
          messages: recovered
            ? [
              { run_id: "run-retry", role: "user", content: "Tailor this resume." },
              { run_id: "run-retry", role: "assistant", content: "One edit is ready for review." },
            ]
            : [{ run_id: "run-retry", role: "user", content: "Tailor this resume." }],
        });
      }
      if (path === "/api/recruitment-team/threads/thread-retry/events") {
        return response(recovered
          ? [
            { sequence: 1, run_id: "run-retry", event_type: "run", status: "running", team_member: "coordinator", summary: "Reviewing request." },
            { sequence: 2, run_id: "run-retry", event_type: "run", status: "failed", team_member: "coordinator", summary: "Stopped.", detail: { command_type: "send_message", retryable: true, recovery_action: "correct_rejected_output" } },
            { sequence: 3, run_id: "run-retry", event_type: "run", status: "running", team_member: "coordinator", summary: "Reviewing request." },
            { sequence: 4, run_id: "run-retry", event_type: "run", status: "completed", team_member: "coordinator", summary: "Turn completed." },
          ]
          : [
            { sequence: 1, run_id: "run-retry", event_type: "run", status: "running", team_member: "coordinator", summary: "Reviewing request." },
            { sequence: 2, run_id: "run-retry", event_type: "run", status: "failed", team_member: "coordinator", summary: "Stopped.", detail: { command_type: "send_message", retryable: true, recovery_action: "correct_rejected_output" } },
          ]);
      }
      if (path === "/api/recruitment-team/threads/thread-retry/proposed-edits") {
        return response(recovered ? [{ id: "edit-1", status: "pending" }] : []);
      }
      throw new Error(`Unexpected request: ${path}`);
    });

    await act(async () => {
      root.render(<RecruitmentTeamPanel user={{ id: 42 }} />);
    });

    expect(container.textContent).toContain("Retry this turn");
    expect(container.textContent).toContain("correct rejected output");
    expect(container.textContent.match(/Tailor this resume\./g)).toHaveLength(1);

    await act(async () => {
      [...container.querySelectorAll("button")]
        .find((button) => button.textContent.includes("Retry this turn"))
        .click();
    });

    expect(retryCalls).toEqual([{
      path: "/api/recruitment-team/threads/thread-retry/runs/run-retry/retry/stream",
      body: {},
    }]);
    expect(container.textContent).toContain("One edit is ready for review.");
    expect(container.textContent.match(/Tailor this resume\./g)).toHaveLength(1);
    expect(container.textContent).not.toContain("Retry this turn");

    await act(async () => root.unmount());
    root = createRoot(container);
    await act(async () => {
      root.render(<RecruitmentTeamPanel user={{ id: 42 }} />);
    });
    expect(container.textContent).toContain("One edit is ready for review.");
    expect(container.textContent.match(/Tailor this resume\./g)).toHaveLength(1);
    expect(container.textContent).not.toContain("Retry this turn");
  });

  it("offers the backend retry path for a failed assessment answer", async () => {
    localStorage.setItem("jobhunter:recruitment-thread:42", "thread-answer-retry");
    const retryCalls = [];
    streamRecruitmentCommand.mockImplementation(async (path, body) => {
      retryCalls.push({ path, body });
      return { run_id: "run-answer-retry", thread_id: "thread-answer-retry", status: "completed" };
    });
    apiFetch.mockImplementation(async (path, options = {}) => {
      if (path === "/api/resume/versions") return response([]);
      if (path === "/api/recruitment-team/threads/thread-answer-retry") {
        return response({
          thread_id: "thread-answer-retry",
          status: "active",
          workflow_state: "assessment_failed",
          case_facts: {},
          messages: [],
        });
      }
      if (path === "/api/recruitment-team/threads/thread-answer-retry/events") {
        return response([{
          sequence: 2,
          run_id: "run-answer-retry",
          event_type: "run",
          status: "failed",
          team_member: "coordinator",
          summary: "Assessment answer stopped.",
          detail: {
            command_type: "answer_assessment_question",
            retryable: true,
            recovery_action: "retry_same_run",
          },
        }]);
      }
      if (path === "/api/recruitment-team/threads/thread-answer-retry/proposed-edits") {
        return response([]);
      }
      throw new Error(`Unexpected request: ${path}`);
    });

    await act(async () => root.render(<RecruitmentTeamPanel user={{ id: 42 }} />));
    expect(container.textContent).toContain("Retry this turn");

    await act(async () => {
      [...container.querySelectorAll("button")]
        .find((button) => button.textContent.includes("Retry this turn"))
        .click();
    });

    expect(retryCalls).toEqual([{
      path: "/api/recruitment-team/threads/thread-answer-retry/runs/run-answer-retry/retry/stream",
      body: {},
    }]);
  });

  it("shows a terminal conversation recovery action without a retry button", async () => {
    localStorage.setItem("jobhunter:recruitment-thread:42", "thread-terminal");
    apiFetch.mockImplementation(async (path) => {
      if (path === "/api/resume/versions") return response([]);
      if (path === "/api/recruitment-team/threads/thread-terminal") {
        return response({
          thread_id: "thread-terminal",
          status: "active",
          workflow_state: "exploring",
          case_facts: {},
          messages: [{ run_id: "run-terminal", role: "user", content: "Try this." }],
        });
      }
      if (path === "/api/recruitment-team/threads/thread-terminal/events") {
        return response([{
          sequence: 2,
          run_id: "run-terminal",
          event_type: "run",
          status: "failed",
          team_member: "coordinator",
          summary: "Stopped.",
          detail: {
            command_type: "send_message",
            retryable: false,
            recovery_action: "operator_review",
          },
        }]);
      }
      if (path.endsWith("/proposed-edits")) return response([]);
      throw new Error(`Unexpected request: ${path}`);
    });

    await act(async () => {
      root.render(<RecruitmentTeamPanel user={{ id: 42 }} />);
    });

    expect(container.textContent).toContain("operator review");
    expect(container.textContent).not.toContain("Retry this turn");
  });

  it("replaces a persisted working turn with stopped and retry after interruption", async () => {
    localStorage.setItem("jobhunter:recruitment-thread:42", "thread-interrupted");
    apiFetch.mockImplementation(async (path) => {
      if (path === "/api/resume/versions") return response([]);
      if (path === "/api/recruitment-team/threads/thread-interrupted") {
        return response({
          thread_id: "thread-interrupted",
          status: "active",
          workflow_state: "exploring",
          case_facts: {},
          messages: [{ run_id: "run-interrupted", role: "user", content: "Keep going." }],
        });
      }
      if (path === "/api/recruitment-team/threads/thread-interrupted/events") {
        return response([
          { sequence: 1, run_id: "run-interrupted", event_type: "run", status: "running", team_member: "coordinator", summary: "Working." },
          { sequence: 2, run_id: "run-interrupted", event_type: "run", status: "failed", team_member: "coordinator", summary: "Stopped.", detail: { command_type: "send_message", error_type: "process_interrupted", retryable: true, recovery_action: "retry_incomplete_stage" } },
        ]);
      }
      if (path.endsWith("/proposed-edits")) return response([]);
      throw new Error(`Unexpected request: ${path}`);
    });

    await act(async () => {
      root.render(<RecruitmentTeamPanel user={{ id: 42 }} />);
    });

    expect(container.textContent).toContain("This turn stopped");
    expect(container.textContent).toContain("retry incomplete stage");
    expect(container.textContent).toContain("Retry this turn");
    expect(container.textContent).not.toContain("Working from");
  });

  it("manages conversation lifecycle and shows retention before permanent deletion", async () => {
    localStorage.setItem("jobhunter:recruitment-thread:42", "thread-1");
    const lifecycle = { title: "Operations search", status: "active", deleted: false };
    let deleteCalls = 0;
    const retention = {
      live_data: "Deleted immediately from the live application database.",
      backups: "Infrastructure backups may expire later.",
      telemetry: "Trace deletion is requested and may not be immediate.",
    };
    apiFetch.mockImplementation(async (path, options = {}) => {
      if (path === "/api/resume/versions") return response([]);
      if (path === "/api/recruitment-team/threads") {
        return response(lifecycle.deleted ? [] : [{
          thread_id: "thread-1",
          title: lifecycle.title,
          status: lifecycle.status,
          workflow_state: "exploring",
          resume_label: "Manufacturing resume",
          last_message: "Current answer",
        }]);
      }
      if (path === "/api/recruitment-team/retention") return response(retention);
      if (path === "/api/recruitment-team/threads/thread-1" && options.method === "PATCH") {
        lifecycle.title = JSON.parse(options.body).title;
        return response({ thread_id: "thread-1", title: lifecycle.title, status: lifecycle.status });
      }
      if (path === "/api/recruitment-team/threads/thread-1/archive") {
        lifecycle.status = "archived";
        return response({ thread_id: "thread-1", title: lifecycle.title, status: lifecycle.status });
      }
      if (path === "/api/recruitment-team/threads/thread-1/restore") {
        lifecycle.status = "active";
        return response({ thread_id: "thread-1", title: lifecycle.title, status: lifecycle.status });
      }
      if (path === "/api/recruitment-team/threads/thread-1" && options.method === "DELETE") {
        deleteCalls += 1;
        lifecycle.deleted = true;
        return response({ thread_id: "thread-1", status: "deleted", retention });
      }
      if (path === "/api/recruitment-team/threads/thread-1") {
        return response({
          thread_id: "thread-1",
          title: lifecycle.title,
          status: lifecycle.status,
          workflow_state: "exploring",
          case_facts: { resume_label: "Manufacturing resume" },
          messages: [{ role: "assistant", content: "Current answer" }],
        });
      }
      if (path === "/api/recruitment-team/threads/thread-1/events") return response([]);
      if (path.endsWith("/proposed-edits")) return response([]);
      throw new Error(`Unexpected request: ${path}`);
    });

    await act(async () => root.render(<RecruitmentTeamPanel user={{ id: 42 }} />));
    const buttonNamed = (name) => container.querySelector(`button[aria-label="${name}"]`);
    const conversations = [...container.querySelectorAll("button")]
      .find((button) => button.textContent.includes("Conversations"));
    await act(async () => conversations.click());

    await act(async () => buttonNamed("Rename Operations search").click());
    const titleInput = container.querySelector('input[maxlength="120"]');
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")
        .set.call(titleInput, "Semiconductor transformation");
      titleInput.dispatchEvent(new Event("input", { bubbles: true }));
      titleInput.closest("form").dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    });
    expect(container.textContent).toContain("Semiconductor transformation");

    await act(async () => buttonNamed("Archive Semiconductor transformation").click());
    expect(container.textContent).toContain("archived. Restore it before continuing");
    expect(container.querySelector("textarea").disabled).toBe(true);

    const restore = [...container.querySelectorAll("button")]
      .find((button) => button.textContent === "Restore conversation");
    await act(async () => restore.click());
    expect(container.querySelector("textarea").disabled).toBe(false);

    await act(async () => buttonNamed("Delete Semiconductor transformation").click());
    expect(container.textContent).toContain(retention.live_data);
    expect(container.textContent).toContain(retention.backups);
    expect(deleteCalls).toBe(0);

    const confirmDelete = [...container.querySelectorAll("button")]
      .find((button) => button.textContent === "Delete permanently");
    await act(async () => confirmDelete.click());
    expect(deleteCalls).toBe(1);
    expect(localStorage.getItem("jobhunter:recruitment-thread:42")).toBeNull();
    expect(container.textContent).toContain("No saved conversations yet.");
  });
});
