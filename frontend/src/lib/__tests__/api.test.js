import { beforeEach, describe, expect, it, vi } from "vitest";

import { AUTH_EXPIRED_EVENT, apiFetch, clearResumeDraftStorage } from "../api.js";

describe("apiFetch", () => {
  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
    vi.restoreAllMocks();
  });

  it("normalizes browser network failures", async () => {
    global.fetch = vi.fn(() => Promise.reject(new TypeError("Failed to fetch")));

    await expect(apiFetch("/api/resume/agent/chat")).rejects.toThrow(
      "Could not reach the backend. Make sure the backend server is running, then try again.",
    );
  });

  it("keeps resume drafts when auth expires", async () => {
    localStorage.setItem("token", "expired-token");
    sessionStorage.setItem("jh_resume_text", "draft");
    sessionStorage.setItem("jh_wizard_step", "3");
    const listener = vi.fn();
    window.addEventListener(AUTH_EXPIRED_EVENT, listener);
    global.fetch = vi.fn(() => Promise.resolve({
      ok: false,
      status: 401,
      text: () => Promise.resolve(""),
      headers: { get: () => "" },
    }));

    await expect(apiFetch("/api/auth/me")).rejects.toThrow("Session expired. Please sign in again.");

    expect(localStorage.getItem("token")).toBeNull();
    expect(sessionStorage.getItem("jh_resume_text")).toBe("draft");
    expect(sessionStorage.getItem("jh_wizard_step")).toBe("3");
    expect(listener).toHaveBeenCalledTimes(1);
    window.removeEventListener(AUTH_EXPIRED_EVENT, listener);
  });

  it("clears the full resume draft when explicitly requested", () => {
    sessionStorage.setItem("jh_resume_profile", "{}");
    sessionStorage.setItem("jh_resume_text", "draft");
    sessionStorage.setItem("jh_resume_template", "modern");
    sessionStorage.setItem("jh_wizard_step", "3");

    clearResumeDraftStorage();

    expect(sessionStorage.getItem("jh_resume_profile")).toBeNull();
    expect(sessionStorage.getItem("jh_resume_text")).toBeNull();
    expect(sessionStorage.getItem("jh_resume_template")).toBeNull();
    expect(sessionStorage.getItem("jh_wizard_step")).toBeNull();
  });
});
