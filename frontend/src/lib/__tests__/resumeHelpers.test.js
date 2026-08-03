import { describe, expect, it } from "vitest";

import {
  extractResumeHeaderMeta,
  getDisplaySubheadingText,
  getRewriteCacheKey,
  groupEducationSections,
  isCanonicalResumeDocument,
  isRewriteResultCurrent,
  moveSectionInText,
  parseSubheadingParts,
  projectResumeDocument,
  stripResumeMarkdown,
} from "../resumeHelpers.jsx";

const RAW_TEXT = [
  "Jane Doe",
  "jane@example.com",
  "EXPERIENCE",
  "Engineering Manager | Example | 2022 - Present",
  "- Built a reporting platform.",
  "SELECTED TALKS",
].join("\n");

function span(value) {
  const start = RAW_TEXT.indexOf(value);
  return [start, start + value.length];
}

const DOCUMENT = {
  schema_version: 3,
  revision: "r_test",
  raw_text: RAW_TEXT,
  warnings: [],
  sections: [{ id: "s_heading", key: "experience", label: "EXPERIENCE" }],
  heading_candidates: [{ block_id: "b_candidate", label: "SELECTED TALKS", suggested_key: null }],
  blocks: [
    { id: "b_name", order: 0, kind: "paragraph", text: "Jane Doe", source_text: "Jane Doe", raw_span: span("Jane Doe"), section_id: null, section_key: "" },
    { id: "b_contact", order: 1, kind: "paragraph", text: "jane@example.com", source_text: "jane@example.com", raw_span: span("jane@example.com"), section_id: null, section_key: "" },
    { id: "b_heading", order: 2, kind: "section_heading", text: "EXPERIENCE", source_text: "EXPERIENCE", raw_span: span("EXPERIENCE"), section_id: "s_heading", section_key: "experience" },
    { id: "b_entry", order: 3, kind: "entry_heading", text: "Engineering Manager | Example | 2022 - Present", source_text: "Engineering Manager | Example | 2022 - Present", raw_span: span("Engineering Manager | Example | 2022 - Present"), section_id: "s_heading", section_key: "experience" },
    { id: "b_bullet", order: 4, kind: "bullet", text: "Built a reporting platform.", source_text: "Built a reporting platform.", raw_span: span("Built a reporting platform."), section_id: "s_heading", section_key: "experience" },
    { id: "b_candidate", order: 5, kind: "candidate_heading", text: "SELECTED TALKS", source_text: "SELECTED TALKS", raw_span: span("SELECTED TALKS"), section_id: "s_heading", section_key: "experience" },
  ],
};

describe("canonical resume projection", () => {
  it("maps canonical kinds without inferring sections from raw text", () => {
    expect(isCanonicalResumeDocument(DOCUMENT)).toBe(true);
    const projected = projectResumeDocument(DOCUMENT, ["reporting"]);

    expect(projected.map((item) => [item.id, item.type, item.sectionKey])).toEqual([
      ["b_name", "paragraph", ""],
      ["b_contact", "paragraph", ""],
      ["b_heading", "heading", "experience"],
      ["b_entry", "subheading", "experience"],
      ["b_bullet", "bullet", "experience"],
      ["b_candidate", "candidate_heading", "experience"],
    ]);
    expect(projected.find((item) => item.id === "b_bullet").keywordMatches).toEqual(["reporting"]);
  });

  it("derives the visible header from canonical source spans", () => {
    expect(extractResumeHeaderMeta(RAW_TEXT, DOCUMENT)).toEqual({
      lines: ["Jane Doe", "jane@example.com"],
      lineIndices: [0, 1],
    });
    expect(extractResumeHeaderMeta(RAW_TEXT, null)).toEqual({ lines: [], lineIndices: [] });
  });

  it("keeps source IDs stable when template display order changes", () => {
    const projected = projectResumeDocument(DOCUMENT, [], ["experience"]);
    expect(projected.find((item) => item.text === "Built a reporting platform.").id).toBe("b_bullet");
  });
});

describe("display-only resume helpers", () => {
  it("strips markdown without changing content", () => {
    expect(stripResumeMarkdown(" **bold** and *italic* ")).toBe("bold and italic");
    expect(stripResumeMarkdown(null)).toBe("");
  });

  it("recognises structured role headings but not ordinary bullets", () => {
    expect(parseSubheadingParts("Dyson | Senior Engineer | Jan 2020 – Present", "experience")).not.toBeNull();
    expect(parseSubheadingParts("Led a team of 5 engineers to deliver on time", "experience")).toBeNull();
    expect(parseSubheadingParts("PMP (in progress, expected 2025)", "certifications")).toBeNull();
  });

  it("keeps standalone date ranges on one visual line", () => {
    expect(getDisplaySubheadingText("2022 – 2025", "experience", "dated")).toBe("2022\u00A0–\u00A02025");
  });

  it("groups canonical education rows for display", () => {
    const grouped = groupEducationSections([
      { id: "heading", type: "heading", sectionKey: "education", text: "EDUCATION", lineIndex: 0, lineIndices: [0] },
      { id: "degree", type: "subheading", variant: "education_main", sectionKey: "education", text: "BSc | NUS", left: "BSc", right: "NUS", lineIndex: 1, lineIndices: [1] },
      { id: "detail", type: "paragraph", sectionKey: "education", text: "Distinction", lineIndex: 2, lineIndices: [2] },
    ]);
    expect(grouped.some((item) => item.type === "education_entry")).toBe(true);
  });
});

describe("resume mutation helpers", () => {
  const inputs = {
    bullet: "Led a finance transformation.",
    jobTitle: "Finance Manager",
    jobDescription: "Own process improvement.",
    usedVerbs: "built, managed",
    rewriteFocus: "specifics",
    focusedFeedback: "Add supported scale.",
  };

  it("invalidates a cached rewrite when any model input changes", () => {
    const result = {
      source_bullet: inputs.bullet,
      job_title: inputs.jobTitle,
      job_description: inputs.jobDescription,
    };
    expect(getRewriteCacheKey(inputs)).toBe(getRewriteCacheKey({ ...inputs }));
    expect(isRewriteResultCurrent(result, inputs)).toBe(true);
    expect(isRewriteResultCurrent(result, { ...inputs, bullet: "Changed bullet." })).toBe(false);
  });

  it("does not duplicate sections when a move has no destination", () => {
    const text = "CORE SKILLS\nPython\nPROFESSIONAL EXPERIENCE\nFinance Manager";
    const sections = [
      { id: "skills", type: "heading", sectionKey: "skills", lineIndex: 0, lineIndices: [0] },
      { id: "python", type: "paragraph", sectionKey: "skills", lineIndex: 1, lineIndices: [1] },
      { id: "experience", type: "heading", sectionKey: "experience", lineIndex: 2, lineIndices: [2] },
      { id: "manager", type: "subheading", sectionKey: "experience", lineIndex: 3, lineIndices: [3] },
    ];
    expect(moveSectionInText(text, sections, "experience", 1)).toBe(text);
  });
});
