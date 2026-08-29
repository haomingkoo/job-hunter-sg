import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import AnalyticsTab from "../AnalyticsTab.jsx";
import { apiFetch } from "../../lib/api.js";

vi.mock("../../lib/api.js", () => ({ apiFetch: vi.fn() }));
vi.mock("recharts", () => ({
  Bar: () => null,
  CartesianGrid: () => null,
  ComposedChart: ({ children }) => <div>{children}</div>,
  Line: () => null,
  ResponsiveContainer: ({ children }) => <div>{children}</div>,
  Tooltip: () => null,
  XAxis: () => null,
  YAxis: () => null,
}));

const analyticsPayload = (partial) => ({
  partial,
  sampled_jobs: partial ? 12000 : 2272,
  total_jobs_with_terms: partial ? 11999 : 2266,
  skill_signal_count: 100,
  company_count: 50,
  sources: [{ source: "Careers@Gov", label: "Careers@Gov", count: partial ? 247 : 2266 }],
  top_skills: [],
  top_titles: [],
  sectors: [],
  top_companies: [],
  hard_skills: [],
  seniority_mix: [],
  agency_subsets: [],
});

describe("AnalyticsTab sample scope", () => {
  let container;
  let root;

  beforeEach(() => {
    vi.clearAllMocks();
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    apiFetch.mockImplementation((url) => Promise.resolve({
      ok: true,
      json: () => Promise.resolve(url.includes("/trends?")
        ? { series: [], recent_top_titles: [], recent_ats_terms: [] }
        : analyticsPayload(!url.includes("source=Careers%40Gov"))),
    }));
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  it("labels the capped sample and explains why a filtered count can increase", async () => {
    await act(async () => root.render(<AnalyticsTab />));

    expect(container.textContent).toContain("Sample roles analysed");
    expect(container.textContent).toContain("Sources in analysed sample");
    expect(container.textContent).toContain("a filtered count may be higher");

    const source = [...container.querySelectorAll("button")]
      .find((button) => button.title === "Filter by Careers@Gov");
    await act(async () => source.click());

    expect(apiFetch).toHaveBeenCalledWith(
      "/api/analytics/skills?limit=200&source=Careers%40Gov",
    );
    expect(container.textContent).toContain("Roles analysed");
    expect(container.textContent).not.toContain("Sample roles analysed");
  });
});
