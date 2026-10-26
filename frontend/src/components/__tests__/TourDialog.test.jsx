import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it } from "vitest";

import TourDialog, { wantsTour } from "../TourDialog.jsx";

describe("TourDialog", () => {
  it("opens only for ?tour=1", () => {
    expect(wantsTour("?tour=1")).toBe(true);
    expect(wantsTour("?tour=0")).toBe(false);
    expect(wantsTour("")).toBe(false);
  });

  it("renders a keyboard trigger and a player that never autoplays", () => {
    const container = document.createElement("div");
    const root = createRoot(container);
    act(() => root.render(<TourDialog />));
    const trigger = container.querySelector("button");
    expect(trigger.textContent).toBe("▶ 30-second tour");
    const video = container.querySelector("video");
    expect(video.autoplay).toBe(false);
    expect(video.getAttribute("preload")).toBe("none");
    expect([...video.querySelectorAll("source")].map((s) => s.type)).toEqual(["video/webm", "video/mp4"]);
    expect(container.textContent).toContain("Music: Sascha Ende, ende.app (CC BY 4.0)");
    act(() => root.unmount());
  });
});
