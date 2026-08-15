import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import ScraperTab from "../ScraperTab.jsx";
import { apiFetch } from "../../lib/api.js";

vi.mock("../../lib/api.js", () => ({
  apiFetch: vi.fn(),
  downloadBlob: vi.fn(),
}));

const job = {
  id: 42,
  title: "AI Engineer",
  company: "Example Company",
  description: "Build reliable AI systems.",
  source: "MyCareersFuture",
  location: "Singapore",
  salary: "$8,000",
  type: "Full Time",
  posted_date: "Today",
  skills: [],
};

const jobsResponse = {
  json: async () => ({
    jobs: [job],
    total: 1,
    pages: 1,
    filter_meta: { employment_types: [], locations: [], sectors: [], sources: [] },
  }),
};

async function renderAndOpen(root, container, trackedJobs = []) {
  await act(async () => {
    root.render(
      <ScraperTab
        user={{ id: 1 }}
        trackedJobs={trackedJobs}
        onTrack={vi.fn()}
        setActiveTab={vi.fn()}
        setSelectedJob={vi.fn()}
        onSignIn={vi.fn()}
      />,
    );
    await Promise.resolve();
  });
  const button = [...container.querySelectorAll("button")]
    .find((item) => item.textContent.includes("Cover Letter"));
  act(() => button.click());
}

describe("ScraperTab cover-letter persistence", () => {
  let container;
  let root;

  beforeEach(() => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    vi.clearAllMocks();
    sessionStorage.setItem("jh_resume_text", "Built reliable Python and AI systems for production teams. ".repeat(3));
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    sessionStorage.clear();
    delete globalThis.IS_REACT_ACT_ENVIRONMENT;
  });

  it("truthfully reports an untracked generated letter as not saved", async () => {
    apiFetch.mockResolvedValueOnce(jobsResponse).mockResolvedValueOnce({
      json: async () => ({ cover_letter: "Dear Hiring Team, " + "Relevant experience. ".repeat(8), saved: false }),
    });
    await renderAndOpen(root, container);
    const generate = [...container.querySelectorAll("button")].find((item) => item.textContent === "Generate");
    await act(async () => generate.click());

    const request = JSON.parse(apiFetch.mock.calls[1][1].body);
    expect(request.workspace_id).toBeNull();
    expect(container.textContent).toContain("Not saved. Track this job to save future letters in Documents.");
  });

  it("saves tracked generation and subsequent candidate edits", async () => {
    apiFetch
      .mockResolvedValueOnce(jobsResponse)
      .mockResolvedValueOnce({
        json: async () => ({ cover_letter: "Dear Hiring Team, " + "Relevant experience. ".repeat(8), saved: true, workspace_id: 9 }),
      })
      .mockResolvedValueOnce({ json: async () => ({}) });
    await renderAndOpen(root, container, [{ id: 9, scraped_job_id: 42, role: job.title, company: job.company }]);
    const generate = [...container.querySelectorAll("button")].find((item) => item.textContent === "Generate");
    await act(async () => generate.click());

    expect(JSON.parse(apiFetch.mock.calls[1][1].body).workspace_id).toBe(9);
    expect(container.textContent).toContain("Saved to Documents.");

    const textarea = container.querySelector("textarea");
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value").set.call(
        textarea,
        "Dear Hiring Team, " + "Candidate verified edit. ".repeat(8),
      );
      textarea.dispatchEvent(new Event("input", { bubbles: true }));
    });
    expect(container.textContent).toContain("You have unsaved changes.");
    const save = [...container.querySelectorAll("button")].find((item) => item.textContent === "Save changes");
    await act(async () => save.click());
    expect(apiFetch.mock.calls[2][0]).toBe("/api/applications/workspaces/9/cover-letter");
    expect(container.textContent).toContain("Saved to Documents.");
  });
});
