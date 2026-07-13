import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { apiFetch } from "../../lib/api.js";
import TrackerTab, { getPipelineStatusMove } from "../TrackerTab.jsx";

vi.mock("../../lib/api.js", () => ({
  API_BASE: "",
  apiFetch: vi.fn(),
}));

function setField(field, value) {
  const setter = Object.getOwnPropertyDescriptor(field.constructor.prototype, "value")?.set;
  setter.call(field, value);
  field.dispatchEvent(new Event("input", { bubbles: true }));
}

describe("TrackerTab workspace creation", () => {
  let container;
  let root;
  let refreshJobs;

  beforeEach(() => {
    apiFetch.mockReset();
    apiFetch.mockResolvedValue({});
    vi.stubGlobal("fetch", vi.fn());
    refreshJobs = vi.fn();
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("creates a workspace from pasted job description", async () => {
    await act(async () => {
      root.render(
        <TrackerTab
          user={{ tier: "pro" }}
          jobs={[]}
          refreshJobs={refreshJobs}
          setActiveTab={() => {}}
        />,
      );
    });

    const pasteButton = Array.from(container.querySelectorAll("button"))
      .find((button) => button.textContent.includes("Paste JD"));
    await act(async () => {
      pasteButton.click();
    });

    await act(async () => {
      setField(container.querySelector("input[placeholder='Company *']"), "GovTech");
      setField(container.querySelector("input[placeholder='Role *']"), "Senior AI Engineer");
      setField(container.querySelector("input[placeholder='Source URL']"), "https://example.com/jobs/1");
      setField(
        container.querySelector("textarea[placeholder='Paste job description *']"),
        "Build agentic workflows for public-sector digital services.",
      );
    });

    const saveButton = Array.from(container.querySelectorAll("button"))
      .find((button) => button.textContent.includes("Save"));
    await act(async () => {
      saveButton.click();
    });

    expect(apiFetch).toHaveBeenCalledTimes(1);
    const [path, options] = apiFetch.mock.calls[0];
    expect(path).toBe("/api/applications/workspaces");
    expect(options.method).toBe("POST");
    expect(JSON.parse(options.body)).toMatchObject({
      company: "GovTech",
      title: "Senior AI Engineer",
      job_description: "Build agentic workflows for public-sector digital services.",
      source_url: "https://example.com/jobs/1",
      source: "Other",
      status: "saved",
      follow_up_date: "",
      notes: "",
    });
    expect(refreshJobs).toHaveBeenCalledTimes(1);
  });

  it("shows a clear error before submitting a workspace without job description", async () => {
    await act(async () => {
      root.render(
        <TrackerTab
          user={{ tier: "pro" }}
          jobs={[]}
          refreshJobs={refreshJobs}
          setActiveTab={() => {}}
        />,
      );
    });

    const pasteButton = Array.from(container.querySelectorAll("button"))
      .find((button) => button.textContent.includes("Paste JD"));
    await act(async () => {
      pasteButton.click();
    });

    await act(async () => {
      setField(container.querySelector("input[placeholder='Company *']"), "GovTech");
      setField(container.querySelector("input[placeholder='Role *']"), "Senior AI Engineer");
    });

    const saveButton = Array.from(container.querySelectorAll("button"))
      .find((button) => button.textContent.includes("Save"));
    await act(async () => {
      saveButton.click();
    });

    expect(container.textContent).toContain("Job description is required to create a workspace.");
    expect(apiFetch).not.toHaveBeenCalled();
  });

  it("opens a workspace detail view from a tracked application", async () => {
    const workspace = {
      id: 123,
      company: "GovTech",
      title: "Senior AI Engineer",
      role: "Senior AI Engineer",
      job_description: "Build agentic workflows for public-sector digital services.",
      source_url: "https://example.com/jobs/1",
      source: "Other",
      status: "saved",
      date_applied: "2026-07-04",
      follow_up_date: "",
      notes: "",
      scraped_job_id: null,
      resume_version_id: 7,
      role_metadata: {},
      stage_history: [{ stage: "saved", date: "2026-07-04", source: "created", notes: "" }],
      created_at: "2026-07-04T00:00:00Z",
      updated_at: "2026-07-04T00:00:00Z",
    };
    apiFetch.mockResolvedValueOnce({ json: vi.fn().mockResolvedValue(workspace) });

    await act(async () => {
      root.render(
        <TrackerTab
          user={{ tier: "pro" }}
          jobs={[{
            id: 123,
            company: "GovTech",
            role: "Senior AI Engineer",
            date_applied: "2026-07-04",
            status: "saved",
            source: "Other",
          }]}
          refreshJobs={refreshJobs}
          setActiveTab={() => {}}
        />,
      );
    });

    const openButton = container.querySelector("button[aria-label='Open workspace for GovTech Senior AI Engineer']");
    await act(async () => {
      openButton.click();
    });

    expect(apiFetch).toHaveBeenCalledWith("/api/applications/workspaces/123");
    expect(container.textContent).toContain("Application Workspace");
    expect(container.textContent).toContain("Senior AI Engineer at GovTech");
    expect(container.textContent).toContain("Build agentic workflows for public-sector digital services.");
    expect(container.textContent).toContain("Saved");
    expect(container.textContent).toContain("Version #7");
    expect(container.textContent).toContain("Agent review not run yet.");
    expect(container.textContent).toContain("No submitted resume recorded yet.");
  });

  it("runs a linked resume through Deep Agent with a clear loading state", async () => {
    const workspace = {
      id: 123,
      company: "GovTech",
      title: "Senior AI Engineer",
      role: "Senior AI Engineer",
      job_description: "Build agentic workflows for public-sector digital services.",
      source: "Other",
      status: "saved",
      date_applied: "2026-07-04",
      resume_version_id: 7,
      role_metadata: {},
      stage_history: [],
    };
    const reviewedWorkspace = {
      ...workspace,
      role_metadata: {
        agent_review: {
          debate_summary: {
            roles: ["recruiter"],
            final_recommendation: "Lead with verified delivery impact.",
            confidence: "high",
          },
        },
      },
    };
    let finishReview;
    const reviewResponse = new Promise((resolve) => {
      finishReview = () => resolve({ json: vi.fn().mockResolvedValue(reviewedWorkspace) });
    });
    apiFetch
      .mockResolvedValueOnce({ json: vi.fn().mockResolvedValue(workspace) })
      .mockReturnValueOnce(reviewResponse);

    await act(async () => {
      root.render(
        <TrackerTab
          jobs={[{ id: 123, company: "GovTech", role: "Senior AI Engineer", status: "saved", source: "Other" }]}
          refreshJobs={refreshJobs}
          setActiveTab={() => {}}
        />,
      );
    });
    await act(async () => {
      container.querySelector("button[aria-label='Open workspace for GovTech Senior AI Engineer']").click();
    });

    const runButton = Array.from(container.querySelectorAll("button"))
      .find((button) => button.textContent.includes("Run Deep Agent review"));
    await act(async () => {
      runButton.click();
    });

    expect(container.querySelector("[role='status']").textContent).toContain("20–40 seconds");
    expect(apiFetch).toHaveBeenLastCalledWith(
      "/api/applications/workspaces/123/agent-review",
      { method: "POST", body: "{}" },
    );

    await act(async () => {
      finishReview();
      await reviewResponse;
    });
    expect(container.textContent).toContain("Lead with verified delivery impact.");
    expect(container.querySelector("[role='status']")).toBeNull();
  });

  it("groups tracked applications by status in board view", async () => {
    await act(async () => {
      root.render(
        <TrackerTab
          user={{ tier: "pro" }}
          jobs={[
            {
              id: 123,
              company: "GovTech",
              role: "Senior AI Engineer",
              date_applied: "2026-07-04",
              status: "saved",
              source: "Other",
            },
            {
              id: 124,
              company: "Grab",
              role: "ML Engineer",
              date_applied: "2026-07-03",
              status: "interview",
              source: "Referral",
            },
          ]}
          refreshJobs={refreshJobs}
          setActiveTab={() => {}}
        />,
      );
    });

    const boardButton = Array.from(container.querySelectorAll("button"))
      .find((button) => button.textContent.includes("Board"));
    await act(async () => {
      boardButton.click();
    });

    const savedColumn = container.querySelector("[data-pipeline-column='saved']");
    const interviewColumn = container.querySelector("[data-pipeline-column='interview']");
    const appliedColumn = container.querySelector("[data-pipeline-column='applied']");
    expect(savedColumn.textContent).toContain("GovTech");
    expect(savedColumn.textContent).toContain("Senior AI Engineer");
    expect(interviewColumn.textContent).toContain("Grab");
    expect(interviewColumn.textContent).toContain("ML Engineer");
    expect(appliedColumn.textContent).toContain("Drop here");
  });

  it("shows outcome counts in the tracker dashboard", async () => {
    await act(async () => {
      root.render(
        <TrackerTab
          user={{ tier: "pro" }}
          jobs={[
            { id: 1, company: "A", role: "Engineer", date_applied: "2026-07-04", status: "applied", source: "Other" },
            { id: 2, company: "B", role: "Engineer", date_applied: "2026-07-04", status: "screening", source: "Other" },
            { id: 3, company: "C", role: "Engineer", date_applied: "2026-07-04", status: "final_round", source: "Other" },
            { id: 4, company: "D", role: "Engineer", date_applied: "2026-07-04", status: "accepted", source: "Other" },
            { id: 5, company: "E", role: "Engineer", date_applied: "2026-07-04", status: "rejected", source: "Other" },
            { id: 6, company: "F", role: "Engineer", date_applied: "2026-07-04", status: "withdrawn", source: "Other" },
            { id: 7, company: "G", role: "Engineer", date_applied: "2026-07-04", status: "no_response", source: "Other" },
          ]}
          refreshJobs={refreshJobs}
          setActiveTab={() => {}}
        />,
      );
    });

    const outcomeValue = (key) => container.querySelector(`[data-outcome-count='${key}'] div`).textContent;
    expect(outcomeValue("submitted")).toBe("1");
    expect(outcomeValue("interview")).toBe("2");
    expect(outcomeValue("offer")).toBe("1");
    expect(outcomeValue("rejected")).toBe("1");
    expect(outcomeValue("withdrawn")).toBe("1");
    expect(outcomeValue("no_response")).toBe("1");
  });

  it("maps a board drop to a status update target", () => {
    const active = { data: { current: { jobId: 123, status: "saved" } } };

    expect(getPipelineStatusMove(active, { id: "status:interview" })).toEqual({
      jobId: 123,
      nextStatus: "interview",
    });
    expect(getPipelineStatusMove(active, { id: "status:saved" })).toBeNull();
    expect(getPipelineStatusMove(active, { id: "status:not_real" })).toBeNull();
    expect(getPipelineStatusMove(active, null)).toBeNull();
  });

  it("shows a saved debate summary in the workspace detail view", async () => {
    const workspace = {
      id: 123,
      company: "GovTech",
      title: "Senior AI Engineer",
      role: "Senior AI Engineer",
      job_description: "Build agentic workflows for public-sector digital services.",
      source_url: "https://example.com/jobs/1",
      source: "Other",
      status: "saved",
      date_applied: "2026-07-04",
      follow_up_date: "",
      notes: "",
      scraped_job_id: null,
      resume_version_id: 7,
      role_metadata: {
        agent_review: {
          debate_summary: {
            roles: ["recruiter", "ats", "skeptic"],
            key_disagreements: ["ATS wants more keyword coverage; skeptic wants proof first."],
            final_recommendation: "Revise one bullet, then rerun review.",
            confidence: "medium",
            trace_id: "trace-123",
          },
        },
      },
      stage_history: [{ stage: "saved", date: "2026-07-04", source: "created", notes: "" }],
      created_at: "2026-07-04T00:00:00Z",
      updated_at: "2026-07-04T00:00:00Z",
    };
    apiFetch.mockResolvedValueOnce({ json: vi.fn().mockResolvedValue(workspace) });

    await act(async () => {
      root.render(
        <TrackerTab
          user={{ tier: "pro" }}
          jobs={[{
            id: 123,
            company: "GovTech",
            role: "Senior AI Engineer",
            date_applied: "2026-07-04",
            status: "saved",
            source: "Other",
          }]}
          refreshJobs={refreshJobs}
          setActiveTab={() => {}}
        />,
      );
    });

    const openButton = container.querySelector("button[aria-label='Open workspace for GovTech Senior AI Engineer']");
    await act(async () => {
      openButton.click();
    });

    expect(container.textContent).toContain("Debate summary");
    expect(container.textContent).toContain("Revise one bullet, then rerun review.");
    expect(container.textContent).toContain("recruiter");
    expect(container.textContent).toContain("ATS wants more keyword coverage; skeptic wants proof first.");
    expect(container.textContent).toContain("Confidence: medium, trace ID: trace-123");
  });

  it("shows a saved interview prep pack in the workspace detail view", async () => {
    const workspace = {
      id: 123,
      company: "GovTech",
      title: "Senior AI Engineer",
      role: "Senior AI Engineer",
      job_description: "Build agentic workflows for public-sector digital services.",
      source_url: "https://example.com/jobs/1",
      source: "Other",
      status: "saved",
      date_applied: "2026-07-04",
      follow_up_date: "",
      notes: "",
      scraped_job_id: null,
      resume_version_id: 7,
      role_metadata: {
        interview_prep_pack: {
          status: "ready",
          summary: { question_count: 2, evidence_question_count: 1, source_count: 3 },
          question_clusters: [
            {
              question_key: "technical:job-board:python",
              type: "technical",
              confidence: "high",
              question: "How have you used Python in work relevant to this role?",
            },
          ],
          evidence_questions: [
            {
              claim_id: "",
              question: "What evidence proves your experience with Applied AI Engineer?",
            },
          ],
        },
      },
      stage_history: [{ stage: "saved", date: "2026-07-04", source: "created", notes: "" }],
      created_at: "2026-07-04T00:00:00Z",
      updated_at: "2026-07-04T00:00:00Z",
    };
    apiFetch.mockResolvedValueOnce({ json: vi.fn().mockResolvedValue(workspace) });

    await act(async () => {
      root.render(
        <TrackerTab
          user={{ tier: "pro" }}
          jobs={[{
            id: 123,
            company: "GovTech",
            role: "Senior AI Engineer",
            date_applied: "2026-07-04",
            status: "saved",
            source: "Other",
          }]}
          refreshJobs={refreshJobs}
          setActiveTab={() => {}}
        />,
      );
    });

    const openButton = container.querySelector("button[aria-label='Open workspace for GovTech Senior AI Engineer']");
    await act(async () => {
      openButton.click();
    });

    expect(container.querySelector("[data-interview-prep-pack]")).not.toBeNull();
    expect(container.textContent).toContain("Interview prep");
    expect(container.textContent).toContain("2 questions · 1 evidence gaps · 3 sources");
    expect(container.textContent).toContain("How have you used Python in work relevant to this role?");
    expect(container.textContent).toContain("What evidence proves your experience with Applied AI Engineer?");
  });

  it("uploads a submitted resume artifact from the workspace detail view", async () => {
    const workspace = {
      id: 123,
      company: "GovTech",
      title: "Senior AI Engineer",
      role: "Senior AI Engineer",
      job_description: "Build agentic workflows for public-sector digital services.",
      source_url: "https://example.com/jobs/1",
      source: "Other",
      status: "saved",
      date_applied: "2026-07-04",
      follow_up_date: "",
      notes: "",
      scraped_job_id: null,
      resume_version_id: 7,
      role_metadata: {},
      stage_history: [{ stage: "saved", date: "2026-07-04", source: "created", notes: "" }],
      created_at: "2026-07-04T00:00:00Z",
      updated_at: "2026-07-04T00:00:00Z",
    };
    const uploadedWorkspace = {
      ...workspace,
      role_metadata: {
        submitted_resume: {
          filename: "submitted.pdf",
          submitted_date: "2026-07-04",
          notes: "Submitted through company portal.",
          word_count: 42,
        },
      },
    };
    apiFetch.mockResolvedValueOnce({ json: vi.fn().mockResolvedValue(workspace) });
    fetch.mockResolvedValueOnce({ ok: true, json: vi.fn().mockResolvedValue(uploadedWorkspace) });

    await act(async () => {
      root.render(
        <TrackerTab
          user={{ tier: "pro" }}
          jobs={[{
            id: 123,
            company: "GovTech",
            role: "Senior AI Engineer",
            date_applied: "2026-07-04",
            status: "saved",
            source: "Other",
          }]}
          refreshJobs={refreshJobs}
          setActiveTab={() => {}}
        />,
      );
    });

    const openButton = container.querySelector("button[aria-label='Open workspace for GovTech Senior AI Engineer']");
    await act(async () => {
      openButton.click();
    });

    const file = new File(["resume"], "submitted.pdf", { type: "application/pdf" });
    const fileInput = container.querySelector("input[type='file']");
    Object.defineProperty(fileInput, "files", { value: [file], configurable: true });
    await act(async () => {
      fileInput.dispatchEvent(new Event("change", { bubbles: true }));
      setField(container.querySelector("input[placeholder='Submitted resume notes']"), "Submitted through company portal.");
    });

    const saveButton = Array.from(container.querySelectorAll("button"))
      .find((button) => button.textContent.includes("Save submitted resume"));
    await act(async () => {
      saveButton.click();
    });

    expect(fetch).toHaveBeenCalledTimes(1);
    const [url, options] = fetch.mock.calls[0];
    expect(url).toBe("/api/applications/workspaces/123/submitted-resume");
    expect(options.method).toBe("POST");
    expect(options.body.get("file")).toBe(file);
    expect(options.body.get("notes")).toBe("Submitted through company portal.");
    expect(container.textContent).toContain("submitted.pdf");
    expect(container.textContent).toContain("2026-07-04 - 42 words");
  });
});
