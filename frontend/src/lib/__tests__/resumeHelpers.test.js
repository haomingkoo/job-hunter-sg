import { describe, it, expect } from "vitest";
import fs from "fs";
import path from "path";
import {
  parseResumeToSections,
  groupEducationSections,
  stripResumeMarkdown,
  splitInlineHeadingContent,
  isHeadingLine,
  getResumeSectionKey,
  parseSubheadingParts,
  getDisplaySubheadingText,
  getRewriteCacheKey,
  isRewriteResultCurrent,
  moveSectionInText,
} from "../resumeHelpers.jsx";

describe("getRewriteCacheKey", () => {
  const inputs = {
    bullet: "Led a finance transformation.",
    jobTitle: "Finance Manager",
    jobDescription: "Own process improvement.",
    usedVerbs: "built, managed",
    rewriteFocus: "specifics",
    focusedFeedback: "Add supported scale.",
  };

  it("reuses rewrites only when every model input is unchanged", () => {
    expect(getRewriteCacheKey(inputs)).toBe(getRewriteCacheKey({ ...inputs }));
    expect(getRewriteCacheKey(inputs)).not.toBe(getRewriteCacheKey({ ...inputs, rewriteFocus: "shorten" }));
    expect(getRewriteCacheKey(inputs)).not.toBe(getRewriteCacheKey({ ...inputs, bullet: "Updated bullet." }));
  });

  it("hides a cached rewrite after its bullet or target job changes", () => {
    const result = {
      source_bullet: inputs.bullet,
      job_title: inputs.jobTitle,
      job_description: inputs.jobDescription,
    };
    expect(isRewriteResultCurrent(result, inputs)).toBe(true);
    expect(isRewriteResultCurrent(result, { ...inputs, bullet: "Changed bullet." })).toBe(false);
    expect(isRewriteResultCurrent(result, { ...inputs, jobTitle: "Another role" })).toBe(false);
  });
});

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

  it("detects configured compound headings", () => {
    expect(isHeadingLine("SELECTED TECHNICAL PROJECTS")).toBe(true);
    expect(isHeadingLine("EDUCATION AND CERTIFICATIONS")).toBe(true);
  });

  it("detects descriptive headings without exact aliases", () => {
    expect(isHeadingLine("FINANCE PROCESS & TRANSFORMATION EXPERIENCE")).toBe(true);
    expect(isHeadingLine("Automation & AI Experience")).toBe(true);
    expect(isHeadingLine("PROFESSIONAL EXPERIENCE (FINANCE & ANALYTICS)")).toBe(true);
    expect(isHeadingLine("EDUCATION & CERTIFICATIONS")).toBe(true);
  });

  it("does not treat an uppercase name as a heading", () => {
    expect(isHeadingLine("HAOMING KOO")).toBe(false);
  });

  it("does not split a skills label on an ordinary space", () => {
    expect(splitInlineHeadingContent(
      "Leadership and Delivery: programme management and adoption",
    )).toBeNull();
  });

  it("does not detect bullet lines", () => {
    expect(isHeadingLine("• Led a team of 5 engineers")).toBe(false);
  });

  it("does not detect regular text", () => {
    expect(isHeadingLine("Managed cross-functional team to deliver project")).toBe(false);
  });

  it("does not promote names, phases, roles, or prose containing section words", () => {
    expect(isHeadingLine("HUI SHAN ANG")).toBe(false);
    expect(isHeadingLine("Deep Skilling Phase")).toBe(false);
    expect(isHeadingLine("Finance Manager | Example Company | 2021 - Present")).toBe(false);
    expect(isHeadingLine("Managed teams with extensive project experience.")).toBe(false);
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

it("keeps descriptive headings as separate sections through the UI parser", () => {
  const parsed = parseResumeToSections([
    "PROFESSIONAL SUMMARY",
    "Finance transformation leader.",
    "FINANCE PROCESS & TRANSFORMATION EXPERIENCE",
    "Finance Manager | Example Company | 2021 - Present",
    "• Led a regional close redesign.",
    "AUTOMATION & AI EXPERIENCE",
    "AI Finance Lead | Example Company | 2023 - Present",
    "• Built forecasting automation.",
    "EDUCATION & CERTIFICATIONS",
    "Bachelor of Accountancy, National University of Singapore, 2015",
  ].join("\n"), []);

  expect(parsed.filter((item) => item.type === "heading").map((item) => item.sectionKey)).toEqual([
    "summary",
    "experience",
    "experience",
    "education",
  ]);
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

  it("keeps certification lines with years as plain credential text", () => {
    expect(parseSubheadingParts("Full Stack Development with AI (NUS x Emeritus, 2025)", "certifications")).toBeNull();
    expect(parseSubheadingParts("GA100 – Generative AI (Heicoders Academy, WSQ Accredited, 2025)", "certifications")).toBeNull();
    expect(parseSubheadingParts("PMP (in progress, expected 2025)", "certifications")).toBeNull();
  });
});

describe("getDisplaySubheadingText", () => {
  it("keeps standalone date ranges on one visual line", () => {
    expect(getDisplaySubheadingText("2022 – 2025", "experience", "dated")).toBe("2022\u00A0–\u00A02025");
  });
});

describe("parseResumeToSections - fixture regressions", () => {
  it("preserves real PDF boundaries without inventing headings or o-bullets", () => {
    const text = [
      "HAOMING KOO",
      "CORE SKILLS",
      "Leadership and Delivery: programme management and adoption",
      "Agentic AI and LLM Engineering: LangGraph and RAG",
      "PROFESSIONAL EXPERIENCE",
      "Associate AI Engineer | AI Singapore | Jan 2026 - Present",
      "Selected via a national assessment for an industry project delivered with a three-person team.",
      "• Built the production agent scaffold across four services",
      "and wrote the phased redesign plan.",
      "• Designed the validation workflow.",
      "SELECTED TECHNICAL PROJECTS",
      "• smart-buoy: streamed positioning data through an ML pipeline",
      "operational dashboards in Tableau.",
      "EDUCATION AND CERTIFICATIONS",
      "• M.Sc., National University of Singapore, 2022",
      "• Languages - English and Mandarin; available from October 2026",
      "and travel",
    ].join("\n");

    const sections = parseResumeToSections(text, []);
    const headingKeys = sections
      .filter((section) => section.type === "heading")
      .map((section) => section.sectionKey);
    const bullets = sections.filter((section) => section.type === "bullet");
    const skillParagraphs = sections.filter(
      (section) => section.type === "paragraph" && section.sectionKey === "skills",
    );

    expect(headingKeys).toEqual(["skills", "experience", "projects", "education"]);
    expect(skillParagraphs).toHaveLength(2);
    expect(bullets.some((section) => section.text.startsWith("perational"))).toBe(false);
    expect(bullets.filter((section) => section.sectionKey === "experience")).toHaveLength(2);
    expect(sections).toContainEqual(expect.objectContaining({
      type: "paragraph",
      sectionKey: "experience",
      text: "Selected via a national assessment for an industry project delivered with a three-person team.",
    }));
    expect(bullets.find((section) => section.text.startsWith("Built"))?.text).toContain("phased redesign plan");
    expect(bullets.find((section) => section.text.startsWith("Languages"))?.text).toContain("and travel");
  });

  it("keeps mixed unmarked and explicit achievement bullets editable", () => {
    const text = [
      "PROFESSIONAL EXPERIENCE",
      "AI Engineer | Example Labs | Jan 2024 - Present",
      "Built a retrieval platform used by operations teams.",
      "Reduced investigation time through deterministic validation.",
      "• Led release testing across three workflows.",
    ].join("\n");

    const sections = parseResumeToSections(text, []);
    const bullets = sections
      .filter((section) => section.type === "bullet")
      .map((section) => section.text);

    expect(bullets).toEqual([
      "Built a retrieval platform used by operations teams.",
      "Reduced investigation time through deterministic validation.",
      "Led release testing across three workflows.",
    ]);
  });

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

  it("does not split AWS transformation certification parentheses into fake dates", () => {
    const text = [
      "Haoming Koo",
      "Certifications",
      "Full Stack Development with AI (NUS x Emeritus, 2025)",
      "GA100 – Generative AI (Heicoders Academy, WSQ Accredited, 2025)",
      "PMP (in progress, expected 2025)",
    ].join("\n");
    const sections = parseResumeToSections(text, []);
    const certificationItems = sections.filter((section) => section.sectionKey === "certifications" && section.type !== "heading");
    expect(certificationItems.every((section) => section.type === "paragraph" || section.type === "spacer")).toBe(true);
    expect(certificationItems.some((section) => section.text === "GA100 – Generative AI (Heicoders Academy, WSQ Accredited, 2025)")).toBe(true);
  });

  it("does not merge a no-period bullet with the next position header (pipe + date)", () => {
    const text = [
      "Haoming Koo",
      "Experience",
      "Software Engineer | GovTech Singapore | Singapore | Jul 2019 – Dec 2021",
      "• Helped with CI/CD pipeline improvements and deployment automation",
      "• Built citizen-facing web applications using React and Node.js",
    ].join("\n");
    const sections = parseResumeToSections(text, []);
    const bullet = sections.find((s) => s.type === "bullet" && s.text.startsWith("Helped with CI/CD"));
    expect(bullet).toBeTruthy();
    expect(bullet.text).not.toContain("GovTech");
    expect(bullet.text).not.toContain("Software Engineer");
  });

  it("does not merge a no-period bullet followed by a new position header below it", () => {
    const text = [
      "Haoming Koo",
      "Experience",
      "Software Engineer | GovTech Singapore | Singapore | Jul 2019 – Dec 2021",
      "• Helped with CI/CD pipeline improvements and deployment automation",
      "Senior Engineer | Shopee | Singapore | Jan 2018 – Jun 2019",
      "• Reduced infrastructure costs by 30% through AWS optimisation",
    ].join("\n");
    const sections = parseResumeToSections(text, []);
    const bullet = sections.find((s) => s.type === "bullet" && s.text.startsWith("Helped with CI/CD"));
    expect(bullet).toBeTruthy();
    expect(bullet.text).not.toContain("Shopee");
    expect(bullet.text).not.toContain("Senior Engineer");
  });

  it("uses normalized section keys when applying template order", () => {
    const parsed = parseResumeToSections([
      "PROFESSIONAL SUMMARY",
      "Finance leader.",
      "CORE SKILLS",
      "Python, SQL",
      "FINANCE PROCESS & TRANSFORMATION EXPERIENCE",
      "Finance Manager | Example Company | 2021 - Present",
    ].join("\n"), [], ["summary", "experience", "skills"]);

    expect(parsed.filter((item) => item.type === "heading").map((item) => item.sectionKey)).toEqual([
      "summary",
      "experience",
      "skills",
    ]);
  });

  it("moves sections by source order even when display order was templated", () => {
    const text = [
      "PROFESSIONAL SUMMARY",
      "Finance leader.",
      "CORE SKILLS",
      "Python, SQL",
      "PROFESSIONAL EXPERIENCE",
      "Finance Manager | Example Company | 2021 - Present",
    ].join("\n");
    const parsed = parseResumeToSections(text, [], ["summary", "experience", "skills"]);
    const experience = parsed.find((item) => item.type === "heading" && item.sectionKey === "experience");

    const moved = moveSectionInText(text, parsed, experience.id, 1);

    expect(moved).toBe(text);
    expect((moved.match(/CORE SKILLS/g) || [])).toHaveLength(1);
    expect((moved.match(/PROFESSIONAL EXPERIENCE/g) || [])).toHaveLength(1);
  });

  it("keeps each dated education or certification line as its own entry", () => {
    const parsed = parseResumeToSections([
      "EDUCATION & CERTIFICATIONS",
      "AI Singapore, AI Apprenticeship Programme 2026",
      "Institute of Data, Certified Data Science & AI 2025",
      "Singapore Chartered Tax Professionals, Accredited Tax Practitioner 2022",
      "ISCA / ACCA, Chartered Accountant of Singapore 2017 / 2015",
      "University of London, B.Sc. Business, Honours 2009",
    ].join("\n"), []);

    expect(groupEducationSections(parsed).filter((item) => item.type === "education_entry")).toHaveLength(5);
  });

  it("does not merge a no-period bullet with a long pipe-and-date position header below", () => {
    const text = [
      "Haoming Koo",
      "Experience",
      "Software Engineer | GovTech Singapore | Singapore | Jul 2019 – Dec 2021",
      "• Helped with CI/CD pipeline improvements and deployment automation",
      "Software Engineer | GovTech Singapore | Singapore | GovTech Singapore | Singapore | Jul 2019 – Dec 2021",
      "• Built citizen-facing web applications using React",
    ].join("\n");
    const sections = parseResumeToSections(text, []);
    const bullet = sections.find((s) => s.type === "bullet" && s.text.startsWith("Helped with CI/CD"));
    expect(bullet).toBeTruthy();
    expect(bullet.text).not.toContain("GovTech");
    expect(bullet.text).not.toContain("2019");
  });
});
