import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import StoriesTab from "../StoriesTab.jsx";


describe("StoriesTab errors", () => {
  let container;
  let root;

  beforeEach(() => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    vi.unstubAllGlobals();
  });

  it("shows a retryable error when the story bank cannot be loaded", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));

    await act(async () => {
      root.render(<StoriesTab />);
    });

    expect(container.querySelector('[role="alert"]')?.textContent).toContain(
      "Could not reach the backend",
    );
    expect(container.textContent).toContain("Try again");
  });
});
