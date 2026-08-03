// Some functions return JSX, so React is required.

import { Fragment } from "react";
import { CheckCircle, AlertCircle, X } from "lucide-react";
import { escapeRegExp, extractKeywordLabel, collectKeywordMatches } from "./helpers.js";
import {
  RESUME_TEMPLATE_STYLES,
  RESUME_ACTION_VERBS,
  RESUME_AVOIDED_PHRASES,
  RESUME_WEAK_STARTS,
  RESUME_BULLET_RE,
  RESUME_METRIC_RE,
  RESUME_SCALE_CUE_PATTERNS,
  RESUME_DATE_HINT_RE,
  RESUME_CERTIFICATION_RE,
  RESUME_EDUCATION_RE,
  RESUME_EDUCATION_INSTITUTION_RE,
  RESUME_DEGREE_RE,
  DEGREE_START_RE,
  RESUME_EDUCATION_DETAIL_RE,
  RESUME_TITLE_HINT_RE,
  RESUME_OVERUSED_IGNORE,
  RESUME_DISPLAY_ACRONYMS,
  RESUME_SMALL_TITLE_WORDS,
  RESUME_SECTION_LABELS,
  BULLET_ACTION_SUGGESTIONS,
  KEYWORD_INSERT_PREFERRED_SECTIONS,
} from "./resumeConstants.js";

export function buildResumeTemplateStyles(templateMeta, templateId) {
  const fallback = RESUME_TEMPLATE_STYLES[templateId] || RESUME_TEMPLATE_STYLES.modern;
  const bodySize = Number.isFinite(templateMeta?.body_size) ? templateMeta.body_size : fallback.bodySize;
  const nameSize = Number.isFinite(templateMeta?.name_size) ? templateMeta.name_size : fallback.nameSize;
  const margins = Number.isFinite(templateMeta?.margins) ? templateMeta.margins : fallback.margins;
  const requestedFont = typeof templateMeta?.font === "string" ? templateMeta.font.trim() : "";
  const fontFamily = requestedFont
    ? requestedFont.includes(",")
      ? requestedFont
      : fallback.fontFamily.toLowerCase().includes(requestedFont.toLowerCase())
        ? fallback.fontFamily
        : `${requestedFont}, ${fallback.fontFamily}`
    : fallback.fontFamily;
  const lineHeight = fallback.lineHeight;
  const headingSize = fallback.headingSize;

  return {
    pageClass: fallback.pageClass,
    pageStyle: {
      fontFamily,
      fontSize: `${bodySize}pt`,
      padding: `${margins * 25.4}mm`,
      width: "100%",
      maxWidth: "210mm",
      minHeight: "auto",
      lineHeight: String(lineHeight),
      overflowWrap: "break-word",
      wordBreak: "break-word",
      overflow: "hidden",
      columnCount: 1,
      columnWidth: "auto",
      columnGap: "normal",
      columnFill: "auto",
    },
    headingClass: fallback.headingClass,
    headingStyle: {
      fontFamily,
      fontSize: `${headingSize}pt`,
      lineHeight: String(lineHeight),
    },
    nameClass: fallback.nameClass,
    nameStyle: {
      fontFamily,
      fontSize: `${nameSize}pt`,
      lineHeight: "1.15",
    },
    contactStyle: {
      fontFamily,
      fontSize: `${Math.max(bodySize - 1, 9)}pt`,
      lineHeight: String(lineHeight),
    },
    subheadingClass: fallback.subheadingClass,
    bodyStyle: {
      fontFamily,
      fontSize: `${bodySize}pt`,
      lineHeight: String(lineHeight),
      display: "block",
      width: "100%",
      maxWidth: "100%",
      columnCount: 1,
      columnWidth: "auto",
      columnGap: "normal",
    },
  };
}

export function stripResumeMarkdown(line) {
  return String(line || "")
    .replace(/\*\*(.*?)\*\*/g, "$1")
    .replace(/__(.*?)__/g, "$1")
    .replace(/\*(.*?)\*/g, "$1")
    .trim();
}

export function hasDateHint(value) {
  return RESUME_DATE_HINT_RE.test(stripResumeMarkdown(value));
}

export function extractResumeMetricSignals(value) {
  const text = stripResumeMarkdown(value);
  if (!text) return [];

  const matches = [];
  const addMatches = (pattern) => {
    const found = text.match(pattern) || [];
    found.forEach((item) => {
      const cleaned = item.trim().replace(/\s+/g, " ");
      if (cleaned) matches.push(cleaned);
    });
  };

  addMatches(/\d+%|\$[\d,]+|\d+[kKmMbB]\b|\d{1,3}(?:,\d{3})+/g);
  RESUME_SCALE_CUE_PATTERNS.forEach(addMatches);

  return [...new Set(matches)];
}

export function isResumeActionVerb(word) {
  const normalized = String(word || "").toLowerCase().replace(/[,:;.]$/, "");
  if (!normalized) return false;
  const baseVerb = normalized.includes("-") ? normalized.split("-").pop() : normalized;
  return RESUME_ACTION_VERBS.has(normalized) || RESUME_ACTION_VERBS.has(baseVerb);
}

export function startsLineWithResumeActionVerb(value) {
  const words = stripResumeMarkdown(value).split(/\s+/).filter(Boolean);
  if (!words.length) return false;
  return isResumeActionVerb(words[0]);
}

export function looksLikeEducationText(value) {
  return RESUME_EDUCATION_RE.test(stripResumeMarkdown(value));
}

export function looksLikeEducationInstitution(value) {
  return RESUME_EDUCATION_INSTITUTION_RE.test(stripResumeMarkdown(value));
}

export function looksLikeCertificationText(value) {
  return RESUME_CERTIFICATION_RE.test(stripResumeMarkdown(value));
}

export function looksLikeEducationDetail(value) {
  return RESUME_EDUCATION_DETAIL_RE.test(stripResumeMarkdown(value));
}

export function looksLikeEducationMain(value) {
  const trimmed = stripResumeMarkdown(value);
  if (!trimmed) return false;
  // Degree-starting lines are always main, even if they contain detail keywords like "Distinction"
  if (DEGREE_START_RE.test(trimmed)) return true;
  return !looksLikeEducationDetail(trimmed)
    && (
      looksLikeEducationText(trimmed)
      || looksLikeEducationInstitution(trimmed)
      || RESUME_DEGREE_RE.test(trimmed)
      || hasDateHint(trimmed)
    );
}

export function startsNewEducationEntry(value) {
  const trimmed = stripResumeMarkdown(value);
  if (!trimmed) return false;
  if (DEGREE_START_RE.test(trimmed)) return true;
  return looksLikeEducationInstitution(trimmed) && !looksLikeEducationDetail(trimmed);
}

export function splitEducationMeta(value) {
  const trimmed = stripResumeMarkdown(value);
  if (!trimmed) return { primary: "", secondary: "" };

  const yearRangeMatch = trimmed.match(/^(.*?)(?:,\s*|\s+)((?:19|20)\d{2}(?:\s*[–—-]\s*(?:present|(?:19|20)\d{2}))?)$/i);
  if (yearRangeMatch) {
    const primary = yearRangeMatch[1].trim().replace(/[,\s]+$/, "");
    const secondary = yearRangeMatch[2].trim();
    return { primary: primary || trimmed, secondary };
  }

  const monthRangeMatch = trimmed.match(/^(.*?)(?:,\s*|\s+)((?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+(?:19|20)\d{2}(?:\s*[–—-]\s*(?:present|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+(?:19|20)\d{2}))?)$/i);
  if (monthRangeMatch) {
    const primary = monthRangeMatch[1].trim().replace(/[,\s]+$/, "");
    const secondary = monthRangeMatch[2].trim();
    return { primary: primary || trimmed, secondary };
  }

  return { primary: trimmed, secondary: "" };
}

const ENTRY_SUBHEADING_SECTIONS = new Set(["experience", "projects", "activities", "career_break"]);
const STRUCTURED_SUBHEADING_SECTIONS = new Set([...ENTRY_SUBHEADING_SECTIONS, "education"]);
const DATE_ONLY_TEXT_RE = /^(?:(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\s+(?:19|20)\d{2}|(?:19|20)\d{2}|(?:present|current)|\d{1,2}\/(?:19|20)\d{2})(?:\s*[–—-]\s*(?:(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\s+(?:19|20)\d{2}|(?:19|20)\d{2}|(?:present|current)|\d{1,2}\/(?:19|20)\d{2}))?$/i;
const COMPANY_OR_LOCATION_RE = /\b(?:technology|technologies|corp(?:oration)?|inc|ltd|pte|limited|group|bank|systems|solutions|services|manufacturing|semiconductor|micron|dyson|apple|meta|tiktok|kla|mondelez|singapore|japan|taiwan|usa|us|boise|hiroshima|taichung|manassas|global|regional|apac|emea|americas)\b/i;

export function isStructuredSubheadingSection(sectionKey = "") {
  return STRUCTURED_SUBHEADING_SECTIONS.has(sectionKey);
}

export function looksLikeDateOnlyText(value) {
  const trimmed = stripResumeMarkdown(value).replace(/[(),]/g, "").replace(/\s+/g, " ").trim();
  if (!trimmed) return false;
  return DATE_ONLY_TEXT_RE.test(trimmed);
}

export function looksLikeResumeTitleLine(value) {
  const trimmed = stripResumeMarkdown(value).replace(/^[|•]\s*/, "").trim();
  if (!trimmed || looksLikeDateOnlyText(trimmed)) return false;
  const words = trimmed.split(/\s+/).filter(Boolean);
  if (words.length > 12) return false;
  if (startsLineWithResumeActionVerb(trimmed) && words.length > 4) return false;
  return RESUME_TITLE_HINT_RE.test(trimmed)
    || (
      words.length <= 8
      && /\(.*\)/.test(trimmed)
      && !/[.!?]$/.test(trimmed)
    );
}

export function looksLikeResumeCompanyLine(value) {
  const trimmed = stripResumeMarkdown(value).replace(/^[|•]\s*/, "").trim();
  if (!trimmed || looksLikeDateOnlyText(trimmed) || looksLikeResumeTitleLine(trimmed)) return false;
  if (looksLikeEducationText(trimmed) || looksLikeCertificationText(trimmed)) return false;
  if (/[.!?]$/.test(trimmed)) return false;
  const words = trimmed.split(/\s+/).filter(Boolean);
  if (words.length > 12) return false;
  return COMPANY_OR_LOCATION_RE.test(trimmed)
    || /^[A-Z][A-Za-z0-9&.,'()/+-]*(?:\s+[A-Z][A-Za-z0-9&.,'()/+-]*){0,7}$/.test(trimmed)
    || trimmed.includes("/");
}

function buildSubheadingLabel(left = "", right = "") {
  return [left, right].filter(Boolean).join(" | ").trim();
}

function mergeSectionMetadata(target, source) {
  target.raw = [target.raw, source.raw].filter(Boolean).join("\n");
  target.lineIndices = [...new Set([...(target.lineIndices || [target.lineIndex]), ...(source.lineIndices || [source.lineIndex])])];
  target.keywordMatches = [...new Set([...(target.keywordMatches || []), ...(source.keywordMatches || [])])];
}

export function getInlineResumeSegments(section) {
  if (section?.type !== "paragraph") return null;
  if (!["skills", "certifications", "personal"].includes(section.sectionKey)) return null;
  const parts = String(section.text || "").split("|").map((part) => part.trim()).filter(Boolean);
  return parts.length >= 2 ? parts : null;
}

export function looksLikeDenseSkillList(parts) {
  return parts.length >= 3
    && parts.every((part) => !hasDateHint(part) && part.split(/\s+/).length <= 6);
}

export function reorderParsedSections(sections, templateOrder = []) {
  if (!templateOrder.length || !sections.length) return sections;

  const normalizeKey = (key) => (key || "").toLowerCase().replace(/[^a-z]/g, "");
  const sectionKeyMap = {
    "professionalsummary": "summary", "careersummary": "summary", "summary": "summary",
    "objective": "summary", "about": "summary",
    "professionalexperience": "experience", "workexperience": "experience", "experience": "experience",
    "education": "education", "academicbackground": "education",
    "coreskills": "skills", "technicalskills": "skills", "skills": "skills",
    "corecompetencies": "skills", "keyskills": "skills",
    "projects": "projects", "personalprojects": "projects",
    "certifications": "certifications", "licensescertifications": "certifications",
    "certificationstechnicalupskilling": "certifications",
    "activities": "activities", "extracurricular": "activities",
    "languages": "languages",
    "personal": "personal",
    "awards": "awards", "honorsawards": "awards",
  };

  const getSectionType = (section) => {
    if (section.sectionKey) return section.sectionKey;
    const raw = normalizeKey(section.heading || section.text || "");
    return sectionKeyMap[raw] || raw;
  };

  const header = [];
  const sectionItems = [];
  for (const s of sections) {
    if (s.type === "heading" || s.type === "entry" || s.type === "bullet") {
      sectionItems.push(s);
    } else if (!sectionItems.length) {
      header.push(s);
    } else {
      sectionItems.push(s);
    }
  }

  const groups = [];
  let currentGroup = null;
  for (const item of sectionItems) {
    if (item.type === "heading") {
      currentGroup = { key: getSectionType(item), items: [item] };
      groups.push(currentGroup);
    } else if (currentGroup) {
      currentGroup.items.push(item);
    } else {
      header.push(item);
    }
  }

  const orderIndex = {};
  templateOrder.forEach((key, i) => { orderIndex[key] = i; });

  groups.sort((a, b) => {
    const ai = orderIndex[a.key] ?? 999;
    const bi = orderIndex[b.key] ?? 999;
    return ai - bi;
  });

  const result = [...header];
  for (const group of groups) {
    result.push(...group.items);
  }
  return result;
}

export function normalizeScoreData(data) {
  const keywordMatch = data?.keyword_match || {};
  const matched = Array.isArray(keywordMatch.matched)
    ? keywordMatch.matched
    : Array.isArray(keywordMatch.found)
      ? keywordMatch.found
      : [];
  const missing = Array.isArray(keywordMatch.missing) ? keywordMatch.missing : [];
  const total = matched.length + missing.length;
  const scorePercent = Number.isFinite(keywordMatch.score_percent)
    ? keywordMatch.score_percent
    : total > 0
      ? Math.round((matched.length / total) * 100)
      : 0;

  return {
    ...data,
    dimensions: data?.dimensions && !Array.isArray(data.dimensions) ? data.dimensions : {},
    keyword_match: {
      matched,
      missing,
      score_percent: scorePercent,
    },
  };
}

export function getStatusMeta(score, max) {
  const ratio = max > 0 ? score / max : 1;
  if (ratio >= 0.8) {
    return {
      label: "Good Job",
      className: "bg-emerald-100 text-emerald-800",
      icon: <CheckCircle size={12} />,
    };
  }
  if (ratio >= 0.5) {
    return {
      label: "On Track",
      className: "bg-amber-100 text-amber-800",
      icon: <AlertCircle size={12} />,
    };
  }
  return {
    label: "Review",
    className: "bg-rose-100 text-rose-800",
    icon: <X size={12} />,
  };
}

export function buildResumeKeywords(selectedJob, scoreData) {
  const collected = [];
  if (Array.isArray(selectedJob?.skills)) collected.push(...selectedJob.skills);
  if (Array.isArray(scoreData?.keyword_match?.matched)) collected.push(...scoreData.keyword_match.matched.slice(0, 12));

  return [...new Set(collected
    .map(extractKeywordLabel)
    .filter((item) => item.length >= 3)
  )];
}

export function buildSkillAlignment(skills, text) {
  const uniqueSkills = [...new Set(
    (Array.isArray(skills) ? skills : [])
      .map(extractKeywordLabel)
      .filter((item) => item.length >= 2),
  )];

  if (uniqueSkills.length === 0) {
    return { matched: [], missing: [] };
  }

  const resumeLower = text.toLowerCase();
  const matched = uniqueSkills.filter((skill) => resumeLower.includes(skill.toLowerCase()));
  const missing = uniqueSkills.filter((skill) => !resumeLower.includes(skill.toLowerCase()));
  return { matched, missing };
}

export function computeKeywordInsertSuggestions(keyword, bulletSections, allKeywordLabels) {
  const keywordLower = keyword.toLowerCase();
  const keywordWords = keywordLower.split(/\s+/).filter((w) => w.length >= 3);

  const scored = bulletSections.map((bullet) => {
    const textLower = bullet.text.toLowerCase();
    const wordCount = bullet.text.split(/\s+/).length;

    let score = 0;

    const wordOverlap = keywordWords.filter((w) => textLower.includes(w)).length;
    score += wordOverlap * 30;

    const sectionKey = (bullet.sectionKey || "").toLowerCase();
    if (KEYWORD_INSERT_PREFERRED_SECTIONS.has(sectionKey)) score += 20;
    if (sectionKey === "summary" || sectionKey === "objective") score -= 10;
    if (sectionKey === "education") score -= 15;

    if (wordCount < 15) score += 10;
    else if (wordCount < 25) score += 5;

    const existingMatches = (allKeywordLabels || []).filter(
      (kw) => kw.toLowerCase() !== keywordLower && textLower.includes(kw.toLowerCase()),
    ).length;
    score += Math.min(existingMatches, 3) * 8;

    return { bullet, score };
  });

  return scored
    .sort((a, b) => b.score - a.score)
    .slice(0, 3)
    .map((item) => item.bullet);
}

const EDUCATION_GPA_RE = /(?:gpa|cgpa|cap)\s*[:.]?\s*\d+\.?\d*\s*[/]?\s*\d*\.?\d*/i;
const EDUCATION_HONORS_RE = /\b(?:first class|second class|distinction|honou?rs?|magna|summa|cum laude|dean.?s list|merit|with distinction|valedictorian)\b/i;

function isEducationEntryStart(item) {
  if (item.type === "subheading" && item.variant === "education_main") return true;
  // Dated subheadings only start new entries if they have substantive education content
  // (prevents "Singapore (2017)" from becoming its own entry)
  if (item.type === "subheading" && item.variant === "dated") {
    const leftText = stripResumeMarkdown(item.left || item.text || "");
    if (DEGREE_START_RE.test(leftText) || RESUME_DEGREE_RE.test(leftText)
      || looksLikeEducationInstitution(leftText) || looksLikeEducationText(leftText)
      || leftText.split(/\s+/).length >= 2) return true;
    return false;
  }
  // Subheading with degree pattern but wrong variant (e.g., "Bachelor of Science – Distinction" parsed as variant=company)
  if (item.type === "subheading" && DEGREE_START_RE.test(stripResumeMarkdown(item.left || item.text || ""))) return true;
  if (item.type === "paragraph" && (startsNewEducationEntry(item.text) || (looksLikeEducationMain(item.text) && !looksLikeEducationDetail(item.text)))) return true;
  // Detect degree patterns even in "detail" lines (BSc with Honours/Distinction)
  if ((item.type === "paragraph" || item.type === "bullet") && DEGREE_START_RE.test(stripResumeMarkdown(item.text || ""))) return true;
  // Detect institution names as entry boundaries (second NUS = new entry)
  if (item.type === "paragraph" && looksLikeEducationInstitution(item.text) && !looksLikeEducationDetail(item.text)) return true;
  if (
    item.type === "paragraph"
    && hasDateHint(item.text)
    && /^[A-Z]/.test(stripResumeMarkdown(item.text || ""))
    && !looksLikeEducationDetail(item.text)
  ) return true;
  return false;
}

function extractEducationFields(items) {
  let degree = "";
  let institution = "";
  let dateRange = "";
  let gpa = "";
  const honors = [];
  const details = [];
  const bullets = [];

  for (const item of items) {
    const text = item.text || "";

    // Extract date from subheading right side or text
    if (!dateRange) {
      if (item.type === "subheading" && item.right && hasDateHint(item.right)) {
        const meta = splitEducationMeta(item.right);
        if (meta.secondary) {
          dateRange = meta.secondary;
        } else {
          // Try year in parentheses (e.g., "National University of Singapore (2022)")
          const parenYear = item.right.match(/\((\d{4})\)\s*$/);
          if (parenYear) dateRange = parenYear[1];
        }
      } else {
        const dateMatch = text.match(/(?:19|20)\d{2}\s*[–—-]\s*(?:(?:19|20)\d{2}|[Pp]resent)/);
        if (dateMatch) {
          dateRange = dateMatch[0];
        } else {
          // Standalone year at start of text (e.g., "2022 GPA 4.85/5.00")
          const yearStartMatch = text.match(/^((?:19|20)\d{2})\b/);
          if (yearStartMatch) dateRange = yearStartMatch[1];
        }
      }
    }

    if (!gpa) {
      const gpaMatch = text.match(EDUCATION_GPA_RE);
      if (gpaMatch) gpa = gpaMatch[0].trim();
    }

    const honorsMatch = text.match(EDUCATION_HONORS_RE);
    if (honorsMatch && !honors.includes(honorsMatch[0])) honors.push(honorsMatch[0]);

    if (item.type === "bullet") {
      bullets.push(item);
      continue;
    }

    if (item.type === "subheading") {
      const left = item.left || "";
      const right = item.right || "";

      if (item.variant === "education_main" || item.variant === "dated") {
        // Strip parenthesized year from left for classification (but extract it as dateRange)
        const cleanLeft = left.replace(/\s*\(\d{4}\)\s*$/, "").trim();
        const leftYearMatch = left.match(/\((\d{4})\)\s*$/);
        if (leftYearMatch && !dateRange) dateRange = leftYearMatch[1];

        if (!degree && (RESUME_DEGREE_RE.test(cleanLeft) || DEGREE_START_RE.test(cleanLeft))) {
          degree = cleanLeft;
        } else if (!institution && looksLikeEducationInstitution(cleanLeft)) {
          institution = cleanLeft;
        } else if (!degree) {
          degree = cleanLeft;
        } else if (institution && /\b(?:of|in|at|for)$/i.test(institution.trim()) && cleanLeft && cleanLeft.split(/\s+/).length <= 3) {
          // Institution continuation (e.g., "Singapore" after "National University of")
          institution = `${institution} ${cleanLeft}`;
        } else if (cleanLeft) {
          details.push(cleanLeft);
        }
        const rightClean = right.replace(/\s*\(\d{4}\)\s*$/, "").trim();
        const rightYearMatch = right.match(/\((\d{4})\)\s*$/);
        if (rightYearMatch && !dateRange) dateRange = rightYearMatch[1];
        const rightMeta = splitEducationMeta(rightClean);
        if (rightMeta.secondary && !dateRange) dateRange = rightMeta.secondary;
        if (rightMeta.primary) {
          if (!institution && looksLikeEducationInstitution(rightMeta.primary)) institution = rightMeta.primary;
          else if (!degree && RESUME_DEGREE_RE.test(rightMeta.primary)) degree = rightMeta.primary;
          else if (!institution) institution = rightMeta.primary;
        }
      } else if (item.variant === "education_detail") {
        const combined = [left, right].filter(Boolean).join(", ");
        if (!gpa && EDUCATION_GPA_RE.test(combined)) {
          gpa = combined.match(EDUCATION_GPA_RE)?.[0] || "";
        }
        // Always strip GPA from detail text (it's already captured in gpa field)
        const remaining = combined.replace(EDUCATION_GPA_RE, "").replace(/^[,·|\s]+|[,·|\s]+$/g, "").trim();
        if (remaining) details.push(remaining);
      }
      continue;
    }

    // Paragraph
    if (looksLikeEducationDetail(text)) {
      if (!gpa && EDUCATION_GPA_RE.test(text)) {
        gpa = text.match(EDUCATION_GPA_RE)?.[0] || "";
      }
      const remaining = text.replace(EDUCATION_GPA_RE, "").replace(/^[,·|\s]+|[,·|\s]+$/g, "").trim();
      if (remaining) details.push(remaining);
    } else if (!degree && (RESUME_DEGREE_RE.test(text) || DEGREE_START_RE.test(text))) {
      degree = text.replace(/(?:19|20)\d{2}\s*[–—-]\s*(?:(?:19|20)\d{2}|[Pp]resent)/, "").trim().replace(/[,\s]+$/, "");
    } else if (!institution && looksLikeEducationInstitution(text)) {
      institution = text.replace(/(?:19|20)\d{2}\s*[–—-]\s*(?:(?:19|20)\d{2}|[Pp]resent)/, "").trim().replace(/[,\s]+$/, "");
    } else if (!degree) {
      degree = text;
    } else if (!institution) {
      institution = text;
    } else {
      details.push(text);
    }
  }

  // Merge location continuations into institution (handles PDF line wrapping
  // e.g., "National University of" + "Singapore" on separate lines)
  if (institution && /\b(?:of|in|at|for)$/i.test(institution.trim()) && details.length > 0) {
    const candidate = details[0];
    if (candidate.split(/\s+/).length <= 3
      && !EDUCATION_GPA_RE.test(candidate)
      && !EDUCATION_HONORS_RE.test(candidate)
      && !hasDateHint(candidate)) {
      institution = `${institution} ${details.shift()}`;
    }
  }

  // Remove honors that already appear in degree text (redundant)
  const filteredHonors = honors.filter((h) => !(degree && degree.toLowerCase().includes(h.toLowerCase())));

  const uniqueDetails = [...new Set(details)].filter((d) => {
    if (!d.trim()) return false;
    const dLower = d.toLowerCase().trim();
    if (degree && degree.toLowerCase() === dLower) return false;
    if (institution && institution.toLowerCase() === dLower) return false;
    return true;
  });

  return { degree, institution, dateRange, gpa, honors: filteredHonors, details: uniqueDetails, bullets };
}

/**
 * Detect if a text block contains an embedded second education entry
 * (e.g., "GPA 4.85/5.00 B.Sc. (Hons), Chemistry NUS, 2017, GPA 4.46/5.00")
 * Returns [beforeText, embeddedEntryText] or null if no split needed.
 */
function splitEmbeddedDegree(text, primaryDegree) {
  if (!text || !primaryDegree) return null;
  // Look for a second degree pattern that isn't the primary one
  const degreePatterns = /\b(B\.?Sc|M\.?Sc|B\.?Eng|M\.?Eng|B\.?A|M\.?A|Bachelor|Master|Ph\.?D|Doctorate|Diploma|MBA|Certificate)\b/gi;
  let match;
  let foundFirst = false;
  while ((match = degreePatterns.exec(text)) !== null) {
    // Skip if this matches the primary degree (already captured)
    if (!foundFirst) { foundFirst = true; continue; }
    const splitIdx = match.index;
    const before = text.slice(0, splitIdx).replace(/[·|\s,]+$/, "").trim();
    const after = text.slice(splitIdx).trim();
    if (after.length > 10) return [before, after];
  }
  return null;
}

export function groupEducationSections(sections) {
  const result = [];
  let i = 0;

  while (i < sections.length) {
    const section = sections[i];

    // Pass through non-education or structural items
    if (section.sectionKey !== "education" || section.type === "heading" || section.type === "spacer") {
      result.push(section);
      i += 1;
      continue;
    }

    // Collect consecutive education content into one entry
    const entryItems = [section];
    const allLineIndices = [...(section.lineIndices || [section.lineIndex])];
    const allKeywords = [...(section.keywordMatches || [])];

    let j = i + 1;
    while (j < sections.length) {
      const next = sections[j];
      if (next.type === "heading" || next.sectionKey !== "education") break;
      if (next.type === "spacer") { j += 1; continue; }
      // New entry boundary
      if (entryItems.length > 0 && isEducationEntryStart(next)) break;
      entryItems.push(next);
      allLineIndices.push(...(next.lineIndices || [next.lineIndex]));
      if (next.keywordMatches?.length) allKeywords.push(...next.keywordMatches);
      j += 1;
    }

    const fields = extractEducationFields(entryItems);
    // Skip empty entries with no meaningful content
    if (!fields.degree && !fields.institution && fields.bullets.length === 0 && fields.details.length === 0) {
      entryItems.forEach((item) => result.push(item));
      i = j;
      continue;
    }

    // Check if details contain an embedded second degree (e.g., B.Sc. after M.Sc. GPA)
    let embeddedEntry = null;
    for (let di = 0; di < fields.details.length; di++) {
      const split = splitEmbeddedDegree(fields.details[di], fields.degree);
      if (split) {
        const [beforeText, afterText] = split;
        // Keep the before part as a detail of the first entry
        fields.details[di] = beforeText;
        if (!beforeText) fields.details.splice(di, 1);
        // Parse the embedded second entry
        const secondFields = extractEducationFields([{ type: "paragraph", text: afterText }]);
        if (secondFields.degree || secondFields.institution) {
          embeddedEntry = secondFields;
        }
        break;
      }
    }

    result.push({
      id: `edu-entry-${section.lineIndex}`,
      type: "education_entry",
      sectionKey: "education",
      lineIndex: section.lineIndex,
      lineIndices: [...new Set(allLineIndices)],
      raw: entryItems.map((item) => item.raw).join("\n"),
      text: entryItems.map((item) => item.text).filter(Boolean).join(" | "),
      keywordMatches: [...new Set(allKeywords)],
      fields,
      items: entryItems,
    });

    // Add the embedded second education entry if found
    if (embeddedEntry) {
      result.push({
        id: `edu-entry-${section.lineIndex}-b`,
        type: "education_entry",
        sectionKey: "education",
        lineIndex: section.lineIndex,
        lineIndices: [...new Set(allLineIndices)],
        raw: "",
        text: [embeddedEntry.degree, embeddedEntry.institution].filter(Boolean).join(" | "),
        keywordMatches: [],
        fields: embeddedEntry,
        items: [],
      });
    }

    i = j;
  }

  return result;
}

export function isLikelySummaryLeadParagraph(value) {
  const trimmed = stripResumeMarkdown(value);
  if (!trimmed) return false;
  if (trimmed.includes("|") || hasDateHint(trimmed) || looksLikeEducationText(trimmed) || looksLikeCertificationText(trimmed)) return false;

  const words = trimmed.split(/\s+/).filter(Boolean);
  if (words.length < 5 || words.length > 28) return false;

  const isAllCapsLine = trimmed === trimmed.toUpperCase() && /[A-Z]/.test(trimmed);
  const hasRoleCue = /\b(?:manager|leader|leadership|experience|operations|engineering|transformation|program|product|strategy|specializ(?:e|ing)|delivery|initiatives)\b/i.test(trimmed);
  return isAllCapsLine || hasRoleCue;
}

export function isShoutySummaryParagraph(value, sectionKey = "") {
  const trimmed = stripResumeMarkdown(value);
  if (sectionKey !== "summary" || !trimmed) return false;
  const lettersOnly = trimmed.replace(/[^A-Za-z]/g, "");
  const words = trimmed.split(/\s+/).filter(Boolean);
  return Boolean(lettersOnly)
    && trimmed === trimmed.toUpperCase()
    && words.length >= 12;
}

export function isMostlyAllCapsContent(value) {
  const trimmed = stripResumeMarkdown(value);
  const lettersOnly = trimmed.replace(/[^A-Za-z]/g, "");
  if (lettersOnly.length < 8) return false;
  return trimmed === trimmed.toUpperCase();
}

export function normalizeDisplayToken(core, { mode = "sentence", sentenceStart = false, titleStart = false } = {}) {
  const sanitizedCore = core.replace(/[.,;:!?]+$/g, "");
  const normalizedCore = sanitizedCore.toLowerCase();

  if (
    !sanitizedCore
    || RESUME_DISPLAY_ACRONYMS.has(core)
    || RESUME_DISPLAY_ACRONYMS.has(sanitizedCore)
    || /\d/.test(sanitizedCore)
    || sanitizedCore.includes("/")
  ) {
    return core;
  }

  if (mode === "title") {
    if (!titleStart && RESUME_SMALL_TITLE_WORDS.has(normalizedCore)) {
      return normalizedCore;
    }
    return normalizedCore.charAt(0).toUpperCase() + normalizedCore.slice(1);
  }

  if (sentenceStart) {
    return normalizedCore.charAt(0).toUpperCase() + normalizedCore.slice(1);
  }
  return normalizedCore;
}

export function toSentenceCaseDisplayText(value) {
  const tokens = String(value || "").split(/(\s+)/);
  let sentenceStart = true;

  return tokens.map((token) => {
    if (!token || /^\s+$/.test(token)) return token;

    const match = token.match(/^([^A-Za-z0-9]*)([A-Za-z0-9/&+-]+)([^A-Za-z0-9]*)$/);
    if (!match) {
      if (/[.!?]$/.test(token)) sentenceStart = true;
      return token;
    }

    const [, prefix, core, suffix] = match;
    const renderedCore = normalizeDisplayToken(core, { mode: "sentence", sentenceStart });

    sentenceStart = /[.!?]$/.test(`${core}${suffix}`);
    return `${prefix}${renderedCore}${suffix}`;
  }).join("");
}

export function toTitleCaseDisplayText(value) {
  const tokens = String(value || "").split(/(\s+)/);
  let wordIndex = 0;

  return tokens.map((token) => {
    if (!token || /^\s+$/.test(token)) return token;

    const match = token.match(/^([^A-Za-z0-9]*)([A-Za-z0-9/&+-]+)([^A-Za-z0-9]*)$/);
    if (!match) return token;

    const [, prefix, core, suffix] = match;
    const renderedCore = normalizeDisplayToken(core, {
      mode: "title",
      titleStart: wordIndex === 0,
    });
    wordIndex += 1;
    return `${prefix}${renderedCore}${suffix}`;
  }).join("");
}

export function getDisplayParagraphText(section) {
  if (!section?.text) return "";
  if (isShoutySummaryParagraph(section.text, section.sectionKey)) {
    return toSentenceCaseDisplayText(section.text);
  }
  if (
    isMostlyAllCapsContent(section.text)
    && (
      section.text.includes("|")
      || section.sectionKey === "skills"
      || section.sectionKey === "certifications"
      || section.sectionKey === "additional_information"
      || looksLikeCertificationText(section.text)
    )
  ) {
    return toTitleCaseDisplayText(section.text);
  }
  return section.text;
}

export function getDisplayInlineSegmentText(value) {
  if (isMostlyAllCapsContent(value)) {
    return toTitleCaseDisplayText(value);
  }
  return value;
}

export function getDisplaySubheadingText(value, sectionKey = "", variant = "") {
  if (!value) return "";
  let displayValue = value;
  if (isMostlyAllCapsContent(value) && (sectionKey === "certifications" || sectionKey === "skills" || variant.startsWith("education"))) {
    displayValue = toTitleCaseDisplayText(value);
  }
  if (looksLikeDateOnlyText(displayValue)) {
    return displayValue.replace(/\s*([–—-])\s*/g, "\u00A0$1\u00A0");
  }
  return displayValue;
}

export function parseSubheadingParts(line, sectionKey = "") {
  const trimmed = stripResumeMarkdown(line);
  if (!trimmed) return null;
  const entrySection = ENTRY_SUBHEADING_SECTIONS.has(sectionKey);
  if (!isStructuredSubheadingSection(sectionKey)) return null;
  if (entrySection && /^[a-z]/.test(trimmed)) return null;

  if (trimmed.includes("|")) {
    const parts = trimmed.split("|").map((part) => part.trim()).filter(Boolean);
    const lastPart = parts[parts.length - 1] || "";
    const hasDateOnRight = hasDateHint(lastPart);
    const datePartIndex = parts.findIndex((part) => looksLikeDateOnlyText(part) || hasDateHint(part));
    const denseSkillList = looksLikeDenseSkillList(parts)
      || ((sectionKey === "skills" || sectionKey === "certifications") && parts.length >= 2 && !hasDateOnRight);

    if (denseSkillList) return null;

    if (sectionKey === "education" && parts.length >= 2) {
      const hasEducationSignal = parts.some((part) => looksLikeEducationText(part) || RESUME_DEGREE_RE.test(part));
      if (!hasDateOnRight && !hasEducationSignal) return null;
      if (parts.length === 2) {
        return {
          left: parts[0],
          right: parts[1],
          variant: DEGREE_START_RE.test(parts[0])
            ? "education_main"
            : (looksLikeEducationDetail(parts[0]) || looksLikeEducationDetail(parts[1]) ? "education_detail" : "education_main"),
        };
      }
      return {
        left: parts[0],
        right: parts.slice(1).join(" | "),
        variant: "education_main",
      };
    }

    if ((entrySection || sectionKey === "certifications") && datePartIndex >= 0) {
      const datePart = parts[datePartIndex];
      const otherParts = parts.filter((_, index) => index !== datePartIndex);
      return {
        left: otherParts[0] || datePart,
        right: buildSubheadingLabel(otherParts.slice(1).join(" | "), datePart),
        variant: "dated",
      };
    }

    if (parts.length === 2 || (entrySection && hasDateOnRight) || (sectionKey === "certifications" && hasDateOnRight)) {
      const right = parts.pop();
      const leftJoined = parts.join(" | ");
      return {
        left: leftJoined,
        right,
        variant: hasDateHint(right) ? "dated" : "company",
      };
    }
  }

  // Try em dash first (prioritize over hyphen to avoid matching "Hons - Distinction" before "— NUS")
  let separatorMatch = trimmed.match(/^(.*?)(?:\s+—\s+)(.*)$/);
  // Fall back to en dash/hyphen (require space on both sides)
  if (!separatorMatch) {
    separatorMatch = trimmed.match(/^(.*?)(?:\s+[–-]\s+)(.*)$/);
  }
  // For education, also handle em dash without preceding space (e.g., "Degree— University")
  if (!separatorMatch && sectionKey === "education") {
    separatorMatch = trimmed.match(/^(.*?)(?:—\s+)(.*)$/);
  }
  if (separatorMatch) {
    const left = separatorMatch[1].trim();
    const right = separatorMatch[2].trim();
    if (sectionKey === "education") {
      return {
        left,
        right,
        variant: DEGREE_START_RE.test(left)
          ? "education_main"
          : (looksLikeEducationDetail(left) || looksLikeEducationDetail(right) ? "education_detail" : "education_main"),
      };
    }
    if (!entrySection && !(sectionKey === "certifications" && hasDateHint(right))) return null;
    return {
      left,
      right,
      variant: hasDateHint(right) || hasDateHint(trimmed) ? "dated" : "company",
    };
  }

  if (entrySection && startsLineWithResumeActionVerb(trimmed) && trimmed.split(/\s+/).filter(Boolean).length > 4) {
    return null;
  }

  // Detect "Title, Department (YYYY-YYYY)" or "Title (YYYY-YYYY)" pattern
  // These are job entry headings with dates in parentheses
  const dateParenMatch = trimmed.match(/^(.+?)\s*\((\d{4})\s*[–—-]\s*(?:\d{4}|[Pp]resent)\)$/);
  if (dateParenMatch) {
    const mainText = dateParenMatch[1].trim();
    const dateText = trimmed.match(/\(.*\)$/)?.[0]?.replace(/[()]/g, "").trim() || "";
    return {
      left: mainText,
      right: dateText,
      variant: "dated",
    };
  }

  // Detect lines with date hints that aren't caught above (e.g., "Company Name, Singapore")
  if (hasDateHint(trimmed) && !trimmed.startsWith("-") && !trimmed.startsWith("•")) {
    const commaIdx = trimmed.lastIndexOf(",");
    if (commaIdx > 0) {
      const left = trimmed.substring(0, commaIdx).trim();
      const right = trimmed.substring(commaIdx + 1).trim();
      if (hasDateHint(right) || hasDateHint(left)) {
        return { left, right, variant: "dated" };
      }
    }
    if (!(entrySection || sectionKey === "education" || sectionKey === "certifications")) return null;
    // No comma but has date - entire line is a heading
    return { left: trimmed, right: "", variant: "dated" };
  }

  // Detect position-like titles in entry sections (no date, no separator)
  // e.g., "Senior Engineer, RegE Process & Equipment Engineer"
  // e.g., "Bio-Lasing R&D (Dr. Derrick Yong)"
  if (entrySection) {
    const words = trimmed.split(/\s+/);
    const wordCount = words.length;
    if (wordCount >= 2 && wordCount <= 12 && (!startsLineWithResumeActionVerb(trimmed) || wordCount <= 8)) {
      const hasComma = trimmed.includes(",");
      const hasParens = /\(.*\)/.test(trimmed);
      if (looksLikeResumeTitleLine(trimmed) || (!startsLineWithResumeActionVerb(trimmed) && hasParens && !/[.!?]$/.test(trimmed))) {
        return { left: trimmed, right: "", variant: "company" };
      }
    }
  }

  // Detect company + location lines: "Company Name, City" or "Company Name, City / Country"
  if (entrySection) {
    const commaIdx = trimmed.indexOf(",");
    if (commaIdx > 0 && commaIdx < trimmed.length - 1) {
      const beforeComma = trimmed.substring(0, commaIdx).trim();
      const afterComma = trimmed.substring(commaIdx + 1).trim();
      const words = trimmed.split(/\s+/);
      // Short line with comma, not a sentence (no period, not starting with action verb)
      if (words.length <= 8 && !trimmed.endsWith(".") && !startsLineWithResumeActionVerb(trimmed)) {
        // Check it looks like a company name (capitalized, contains known location patterns or org words)
        const LOCATION_RE = /\b(?:singapore|japan|taiwan|usa|us|uk|china|india|australia|germany|france|korea|malaysia|indonesia|thailand|vietnam|hong kong|global|regional|asia|apac|emea|americas|boise|hiroshima|taichung|manassas|arizona)\b/i;
        const ORG_RE = /\b(?:technology|technologies|corporation|corp|inc|ltd|pte|limited|group|bank|financial|consulting|services|solutions|systems|networks|semiconductor|manufacturing)\b/i;
        if (LOCATION_RE.test(afterComma) || ORG_RE.test(beforeComma)) {
          return { left: trimmed, right: "", variant: "company" };
        }
      }
    }

    if (looksLikeResumeCompanyLine(trimmed)) {
      return { left: trimmed, right: "", variant: "company" };
    }
  }

  return null;
}

export function analyzeBulletFeedback(text, resumeText = "", sectionKey = "") {
  const trimmed = text.trim();
  const lowered = trimmed.toLowerCase();
  const firstWord = trimmed.split(/\s+/)[0]?.toLowerCase().replace(/[,:;.]$/, "") || "";
  const metricSignals = extractResumeMetricSignals(trimmed);
  const hasMetric = metricSignals.length > 0;
  const weakStart = RESUME_WEAK_STARTS.find((phrase) => lowered.startsWith(phrase));
  const keywordMatches = collectKeywordMatches(trimmed, []);
  const bulletLengthWords = trimmed.split(/\s+/).filter(Boolean).length;
  const bulletLengthChars = trimmed.length;
  const isTooShort = bulletLengthChars < 40 || bulletLengthWords < 7;
  const isTooLong = bulletLengthChars > 210 || bulletLengthWords > 30;
  const hasActionVerb = isResumeActionVerb(firstWord);
  const wordCounts = resumeText ? getWordCounts(resumeText) : {};
  const overusedWords = [...new Set(
    (lowered.match(/[a-z][a-z-]*/g) || []).filter((word) => (
      word.length > 4
      && !RESUME_OVERUSED_IGNORE.has(word)
      && (wordCounts[word] || 0) >= 4
    )),
  )].slice(0, 4);
  const avoidedMatches = RESUME_AVOIDED_PHRASES.filter((phrase) => lowered.includes(phrase));
  const skipAnnotation = sectionKey === "education"
    || sectionKey === "certifications"
    || sectionKey === "skills"
    || sectionKey === "languages"
    || sectionKey === "awards"
    || looksLikeCertificationText(lowered)
    || looksLikeEducationText(lowered);

  return {
    trimmed,
    lowered,
    firstWord,
    hasMetric,
    weakStart,
    keywordMatches,
    metricSignals,
    bulletLengthWords,
    bulletLengthChars,
    isTooShort,
    isTooLong,
    hasActionVerb,
    overusedWords,
    avoidedMatches,
    skipAnnotation,
    actionIssue: Boolean(weakStart || !hasActionVerb),
    specificsIssue: !hasMetric,
    overusedIssue: overusedWords.length > 0 || avoidedMatches.length > 0,
    lengthIssue: isTooShort || isTooLong,
  };
}

export function annotateBullet(text, keywords, resumeText = "", sectionKey = "") {
  const analysis = analyzeBulletFeedback(text, resumeText, sectionKey);
  if (analysis.skipAnnotation) {
    return null;
  }

  const keywordMatches = collectKeywordMatches(analysis.trimmed, keywords);
  const issueIds = [];
  if (analysis.actionIssue) issueIds.push("action_oriented");
  if (analysis.overusedIssue) issueIds.push("overused_avoided");
  if (analysis.lengthIssue) issueIds.push("bullet_length");

  if (analysis.actionIssue || analysis.overusedIssue || analysis.lengthIssue) {
    let message = "Tighten this bullet so the impact is clearer.";
    if (analysis.weakStart) message = `Replace "${analysis.weakStart}" with a stronger verb.`;
    else if (!analysis.hasActionVerb) message = "Start with a stronger action verb so the outcome lands faster.";
    else if (analysis.overusedIssue && analysis.lengthIssue) message = "This bullet is dense and repeats a few broad terms. Trim it and sharpen the language.";
    else if (analysis.overusedIssue) message = "A few repeated or filler terms are diluting the impact.";
    else if (analysis.isTooShort) message = "Add more outcome detail so this bullet feels complete.";
    else if (analysis.isTooLong) message = "Split or tighten this bullet so the strongest result lands earlier.";

    const tone = analysis.actionIssue ? "rose" : "amber";
    return {
      tone,
      label: issueIds.length > 1 ? `${issueIds.length} Issues` : "Review Bullet",
      icon: tone === "rose" ? <X size={14} /> : <AlertCircle size={14} />,
      borderClass: tone === "rose" ? "border-rose-300 bg-rose-50/70" : "border-amber-300 bg-amber-50/70",
      pillClass: tone === "rose" ? "bg-rose-100 text-rose-800" : "bg-amber-100 text-amber-800",
      message,
      keywordMatches,
      issueIds,
      issueCount: issueIds.length,
    };
  }

  return {
    tone: "emerald",
    label: analysis.hasMetric ? "Solid Impact" : "Good Start",
    icon: <CheckCircle size={14} />,
    borderClass: "border-emerald-300 bg-emerald-50/70",
    pillClass: "bg-emerald-100 text-emerald-800",
    message: analysis.hasMetric
      ? "This bullet already shows measurable impact."
      : "This bullet starts well. Add a metric if you have one.",
    keywordMatches,
    issueIds: [],
    issueCount: 0,
  };
}

function tryMergeSubheadingWithPrevious(parsed, section) {
  if (!ENTRY_SUBHEADING_SECTIONS.has(section.sectionKey)) return false;

  const recentItems = [...parsed].reverse().filter((item) => item.type !== "spacer").slice(0, 5);
  const previousSubheading = recentItems.find((item) => item.type === "subheading" && item.sectionKey === section.sectionKey);
  if (!previousSubheading) return false;

  const currentText = looksLikeDateOnlyText(section.text)
    ? section.text
    : buildSubheadingLabel(section.left, section.right) || section.text;
  const previousText = buildSubheadingLabel(previousSubheading.left, previousSubheading.right) || previousSubheading.text;

  if (looksLikeDateOnlyText(currentText)) {
    previousSubheading.right = buildSubheadingLabel(previousSubheading.right, currentText);
    previousSubheading.variant = "dated";
    previousSubheading.text = buildSubheadingLabel(previousSubheading.left, previousSubheading.right);
    mergeSectionMetadata(previousSubheading, section);
    return true;
  }

  if (recentItems[0] !== previousSubheading) return false;

  const previousTitleLike = looksLikeResumeTitleLine(previousSubheading.left || previousText);
  const previousCompanyLike = looksLikeResumeCompanyLine(previousText);
  const currentTitleLike = looksLikeResumeTitleLine(section.left || currentText);
  const currentCompanyLike = looksLikeResumeCompanyLine(currentText);

  if (previousCompanyLike && (currentTitleLike || section.variant === "dated")) {
    previousSubheading.left = section.left || currentText;
    previousSubheading.right = buildSubheadingLabel(previousText, section.right || (section.left ? "" : currentText));
    previousSubheading.variant = section.variant === "dated" || hasDateHint(previousSubheading.right) ? "dated" : "company";
    previousSubheading.text = buildSubheadingLabel(previousSubheading.left, previousSubheading.right);
    mergeSectionMetadata(previousSubheading, section);
    return true;
  }

  if (previousTitleLike && (currentCompanyLike || section.variant === "dated")) {
    previousSubheading.left = previousText;
    previousSubheading.right = currentText;
    previousSubheading.variant = section.variant === "dated" || hasDateHint(currentText) ? "dated" : "company";
    previousSubheading.text = buildSubheadingLabel(previousSubheading.left, previousSubheading.right);
    mergeSectionMetadata(previousSubheading, section);
    return true;
  }

  return false;
}

export function isCanonicalResumeDocument(value) {
  return Boolean(
    value
    && typeof value === "object"
    && typeof value.raw_text === "string"
    && Array.isArray(value.blocks)
    && Array.isArray(value.sections)
    && Array.isArray(value.warnings),
  );
}

function canonicalLineLocation(rawText, rawSpan) {
  const start = Array.isArray(rawSpan) && Number.isInteger(rawSpan[0]) ? rawSpan[0] : 0;
  const end = Array.isArray(rawSpan) && Number.isInteger(rawSpan[1]) ? rawSpan[1] : start;
  const lineIndex = (rawText.slice(0, start).match(/\n/g) || []).length;
  const endLineIndex = lineIndex + (rawText.slice(start, end).match(/\n/g) || []).length;
  return {
    lineIndex,
    lineIndices: Array.from(
      { length: endLineIndex - lineIndex + 1 },
      (_, offset) => lineIndex + offset,
    ),
  };
}

export function projectResumeDocument(document, keywords = [], templateOrder = []) {
  if (!isCanonicalResumeDocument(document)) return [];
  const parsed = [];
  const candidateByBlock = new Map(
    (document.heading_candidates || []).map((candidate) => [candidate.block_id, candidate]),
  );

  [...document.blocks]
    .sort((left, right) => left.order - right.order)
    .forEach((block) => {
      const location = canonicalLineLocation(document.raw_text, block.raw_span);
      const base = {
        id: block.id,
        ...location,
        raw: block.source_text,
        text: block.text,
        sectionKey: block.section_key || "",
        keywordMatches: collectKeywordMatches(block.text, keywords),
        canonicalBlock: block,
      };

      if (block.kind === "section_heading") {
        parsed.push({ ...base, type: "heading" });
        return;
      }
      if (block.kind === "candidate_heading") {
        parsed.push({
          ...base,
          type: "candidate_heading",
          headingCandidate: candidateByBlock.get(block.id) || null,
        });
        return;
      }
      if (block.kind === "bullet") {
        parsed.push({
          ...base,
          type: "bullet",
          annotation: annotateBullet(block.text, keywords, document.raw_text, block.section_key || ""),
        });
        return;
      }
      if (block.kind === "entry_heading") {
        const subheading = parseSubheadingParts(block.text, block.section_key || "") || {
          left: block.text,
          right: "",
          variant: "company",
        };
        const section = { ...base, ...subheading, type: "subheading" };
        if (!tryMergeSubheadingWithPrevious(parsed, section)) parsed.push(section);
        return;
      }
      parsed.push({ ...base, type: "paragraph" });
    });

  return reorderParsedSections(parsed, templateOrder);
}

export function extractResumeHeaderMeta(text, document = null) {
  if (isCanonicalResumeDocument(document) && document.raw_text === text) {
    const headerBlocks = [...document.blocks]
      .sort((left, right) => left.order - right.order)
      .filter((block) => !block.section_id && block.kind === "paragraph")
      .slice(0, 4);
    return {
      lines: headerBlocks.map((block) => block.text),
      lineIndices: headerBlocks.flatMap(
        (block) => canonicalLineLocation(document.raw_text, block.raw_span).lineIndices,
      ),
    };
  }
  return { lines: [], lineIndices: [] };
}

export function renderHighlightedText(text, keywords) {
  if (!text) return text || "";
  if (!keywords.length) return text;
  const sorted = [...keywords].sort((a, b) => b.length - a.length);
  const pattern = new RegExp(`(${sorted.map((keyword) => escapeRegExp(keyword)).join("|")})`, "ig");
  const parts = text.split(pattern);
  if (parts.length === 1) return text;

  return parts.map((part, index) => {
    const isMatch = sorted.some((keyword) => keyword.toLowerCase() === part.toLowerCase());
    if (!isMatch) return <span key={`${part}-${index}`}>{part}</span>;
    return (
      <strong key={`${part}-${index}`} className="rounded bg-sky-50 px-0.5 font-semibold text-sky-800">
        {part}
      </strong>
    );
  });
}

export function updateResumeLine(text, section, nextValue) {
  const lines = text.replace(/\r\n?/g, "\n").split("\n");
  const cleanValue = nextValue.replace(/\r/g, "").trim();
  const targetLines = Array.isArray(section.lineIndices) && section.lineIndices.length > 0
    ? section.lineIndices
    : [section.lineIndex];

  if (section.type === "bullet") {
    lines[section.lineIndex] = cleanValue ? `${section.marker || "•"} ${cleanValue}` : "";
    return lines.join("\n");
  }

  lines[targetLines[0]] = cleanValue;
  targetLines.slice(1).forEach((index) => {
    lines[index] = "";
  });
  return lines.join("\n");
}

export function promoteLineToPosition(text, section) {
  const lines = text.replace(/\r\n?/g, "\n").split("\n");
  const lineIdx = section.lineIndex;
  const line = lines[lineIdx];
  if (!line) return text;

  const bMatch = line.match(RESUME_BULLET_RE);
  let cleaned = bMatch ? bMatch[2].trim() : stripResumeMarkdown(line).trim();

  // Convert date in parentheses to pipe format: "Title (2019-2020)" → "Title | 2019-2020"
  const dateInParen = cleaned.match(/\s*\((\d{4}\s*[–—-]\s*(?:\d{4}|[Pp]resent))\)\s*$/);
  if (dateInParen) {
    cleaned = cleaned.replace(/\s*\((\d{4}\s*[–—-]\s*(?:\d{4}|[Pp]resent))\)\s*$/, ` | ${dateInParen[1]}`);
  } else if (!cleaned.includes("|") && !hasDateHint(cleaned)) {
    cleaned = `${cleaned} | Present`;
  }

  lines[lineIdx] = cleaned;
  return lines.join("\n");
}

export function promoteLineToSection(text, section) {
  const lines = text.replace(/\r\n?/g, "\n").split("\n");
  const lineIdx = section.lineIndex;
  const line = lines[lineIdx];
  if (!line) return text;

  const bMatch = line.match(RESUME_BULLET_RE);
  let cleaned = bMatch ? bMatch[2].trim() : stripResumeMarkdown(line).trim();
  cleaned = cleaned.toUpperCase();

  if (lineIdx > 0 && lines[lineIdx - 1].trim()) {
    lines.splice(lineIdx, 1, "", cleaned);
  } else {
    lines[lineIdx] = cleaned;
  }

  return lines.join("\n");
}

export function demoteLineToBullet(text, section) {
  const lines = text.replace(/\r\n?/g, "\n").split("\n");
  const targetLines = Array.isArray(section.lineIndices) && section.lineIndices.length > 0
    ? section.lineIndices
    : [section.lineIndex];

  const combinedText = targetLines
    .filter((idx) => idx >= 0 && idx < lines.length)
    .map((idx) => stripResumeMarkdown(lines[idx] || ""))
    .filter(Boolean)
    .join(" ");

  if (!combinedText.trim() || targetLines[0] < 0 || targetLines[0] >= lines.length) return text;
  lines[targetLines[0]] = `• ${combinedText}`;
  targetLines.slice(1).forEach((idx) => { if (idx >= 0 && idx < lines.length) lines[idx] = ""; });

  return lines.join("\n");
}

export function moveResumeBullet(text, fromLineIndex, toLineIndex) {
  if (fromLineIndex === toLineIndex) return text;
  const lines = text.replace(/\r\n?/g, "\n").split("\n");
  if (fromLineIndex < 0 || fromLineIndex >= lines.length) return text;
  if (toLineIndex < 0 || toLineIndex >= lines.length) return text;
  const [removed] = lines.splice(fromLineIndex, 1);
  const insertAt = toLineIndex > fromLineIndex ? toLineIndex - 1 : toLineIndex;
  lines.splice(insertAt, 0, removed);
  return lines.join("\n");
}

export function moveSectionInText(text, parsedSections, headingId, direction) {
  const lines = text.replace(/\r\n?/g, "\n").split("\n");
  const headings = parsedSections
    .filter((s) => s.type === "heading")
    .sort((a, b) => a.lineIndex - b.lineIndex);
  const currentHeading = headings.find((h) => h.id === headingId);
  if (!currentHeading) return text;

  const currentIdx = headings.indexOf(currentHeading);
  const targetIdx = currentIdx + direction;
  if (targetIdx < 0 || targetIdx >= headings.length) return text;

  const getRange = (idx) => {
    const start = headings[idx].lineIndex;
    const end = idx + 1 < headings.length ? headings[idx + 1].lineIndex : lines.length;
    return [start, end];
  };

  const [aStart, aEnd] = getRange(currentIdx);
  const [bStart, bEnd] = getRange(targetIdx);
  const aBlock = lines.slice(aStart, aEnd);
  const bBlock = lines.slice(bStart, bEnd);

  const [firstStart, , firstBlock, secondStart, secondEnd, secondBlock] = aStart < bStart
    ? [aStart, aEnd, aBlock, bStart, bEnd, bBlock]
    : [bStart, bEnd, bBlock, aStart, aEnd, aBlock];

  return [
    ...lines.slice(0, firstStart),
    ...secondBlock,
    ...firstBlock,
    ...lines.slice(secondEnd),
  ].join("\n");
}

export function insertResumeLineAfter(text, section, nextValue) {
  const lines = text.replace(/\r\n?/g, "\n").split("\n");
  lines.splice(section.lineIndex + 1, 0, nextValue.replace(/\r/g, ""));
  return lines.join("\n");
}

export function removeResumeLine(text, section) {
  const lines = text.replace(/\r\n?/g, "\n").split("\n");
  lines.splice(section.lineIndex, 1);
  return lines.join("\n");
}

export function removeResumeSectionBlock(text, section, parsedSections = []) {
  if (!section) return text;

  // Heading/heading_paragraph: delete entire section to next heading
  if (["heading", "heading_paragraph"].includes(section.type)) {
    const lines = text.replace(/\r\n?/g, "\n").split("\n");
    const startIndex = section.lineIndex;
    const nextHeading = parsedSections.find(
      (candidate) => candidate.lineIndex > startIndex && ["heading", "heading_paragraph"].includes(candidate.type),
    );
    const endIndexExclusive = nextHeading ? nextHeading.lineIndex : lines.length;
    lines.splice(startIndex, Math.max(endIndexExclusive - startIndex, 1));
    return _cleanSplicedLines(lines);
  }

  // Subheading (position/entry): delete entry heading + its bullets until next boundary
  if (section.type === "subheading") {
    const lines = text.replace(/\r\n?/g, "\n").split("\n");
    const indices = section.lineIndices?.length ? section.lineIndices : [section.lineIndex];
    const startIndex = Math.min(...indices);
    const maxIndex = Math.max(...indices);
    const nextBoundary = parsedSections.find(
      (candidate) => candidate.lineIndex > maxIndex
        && ["heading", "heading_paragraph", "subheading", "education_entry"].includes(candidate.type),
    );
    const endIndexExclusive = nextBoundary ? nextBoundary.lineIndex : lines.length;
    lines.splice(startIndex, Math.max(endIndexExclusive - startIndex, 1));
    return _cleanSplicedLines(lines);
  }

  // Education entry: delete all lines belonging to the entry
  if (section.type === "education_entry" && section.lineIndices?.length > 1) {
    const lines = text.replace(/\r\n?/g, "\n").split("\n");
    const sorted = [...section.lineIndices].sort((a, b) => b - a);
    for (const idx of sorted) {
      if (idx >= 0 && idx < lines.length) lines.splice(idx, 1);
    }
    return _cleanSplicedLines(lines);
  }

  return removeResumeLine(text, section);
}

function _cleanSplicedLines(lines) {
  const cleanedLines = [];
  lines.forEach((line) => {
    if (!stripResumeMarkdown(line) && !cleanedLines[cleanedLines.length - 1]?.trim()) {
      return;
    }
    cleanedLines.push(line);
  });
  return cleanedLines.join("\n").replace(/\n{3,}/g, "\n\n").trim();
}

export function getDownloadFilename(response, fallbackName) {
  const contentDisposition = response.headers.get("Content-Disposition") || "";
  const match = contentDisposition.match(/filename="?([^"]+)"?/i);
  return match?.[1] || fallbackName;
}

export function getWordCounts(text) {
  const counts = {};
  (text.toLowerCase().match(/[a-z][a-z-]*/g) || []).forEach((word) => {
    counts[word] = (counts[word] || 0) + 1;
  });
  return counts;
}

export function normalizeReviewSuggestion(item, index) {
  if (!item || typeof item !== "object" || typeof item.original !== "string") return null;
  const status = item.status === "keep" ? "keep" : item.status === "improve" ? "improve" : "";
  if (!status) return null;

  return {
    id: `review-${index}-${item.original.slice(0, 24)}`,
    original: item.original.trim(),
    status,
    issue: typeof item.issue === "string" ? item.issue.trim() : "",
    suggested: typeof item.suggested === "string" ? item.suggested.trim() : "",
    reason: typeof item.reason === "string" ? item.reason.trim() : "",
  };
}

export function summarizeTailoringChanges(changes = []) {
  const labels = {
    ai_phrase_cleanup: "phrase cleanup",
    bullet_rewrite: "bullet rewrite",
    verb_dedup: "section polish",
    summary_rewrite: "summary rewrite",
  };

  return changes.reduce((summary, change) => {
    const key = labels[change?.type] || "other";
    summary[key] = (summary[key] || 0) + 1;
    return summary;
  }, {});
}

export function getAtsGapKey(gap) {
  return [
    gap?.skill || "",
    gap?.suggested_section || "",
    gap?.required ? "required" : "preferred",
    gap?.action || "",
  ].join("::");
}

export function getBulletFeedbackTabs(section, resumeText) {
  if (!section?.text) return [];

  const analysis = analyzeBulletFeedback(section.text, resumeText, section.sectionKey);
  if (analysis.skipAnnotation) return [];

  const text = analysis.trimmed;
  const metricMatches = analysis.metricSignals || [];
  const lengthGood = !analysis.lengthIssue;

  return [
    {
      id: "action_oriented",
      title: "Action Oriented",
      tone: analysis.actionIssue ? "rose" : "emerald",
      status: analysis.actionIssue ? "issue" : "good",
      summary: !analysis.actionIssue
        ? `This bullet already opens with "${text.split(/\s+/)[0]}," which gives it momentum.`
        : "This bullet would read stronger if it opened with a clearer action verb.",
      chips: !analysis.actionIssue
        ? [text.split(/\s+/)[0]]
        : BULLET_ACTION_SUGGESTIONS,
      tip: !analysis.actionIssue
        ? "Keep the opening verb, then tighten the rest around the outcome."
        : "Try replacing the opening with a sharper verb that signals what you actually drove or delivered.",
    },
    {
      id: "specifics",
      title: "Specifics",
      tone: metricMatches.length > 0 ? "emerald" : "amber",
      status: metricMatches.length > 0 ? "good" : "issue",
      summary: metricMatches.length > 0
        ? "This bullet already includes measurable scope or outcomes."
        : "Add concrete scope, outcome, or scale so the reader can see the size of the work.",
      chips: metricMatches.length > 0
        ? metricMatches.slice(0, 4)
        : ["team size", "% improvement", "$ impact", "timeline"],
      tip: metricMatches.length > 0
        ? "You can still sharpen the impact by placing the strongest metric earlier in the sentence."
        : "Examples that help: team size, budget, time saved, revenue impact, coverage, quality, or time-to-launch.",
    },
    {
      id: "overused_avoided",
      title: "Overused & Avoided",
      tone: analysis.overusedIssue ? "rose" : "emerald",
      status: analysis.overusedIssue ? "issue" : "good",
      summary: analysis.overusedIssue
        ? "A few repeated or filler terms are diluting the impact of this bullet."
        : "This bullet avoids the most obvious filler phrasing.",
      chips: [...analysis.avoidedMatches, ...analysis.overusedWords].slice(0, 5),
      tip: analysis.overusedIssue
        ? "Swap repeated terms for more specific language, and remove filler phrases unless they add real meaning."
        : "Keep favouring concrete nouns and verbs over generic phrasing.",
    },
    {
      id: "bullet_length",
      title: "Bullet Length",
      tone: lengthGood ? "emerald" : "amber",
      status: lengthGood ? "good" : "issue",
      summary: lengthGood
        ? "This bullet sits in a healthy length range for scanability."
        : analysis.bulletLengthChars < 40
          ? "This bullet is too short to communicate real scope."
          : "This bullet is getting long and may be harder to scan quickly.",
      chips: [`${analysis.bulletLengthWords} words`, `${analysis.bulletLengthChars} chars`],
      tip: lengthGood
        ? "Aim to keep most bullets at roughly one to two lines in the final document."
        : analysis.bulletLengthChars < 40
          ? "Add the outcome, scale, or context so the reader understands why the work mattered."
          : "Split the detail or trim supporting clauses so the strongest result lands earlier.",
    },
  ];
}

export function getBulletRewriteFocus(section, resumeText, activeTabId = "") {
  if (!section?.text) return "";

  const analysis = analyzeBulletFeedback(section.text, resumeText, section.sectionKey);
  const focus = new Set();

  if (analysis.isTooLong || activeTabId === "bullet_length") {
    focus.add("bullet_length");
    focus.add("shorten");
    focus.add("bulletize");
  }
  if (analysis.actionIssue || activeTabId === "action_oriented") {
    focus.add("action_oriented");
  }
  if (analysis.specificsIssue || activeTabId === "specifics") {
    focus.add("specifics");
  }
  if (analysis.overusedIssue || activeTabId === "overused_avoided") {
    focus.add("overused_avoided");
    focus.add("tighten");
  }

  return [...focus].join(",");
}

export function getRewriteButtonLabel(activeBulletTab, selectedBullet) {
  if (!selectedBullet) return "AI Rewrite This Bullet";
  if (activeBulletTab?.id === "bullet_length" && activeBulletTab.status === "issue") {
    return "AI Shorten This Bullet";
  }
  if (activeBulletTab?.id === "overused_avoided" && activeBulletTab.status === "issue") {
    return "AI Tighten This Bullet";
  }
  if (activeBulletTab?.id === "action_oriented" && activeBulletTab.status === "issue") {
    return "AI Strengthen This Bullet";
  }
  if (activeBulletTab?.id === "specifics" && activeBulletTab.status === "issue") {
    return "AI Sharpen This Bullet";
  }
  return "AI Rewrite This Bullet";
}

export function getRewriteCacheKey({
  bullet = "",
  jobTitle = "",
  jobDescription = "",
  usedVerbs = "",
  rewriteFocus = "",
  focusedFeedback = "",
} = {}) {
  return JSON.stringify([bullet, jobTitle, jobDescription, usedVerbs, rewriteFocus, focusedFeedback]);
}

export function isRewriteResultCurrent(result, { bullet = "", jobTitle = "", jobDescription = "" } = {}) {
  return Boolean(
    result
    && result.source_bullet === bullet
    && result.job_title === jobTitle
    && result.job_description === jobDescription
  );
}

export function normalizeRewriteOptionText(value) {
  const cleaned = stripResumeMarkdown(String(value || ""))
    .replace(/^[•\-*o▪●\u2022\u2023\u25E6\u2043\u2219\u25AA\u25AB\u25CF\uF0B7]+\s*/, "")
    .trim();
  if (!cleaned) return "";
  return cleaned.replace(/^([^A-Za-z]*)([a-z])/, (_, prefix, char) => `${prefix}${char.toUpperCase()}`);
}

export function getRewriteFocusIds(rewriteFocus = "") {
  return String(rewriteFocus).split(",").map((item) => item.trim()).filter(Boolean);
}

export function getIssueLabel(issueId = "") {
  if (issueId === "action_oriented") return "action opening";
  if (issueId === "specifics") return "specifics";
  if (issueId === "overused_avoided") return "overused wording";
  if (issueId === "bullet_length") return "bullet length";
  return issueId;
}

export function evaluateRewriteOption(option, section, resumeText, rewriteFocus = "") {
  const normalizedOption = normalizeRewriteOptionText(option);
  const analysis = analyzeBulletFeedback(normalizedOption, resumeText, section?.sectionKey || "");
  const issueIds = [];
  if (analysis.actionIssue) issueIds.push("action_oriented");
  if (analysis.specificsIssue) issueIds.push("specifics");
  if (analysis.overusedIssue) issueIds.push("overused_avoided");
  if (analysis.lengthIssue) issueIds.push("bullet_length");

  const focusIds = getRewriteFocusIds(rewriteFocus);
  const unresolvedFocused = issueIds.filter((issueId) => focusIds.includes(issueId));

  return {
    text: normalizedOption,
    issueIds,
    issueCount: issueIds.length,
    focusIds,
    unresolvedFocused,
    focusMisses: unresolvedFocused.length,
    clearsFocusedIssue: focusIds.length > 0 ? unresolvedFocused.length === 0 : issueIds.length === 0,
  };
}

export function getRewriteOptionMeta(optionIndex, rewriteFocus = "", optionEvaluation = null) {
  const focus = new Set(getRewriteFocusIds(rewriteFocus));
  const focusLabel = focus.has("bullet_length")
    ? "shortening this bullet"
    : focus.has("overused_avoided")
      ? "tightening the wording"
      : focus.has("action_oriented")
        ? "strengthening the action verb"
        : focus.has("specifics")
          ? "adding sharper evidence"
          : "improving this bullet";

  if (optionIndex === 0) {
    const detail = optionEvaluation?.clearsFocusedIssue
      ? `Best fit for ${focusLabel}.`
      : optionEvaluation?.unresolvedFocused?.length
        ? `Closest match, but still needs work on ${optionEvaluation.unresolvedFocused.map(getIssueLabel).join(" and ")}.`
        : `Best fit for ${focusLabel}.`;
    return {
      label: "Option 1",
      detail,
      cta: "Use Option 1",
    };
  }

  if (optionIndex === 1) {
    return {
      label: "Option 2",
      detail: "A different phrasing with the same evidence.",
      cta: "Use Option 2",
    };
  }

  return {
    label: "Option 3",
    detail: "Another viable way to phrase the same point.",
    cta: "Use Option 3",
  };
}

export function rankRewriteOptions(options, section, resumeText, rewriteFocus = "") {
  return [...options]
    .map((option, index) => {
      const evaluation = evaluateRewriteOption(option, section, resumeText, rewriteFocus);
      return {
        text: evaluation.text,
        index,
        issueCount: evaluation.issueCount,
        focusMisses: evaluation.focusMisses,
        clearsFocusedIssue: evaluation.clearsFocusedIssue,
      };
    })
    .sort((left, right) => (
      Number(right.clearsFocusedIssue) - Number(left.clearsFocusedIssue)
      || left.focusMisses - right.focusMisses
      || left.issueCount - right.issueCount
      || left.index - right.index
    ))
    .map((item) => item.text);
}

export function buildFocusedFeedbackContext(activeTab, tabs = []) {
  const usableTabs = Array.isArray(tabs) ? tabs.filter(Boolean) : [];
  if (!usableTabs.length && !activeTab) return "";

  const issueTabs = usableTabs.filter((tab) => tab.status === "issue");
  const primaryTab = activeTab || issueTabs[0] || usableTabs[0] || null;
  const supportingTabs = issueTabs.filter((tab) => tab.id !== primaryTab?.id).slice(0, 2);
  const sections = [];

  if (primaryTab) {
    sections.push(`Primary issue: ${primaryTab.title}. ${primaryTab.summary} Guidance: ${primaryTab.tip}`);
    if (primaryTab.chips?.length) {
      sections.push(`Signals: ${primaryTab.chips.join(", ")}`);
    }
  }

  if (supportingTabs.length) {
    sections.push(`Also watch for: ${supportingTabs.map((tab) => `${tab.title} (${tab.summary})`).join("; ")}`);
  }

  return sections.join("\n");
}
