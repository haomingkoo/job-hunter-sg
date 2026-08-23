import { describe, expect, it } from "vitest";

import { parsePublicJobStats } from "../HomePage.jsx";


describe("HomePage public job statistics", () => {
  it("derives listing and active-source counts from the jobs response", () => {
    expect(parsePublicJobStats({
      total: 76216,
      filter_meta: {
        sources: [
          { value: "MyCareersFuture", count: 74884 },
          { value: "Careers@Gov", count: 1332 },
          { value: "Disabled", count: 0 },
        ],
      },
    })).toEqual({ jobCount: 76216, sourceCount: 2 });
  });

  it("does not manufacture statistics from a missing or malformed response", () => {
    expect(parsePublicJobStats(null)).toBeNull();
    expect(parsePublicJobStats({ total: "many", filter_meta: { sources: [] } })).toBeNull();
    expect(parsePublicJobStats({ total: 100 })).toBeNull();
  });

  it("accepts an honest zero-job response", () => {
    expect(parsePublicJobStats({ total: 0, filter_meta: { sources: [] } })).toEqual({
      jobCount: 0,
      sourceCount: 0,
    });
  });
});
