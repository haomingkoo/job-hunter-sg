import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import ScraperTab from "../ScraperTab.jsx";
import { apiFetch } from "../../lib/api.js";

vi.mock("../../lib/api.js", () => ({
  apiFetch: vi.fn(),
}));

const jobsResponse = (source = "MyCareersFuture") => ({
  json: () => Promise.resolve({
    jobs: [],
    total: 0,
    pages: 1,
    filter_meta: {
      employment_types: [],
      locations: [
        { value: "Central Area", count: 250 },
        { value: "West Region", count: 125 },
      ],
      sectors: [],
      sources: [
        { value: "MyCareersFuture", label: "MyCareersFuture", count: 12000 },
        { value: "Careers@Gov", label: "Careers@Gov", count: 2000 },
      ],
    },
    source,
  }),
});

describe("ScraperTab source filter", () => {
  let container;
  let root;

  beforeEach(() => {
    vi.clearAllMocks();
    apiFetch.mockResolvedValue(jobsResponse());
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  it("loads source options and sends the selected source to the jobs API", async () => {
    await act(async () => {
      root.render(
        <ScraperTab
          user={null}
          trackedJobs={[]}
          onTrack={vi.fn()}
          setActiveTab={vi.fn()}
          setSelectedJob={vi.fn()}
          onSignIn={vi.fn()}
        />,
      );
    });

    const sourceRadio = [...container.querySelectorAll('input[name="source"]')]
      .find((input) => input.parentElement.textContent.includes("MyCareersFuture"));

    expect(sourceRadio).toBeTruthy();
    expect(container.textContent).toContain("12,000");

    await act(async () => {
      sourceRadio.click();
    });

    expect(apiFetch).toHaveBeenLastCalledWith(
      "/api/jobs?page=1&per_page=20&source=MyCareersFuture",
      { method: "GET" },
    );
  });

  it("sends location, experience, and salary sort to the jobs API", async () => {
    await act(async () => {
      root.render(
        <ScraperTab
          user={null}
          trackedJobs={[]}
          onTrack={vi.fn()}
          setActiveTab={vi.fn()}
          setSelectedJob={vi.fn()}
          onSignIn={vi.fn()}
        />,
      );
    });

    const findCheckbox = (label) => [...container.querySelectorAll('input[type="checkbox"]')]
      .find((input) => input.parentElement.textContent.includes(label));

    expect(container.textContent).toContain("Central Area");
    expect(container.textContent).toContain("250");

    await act(async () => {
      findCheckbox("Central Area").click();
    });
    expect(apiFetch).toHaveBeenLastCalledWith(
      "/api/jobs?page=1&per_page=20&location=Central+Area",
      { method: "GET" },
    );

    await act(async () => {
      findCheckbox("3-5 yrs").click();
    });
    expect(apiFetch).toHaveBeenLastCalledWith(
      "/api/jobs?page=1&per_page=20&experience=3-5+yrs&location=Central+Area",
      { method: "GET" },
    );

    const sort = container.querySelector("select");
    await act(async () => {
      sort.value = "salary";
      sort.dispatchEvent(new Event("change", { bubbles: true }));
    });
    expect(apiFetch).toHaveBeenLastCalledWith(
      "/api/jobs?page=1&per_page=20&experience=3-5+yrs&location=Central+Area&sort=salary",
      { method: "GET" },
    );
  });
});
