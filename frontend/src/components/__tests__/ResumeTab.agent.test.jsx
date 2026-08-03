import React from "react";
import { act } from "react-dom/test-utils";
import { createRoot } from "react-dom/client";
import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";

import ResumeTab, { buildAgentJobContext, buildAgentScoreContext } from "../ResumeTab.jsx";

function responseJson(data, ok = true) {
  return Promise.resolve({
    ok,
    status: ok ? 200 : 500,
    json: () => Promise.resolve(data),
    text: () => Promise.resolve(typeof data === "string" ? data : JSON.stringify(data)),
    headers: { get: () => "" },
  });
}

function setField(field, value) {
  const setter = Object.getOwnPropertyDescriptor(field.constructor.prototype, "value")?.set;
  setter.call(field, value);
  field.dispatchEvent(new Event("input", { bubbles: true }));
}

describe("ResumeTab Agent v2", () => {
  let container;
  let root;

  beforeEach(() => {
    sessionStorage.clear();
    sessionStorage.setItem(
      "jh_resume_text",
      "Jane Doe\njane@example.com\n\nEXPERIENCE\n- Built data pipeline processing 10M events daily",
    );
    sessionStorage.setItem("jh_wizard_step", "3");
    global.fetch = vi.fn((url, options = {}) => {
      const target = String(url);
      if (target.includes("/api/resume/ingest-text")) {
        const { resume_text: rawText } = JSON.parse(options.body);
        return responseJson({ raw_text: rawText, blocks: [], sections: [], warnings: [] });
      }
      if (target.includes("/api/resume/score")) {
        return responseJson({ overall_score: 78, checks: {} });
      }
      if (target.includes("/api/ai/status")) {
        return responseJson({ healthy: true });
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

  it("keeps a selected-job snapshot for reviews after a listing disappears", () => {
    expect(buildAgentJobContext({
      id: 347820,
      title: "Finance Process Intelligence Manager",
      company: "Micron",
      description: "Lead process intelligence and transformation.",
      jobTermsPreview: ["process intelligence"],
      location: "Singapore",
      source: "MyCareersFuture",
    })).toEqual({
      title: "Finance Process Intelligence Manager",
      company: "Micron",
      description: "Lead process intelligence and transformation.",
      terms: ["process intelligence"],
      location: "Singapore",
      source: "MyCareersFuture",
    });
  });

  it("reuses the compact rule-based score without sending every bullet diagnostic", () => {
    expect(buildAgentScoreContext({
      overall_score: 77,
      quality_score: 77,
      dimensions: { impact: { score: 21, max: 40 }, presentation: { score: 30, max: 30 } },
      keyword_match: { matched: ["Python"], missing: ["SQL", "AWS"], score_percent: 33 },
    })).toEqual({
      overall_score: 77,
      quality_score: 77,
      dimensions: { impact: { score: 21, max: 40 }, presentation: { score: 30, max: 30 } },
      keyword_match: { matched: 1, missing: 2, score_percent: 33 },
    });
  });

  it("searches again with the exact refined resume version after export", async () => {
    sessionStorage.setItem("jh_wizard_step", "4");
    const onSearchMatchingJobs = vi.fn();
    const onInitialResumeVersionLoaded = vi.fn();
    global.URL.createObjectURL = vi.fn(() => "blob:resume");
    global.URL.revokeObjectURL = vi.fn();
    global.fetch = vi.fn((url, options = {}) => {
      const target = String(url);
      if (target.endsWith("/api/resume/versions/19")) {
        return responseJson({
          id: 19,
          label: "Recruitment team edits",
          resume_text: "Jane Doe\njane@example.com\n\nEXPERIENCE\n- Led semiconductor transformation across four regions",
          resume_structured: null,
        });
      }
      if (target.endsWith("/api/resume/versions")) {
        return responseJson([{ id: 19, label: "Recruitment team edits", is_master: false }]);
      }
      if (target.includes("/api/resume/download")) {
        return Promise.resolve({
          ok: true,
          status: 200,
          headers: { get: () => "attachment; filename=resume.docx" },
          blob: () => Promise.resolve(new Blob(["resume"])),
        });
      }
      if (target.includes("/api/resume/ingest-text")) {
        const { resume_text: rawText } = JSON.parse(options.body);
        return responseJson({ raw_text: rawText, blocks: [], sections: [], warnings: [] });
      }
      if (target.includes("/api/resume/score")) return responseJson({ overall_score: 78, checks: {} });
      if (target.includes("/api/ai/status")) return responseJson({ healthy: true });
      return responseJson([]);
    });

    await act(async () => {
      root.render(
        <ResumeTab
          selectedJob={null}
          user={{ id: 1 }}
          setActiveTab={() => {}}
          initialResumeVersionId={19}
          onInitialResumeVersionLoaded={onInitialResumeVersionLoaded}
          onSearchMatchingJobs={onSearchMatchingJobs}
        />,
      );
      await Promise.resolve();
      await Promise.resolve();
    });

    const downloadButton = [...container.querySelectorAll("button")]
      .find((button) => button.textContent.includes("Download DOCX"));
    await act(async () => {
      downloadButton.click();
      await Promise.resolve();
      await Promise.resolve();
    });
    const searchButton = [...container.querySelectorAll("button")]
      .find((button) => button.textContent.includes("Search Matching Jobs"));
    await act(async () => searchButton.click());

    expect(onInitialResumeVersionLoaded).toHaveBeenCalledWith(19);
    expect(onSearchMatchingJobs).toHaveBeenCalledWith(19);
    expect(global.fetch.mock.calls.filter(([url, request]) => (
      String(url).endsWith("/api/resume/versions") && request?.method === "POST"
    ))).toHaveLength(0);
  });

  it("v2 toggle renders and does not affect the classic editor", async () => {
    await act(async () => {
      root.render(<ResumeTab selectedJob={null} user={null} setActiveTab={() => {}} />);
    });

    const classicButton = Array.from(container.querySelectorAll("button"))
      .find((button) => button.textContent.includes("Classic"));
    const agentButton = Array.from(container.querySelectorAll("button"))
      .find((button) => button.textContent.includes("Agent review"));
    const classicEditor = container.querySelector("[data-testid='classic-resume-editor']");

    expect(classicButton).toBeTruthy();
    expect(agentButton).toBeTruthy();
    expect(classicEditor.className).not.toContain("hidden");

    await act(async () => {
      agentButton.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    expect(container.querySelector("[data-testid='resume-agent-v2-panel']")).toBeTruthy();
    expect(classicEditor.className).toContain("hidden");
    expect(container.textContent).toContain("Add LinkedIn or profile context");
    expect(container.textContent).toContain("This usually takes 30 seconds to 2 minutes.");

    await act(async () => {
      classicButton.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    expect(container.querySelector("[data-testid='resume-agent-v2-panel']")).toBeFalsy();
    expect(classicEditor.className).not.toContain("hidden");
  });

  it("scores a first upload once", async () => {
    sessionStorage.clear();
    global.fetch = vi.fn((url, options = {}) => {
      const target = String(url);
      if (target.includes("/api/resume/ingest-text")) {
        const { resume_text: rawText } = JSON.parse(options.body);
        return responseJson({ raw_text: rawText, blocks: [], sections: [], warnings: [] });
      }
      if (target.includes("/api/resume/upload")) {
        return responseJson({
          text: "Jane Doe\nPROFESSIONAL EXPERIENCE\n• Built a reporting pipeline used by 50 finance users every month.",
          name: "Jane Doe",
          parse_quality: { warnings: [] },
        });
      }
      if (target.includes("/api/resume/score")) {
        return responseJson({ overall_score: 78, checks: {} });
      }
      if (target.includes("/api/ai/status")) {
        return responseJson({ healthy: true });
      }
      return responseJson([]);
    });

    await act(async () => {
      root.render(<ResumeTab selectedJob={null} user={null} setActiveTab={() => {}} />);
    });
    const input = container.querySelector('input[type="file"]');
    Object.defineProperty(input, "files", {
      value: [new File(["resume"], "resume.pdf", { type: "application/pdf" })],
    });

    await act(async () => {
      input.dispatchEvent(new Event("change", { bubbles: true }));
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(global.fetch.mock.calls.filter(([url]) => String(url).includes("/api/resume/score"))).toHaveLength(1);
  });

  it("confirms a candidate heading through the canonical document endpoint", async () => {
    const rawText = "Jane Doe\n\nEXPERIENCE\n- Built a reporting platform.\n\nSELECTED TALKS\nSpoke at PyCon Singapore.";
    sessionStorage.setItem("jh_resume_text", rawText);
    const candidate = {
      schema_version: 3,
      document_id: "d_resume",
      revision: "r_before",
      raw_text: rawText,
      warnings: [],
      decisions: [],
      heading_candidates: [{ block_id: "b_talks", label: "SELECTED TALKS", suggested_key: null }],
      sections: [{ id: "s_experience", key: "experience", label: "EXPERIENCE" }],
      blocks: [
        { id: "b_name", order: 0, kind: "paragraph", text: "Jane Doe", source_text: "Jane Doe", raw_span: [0, 8], section_id: null, section_key: "" },
        { id: "b_experience", order: 1, kind: "section_heading", text: "EXPERIENCE", source_text: "EXPERIENCE", raw_span: [10, 20], section_id: "s_experience", section_key: "experience" },
        { id: "b_bullet", order: 2, kind: "bullet", text: "Built a reporting platform.", source_text: "Built a reporting platform.", raw_span: [23, 50], section_id: "s_experience", section_key: "experience" },
        { id: "b_talks", order: 3, kind: "candidate_heading", classification: "candidate_heading", text: "SELECTED TALKS", source_text: "SELECTED TALKS", raw_span: [52, 66], section_id: "s_experience", section_key: "experience" },
        { id: "b_talk", order: 4, kind: "paragraph", text: "Spoke at PyCon Singapore.", source_text: "Spoke at PyCon Singapore.", raw_span: [67, rawText.length], section_id: "s_experience", section_key: "experience" },
      ],
    };
    const confirmed = {
      ...candidate,
      revision: "r_after",
      decisions: [{ type: "confirm_heading", block_id: "b_talks", section_key: null }],
      heading_candidates: [],
      sections: [
        ...candidate.sections,
        { id: "s_talks", key: null, label: "SELECTED TALKS" },
      ],
      blocks: candidate.blocks.map((block) => block.id === "b_talks"
        ? { ...block, kind: "section_heading", classification: "custom_section", section_id: "s_talks", section_key: "" }
        : block),
    };
    global.fetch = vi.fn((url) => {
      const target = String(url);
      if (target.includes("/api/resume/ingest-text")) return responseJson(candidate);
      if (target.includes("/api/resume/confirm-heading")) return responseJson(confirmed);
      if (target.includes("/api/resume/score")) return responseJson({ overall_score: 78, checks: {} });
      if (target.includes("/api/ai/status")) return responseJson({ healthy: true });
      return responseJson([]);
    });

    await act(async () => {
      root.render(<ResumeTab selectedJob={null} user={null} setActiveTab={() => {}} />);
      await Promise.resolve();
      await Promise.resolve();
    });
    const confirmButton = Array.from(container.querySelectorAll("button"))
      .find((button) => button.textContent.includes("Confirm as section"));
    expect(confirmButton).toBeTruthy();

    await act(async () => {
      confirmButton.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      await Promise.resolve();
      await Promise.resolve();
    });

    const request = global.fetch.mock.calls.find(([url]) => String(url).includes("/api/resume/confirm-heading"));
    expect(JSON.parse(request[1].body)).toMatchObject({
      block_id: "b_talks",
      expected_revision: "r_before",
      section_key: null,
    });
    expect(container.textContent).not.toContain("This may be a section heading");
    expect(container.textContent).not.toContain("Confirm as section");
    expect(container.textContent).toContain("SELECTED TALKS");
  });

  it("starts a detached review and reconnects through session state", async () => {
    global.fetch = vi.fn((url, options = {}) => {
      const target = String(url);
      if (target.includes("/api/resume/ingest-text")) {
        const { resume_text: rawText } = JSON.parse(options.body);
        return responseJson({ raw_text: rawText, blocks: [], sections: [], warnings: [] });
      }
      if (target.includes("/api/resume/agent/start")) {
        return responseJson({ session_id: "detached-1", status: "queued" });
      }
      if (target.includes("/api/resume/agent/detached-1/state")) {
        return responseJson({
          session_id: "detached-1",
          status: "completed",
          progress: "Review complete",
          response: "Evidence-bound review ready.",
          todos: [],
          persona_findings: [{
            persona: "ats",
            category: "role terminology",
            evidence_ids: ["b_pipeline"],
            target_job_fields: ["description", "terms"],
            message: "The resume shows relevant delivery experience.",
            rationale: "The cited bullet supports the role requirement.",
            suggested_action: "Use the supported target term once.",
          }],
          tool_spans: [{
            name: "score_resume",
            status: "success",
            duration_ms: 24,
            input_keys: ["resume_text"],
            result: { overall_score: 78 },
          }],
          pending_diffs: [],
          document: {
            raw_text: "Jane Doe\njane@example.com\n\nEXPERIENCE\n- Built data pipeline processing 10M events daily",
            sections: [],
            warnings: [],
            blocks: [{
              id: "b_pipeline",
              kind: "bullet",
              text: "Built data pipeline processing 10M events daily",
              source_text: "Built data pipeline processing 10M events daily",
              raw_span: [39, 87],
              order: 0,
              section_key: "experience",
            }],
          },
        });
      }
      if (target.includes("/api/resume/score")) return responseJson({ overall_score: 78, checks: {} });
      if (target.includes("/api/ai/status")) return responseJson({ healthy: true });
      return responseJson([]);
    });
    await act(async () => {
      root.render(<ResumeTab selectedJob={null} user={{ id: 1 }} setActiveTab={() => {}} />);
    });
    const agentButton = Array.from(container.querySelectorAll("button"))
      .find((button) => button.textContent.includes("Agent review"));
    await act(async () => agentButton.dispatchEvent(new MouseEvent("click", { bubbles: true })));
    const prompt = container.querySelector('textarea[placeholder^="Ask for ATS gaps"]');
    await act(async () => setField(prompt, "Review this resume"));
    const send = container.querySelector('button[title="Send to Agent Review"]');

    await act(async () => {
      send.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(global.fetch.mock.calls.some(([url]) => String(url).includes("/api/resume/agent/start"))).toBe(true);
    expect(sessionStorage.getItem("jh_resume_agent_session")).toBe("detached-1");
    expect(container.textContent).toContain("Evidence-bound review ready.");
    expect(container.textContent).toContain("Resume evidence:");
    expect(container.textContent).toContain("Built data pipeline processing 10M events daily");
    expect(container.textContent).toContain("Target-job evidence: description, terms");
    expect(container.textContent).toContain("Reasoning: The cited bullet supports the role requirement.");
    expect(container.textContent).toContain("score_resume");
    expect(container.textContent).toContain("success · 24 ms");
    expect(container.textContent).toContain("overall_score=78");
  });

});
