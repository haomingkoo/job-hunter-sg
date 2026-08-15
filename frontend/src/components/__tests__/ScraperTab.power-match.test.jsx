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
  id: 17,
  title: "Platform Engineer",
  company: "Example Employer",
  location: "Singapore",
  salary: "$8,000",
  source: "MyCareersFuture",
  skills: ["Python"],
  job_terms_preview: ["Python"],
  job_terms_preview_ready: true,
  description: "Build reliable platforms.",
};

const jobsResponse = ({ ready = false, filtered = false } = {}) => ({
  json: () => Promise.resolve({
    jobs: ready ? [{
      ...job,
      power_match_score: 82,
      power_match_label: "Strong Match",
    }] : [job],
    total: filtered ? 1 : 1,
    pages: 1,
    filter_meta: {
      employment_types: [],
      locations: [],
      sectors: [],
      sources: [],
    },
    power_match: ready
      ? {
        status: "ready",
        reason: "ready",
        message: "Browse scores are ready for this resume and job corpus.",
        generate_action: "Refresh Power Match scores",
        score_count: 1,
      }
      : {
        status: "not_ready",
        reason: "snapshot_missing",
        message: "Generate Power Match scores to use scored Browse.",
        generate_action: "Generate Power Match scores",
      },
  }),
});

const renderScraper = async (root) => {
  await act(async () => {
    root.render(
      <ScraperTab
        user={{ id: 9, email: "candidate@example.com" }}
        trackedJobs={[]}
        onTrack={vi.fn()}
        setActiveTab={vi.fn()}
        setSelectedJob={vi.fn()}
        onSignIn={vi.fn()}
      />,
    );
  });
};

describe("ScraperTab persisted Power Match scores", () => {
  let container;
  let root;

  beforeEach(() => {
    vi.clearAllMocks();
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  it("only generates explicitly, renders saved scores, and filters on the server", async () => {
    let generated = false;
    apiFetch.mockImplementation((url, options) => {
      if (options?.method === "POST") {
        generated = true;
        return Promise.resolve({ json: () => Promise.resolve({ recommendations: [] }) });
      }
      return Promise.resolve(jobsResponse({
        ready: generated,
        filtered: url.includes("min_match_score=55"),
      }));
    });

    await renderScraper(root);

    expect(apiFetch).toHaveBeenCalledTimes(1);
    expect(apiFetch).toHaveBeenCalledWith(
      "/api/jobs?page=1&per_page=20&sort=balanced",
      { method: "GET" },
    );
    expect(container.textContent).toContain("Generate Power Match scores to use scored Browse.");
    const scoreFilter = container.querySelector('select[aria-label="Minimum Power Match score"]');
    expect(scoreFilter.disabled).toBe(true);

    const generate = [...container.querySelectorAll("button")]
      .find((button) => button.textContent.includes("Generate Power Match scores"));
    await act(async () => generate.click());

    const postCalls = apiFetch.mock.calls.filter(([, options]) => options?.method === "POST");
    expect(postCalls).toEqual([[
      "/api/jobs/power-match?limit=200&direct_employers_only=false",
      { method: "POST", timeoutMs: 45000 },
    ]]);
    expect(container.textContent).toContain("82 · Strong Match");
    expect(container.textContent).toContain("Refresh Power Match scores");
    expect(scoreFilter.disabled).toBe(false);

    await act(async () => {
      scoreFilter.value = "55";
      scoreFilter.dispatchEvent(new Event("change", { bubbles: true }));
    });

    expect(apiFetch).toHaveBeenLastCalledWith(
      "/api/jobs?page=1&per_page=20&min_match_score=55&sort=balanced",
      { method: "GET" },
    );
    expect(apiFetch.mock.calls.every(([url]) => (
      url.startsWith("/api/jobs?") || url.startsWith("/api/jobs/power-match?")
    ))).toBe(true);
  });

  it("shows generation errors and keeps the mobile filter usable", async () => {
    apiFetch.mockImplementation((_url, options) => {
      if (options?.method === "POST") return Promise.reject(new Error("Quota exhausted for today."));
      return Promise.resolve(jobsResponse());
    });

    await renderScraper(root);
    const generate = [...container.querySelectorAll("button")]
      .find((button) => button.textContent.includes("Generate Power Match scores"));
    await act(async () => generate.click());

    expect(container.textContent).toContain("Quota exhausted for today.");
    expect(generate.className).toContain("min-h-10");

    const filters = [...container.querySelectorAll("button")]
      .find((button) => button.textContent.trim() === "Filters");
    await act(async () => filters.click());
    const drawer = [...container.querySelectorAll("div")]
      .find((element) => typeof element.className === "string" && element.className.includes("fixed inset-0"));
    expect(drawer).toBeTruthy();
    expect(drawer.querySelector('select[aria-label="Minimum Power Match score"]')).toBeTruthy();
  });
});
