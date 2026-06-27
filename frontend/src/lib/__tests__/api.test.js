import { describe, expect, it, vi } from "vitest";

import { apiFetch } from "../api.js";

describe("apiFetch", () => {
  it("normalizes browser network failures", async () => {
    global.fetch = vi.fn(() => Promise.reject(new TypeError("Failed to fetch")));

    await expect(apiFetch("/api/resume/agent/chat")).rejects.toThrow(
      "Could not reach the backend. Make sure the backend server is running, then try again.",
    );
  });
});
