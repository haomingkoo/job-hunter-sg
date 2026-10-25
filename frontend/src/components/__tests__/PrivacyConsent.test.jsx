import React from "react";
import { act } from "react-dom/test-utils";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import ResumeTab from "../ResumeTab.jsx";
import SiteFooter from "../SiteFooter.jsx";

function responseJson(data) {
  return Promise.resolve({
    ok: true,
    status: 200,
    json: () => Promise.resolve(data),
    text: () => Promise.resolve(JSON.stringify(data)),
    headers: { get: () => "" },
  });
}

function uploadCalls() {
  return global.fetch.mock.calls.filter(([url]) => String(url).includes("/api/resume/upload"));
}

describe("privacy surfaces", () => {
  let container;
  let root;

  beforeEach(() => {
    sessionStorage.clear();
    global.fetch = vi.fn((url) => {
      if (String(url).includes("/api/resume/upload")) {
        return responseJson({ text: "Jane Doe\nEXPERIENCE\n- Built a reporting pipeline.", parse_quality: { warnings: [] } });
      }
      return responseJson([]);
    });
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    vi.restoreAllMocks();
    sessionStorage.clear();
  });

  async function renderAnonymousResumeTab() {
    await act(async () => {
      root.render(<ResumeTab selectedJob={null} user={null} setActiveTab={() => {}} />);
    });
  }

  async function chooseFile() {
    const input = container.querySelector('input[type="file"]');
    Object.defineProperty(input, "files", {
      configurable: true,
      value: [new File(["resume"], "resume.pdf", { type: "application/pdf" })],
    });
    await act(async () => {
      input.dispatchEvent(new Event("change", { bubbles: true }));
      await Promise.resolve();
    });
  }

  it("blocks an anonymous upload until the processing notice is accepted", async () => {
    await renderAnonymousResumeTab();

    await chooseFile();

    expect(uploadCalls()).toHaveLength(0);
    expect(container.textContent).toContain("Please tick the box");
    expect(container.textContent).toContain("SEA-LION");
    expect(container.querySelector('a[href="/api/privacy"]')).toBeTruthy();
  });

  it("sends the consent flag once the visitor ticks the box", async () => {
    await renderAnonymousResumeTab();
    const checkbox = container.querySelector('input[aria-describedby="resume-upload-notice"]');
    await act(async () => {
      checkbox.click();
    });

    await chooseFile();

    expect(uploadCalls()).toHaveLength(1);
    expect(uploadCalls()[0][1].body.get("consent")).toBe("true");
  });

  it("renders privacy, terms and contact links in the footer", async () => {
    await act(async () => {
      root.render(<SiteFooter />);
    });

    const hrefs = [...container.querySelectorAll("footer a")].map((link) => link.getAttribute("href"));
    expect(hrefs).toEqual(["/api/privacy", "/api/terms", "mailto:privacy@kooexperience.com", "https://kooexperience.com/"]);
    expect(container.textContent).toContain("© 2026 Haoming Koo");
  });
});
