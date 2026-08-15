import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import DocumentsTab, { filterDocuments } from "../DocumentsTab.jsx";
import { apiFetch, downloadBlob } from "../../lib/api.js";

vi.mock("../../lib/api.js", () => ({
  apiFetch: vi.fn(),
  downloadBlob: vi.fn(),
}));

const response = (value) => ({ json: vi.fn().mockResolvedValue(value) });

describe("DocumentsTab", () => {
  let container;
  let root;

  beforeEach(() => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    vi.clearAllMocks();
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText: vi.fn().mockResolvedValue(undefined) },
    });
    apiFetch
      .mockResolvedValueOnce(response([{
        id: 7,
        label: "GovTech resume",
        job_title: "Senior AI Engineer",
        job_company: "GovTech",
        updated_at: "2026-08-14T00:00:00Z",
      }]))
      .mockResolvedValueOnce(response([{
        id: 12,
        role: "Platform Engineer",
        company: "Example Bank",
        role_metadata: {
          cover_letter: {
            content: "Dear Hiring Team, I build reliable platforms.",
            updated_at: "2026-08-15T00:00:00Z",
          },
        },
      }]));
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    delete globalThis.IS_REACT_ACT_ENVIRONMENT;
  });

  it("searches, reopens resumes, and copies and downloads cover letters", async () => {
    const onOpenResume = vi.fn();
    await act(async () => {
      root.render(<DocumentsTab onOpenResume={onOpenResume} />);
      await Promise.resolve();
      await Promise.resolve();
    });

    const articles = container.querySelectorAll("article");
    expect(articles).toHaveLength(2);
    expect(articles[0].textContent).toContain("Example Bank");

    const resumeButton = [...container.querySelectorAll("button")]
      .find((button) => button.textContent.includes("Open resume"));
    act(() => resumeButton.click());
    expect(onOpenResume).toHaveBeenCalledWith(7);

    const copyButton = [...container.querySelectorAll("button")]
      .find((button) => button.textContent.includes("Copy"));
    await act(async () => copyButton.click());
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith("Dear Hiring Team, I build reliable platforms.");

    const downloadButton = [...container.querySelectorAll("button")]
      .find((button) => button.textContent.includes("Download"));
    act(() => downloadButton.click());
    expect(downloadBlob).toHaveBeenCalledWith(expect.any(Blob), "Cover_Letter_Example_Bank_Platform_Engineer.txt");

    const search = container.querySelector("input[aria-label='Search documents']");
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set.call(search, "resume");
      search.dispatchEvent(new Event("input", { bubbles: true }));
    });
    expect(container.querySelectorAll("article")).toHaveLength(1);
    expect(container.textContent).toContain("GovTech resume");
  });

  it("matches type, label, company, and role", () => {
    const documents = [{ type: "cover letter", label: "Draft", company: "DBS", role: "AI Engineer" }];
    expect(filterDocuments(documents, "cover")).toEqual(documents);
    expect(filterDocuments(documents, "dbs")).toEqual(documents);
    expect(filterDocuments(documents, "engineer")).toEqual(documents);
    expect(filterDocuments(documents, "unrelated")).toEqual([]);
  });
});
