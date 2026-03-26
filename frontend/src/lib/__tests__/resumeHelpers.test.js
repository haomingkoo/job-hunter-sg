import { describe, it, expect } from "vitest";
import fs from "fs";
import path from "path";
import {
  parseResumeToSections,
  stripResumeMarkdown,
  isHeadingLine,
  getResumeSectionKey,
  parseSubheadingParts,
} from "../resumeHelpers.jsx";

// ── Load curated resume fixtures ────────────────────────────────────────────

const FIXTURES_DIR = path.resolve(__dirname, "../../../../tests/fixtures/resumes_curated");
const fixtureFiles = fs.readdirSync(FIXTURES_DIR)
  .filter((f) => f.endsWith(".txt"))
  .sort();

const fixtures = fixtureFiles.map((filename) => ({
  name: filename.replace(".txt", ""),
  text: fs.readFileSync(path.join(FIXTURES_DIR, filename), "utf-8"),
}));

// ── Property tests: parseResumeToSections ───────────────────────────────────

describe("parseResumeToSections - property tests", () => {
  const VALID_TYPES = new Set([
    "heading",
    "heading_paragraph",
    "subheading",
    "bullet",
    "paragraph",
    "spacer",
    "education_entry",
  ]);

  describe.each(fixtures)("$name", ({ text }) => {
    let sections;

    beforeAll(() => {
      sections = parseResumeToSections(text, []);
    });

    it("returns array", () => {
      expect(Array.isArray(sections)).toBe(true);
      expect(sections.length).toBeGreaterThan(0);
    });

    it("every section has id, type, sectionKey", () => {
      for (const section of sections) {
        expect(section).toHaveProperty("id");
        expect(section).toHaveProperty("type");
        expect(section).toHaveProperty("sectionKey");
      }
    });

    it("valid types: heading, heading_paragraph, subheading, bullet, paragraph, spacer, education_entry", () => {
      for (const section of sections) {
        expect(VALID_TYPES).toContain(section.type);
      }
    });

    it("headings have non-empty sectionKey", () => {
      for (const section of sections) {
        if (section.type === "heading") {
          expect(section.sectionKey).toBeTruthy();
        }
      }
    });

    it("bullets have text property", () => {
      for (const section of sections) {
        if (section.type === "bullet") {
          expect(section).toHaveProperty("text");
          expect(typeof section.text).toBe("string");
        }
      }
    });
  });
});

// ── Unit tests: stripResumeMarkdown ─────────────────────────────────────────

describe("stripResumeMarkdown", () => {
  it("strips single asterisks", () => {
    expect(stripResumeMarkdown("*hello*")).toBe("hello");
  });

  it("strips double asterisks (bold)", () => {
    expect(stripResumeMarkdown("**bold text**")).toBe("bold text");
  });

  it("strips underscores", () => {
    expect(stripResumeMarkdown("__underlined__")).toBe("underlined");
  });

  it("handles mixed markdown", () => {
    expect(stripResumeMarkdown("**bold** and *italic*")).toBe("bold and italic");
  });

  it("trims whitespace", () => {
    expect(stripResumeMarkdown("  hello  ")).toBe("hello");
  });

  it("handles null/undefined", () => {
    expect(stripResumeMarkdown(null)).toBe("");
    expect(stripResumeMarkdown(undefined)).toBe("");
  });
});

// ── Unit tests: isHeadingLine ───────────────────────────────────────────────

describe("isHeadingLine", () => {
  it("detects CERTIFICATIONS & UPSKILLING", () => {
    expect(isHeadingLine("CERTIFICATIONS & UPSKILLING")).toBe(true);
  });

  it("detects KEY SKILLS", () => {
    expect(isHeadingLine("KEY SKILLS")).toBe(true);
  });

  it("detects EXPERIENCE", () => {
    expect(isHeadingLine("EXPERIENCE")).toBe(true);
  });

  it("detects EDUCATION", () => {
    expect(isHeadingLine("EDUCATION")).toBe(true);
  });

  it("detects PROFESSIONAL EXPERIENCE", () => {
    expect(isHeadingLine("PROFESSIONAL EXPERIENCE")).toBe(true);
  });

  it("does not detect bullet lines", () => {
    expect(isHeadingLine("• Led a team of 5 engineers")).toBe(false);
  });

  it("does not detect regular text", () => {
    expect(isHeadingLine("Managed cross-functional team to deliver project")).toBe(false);
  });
});

// ── Unit tests: getResumeSectionKey ─────────────────────────────────────────

describe("getResumeSectionKey", () => {
  it("returns awards for awards heading", () => {
    expect(getResumeSectionKey("Awards")).toBe("awards");
  });

  it("returns experience for Professional Experience", () => {
    expect(getResumeSectionKey("Professional Experience")).toBe("experience");
  });

  it("returns education for Education heading", () => {
    expect(getResumeSectionKey("Education")).toBe("education");
  });

  it("returns skills for Key Skills", () => {
    expect(getResumeSectionKey("Key Skills")).toBe("skills");
  });

  it("returns certifications for Certifications heading", () => {
    expect(getResumeSectionKey("Certifications")).toBe("certifications");
  });

  it("returns certifications for Certifications & Upskilling (shared config exact match)", () => {
    // Shared classification config maps this heading explicitly to certifications
    expect(getResumeSectionKey("Certifications & Upskilling")).toBe("certifications");
  });

  it("returns summary for Professional Summary", () => {
    expect(getResumeSectionKey("Professional Summary")).toBe("summary");
  });
});

// ── Unit tests: parseSubheadingParts ────────────────────────────────────────

describe("parseSubheadingParts", () => {
  it("detects comma-separated company line", () => {
    const result = parseSubheadingParts("Senior Engineer, Central Engineering, Jan 2020 – Present", "experience");
    expect(result).not.toBeNull();
    expect(result.variant).toBe("dated");
  });

  it("detects title with parens", () => {
    const result = parseSubheadingParts("Project Manager (2019 – 2022)", "experience");
    expect(result).not.toBeNull();
    expect(result.variant).toBe("dated");
  });

  it("detects pipe-separated role and date", () => {
    const result = parseSubheadingParts("Dyson | Senior Engineer | Jan 2020 – Present", "experience");
    expect(result).not.toBeNull();
  });

  it("returns null for regular bullet text", () => {
    const result = parseSubheadingParts("Led a team of 5 engineers to deliver on time", "experience");
    expect(result).toBeNull();
  });

  it("returns null for empty input", () => {
    expect(parseSubheadingParts("", "experience")).toBeNull();
    expect(parseSubheadingParts(null, "experience")).toBeNull();
  });
});
