import { describe, expect, it } from "vitest";

import {
  ACTIVITY_HISTORY_LIMIT,
  activityDetail,
  normalizeActivityEvents,
} from "../recruitmentActivity.js";


describe("recruitment activity contract", () => {
  it("uses structured tool metadata instead of parsing contradictory prose", () => {
    const detail = activityDetail({
      team_member: "coordinator",
      summary: "coordinator called search_jobs.",
      detail: { tool_name: "read_target_job", stage: "call" },
    });

    expect(detail).toEqual({ tool_name: "read_target_job", stage: "call" });
  });

  it("adapts persisted legacy call summaries without changing their stored shape", () => {
    const detail = activityDetail({
      team_member: "coordinator",
      summary: "coordinator called search_jobs.",
      detail: {},
    });

    expect(detail).toEqual({ tool_name: "search_jobs", stage: "call" });
  });

  it("keeps only the newest bounded activity history after ordering and deduping", () => {
    const events = Array.from({ length: ACTIVITY_HISTORY_LIMIT + 3 }, (_, index) => ({
      sequence: index + 1,
    }));

    const normalized = normalizeActivityEvents([events.at(-1), ...events, events[0]]);

    expect(normalized).toHaveLength(ACTIVITY_HISTORY_LIMIT);
    expect(normalized[0].sequence).toBe(4);
    expect(normalized.at(-1).sequence).toBe(ACTIVITY_HISTORY_LIMIT + 3);
  });
});
