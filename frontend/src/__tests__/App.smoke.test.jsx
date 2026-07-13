import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("framer-motion", async (importOriginal) => ({
  ...(await importOriginal()),
  AnimatePresence: ({ children }) => children,
}));

import JobHunterSG, { readActiveTab } from "../App.jsx";
import { AUTH_EXPIRED_EVENT, AUTH_SYNC_KEY } from "../lib/api.js";

function jsonResponse(data, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: { get: () => "application/json" },
    json: async () => data,
    text: async () => JSON.stringify(data),
  };
}

async function flushEffects() {
  for (let index = 0; index < 6; index += 1) {
    await act(async () => Promise.resolve());
  }
}

describe("JobHunterSG app shell", () => {
  let container;
  let root;

  beforeEach(() => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    localStorage.clear();
    sessionStorage.clear();
    window.history.replaceState({}, "", "/");
    vi.restoreAllMocks();
    global.IntersectionObserver = class {
      observe() {}
      unobserve() {}
      disconnect() {}
    };
    window.scrollTo = vi.fn();
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    delete global.IntersectionObserver;
    delete globalThis.IS_REACT_ACT_ENVIRONMENT;
    vi.restoreAllMocks();
  });

  it("mounts the public app shell without auth", async () => {
    await act(async () => {
      root.render(<JobHunterSG />);
    });

    expect(container.textContent).toContain("Job Hunter SG");
    expect(container.textContent).toContain("Sign In");
  });

  it("keeps the reminders route reachable", () => {
    expect(readActiveTab("#reminders")).toBe("reminders");
  });

  it("opens the tab named by a direct hash URL", async () => {
    window.history.replaceState({}, "", "/#resume");
    global.fetch = vi.fn(async (url) => {
      const path = String(url);
      if (path.endsWith("/api/auth/config")) return jsonResponse({ mode: "password" });
      if (path.endsWith("/api/auth/me")) return jsonResponse({ detail: "Not authenticated" }, 401);
      if (path.endsWith("/api/resume/templates")) return jsonResponse({ templates: [] });
      if (path.endsWith("/api/resume/versions")) return jsonResponse({ versions: [] });
      if (path.endsWith("/api/ai/status")) return jsonResponse({ status: "available" });
      return jsonResponse({});
    });

    await act(async () => {
      root.render(<JobHunterSG />);
    });
    await flushEffects();

    expect(container.textContent).toContain("How would you like to start?");
    expect(container.textContent).not.toContain("Find the role that fits you best");
  });

  it("opens sign-in without leaving the resume when an anonymous AI action is gated", async () => {
    window.history.replaceState({}, "", "/#resume");
    sessionStorage.setItem("jh_resume_text", "anonymous draft");
    global.fetch = vi.fn(async (url) => {
      const path = String(url);
      if (path.endsWith("/api/auth/config")) return jsonResponse({ mode: "password" });
      if (path.endsWith("/api/auth/me")) return jsonResponse({ detail: "Not authenticated" }, 401);
      if (path.endsWith("/api/resume/templates")) return jsonResponse({ templates: [] });
      if (path.endsWith("/api/resume/versions")) return jsonResponse({ versions: [] });
      if (path.endsWith("/api/ai/status")) return jsonResponse({ status: "available" });
      return jsonResponse({});
    });

    await act(async () => {
      root.render(<JobHunterSG />);
    });
    await flushEffects();
    await act(async () => {
      window.dispatchEvent(new CustomEvent(AUTH_EXPIRED_EVENT, {
        detail: { reason: "required" },
      }));
    });

    expect(window.location.hash).toBe("#resume");
    expect(container.textContent).toContain("Welcome back");
    expect(container.textContent).toContain("Resume Workspace");
    expect(container.textContent).toContain("anonymous draft");
    expect(sessionStorage.getItem("jh_resume_text")).toBe("anonymous draft");
  });

  it("removes email-link secrets before app requests run", async () => {
    window.history.replaceState(
      {},
      "",
      "/?source=mcf&verify_token=legacy#reset_token=fragment&tab=account",
    );
    const requestLocations = [];
    global.fetch = vi.fn(async () => {
      requestLocations.push(window.location.href);
      return {
        ok: true,
        status: 200,
        json: async () => ({ mode: "password", total: 0, jobs: [] }),
      };
    });

    await act(async () => {
      root.render(<JobHunterSG />);
    });

    expect(window.location.search).toBe("?source=mcf");
    expect(window.location.hash).toBe("#tab=account");
    expect(requestLocations.length).toBeGreaterThan(0);
    expect(requestLocations.every((url) => !url.includes("legacy") && !url.includes("fragment"))).toBe(true);
  });

  it("discards stale tracked jobs when another tab switches accounts", async () => {
    localStorage.setItem("token", "token-a");
    sessionStorage.setItem("jh_resume_text", "Account A private resume");
    let resolveAccountATracked;
    const accountATracked = new Promise((resolve) => { resolveAccountATracked = resolve; });

    global.fetch = vi.fn(async (url, options = {}) => {
      const path = String(url);
      const authorization = options.headers?.Authorization;
      if (path.endsWith("/api/auth/config")) return jsonResponse({ mode: "password" });
      if (path.endsWith("/api/auth/me")) {
        return authorization === "Bearer token-b"
          ? jsonResponse({ id: 2, name: "Account B", email: "b@example.com" })
          : jsonResponse({ id: 1, name: "Account A", email: "a@example.com" });
      }
      if (path.endsWith("/api/tracked")) {
        if (authorization === "Bearer token-a") return accountATracked;
        return jsonResponse([
          {
            id: 2,
            company: "Account B Employer",
            role: "Account B Role",
            status: "applied",
            source: "MyCareersFuture",
            date_applied: "2026-07-13",
          },
        ]);
      }
      if (path.includes("/api/jobs?")) return jsonResponse({ total: 0, jobs: [] });
      return jsonResponse({});
    });

    await act(async () => {
      root.render(<JobHunterSG />);
    });
    await flushEffects();
    expect(global.fetch).toHaveBeenCalledWith(
      "/api/tracked",
      expect.objectContaining({ headers: expect.objectContaining({ Authorization: "Bearer token-a" }) }),
    );

    await act(async () => {
      localStorage.setItem("token", "token-b");
      window.dispatchEvent(new StorageEvent("storage", {
        key: "token",
        oldValue: "token-a",
        newValue: "token-b",
      }));
    });
    await flushEffects();
    expect(sessionStorage.getItem("jh_resume_text")).toBeNull();

    await act(async () => {
      resolveAccountATracked(jsonResponse([
        {
          id: 1,
          company: "Account A Employer",
          role: "Account A Role",
          status: "applied",
        },
      ]));
    });
    await flushEffects();

    const startButton = [...container.querySelectorAll("button")]
      .find((button) => button.textContent.includes("Start exploring"));
    await act(async () => {
      startButton.click();
      await new Promise((resolve) => window.setTimeout(resolve, 350));
    });
    await flushEffects();
    const applicationsButton = [...container.querySelectorAll("button")]
      .find((button) => button.textContent.trim() === "Applications");
    await act(async () => {
      applicationsButton.click();
      await new Promise((resolve) => window.setTimeout(resolve, 350));
    });
    await flushEffects();

    expect(container.textContent).toContain("Account B Employer");
    expect(container.textContent).not.toContain("Account A Employer");
  });

  it("clears Cloudflare account data when another tab changes identity", async () => {
    let identity = { id: 1, name: "Account A", email: "a@example.com" };
    let identityRequests = 0;
    sessionStorage.setItem("jh_resume_owner", "1");
    sessionStorage.setItem("jh_resume_text", "Account A private resume");

    global.fetch = vi.fn(async (url) => {
      const path = String(url);
      if (path.endsWith("/api/auth/config")) return jsonResponse({ mode: "cloudflare" });
      if (path.endsWith("/api/auth/me")) {
        identityRequests += 1;
        return jsonResponse(identity);
      }
      if (path.endsWith("/api/tracked")) return jsonResponse([]);
      return jsonResponse({});
    });

    await act(async () => {
      root.render(<JobHunterSG />);
    });
    await flushEffects();
    expect(container.textContent).toContain("Account A");

    identity = { id: 2, name: "Account B", email: "b@example.com" };
    await act(async () => {
      window.dispatchEvent(new StorageEvent("storage", {
        key: AUTH_SYNC_KEY,
        oldValue: null,
        newValue: "login:other-tab",
      }));
    });
    await flushEffects();

    expect(identityRequests).toBe(2);
    expect(sessionStorage.getItem("jh_resume_text")).toBeNull();
    expect(sessionStorage.getItem("jh_resume_owner")).toBe("2");
    expect(container.textContent).toContain("Account B");
    expect(container.textContent).not.toContain("Account A");
  });

  it("does not restore a logged-out Cloudflare account from a stale auth response", async () => {
    let resolveIdentity;
    const pendingIdentity = new Promise((resolve) => { resolveIdentity = resolve; });
    global.fetch = vi.fn(async (url) => {
      const path = String(url);
      if (path.endsWith("/api/auth/config")) return jsonResponse({ mode: "cloudflare" });
      if (path.endsWith("/api/auth/me")) return pendingIdentity;
      return jsonResponse({});
    });

    await act(async () => {
      root.render(<JobHunterSG />);
    });
    await flushEffects();

    await act(async () => {
      window.dispatchEvent(new StorageEvent("storage", {
        key: AUTH_SYNC_KEY,
        oldValue: null,
        newValue: "logout:other-tab",
      }));
    });
    await act(async () => {
      resolveIdentity(jsonResponse({ id: 1, name: "Account A", email: "a@example.com" }));
    });
    await flushEffects();

    expect(container.textContent).not.toContain("Account A");
    expect(container.textContent).not.toContain("Loading...");
  });
});
