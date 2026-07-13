import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import AccountTab from "../AccountTab.jsx";
import TrackerTab from "../TrackerTab.jsx";
import { apiFetch, clearResumeDraftStorage } from "../../lib/api.js";

vi.mock("../../lib/api.js", () => ({
  API_BASE: "http://localhost:8000",
  apiFetch: vi.fn(),
  clearResumeDraftStorage: vi.fn(),
}));

describe("single account access", () => {
  let container;
  let root;

  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    sessionStorage.clear();
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  const setInput = (input, value) => {
    act(() => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set.call(input, value);
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });
  };

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  it("lets every signed-in account add applications and export CSV", async () => {
    await act(async () => {
      root.render(
        <TrackerTab
          jobs={[{
            id: 1,
            company: "Example Co",
            role: "Engineer",
            date_applied: "2026-07-13",
            source: "MyCareersFuture",
            status: "applied",
          }]}
          refreshJobs={vi.fn()}
          setActiveTab={vi.fn()}
        />,
      );
    });

    const buttons = [...container.querySelectorAll("button")];
    expect(buttons.find((button) => button.textContent.includes("Export CSV"))).toBeTruthy();
    expect(buttons.find((button) => button.textContent.trim() === "Add")?.disabled).toBe(false);
    expect(container.textContent).not.toContain("Upgrade");
  });

  it("shows usage and privacy without exposing account tiers or plans", async () => {
    apiFetch.mockImplementation((url) => Promise.resolve({
      json: () => Promise.resolve(url === "/api/usage"
        ? {
            tier: "free",
            searches_today: 2,
            searches_limit: 100,
            ai_today: 1,
            ai_limit: 20,
            tracked_jobs: 3,
            tracked_limit: 50,
          }
        : { enabled: false }),
    }));

    await act(async () => {
      root.render(
        <AccountTab
          user={{ name: "Asha", email: "asha@example.com", tier: "free" }}
          onLogout={vi.fn()}
          setActiveTab={vi.fn()}
        />,
      );
    });

    expect(container.textContent).toContain("AI requests today");
    expect(container.textContent).not.toContain("Current tier");
    expect(container.textContent).not.toContain("Plan Comparison");
    expect(container.textContent).not.toContain("Upgrade");

    const privacyButton = [...container.querySelectorAll("button")]
      .find((button) => button.textContent.trim() === "Privacy");
    await act(async () => privacyButton.click());

    expect(container.textContent).toContain("Legal & Privacy");
  });

  it("changes passwords only in password mode and stores the replacement token", async () => {
    apiFetch.mockImplementation((url) => Promise.resolve({
      json: () => Promise.resolve(url === "/api/auth/change-password"
        ? { message: "Password updated.", token: "new-token" }
        : {}),
    }));

    await act(async () => {
      root.render(
        <AccountTab
          user={{ name: "Asha", email: "asha@example.com" }}
          authMode="password"
          onLogout={vi.fn()}
        />,
      );
    });

    const updateButton = [...container.querySelectorAll("button")]
      .find((button) => button.textContent.includes("Update Password"));
    const form = updateButton.closest("form");
    const inputs = form.querySelectorAll('input[type="password"]');
    setInput(inputs[0], "old-password");
    setInput(inputs[1], "new-password");
    setInput(inputs[2], "new-password");
    await act(async () => {
      form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    });

    expect(apiFetch).toHaveBeenCalledWith("/api/auth/change-password", {
      method: "POST",
      body: JSON.stringify({ current_password: "old-password", new_password: "new-password" }),
    });
    expect(localStorage.getItem("token")).toBe("new-token");
    expect(container.textContent).toContain("Password updated.");
  });

  it("requires exact email and current password before deleting local account data", async () => {
    const onAccountDeleted = vi.fn();
    apiFetch.mockImplementation((url) => Promise.resolve({
      json: () => Promise.resolve(url === "/api/account"
        ? { message: "Account deleted." }
        : {}),
    }));
    localStorage.setItem("token", "old-token");

    await act(async () => {
      root.render(
        <AccountTab
          user={{ name: "Asha", email: "asha@example.com" }}
          authMode="password"
          onAccountDeleted={onAccountDeleted}
          onLogout={vi.fn()}
        />,
      );
    });

    const deleteButton = [...container.querySelectorAll("button")]
      .find((button) => button.textContent.includes("Delete My Account"));
    const form = deleteButton.closest("form");
    const email = form.querySelector('input[type="email"]');
    const password = form.querySelector('input[type="password"]');
    setInput(email, "wrong@example.com");
    setInput(password, "current-password");
    expect(deleteButton.disabled).toBe(true);
    setInput(email, "asha@example.com");
    expect(deleteButton.disabled).toBe(false);
    await act(async () => {
      form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    });

    expect(apiFetch).toHaveBeenCalledWith("/api/account", {
      method: "DELETE",
      body: JSON.stringify({ confirm_email: "asha@example.com", current_password: "current-password" }),
    });
    expect(localStorage.getItem("token")).toBeNull();
    expect(clearResumeDraftStorage).toHaveBeenCalledOnce();
    expect(onAccountDeleted).toHaveBeenCalledWith(undefined);
  });

  it("does not expose password maintenance in Cloudflare mode", async () => {
    apiFetch.mockResolvedValue({ json: () => Promise.resolve({}) });

    await act(async () => {
      root.render(
        <AccountTab
          user={{ name: "Asha", email: "asha@example.com" }}
          authMode="cloudflare"
          onLogout={vi.fn()}
        />,
      );
    });

    expect(container.textContent).not.toContain("Change Password");
    const deleteButton = [...container.querySelectorAll("button")]
      .find((button) => button.textContent.includes("Delete My Account"));
    expect(deleteButton.closest("form").querySelector('input[type="password"]')).toBeNull();
  });
});
