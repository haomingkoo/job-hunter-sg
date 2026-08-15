import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  AUTH_EXPIRED_EVENT,
  apiFetch,
  bindResumeDraftStorageToUser,
  clearResumeDraftStorage,
} from "../api.js";

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

  it("does not send a JSON content type for form data", async () => {
    global.fetch = vi.fn(() => Promise.resolve({ ok: true, status: 200 }));
    const body = new FormData();
    body.append("file", new Blob(["resume"]), "resume.txt");

    await apiFetch("/api/resume/upload", { method: "POST", body });

    expect(global.fetch.mock.calls[0][1].headers["Content-Type"]).toBeUndefined();
  });

  it("clears resume drafts when auth expires", async () => {
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
    expect(sessionStorage.getItem("jh_resume_text")).toBeNull();
    expect(sessionStorage.getItem("jh_wizard_step")).toBeNull();
    expect(listener).toHaveBeenCalledTimes(1);
    window.removeEventListener(AUTH_EXPIRED_EVENT, listener);
  });

  it("preserves an anonymous draft and requests sign-in for an account-only feature", async () => {
    sessionStorage.setItem("jh_resume_text", "anonymous draft");
    sessionStorage.setItem("jh_wizard_step", "3");
    const listener = vi.fn();
    window.addEventListener(AUTH_EXPIRED_EVENT, listener);
    global.fetch = vi.fn(() => Promise.resolve({
      ok: false,
      status: 401,
      text: () => Promise.resolve(""),
      headers: { get: () => "" },
    }));

    await expect(apiFetch("/api/ai/coach")).rejects.toThrow(
      "Please sign in to use this feature.",
    );

    expect(sessionStorage.getItem("jh_resume_text")).toBe("anonymous draft");
    expect(sessionStorage.getItem("jh_wizard_step")).toBe("3");
    expect(listener).toHaveBeenCalledTimes(1);
    expect(listener.mock.calls[0][0].detail).toEqual({ reason: "required" });
    window.removeEventListener(AUTH_EXPIRED_EVENT, listener);
  });

  it("preserves typed API error details", async () => {
    global.fetch = vi.fn(() => Promise.resolve({
      ok: false,
      status: 409,
      text: () => Promise.resolve(JSON.stringify({
        detail: {
          code: "power_match_not_ready",
          status: "not_ready",
          message: "Your resume changed. Generate Browse scores again.",
        },
      })),
      headers: { get: () => "application/json" },
    }));

    const error = await apiFetch("/api/jobs?min_match_score=55").catch((caught) => caught);

    expect(error.message).toBe("Your resume changed. Generate Browse scores again.");
    expect(error.detail).toMatchObject({
      code: "power_match_not_ready",
      status: "not_ready",
    });
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

  it("preserves an anonymous draft for its first account but clears it on an account switch", () => {
    sessionStorage.setItem("jh_resume_text", "anonymous draft");

    bindResumeDraftStorageToUser(1);
    expect(sessionStorage.getItem("jh_resume_text")).toBe("anonymous draft");

    bindResumeDraftStorageToUser(2);
    expect(sessionStorage.getItem("jh_resume_text")).toBeNull();
  });
});
