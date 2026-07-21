import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// reportCount is module-level state, so each test needs a fresh module
// instance (vi.resetModules + dynamic import) rather than sharing one across
// the whole file -- otherwise the page-load cap test would be affected by
// however many reports earlier tests already sent.
async function freshModule() {
  vi.resetModules();
  return import("../errorReporting.js");
}

// vi.resetModules() only clears the JS module cache -- it does NOT remove
// listeners a previous test's installGlobalErrorReporting() already attached
// to the shared jsdom `window`. Track every addEventListener call so each
// test can clean up exactly what it added, or later tests double-count.
let addedListeners = [];

describe("installGlobalErrorReporting", () => {
  beforeEach(() => {
    global.fetch = vi.fn().mockResolvedValue({ ok: true });
    addedListeners = [];
    const originalAddEventListener = window.addEventListener.bind(window);
    vi.spyOn(window, "addEventListener").mockImplementation((type, listener) => {
      addedListeners.push([type, listener]);
      originalAddEventListener(type, listener);
    });
  });

  afterEach(() => {
    for (const [type, listener] of addedListeners) {
      window.removeEventListener(type, listener);
    }
    vi.restoreAllMocks();
  });

  it("reports an uncaught error event to the backend", async () => {
    const { installGlobalErrorReporting } = await freshModule();
    installGlobalErrorReporting();

    window.dispatchEvent(
      Object.assign(new Event("error"), {
        message: "TypeError: something broke",
        error: { stack: "at foo (bar.js:1:1)" },
      }),
    );

    expect(global.fetch).toHaveBeenCalledTimes(1);
    const [url, options] = global.fetch.mock.calls[0];
    expect(url).toBe("/api/client-error");
    expect(options.method).toBe("POST");
    expect(options.keepalive).toBe(true);
    const body = JSON.parse(options.body);
    expect(body.message).toBe("TypeError: something broke");
    expect(body.stack).toBe("at foo (bar.js:1:1)");
  });

  it("reports an unhandled promise rejection to the backend", async () => {
    const { installGlobalErrorReporting } = await freshModule();
    installGlobalErrorReporting();

    window.dispatchEvent(
      Object.assign(new Event("unhandledrejection"), {
        reason: { message: "Failed to fetch", stack: "at reader.read" },
      }),
    );

    expect(global.fetch).toHaveBeenCalledTimes(1);
    const body = JSON.parse(global.fetch.mock.calls[0][1].body);
    expect(body.message).toBe("Failed to fetch");
  });

  it("stops reporting after the per-page-load cap to avoid flooding on an error loop", async () => {
    const { installGlobalErrorReporting } = await freshModule();
    installGlobalErrorReporting();

    for (let i = 0; i < 15; i += 1) {
      window.dispatchEvent(Object.assign(new Event("error"), { message: `error ${i}` }));
    }

    expect(global.fetch).toHaveBeenCalledTimes(10);
  });
});
