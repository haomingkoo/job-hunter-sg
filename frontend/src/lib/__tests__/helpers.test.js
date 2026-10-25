import { describe, expect, it } from "vitest";
import { displayJobTitle, formatPostingDate } from "../helpers.js";

describe("formatPostingDate", () => {
  it("writes ISO dates for people", () => {
    expect(formatPostingDate("2026-10-25")).toBe("25 Oct 2026");
    expect(formatPostingDate("2026-10-25", { year: false })).toBe("25 Oct");
  });

  it("leaves already-readable or missing dates alone", () => {
    expect(formatPostingDate("14 Aug 2026")).toBe("14 Aug 2026");
    expect(formatPostingDate("")).toBe("");
    expect(formatPostingDate(null)).toBe("");
  });
});

describe("displayJobTitle", () => {
  it("strips emoji without touching the words", () => {
    expect(displayJobTitle("Sales & Marketing Associate | Regional Exposure ✈️")).toBe("Sales & Marketing Associate | Regional Exposure");
    expect(displayJobTitle("Data Analyst")).toBe("Data Analyst");
    expect(displayJobTitle("👋🏻BRAND AMBASSADORS")).toBe("BRAND AMBASSADORS");
  });
});
