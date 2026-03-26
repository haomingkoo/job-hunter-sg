import { describe, it, expect } from "vitest";
import fs from "fs";
import path from "path";
import {
  parseResumeToSections,
  groupEducationSections,
  stripResumeMarkdown,
  isHeadingLine,
  getResumeSectionKey,
  parseSubheadingParts,
  getDisplaySubheadingText,
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

function getFixtureText(filename) {
  return fs.readFileSync(path.join(FIXTURES_DIR, filename), "utf-8");
}

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

  it("does not mistake innovation text for a dated summary subheading", () => {
    const line = "7+ years of global experience in driving strategic yield improvement programs and system innovation for DRAM, NAND, and logic nodes.";
    expect(parseSubheadingParts(line, "summary")).toBeNull();
  });

  it("does not mistake decisions text for a dated experience heading", () => {
    const line = "Led 0→1 development of the Process Integration Package (PIP): a data platform standardizing risk/conversion decisions across 4 global sites.";
    expect(parseSubheadingParts(line, "experience")).toBeNull();
  });
});

describe("getDisplaySubheadingText", () => {
  it("keeps standalone date ranges on one visual line", () => {
    expect(getDisplaySubheadingText("2022 – 2025", "experience", "dated")).toBe("2022\u00A0–\u00A02025");
  });
});

describe("parseResumeToSections - fixture regressions", () => {
  it("groups Dyson company, title, and standalone date into one experience subheading", () => {
    const sections = parseResumeToSections(getFixtureText("Haoming_Koo_Dyson_Resume.txt"), []);
    const experienceSubheadings = sections.filter((section) => section.type === "subheading" && section.sectionKey === "experience");
    expect(experienceSubheadings.some((section) => (
      String(section.left || "").includes("Manager, Central Engineering")
      && String(section.right || "").includes("Micron Technology")
      && String(section.right || "").includes("2022 – 2025")
    ))).toBe(true);
    expect(experienceSubheadings.some((section) => String(section.text || "").trim() === "2022 – 2025")).toBe(false);

    const acceleratorBullet = sections.find((section) => section.type === "bullet" && section.sectionKey === "experience" && section.text.includes("Accelerator Program"));
    expect(acceleratorBullet?.text).toContain("3,000+ engineers across four global fabs");
  });

  it("recognizes Apple skills heading and keeps GPA lines out of headings", () => {
    const sections = parseResumeToSections(getFixtureText("Haoming_Koo_Apple_BusinessProcessReengineeringManager_Resume.txt"), []);
    const headings = sections.filter((section) => section.type === "heading");
    expect(headings.some((section) => section.sectionKey === "skills" && section.text === "Skills & Tools")).toBe(true);
    expect(headings.some((section) => String(section.text || "").includes("GPA"))).toBe(false);
  });

  it("keeps Mondelez experience entries close to the expected count", () => {
    const sections = parseResumeToSections(getFixtureText("Haoming_Koo_Mondelez.txt"), []);
    const experienceSubheadings = sections.filter((section) => section.type === "subheading" && section.sectionKey === "experience");
    expect(experienceSubheadings.length).toBeLessThanOrEqual(5);
  });

  it("keeps TikTok education GPA text inside education entries instead of heading fragments", () => {
    const parsed = parseResumeToSections(getFixtureText("Haoming_Koo_TikTok_DataProductManager_Resume.txt"), []);
    const headings = parsed.filter((section) => section.type === "heading");
    expect(headings.some((section) => String(section.text || "").includes("GPA"))).toBe(false);

    const grouped = groupEducationSections(parsed);
    const educationEntries = grouped.filter((section) => section.type === "education_entry");
    expect(educationEntries.length).toBe(2);
  });

  it("maps KLA tools and systems heading into the skills section", () => {
    const sections = parseResumeToSections(getFixtureText("Haoming_Koo_KLA_TPM_Resume.txt"), []);
    const headings = sections.filter((section) => section.type === "heading" && section.sectionKey === "skills");
    expect(headings.some((section) => section.text === "TOOLS & SYSTEMS")).toBe(true);
  });
});
