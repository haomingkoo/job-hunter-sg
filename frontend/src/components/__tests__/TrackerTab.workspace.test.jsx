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
    refreshJobs = vi.fn();
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    vi.restoreAllMocks();
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
});
