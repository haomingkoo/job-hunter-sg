import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import AuthModal from "../AuthModal.jsx";

const response = (data) => ({
  ok: true,
  json: () => Promise.resolve(data),
  text: () => Promise.resolve(JSON.stringify(data)),
});

const errorResponse = (status, detail) => ({
  ok: false,
  status,
  text: () => Promise.resolve(JSON.stringify({ detail })),
});

describe("account authentication lifecycle", () => {
  let container;
  let root;

  beforeEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    vi.restoreAllMocks();
  });

  const setInput = (placeholder, value) => {
    const input = [...container.querySelectorAll("input")]
      .find((candidate) => candidate.placeholder === placeholder);
    act(() => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set.call(input, value);
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });
  };

  it("asks a password signup to verify email instead of expecting a JWT", async () => {
    const onAuth = vi.fn();
    global.fetch = vi.fn().mockResolvedValue(response({ message: "Verification email sent." }));

    await act(async () => {
      root.render(<AuthModal onAuth={onAuth} onClose={vi.fn()} />);
    });
    const signupButton = [...container.querySelectorAll("button")]
      .find((button) => button.textContent.includes("Don't have an account"));
    act(() => signupButton.click());
    setInput("Full Name", "Asha Tan");
    setInput("Email", "asha@example.com");
    setInput("Password", "correct-horse");
    act(() => container.querySelector('input[type="checkbox"]').click());

    await act(async () => {
      container.querySelector("form").dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    });

    expect(global.fetch).toHaveBeenCalledWith("/api/auth/signup", expect.objectContaining({ method: "POST" }));
    expect(container.textContent).toContain("Verification email sent.");
    expect(container.textContent).toContain("Check your email");
    expect(localStorage.getItem("token")).toBeNull();
    expect(onAuth).not.toHaveBeenCalled();

    const resendButton = [...container.querySelectorAll("button")]
      .find((button) => button.textContent.includes("Resend Verification Email"));
    await act(async () => resendButton.click());
    expect(global.fetch).toHaveBeenLastCalledWith(
      "/api/auth/resend-verification",
      expect.objectContaining({ body: JSON.stringify({ email: "asha@example.com" }) }),
    );
    expect(container.textContent).toContain("If your account is awaiting verification");
  });

  it("offers legacy unverified accounts a resend link after sign in", async () => {
    global.fetch = vi.fn()
      .mockResolvedValueOnce(errorResponse(403, "Verify your email before signing in"))
      .mockResolvedValueOnce(response({ message: "If the account exists, an email was sent." }));

    await act(async () => {
      root.render(<AuthModal onAuth={vi.fn()} onClose={vi.fn()} />);
    });
    setInput("Email", "legacy@example.com");
    setInput("Password", "correct-horse");
    await act(async () => {
      container.querySelector("form").dispatchEvent(
        new Event("submit", { bubbles: true, cancelable: true }),
      );
    });

    expect(container.textContent).toContain("Check your email");
    expect(container.textContent).toContain("Verify your email before signing in");
    const resendButton = [...container.querySelectorAll("button")]
      .find((button) => button.textContent.includes("Resend Verification Email"));
    await act(async () => resendButton.click());

    expect(global.fetch).toHaveBeenLastCalledWith(
      "/api/auth/resend-verification",
      expect.objectContaining({ body: JSON.stringify({ email: "legacy@example.com" }) }),
    );
  });

  it("verifies an email-link token and signs the account in", async () => {
    const user = { id: 7, name: "Asha", email: "asha@example.com" };
    const onAuth = vi.fn();
    const onVerifyComplete = vi.fn();
    global.fetch = vi.fn().mockResolvedValue(response({ token: "verified-token", user }));

    await act(async () => {
      root.render(
        <AuthModal
          initialVerifyToken="email-token"
          onAuth={onAuth}
          onVerifyComplete={onVerifyComplete}
        />,
      );
    });
    setInput("Full Name", "Asha Tan");
    setInput("Choose password", "correct-horse");
    setInput("Confirm password", "correct-horse");
    act(() => container.querySelector('input[type="checkbox"]').click());
    await act(async () => {
      container.querySelector("form").dispatchEvent(
        new Event("submit", { bubbles: true, cancelable: true }),
      );
    });

    expect(global.fetch).toHaveBeenCalledWith(
      "/api/auth/verify-email",
      expect.objectContaining({
        body: JSON.stringify({
          token: "email-token",
          password: "correct-horse", // pragma: allowlist secret
          name: "Asha Tan",
          accepted_terms: true,
        }),
      }),
    );
    expect(localStorage.getItem("token")).toBe("verified-token");
    expect(onVerifyComplete).toHaveBeenCalledOnce();
    expect(onAuth).toHaveBeenCalledWith(user, "verified-token");
  });

  it("does not activate an account when verification passwords differ", async () => {
    global.fetch = vi.fn();
    await act(async () => {
      root.render(<AuthModal initialVerifyToken="email-token" onAuth={vi.fn()} />);
    });
    setInput("Full Name", "Asha Tan");
    setInput("Choose password", "correct-horse");
    setInput("Confirm password", "different-horse");
    act(() => container.querySelector('input[type="checkbox"]').click());
    await act(async () => {
      container.querySelector("form").dispatchEvent(
        new Event("submit", { bubbles: true, cancelable: true }),
      );
    });

    expect(container.textContent).toContain("Passwords do not match.");
    expect(global.fetch).not.toHaveBeenCalled();
  });

  it("ignores a login response after another tab replaces the modal identity", async () => {
    let resolveLogin;
    const pendingLogin = new Promise((resolve) => { resolveLogin = resolve; });
    const onAuth = vi.fn();
    global.fetch = vi.fn(() => pendingLogin);

    await act(async () => {
      root.render(<AuthModal onAuth={onAuth} onClose={vi.fn()} />);
    });
    setInput("Email", "a@example.com");
    setInput("Password", "correct-horse");
    act(() => {
      container.querySelector("form").dispatchEvent(
        new Event("submit", { bubbles: true, cancelable: true }),
      );
    });

    localStorage.setItem("token", "token-b");
    await act(async () => {
      root.render(<div>Account B</div>);
    });
    await act(async () => {
      resolveLogin(response({
        token: "token-a",
        user: { id: 1, name: "Account A", email: "a@example.com" },
      }));
    });

    expect(localStorage.getItem("token")).toBe("token-b");
    expect(onAuth).not.toHaveBeenCalled();
    expect(container.textContent).toBe("Account B");
  });

  it("navigates to Cloudflare before attempting registration", async () => {
    global.fetch = vi.fn();

    await act(async () => {
      root.render(
        <AuthModal
          authConfig={{
            mode: "cloudflare",
            cloudflare_login_url: "https://access.example.com/login",
          }}
          onAuth={vi.fn()}
        />,
      );
    });

    expect(container.querySelector("form")).toBeNull();
    expect(container.querySelector('a[href="https://access.example.com/login"]')?.textContent)
      .toContain("Continue with Cloudflare");
    expect(global.fetch).not.toHaveBeenCalled();
  });

  it("uses explicit Cloudflare account consent without a password after identity verification", async () => {
    const user = { id: 8, name: "Asha", email: "asha@example.com" };
    const onAuth = vi.fn();
    global.fetch = vi.fn().mockResolvedValue(response(user));

    await act(async () => {
      root.render(
        <AuthModal
          authConfig={{
            mode: "cloudflare",
            cloudflare_login_url: "https://access.example.com/login",
          }}
          cloudflareIdentityReady
          onAuth={onAuth}
        />,
      );
    });

    expect(container.querySelector('input[type="password"]')).toBeNull();
    expect(container.querySelector('a[href="https://access.example.com/login"]')).toBeNull();
    setInput("Full Name", "Asha Tan");
    act(() => container.querySelector('input[type="checkbox"]').click());
    await act(async () => {
      container.querySelector("form").dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    });

    expect(global.fetch).toHaveBeenCalledWith(
      "/api/auth/cloudflare/register",
      expect.objectContaining({
        credentials: "include",
        body: JSON.stringify({ name: "Asha Tan", accepted_terms: true }),
      }),
    );
    expect(onAuth).toHaveBeenCalledWith(user, null);
  });
});
