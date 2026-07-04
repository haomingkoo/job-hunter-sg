import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import JobHunterSG from "../App.jsx";

describe("JobHunterSG app shell", () => {
  let container;
  let root;

  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
    vi.restoreAllMocks();
    global.IntersectionObserver = class {
      observe() {}
      unobserve() {}
      disconnect() {}
    };
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    delete global.IntersectionObserver;
    vi.restoreAllMocks();
  });

  it("mounts the public app shell without auth", async () => {
    await act(async () => {
      root.render(<JobHunterSG />);
    });

    expect(container.textContent).toContain("Job Hunter SG");
    expect(container.textContent).toContain("Sign In");
  });
});
