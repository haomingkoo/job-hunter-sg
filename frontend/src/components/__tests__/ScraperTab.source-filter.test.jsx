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

const changeInput = (input, value) => {
  Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set.call(input, value);
  input.dispatchEvent(new Event("input", { bubbles: true }));
};

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
      "/api/jobs?page=1&per_page=20&source=MyCareersFuture&sort=balanced",
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
      "/api/jobs?page=1&per_page=20&location=Central+Area&sort=balanced",
      { method: "GET" },
    );

    await act(async () => {
      findCheckbox("3-5 yrs").click();
    });
    expect(apiFetch).toHaveBeenLastCalledWith(
      "/api/jobs?page=1&per_page=20&experience=3-5+yrs&location=Central+Area&sort=balanced",
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

  it("wires native posted dates and resets them with the other filters", async () => {
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

    const postedFrom = container.querySelector('input[aria-label="Posted from"]');
    const postedTo = container.querySelector('input[aria-label="Posted to"]');
    expect(postedFrom.type).toBe("date");
    expect(postedTo.type).toBe("date");

    await act(async () => {
      changeInput(postedFrom, "2026-08-01");
    });
    expect(apiFetch).toHaveBeenLastCalledWith(
      "/api/jobs?page=1&per_page=20&posted_from=2026-08-01&sort=balanced",
      { method: "GET" },
    );

    await act(async () => {
      changeInput(postedTo, "2026-08-15");
    });
    expect(apiFetch).toHaveBeenLastCalledWith(
      "/api/jobs?page=1&per_page=20&posted_from=2026-08-01&posted_to=2026-08-15&sort=balanced",
      { method: "GET" },
    );
    expect(container.textContent).toContain("Posted 2026-08-01 to 2026-08-15");

    const clear = [...container.querySelectorAll("button")]
      .find((button) => button.textContent.includes("Clear all filters"));
    await act(async () => clear.click());
    expect(apiFetch).toHaveBeenLastCalledWith(
      "/api/jobs?page=1&per_page=20&sort=balanced",
      { method: "GET" },
    );
  });

  it("uses the Singapore date for Scraped today and exposes filters in the mobile drawer", async () => {
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

    const today = new Intl.DateTimeFormat("en-CA", {
      timeZone: "Asia/Singapore",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    }).format(new Date());
    const scrapedToday = [...container.querySelectorAll("button")]
      .find((button) => button.textContent.trim() === "Scraped today");

    await act(async () => scrapedToday.click());
    expect(apiFetch).toHaveBeenLastCalledWith(
      `/api/jobs?page=1&per_page=20&scraped_from=${today}&scraped_to=${today}&sort=balanced`,
      { method: "GET" },
    );
    expect(container.textContent).toContain(`Scraped ${today}`);

    const mobileFilters = [...container.querySelectorAll("button")]
      .find((button) => button.textContent.startsWith("Filters"));
    await act(async () => mobileFilters.click());
    expect(container.querySelector('button[aria-label="Close filters"]')).toBeTruthy();
    expect(container.querySelectorAll('input[aria-label="Scraped from"]').length).toBe(2);
  });

  it("labels posting and scrape dates separately without inventing missing dates", async () => {
    apiFetch.mockResolvedValue({
      json: () => Promise.resolve({
        jobs: [
          {
            id: 1,
            title: "Dated role",
            company: "Example Employer",
            source: "MyCareersFuture",
            posted_date: "14 Aug 2026",
            // Legacy writers stored offset-free UTC. 16:00 UTC is midnight in Singapore.
            scraped_at: "2026-08-14T16:00:00",
          },
          {
            id: 2,
            title: "Undated role",
            company: "Example Employer",
            source: "Careers@Gov",
          },
        ],
        total: 2,
        pages: 1,
        filter_meta: { employment_types: [], locations: [], sectors: [], sources: [] },
      }),
    });

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

    expect(container.textContent).toContain("Posted 14 Aug 2026");
    expect(container.textContent).toContain("Scraped 15 Aug 2026");
    expect(container.textContent).not.toContain("Posted date unavailable");
    expect(container.textContent).not.toContain("Scraped date unavailable");
  });
});
