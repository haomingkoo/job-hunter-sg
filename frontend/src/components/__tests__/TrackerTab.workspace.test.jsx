import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { apiFetch } from "../../lib/api.js";
import TrackerTab from "../TrackerTab.jsx";

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
