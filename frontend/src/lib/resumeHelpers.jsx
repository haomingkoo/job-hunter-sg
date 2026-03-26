// Resume helper functions extracted from App.jsx (Phase 3)
// Some functions return JSX, so React is required.

import { Fragment } from "react";
import { CheckCircle, AlertCircle, X } from "lucide-react";
import { escapeRegExp, extractKeywordLabel, collectKeywordMatches } from "./helpers.js";
import {
  RESUME_TEMPLATE_STYLES,
  RESUME_HEADINGS,
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
  RESUME_SECTION_KEY_MAP,
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
      width: "210mm",
      minHeight: "297mm",
      maxWidth: "100%",
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

export function normalizeHeadingLabel(value) {
  return stripResumeMarkdown(value)
    .toLowerCase()
    .replace(/[:*]+$/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

export function splitInlineHeadingContent(value) {
  const cleaned = stripResumeMarkdown(value);
  if (!cleaned) return null;

  const headingCandidates = [...RESUME_HEADINGS].sort((a, b) => b.length - a.length);
  for (const heading of headingCandidates) {
    const pattern = new RegExp(
      `^(${escapeRegExp(heading)})(?:\\s*[:|-]\\s*|\\s*\\|\\s*)(.+)$`,
      "i",
    );
    const match = cleaned.match(pattern);
    if (!match) continue;
    const bodyText = match[2].trim();
    if (!bodyText) continue;
    if (normalizeHeadingLabel(bodyText) === heading) continue;
    return {
      headingText: match[1].trim().replace(/:$/, ""),
      bodyText,
      sectionKey: getResumeSectionKey(match[1]),
    };
  }

  // Fallback: check if line STARTS with a known heading followed by content (no separator)
  // e.g., "KEY SKILLS Program Management • Engineering Strategy • ..."
  for (const heading of headingCandidates) {
    if (cleaned.toLowerCase().startsWith(heading.toLowerCase() + " ")) {
      const bodyText = cleaned.substring(heading.length).trim();
      if (bodyText && bodyText.length > 10) {
        return {
          headingText: cleaned.substring(0, heading.length),
          bodyText,
          sectionKey: getResumeSectionKey(heading),
        };
      }
    }
  }

  return null;
}

export function getResumeSectionKey(value) {
  const normalized = normalizeHeadingLabel(value);
  if (!normalized) return "";

  // Check the shared config map first (single source of truth)
  if (RESUME_SECTION_KEY_MAP[normalized]) return RESUME_SECTION_KEY_MAP[normalized];

  // Fallback: fuzzy heuristic matching for headings not in the map
  if (normalized.includes("academic qualification") || normalized.includes("academic qualifications")) return "education";
  if (
    normalized.includes("summary")
    || normalized.includes("profile")
    || normalized.includes("qualification")
  ) return "summary";
  if (normalized.includes("education")) return "education";
  if (normalized.includes("academic background")) return "education";
  if (normalized.includes("experience")) {
    if (normalized.includes("co-curricular") || normalized.includes("extra-curricular") || normalized.includes("volunteer") || normalized.includes("activities")) {
      return "activities";
    }
    if (normalized.includes("project")) return "projects";
    return "experience";
  }
  if (
    normalized.includes("employment history")
    || normalized.includes("career history")
    || normalized.includes("professional background")
  ) return "experience";
  if (normalized.includes("skill") || normalized.includes("competenc") || normalized.includes("proficienc")) return "skills";
  if (normalized.includes("project")) return "projects";
  if (
    normalized.includes("certification")
    || normalized.includes("license")
    || normalized.includes("upskilling")
  ) return "certifications";
  if (normalized.includes("activity") || normalized.includes("leadership") || normalized.includes("volunteer") || normalized.includes("club")) return "activities";
  if (normalized.includes("additional information")) return "personal";
  if (normalized.includes("language")) return "personal";
  if (normalized === "personal" || normalized.includes("personal information")) return "personal";
  if (normalized.includes("award") || normalized.includes("honor") || normalized.includes("publication")) return "awards";
  return "";
}

export function isAllCapsHeading(line) {
  const trimmed = stripResumeMarkdown(line);
  if (!trimmed || trimmed !== trimmed.toUpperCase() || !/[A-Z]/.test(trimmed)) return false;
  const words = trimmed.split(/\s+/);
  if (words.length > 4) return false;
  if (/^[•\-*]/.test(trimmed)) return false;
  if (/\d/.test(trimmed)) return false;
  if (looksLikeEducationDetail(trimmed)) return false;
  // Removed certification/in-progress filter: ALL-CAPS lines (2-4 words) are section headings,
  // not entry content. Mixed-case entries like "AWS Certified Solutions Architect" are already
  // filtered by the trimmed !== trimmed.toUpperCase() check above.
  if (trimmed.endsWith(".")) return false;
  if (/\(.*\)/.test(trimmed)) return false;
  return true;
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
const STRUCTURED_SUBHEADING_SECTIONS = new Set([...ENTRY_SUBHEADING_SECTIONS, "education", "certifications"]);
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

export function pruneEmptySectionGroups(sections) {
  const pruned = [];

  for (let index = 0; index < sections.length; index += 1) {
    const current = sections[index];

    if (current?.type !== "heading") {
      pruned.push(current);
      continue;
    }

    const groupItems = [current];
    let nextIndex = index + 1;
    let hasRenderableContent = false;

    while (nextIndex < sections.length) {
      const next = sections[nextIndex];
      if (next?.type === "heading" || next?.type === "heading_paragraph") break;
      groupItems.push(next);
      if (next?.type && next.type !== "spacer") {
        hasRenderableContent = true;
      }
      nextIndex += 1;
    }

    if (hasRenderableContent) {
      pruned.push(...groupItems);
    }

    index = nextIndex - 1;
  }

  return pruned;
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

export function isHeadingLine(line) {
  const trimmed = stripResumeMarkdown(line);
  const normalized = normalizeHeadingLabel(trimmed);
  if (!normalized) return false;
  if (RESUME_HEADINGS.has(normalized)) return true;
  if (trimmed.endsWith(":") && RESUME_HEADINGS.has(normalizeHeadingLabel(trimmed.slice(0, -1)))) return true;
  return isAllCapsHeading(trimmed);
}

export function buildEducationPair(lines, lineIndex, currentSectionKey, keywords) {
  if (currentSectionKey !== "education") return null;

  const current = stripResumeMarkdown(lines[lineIndex]);
  const nextRaw = lines[lineIndex + 1];
  const thirdRaw = lines[lineIndex + 2];
  let next = stripResumeMarkdown(nextRaw);
  const third = stripResumeMarkdown(thirdRaw);

  if (!current || !next || isHeadingLine(next) || RESUME_BULLET_RE.test(nextRaw || "")) return null;

  let consumed = 1;
  const canExtendEducationMeta = third
    && !isHeadingLine(third)
    && !RESUME_BULLET_RE.test(thirdRaw || "")
    && !startsNewEducationEntry(third)
    && looksLikeEducationText(next)
    && !hasDateHint(next)
    && (hasDateHint(third) || /singapore|canada|usa|uk|australia|japan|taiwan|university|college|school|institute/i.test(third));

  if (canExtendEducationMeta && next.length + (third?.length || 0) < 80) {
    next = `${next} ${third}`.replace(/\s+/g, " ").trim();
    consumed = 2;
  }

  const currentIsEducationMain = looksLikeEducationMain(current);
  const nextIsEducationMain = looksLikeEducationMain(next);
  if (currentIsEducationMain && nextIsEducationMain) {
    return {
      type: "subheading",
      left: current,
      right: next,
      variant: "education_main",
      text: `${current} | ${next}`,
      keywordMatches: collectKeywordMatches(`${current} ${next}`, keywords),
      lineIndices: Array.from({ length: consumed + 1 }, (_, offset) => lineIndex + offset),
      consumed,
    };
  }

  const currentIsEducationDetail = looksLikeEducationDetail(current);
  const nextIsEducationDetail = looksLikeEducationDetail(next);
  if (currentIsEducationDetail && nextIsEducationDetail) {
    return {
      type: "subheading",
      left: current,
      right: next,
      variant: "education_detail",
      text: `${current} | ${next}`,
      keywordMatches: collectKeywordMatches(`${current} ${next}`, keywords),
      lineIndices: Array.from({ length: consumed + 1 }, (_, offset) => lineIndex + offset),
      consumed,
    };
  }

  return null;
}

// ─── Education Entry Grouping (ported from backend resume_structurer.py) ─────
const EDUCATION_GPA_RE = /(?:gpa|cgpa|cap)\s*[:.]?\s*\d+\.?\d*\s*[/]?\s*\d*\.?\d*/i;
const EDUCATION_HONORS_RE = /\b(?:first class|second class|distinction|honou?rs?|magna|summa|cum laude|dean.?s list|merit|with distinction|valedictorian)\b/i;

function isEducationEntryStart(item) {
  if (item.type === "subheading" && (item.variant === "education_main" || item.variant === "dated")) return true;
  if (item.type === "paragraph" && (startsNewEducationEntry(item.text) || (looksLikeEducationMain(item.text) && !looksLikeEducationDetail(item.text)))) return true;
  // Also detect degree patterns in any text type (handles chat-generated resumes)
  if ((item.type === "paragraph" || item.type === "bullet") && DEGREE_START_RE.test(stripResumeMarkdown(item.text || ""))) return true;
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
        dateRange = meta.secondary || item.right;
      } else {
        const dateMatch = text.match(/(?:19|20)\d{2}\s*[–—-]\s*(?:(?:19|20)\d{2}|[Pp]resent)/);
        if (dateMatch) dateRange = dateMatch[0];
      }
    }

    // Extract GPA
    if (!gpa) {
      const gpaMatch = text.match(EDUCATION_GPA_RE);
      if (gpaMatch) gpa = gpaMatch[0].trim();
    }

    // Extract honors
    const honorsMatch = text.match(EDUCATION_HONORS_RE);
    if (honorsMatch && !honors.includes(honorsMatch[0])) honors.push(honorsMatch[0]);

    // Classify by item type
    if (item.type === "bullet") {
      bullets.push(item);
      continue;
    }

    if (item.type === "subheading") {
      const left = item.left || "";
      const right = item.right || "";

      if (item.variant === "education_main" || item.variant === "dated") {
        if (!degree && (RESUME_DEGREE_RE.test(left) || DEGREE_START_RE.test(left))) {
          degree = left;
        } else if (!institution && looksLikeEducationInstitution(left)) {
          institution = left;
        } else if (!degree) {
          degree = left;
        }
        const rightMeta = splitEducationMeta(right);
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
          const remaining = combined.replace(EDUCATION_GPA_RE, "").replace(/^[,|\s]+|[,|\s]+$/g, "").trim();
          if (remaining) details.push(remaining);
        } else {
          details.push(combined);
        }
      }
      continue;
    }

    // Paragraph
    if (looksLikeEducationDetail(text)) {
      if (!gpa && EDUCATION_GPA_RE.test(text)) {
        gpa = text.match(EDUCATION_GPA_RE)?.[0] || "";
        const remaining = text.replace(EDUCATION_GPA_RE, "").replace(/^[,|\s]+|[,|\s]+$/g, "").trim();
        if (remaining) details.push(remaining);
      } else {
        details.push(text);
      }
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

  return { degree, institution, dateRange, gpa, honors, details, bullets };
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
    // Found a second degree - split here
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

/**
 * When a heading_paragraph (inline heading + body on same line) is followed by
 * a separate paragraph in the same section, the body text shows twice.
 * Demote the heading_paragraph to a plain heading so the standalone paragraph
 * is the single source of truth.
 */
export function dedupeHeadingParagraphs(sections) {
  return sections.map((section, index) => {
    if (section.type !== "heading_paragraph") return section;

    // Look ahead past spacers for a paragraph in the same section
    let nextIndex = index + 1;
    while (nextIndex < sections.length && sections[nextIndex].type === "spacer") nextIndex += 1;
    const next = sections[nextIndex];
    if (next && next.type === "paragraph" && next.sectionKey === section.sectionKey) {
      // Convert to plain heading -- the following paragraph carries the content
      return {
        ...section,
        type: "heading",
        text: section.headingText,
        keywordMatches: [],
      };
    }
    return section;
  });
}

export function mergeParsedParagraphRuns(sections) {
  const merged = [];

  sections.forEach((section) => {
    const previous = merged[merged.length - 1];
    const previousContext = merged.length >= 2 ? merged[merged.length - 2] : null;
    const previousLooksLikeLostBullet = previous?.type === "paragraph"
      ? inferWordBulletLines(previous.text, previous.sectionKey, previousContext)?.length > 0
      : false;
    const currentLooksLikeLostBullet = section?.type === "paragraph"
      ? inferWordBulletLines(section.text, section.sectionKey, previous)?.length > 0
      : false;
    const canMergeParagraph = previous
      && previous.type === "paragraph"
      && section.type === "paragraph"
      && previous.sectionKey === section.sectionKey
      && previous.lineIndices?.length
      && section.lineIndices?.length
      && previous.lineIndices[previous.lineIndices.length - 1] + 1 === section.lineIndices[0]
      && !previousLooksLikeLostBullet
      && !currentLooksLikeLostBullet;

    if (canMergeParagraph) {
      previous.text = `${previous.text} ${section.text}`.trim();
      previous.raw = `${previous.raw}\n${section.raw}`;
      previous.keywordMatches = [...new Set([...(previous.keywordMatches || []), ...(section.keywordMatches || [])])];
      previous.lineIndices = [...previous.lineIndices, ...section.lineIndices];
      return;
    }

    merged.push(section);
  });

  return merged;
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

export function mergeSummaryLeadParagraphs(sections) {
  const merged = [];

  for (let index = 0; index < sections.length; index += 1) {
    const current = sections[index];
    if (!(current?.type === "paragraph" && current.sectionKey === "summary" && isLikelySummaryLeadParagraph(current.text))) {
      merged.push(current);
      continue;
    }

    let nextIndex = index + 1;
    while (sections[nextIndex]?.type === "spacer") nextIndex += 1;
    const next = sections[nextIndex];

    if (next?.type === "paragraph" && next.sectionKey === "summary") {
      merged.push({
        ...current,
        text: `${current.text} ${next.text}`.replace(/\s+/g, " ").trim(),
        raw: `${current.raw}\n${next.raw}`,
        keywordMatches: [...new Set([...(current.keywordMatches || []), ...(next.keywordMatches || [])])],
        lineIndices: [...(current.lineIndices || []), ...(next.lineIndices || [])],
      });
      index = nextIndex;
      continue;
    }

    merged.push(current);
  }

  return merged;
}

export function parseSubheadingParts(line, sectionKey = "") {
  const trimmed = stripResumeMarkdown(line);
  if (!trimmed) return null;
  const entrySection = ENTRY_SUBHEADING_SECTIONS.has(sectionKey);
  if (!isStructuredSubheadingSection(sectionKey)) return null;

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
          variant: looksLikeEducationDetail(parts[0]) || looksLikeEducationDetail(parts[1]) ? "education_detail" : "education_main",
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

  const separatorMatch = trimmed.match(/^(.*?)(?:\s+[–—-]\s+)(.*)$/);
  if (separatorMatch) {
    const left = separatorMatch[1].trim();
    const right = separatorMatch[2].trim();
    if (sectionKey === "education") {
      return {
        left,
        right,
        variant: looksLikeEducationDetail(left) || looksLikeEducationDetail(right) ? "education_detail" : "education_main",
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
      if (looksLikeResumeTitleLine(trimmed) || (!startsLineWithResumeActionVerb(trimmed) && ((hasComma && wordCount <= 10) || hasParens))) {
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

export function splitActionSentenceBullets(text) {
  const parts = stripResumeMarkdown(text).split(/(?<=[.;])\s+(?=[A-Z])/).map((part) => part.trim()).filter(Boolean);
  if (parts.length <= 1) return [stripResumeMarkdown(text)];
  if (!parts.every((part) => startsLineWithResumeActionVerb(part))) return [stripResumeMarkdown(text)];
  return parts.map((part) => part.replace(/[.;]+$/, "").trim()).filter(Boolean);
}

export function looksLikeWordBulletLead(text) {
  const cleaned = stripResumeMarkdown(text);
  if (!cleaned) return false;
  return startsLineWithResumeActionVerb(cleaned)
    || /^(?:co-|re-)?[A-Za-z]+(?:ed|ing)\b/.test(cleaned)
    || /^(?:Built|Led|Drove|Created|Managed|Supported|Partnered|Worked|Chaired|Completed|Currently|Directed|Engineered|Developed|Standardized|Implemented|Optimized|Scaled|Reduced|Improved|Delivered)\b/i.test(cleaned);
}

export function inferWordBulletLines(text, currentSectionKey, previousSection) {
  const cleaned = stripResumeMarkdown(text);
  if (!cleaned) return null;

  const bulletFriendlySection = ["experience", "projects", "activities", "certifications", "awards"].includes(currentSectionKey);
  if (!bulletFriendlySection) return null;

  if (cleaned.includes("|")) return null;
  if (parseSubheadingParts(cleaned, currentSectionKey)) return null;

  const startsWithAction = looksLikeWordBulletLead(cleaned);
  const hasMetric = RESUME_METRIC_RE.test(cleaned);
  const hasResultCue = /(?:improv|reduc|increas|deliver|achiev|saving|revenue|cost|efficien|quality|yield|launched|deployed|implemented)/i.test(cleaned);
  const wordCount = cleaned.split(/\s+/).filter(Boolean).length;
  const previousWasBullet = previousSection?.type === "bullet";
  const looksLikeAchievementSentence = wordCount >= 5
    && (
      startsWithAction
      || (hasMetric && wordCount >= 6)
      || (hasResultCue && wordCount >= 7)
      || (previousWasBullet && wordCount >= 6)
    );
  const previousCreatesBulletContext = previousSection
    && (
      previousSection.type === "subheading"
      || previousSection.type === "heading"
      || previousSection.type === "heading_paragraph"
      || previousWasBullet
      || (previousSection.type === "paragraph" && hasDateHint(previousSection.text))
    );

  if (!looksLikeAchievementSentence) return null;
  if (!previousCreatesBulletContext && !(startsWithAction && (hasMetric || hasResultCue))) return null;

  const inferredBullets = splitActionSentenceBullets(cleaned);
  if (!inferredBullets.length) return null;
  return inferredBullets;
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

function shouldMergeContinuationLine(line, currentSectionKey, previousItem) {
  const trimmed = stripResumeMarkdown(line);
  if (!trimmed || !previousItem || previousItem.sectionKey !== currentSectionKey) return false;
  if (!["bullet", "paragraph"].includes(previousItem.type)) return false;
  if (RESUME_BULLET_RE.test(line) || isHeadingLine(trimmed) || splitInlineHeadingContent(trimmed)) return false;

  const previousText = stripResumeMarkdown(previousItem.text || "");
  const previousEndsSentence = /[.!?]$/.test(previousText);
  const startsLowercase = /^[a-z(]/.test(trimmed);
  const definiteNewEntry = looksLikeDateOnlyText(trimmed)
    || looksLikeResumeTitleLine(trimmed)
    || (currentSectionKey === "education" && (startsNewEducationEntry(trimmed) || RESUME_DEGREE_RE.test(trimmed)));

  if (previousItem.type === "bullet") {
    if (!previousEndsSentence && !definiteNewEntry) return true;
    return startsLowercase && !definiteNewEntry;
  }

  if (startsLowercase && !definiteNewEntry) return true;
  return !previousEndsSentence && !definiteNewEntry && trimmed.length <= 90 && !hasDateHint(trimmed);
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

export function parseResumeToSections(text, keywords, templateOrder = []) {
  const parsed = [];
  let currentSectionKey = "";

  // Pre-process: rejoin lines broken by PDF extraction
  const rawLines = text.replace(/\r\n?/g, "\n").split("\n");
  const lines = [];
  for (let i = 0; i < rawLines.length; i += 1) {
    const current = rawLines[i];
    const trimmed = current.trim();

    // Merge bullet marker on its own line with the next non-empty line
    // e.g., "•\n" + "Business & Economic Analysis: ..." → "• Business & Economic Analysis: ..."
    if (/^[•\-\*▪\u2022\u2023\u25E6\u2043\u2219]\s*$/.test(trimmed)) {
      let nextIdx = i + 1;
      while (nextIdx < rawLines.length && !rawLines[nextIdx].trim()) nextIdx += 1;
      if (nextIdx < rawLines.length) {
        lines.push(`${trimmed} ${rawLines[nextIdx].trim()}`);
        i = nextIdx;
        continue;
      }
    }

    // Merge heading + "&" continuation (e.g., "CERTIFICATIONS\n& Career Development")
    if (trimmed && isHeadingLine(stripResumeMarkdown(trimmed))) {
      const nextLine = (rawLines[i + 1] || "").trim();
      if (nextLine.startsWith("&") || nextLine.startsWith("and ")) {
        lines.push(`${trimmed} ${nextLine}`);
        i += 1;
        continue;
      }
    }

    // Merge pipe-prefixed continuations used in some extracted education/date lines
    if (lines.length > 0 && trimmed.startsWith("|")) {
      lines[lines.length - 1] = `${lines[lines.length - 1]} ${trimmed}`.replace(/\s+/g, " ").trim();
      continue;
    }

    // Merge continuation lines that start with lowercase into previous line
    if (lines.length > 0 && trimmed && /^[a-z]/.test(trimmed)) {
      const prev = lines[lines.length - 1].trim();
      // Only merge if previous line doesn't end with period (completed sentence)
      if (prev && !prev.endsWith(".") && !prev.endsWith(":")) {
        lines[lines.length - 1] = `${lines[lines.length - 1]} ${trimmed}`;
        continue;
      }
    }

    lines.push(current);
  }

  for (let lineIndex = 0; lineIndex < lines.length; lineIndex += 1) {
    const line = lines[lineIndex];
    const normalizedLine = stripResumeMarkdown(line);
    const base = {
      id: `line-${lineIndex}`,
      lineIndex,
      lineIndices: [lineIndex],
      raw: line,
      text: normalizedLine,
    };

    if (!normalizedLine) {
      parsed.push({ ...base, type: "spacer", sectionKey: currentSectionKey });
      continue;
    }

    const inlineHeading = splitInlineHeadingContent(normalizedLine);
    if (inlineHeading) {
      currentSectionKey = inlineHeading.sectionKey || currentSectionKey;
      parsed.push({
        ...base,
        type: "heading_paragraph",
        headingText: inlineHeading.headingText,
        bodyText: inlineHeading.bodyText,
        sectionKey: inlineHeading.sectionKey,
        keywordMatches: collectKeywordMatches(inlineHeading.bodyText, keywords),
      });
      continue;
    }

    if (isHeadingLine(normalizedLine)) {
      currentSectionKey = getResumeSectionKey(normalizedLine) || currentSectionKey;
      parsed.push({
        ...base,
        type: "heading",
        text: normalizedLine.replace(/:$/, ""),
        sectionKey: currentSectionKey,
        keywordMatches: [],
      });
      continue;
    }

    const previousMeaningfulSection = [...parsed].reverse().find((section) => section.type !== "spacer");
    if (!RESUME_BULLET_RE.test(line) && shouldMergeContinuationLine(line, currentSectionKey, previousMeaningfulSection)) {
      previousMeaningfulSection.text = `${previousMeaningfulSection.text} ${normalizedLine}`.replace(/\s+/g, " ").trim();
      previousMeaningfulSection.raw = `${previousMeaningfulSection.raw}\n${line}`;
      previousMeaningfulSection.lineIndices = [...(previousMeaningfulSection.lineIndices || [previousMeaningfulSection.lineIndex]), lineIndex];
      if (previousMeaningfulSection.type === "bullet") {
        previousMeaningfulSection.annotation = annotateBullet(previousMeaningfulSection.text, keywords, text, currentSectionKey);
      } else if (previousMeaningfulSection.type === "paragraph") {
        previousMeaningfulSection.keywordMatches = collectKeywordMatches(previousMeaningfulSection.text, keywords);
      }
      continue;
    }

    const bulletMatch = line.match(RESUME_BULLET_RE);
    // Auto-promote bullets whose content looks like an entry heading (e.g., "• Senior Engineer (2019-2020)")
    let subheadingParts;
    if (bulletMatch) {
      const canPromoteBulletHeading = ENTRY_SUBHEADING_SECTIONS.has(currentSectionKey) || currentSectionKey === "education";
      const bulletText = stripResumeMarkdown(bulletMatch[2]);
      const promoted = canPromoteBulletHeading ? parseSubheadingParts(bulletText, currentSectionKey) : null;
      subheadingParts = promoted && (promoted.variant === "dated" || promoted.variant.startsWith("education")) ? promoted : null;
    } else {
      subheadingParts = parseSubheadingParts(normalizedLine, currentSectionKey);
    }
    if (subheadingParts) {
      const displayText = bulletMatch ? stripResumeMarkdown(bulletMatch[2]) : normalizedLine;
      const subheadingSection = {
        ...base,
        type: "subheading",
        ...subheadingParts,
        text: displayText,
        sectionKey: currentSectionKey,
        keywordMatches: collectKeywordMatches(displayText, keywords),
      };
      if (tryMergeSubheadingWithPrevious(parsed, subheadingSection)) continue;
      parsed.push(subheadingSection);
      continue;
    }

    const educationPair = bulletMatch ? null : buildEducationPair(lines, lineIndex, currentSectionKey, keywords);
    if (educationPair) {
      parsed.push({
        ...base,
        ...educationPair,
        id: `line-${lineIndex}-education-pair`,
        sectionKey: currentSectionKey,
      });
      lineIndex += educationPair.consumed;
      continue;
    }

    if (bulletMatch) {
      const textValue = stripResumeMarkdown(bulletMatch[2]);
      parsed.push({
        ...base,
        type: "bullet",
        marker: bulletMatch[1].trim(),
        text: textValue,
        sectionKey: currentSectionKey,
        annotation: annotateBullet(textValue, keywords, text, currentSectionKey),
      });
      continue;
    }

    const previousParsedSection = [...parsed].reverse().find((section) => section.type !== "spacer");
    const inferredBullets = inferWordBulletLines(normalizedLine, currentSectionKey, previousParsedSection);
    if (inferredBullets) {
      inferredBullets.forEach((bulletText, inferredIndex) => {
        parsed.push({
          ...base,
          id: inferredBullets.length > 1 ? `${base.id}-inferred-${inferredIndex}` : base.id,
          type: "bullet",
          marker: "",
          text: bulletText,
          sectionKey: currentSectionKey,
          annotation: annotateBullet(bulletText, keywords, text, currentSectionKey),
        });
      });
      continue;
    }

    // Continuation line detection: if this line doesn't start with a capital
    // letter after a period (new sentence start), or is short and follows a
    // bullet/paragraph, merge it with the previous item instead of creating
    // a new paragraph. This handles PDF line-wrapping artifacts.
    const prevItem = [...parsed].reverse().find((s) => s.type !== "spacer");
    const isContinuation = shouldMergeContinuationLine(line, currentSectionKey, prevItem);
    if (isContinuation && prevItem) {
      prevItem.text = `${prevItem.text} ${normalizedLine}`.replace(/\s+/g, " ").trim();
      prevItem.raw = `${prevItem.raw}\n${line}`;
      prevItem.lineIndices = [...(prevItem.lineIndices || [prevItem.lineIndex]), lineIndex];
      if (prevItem.type === "bullet") {
        prevItem.annotation = annotateBullet(prevItem.text, keywords, text, currentSectionKey);
      } else if (prevItem.type === "paragraph") {
        prevItem.keywordMatches = collectKeywordMatches(prevItem.text, keywords);
      }
      continue;
    }

    parsed.push({
      ...base,
      type: "paragraph",
      sectionKey: currentSectionKey,
      keywordMatches: collectKeywordMatches(normalizedLine, keywords),
    });
  }

  return pruneEmptySectionGroups(
    reorderParsedSections(mergeSummaryLeadParagraphs(mergeParsedParagraphRuns(dedupeHeadingParagraphs(parsed))), templateOrder),
  );
}

export function extractResumeHeaderMeta(text) {
  const lines = text.replace(/\r\n?/g, "\n").split("\n");
  const headerLines = [];
  const lineIndices = [];
  for (let index = 0; index < lines.length; index += 1) {
    const trimmed = stripResumeMarkdown(lines[index]);
    if (!trimmed) {
      if (headerLines.length > 0) break;
      continue;
    }
    if (isHeadingLine(trimmed)) break;
    if (splitInlineHeadingContent(trimmed)) break;
    if (RESUME_BULLET_RE.test(lines[index])) break;
    headerLines.push(trimmed);
    lineIndices.push(index);
    if (headerLines.length >= 4) break;
  }
  return { lines: headerLines, lineIndices };
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

// ─── Resume Line Editing ───────────────────────────────────────────────────
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
  const headings = parsedSections.filter((s) => s.type === "heading");
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

export function getTailorChangeKey(change, index = 0) {
  if (!change) return `change-${index}`;
  if (change.type === "summary_rewrite") return "summary";
  return change.bullet_id || `${change.type || "change"}-${index}`;
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
        : "Keep favoring concrete nouns and verbs over generic phrasing.",
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
      label: optionEvaluation?.clearsFocusedIssue ? "Recommended Rewrite" : "Closest Rewrite",
      detail,
      cta: optionEvaluation?.clearsFocusedIssue ? "Use Recommended Rewrite" : "Use Closest Rewrite",
    };
  }

  if (optionIndex === 1) {
    return {
      label: focus.has("bullet_length") || focus.has("overused_avoided") ? "More Concise Rewrite" : "Alternative Rewrite",
      detail: focus.has("bullet_length") || focus.has("overused_avoided")
        ? "Leans shorter and faster to scan."
        : "A different phrasing with the same evidence.",
      cta: focus.has("bullet_length") || focus.has("overused_avoided") ? "Use Concise Rewrite" : "Use Alternative Rewrite",
    };
  }

  return {
    label: focus.has("action_oriented") || focus.has("specifics") ? "Stronger Rewrite" : "Alternative Rewrite",
    detail: focus.has("action_oriented") || focus.has("specifics")
      ? "Pushes harder on impact, verbs, or evidence."
      : "Another viable way to phrase the same point.",
    cta: focus.has("action_oriented") || focus.has("specifics") ? "Use Stronger Rewrite" : "Use Alternative Rewrite",
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
