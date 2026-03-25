import { extractKeywordLabel } from "./helpers.js";

export const JOB_STUDY_AREA_TAGS = new Set([
  "computer science",
  "engineering",
  "mathematics",
  "medical study",
  "statistics",
]);

export const JOB_STUDY_AREA_CONTEXT_RE = /(areas?\s+of\s+study|field[s]?\s+of\s+study|degree(?:\s+or)?\s+above|bachelor|master|phd|major(?:ing)?\s+in|equivalent work experience|disciplines?)/i;
export const ALIGNMENT_TERM_BLACKLIST = new Set([
  "expects",
  "expects:",
  "required",
  "requirement",
  "requirements",
  "responsibility",
  "responsibilities",
  "common direction",
  "understand",
  "understanding",
  "deliverables",
  "programs",
  "business goals",
]);

export function getJobSkillContext(description = "", skill = "") {
  const text = String(description || "");
  const phrase = String(skill || "").trim();
  if (!text || !phrase) return "";
  const lowerText = text.toLowerCase();
  const lowerPhrase = phrase.toLowerCase();
  const index = lowerText.indexOf(lowerPhrase);
  if (index === -1) return "";
  const start = Math.max(0, index - 100);
  const end = Math.min(text.length, index + phrase.length + 100);
  return text.slice(start, end);
}

export function buildJobSkillDisplay(skills = [], description = "") {
  const uniqueSkills = [...new Set((Array.isArray(skills) ? skills : []).map((skill) => String(skill || "").trim()).filter(Boolean))];
  const visibleSkills = [];
  const hiddenStudyAreas = [];

  uniqueSkills.forEach((skill) => {
    const normalized = skill.toLowerCase();
    const context = getJobSkillContext(description, skill);
    const looksLikeStudyArea = JOB_STUDY_AREA_TAGS.has(normalized)
      || normalized.endsWith(" study")
      || JOB_STUDY_AREA_CONTEXT_RE.test(context);

    if (looksLikeStudyArea) hiddenStudyAreas.push(skill);
    else visibleSkills.push(skill);
  });

  return {
    sourceTagCount: uniqueSkills.length,
    visibleSkills,
    hiddenStudyAreas,
  };
}

export function normalizeJobTermLabels(items = []) {
  return [...new Set(
    (Array.isArray(items) ? items : [])
      .map((item) => {
        if (typeof item === "string") return item.trim();
        if (item && typeof item === "object") return String(item.skill || "").trim();
        return "";
      })
      .filter(Boolean),
  )];
}

export function cleanAlignmentTerms(items = [], description = "") {
  const cleaned = [];
  const seen = new Set();

  (Array.isArray(items) ? items : []).forEach((item) => {
    const rawLabel = extractKeywordLabel(item)
      .replace(/^[\s:;,.|-]+|[\s:;,.|-]+$/g, "")
      .replace(/\s+/g, " ")
      .trim();
    if (!rawLabel || rawLabel.length < 2 || !/[a-z]/i.test(rawLabel)) return;

    const normalized = rawLabel.toLowerCase();
    if (ALIGNMENT_TERM_BLACKLIST.has(normalized)) return;

    const context = item?.jd_context || item?.resume_context || getJobSkillContext(description, rawLabel);
    const looksLikeStudyArea = JOB_STUDY_AREA_TAGS.has(normalized)
      || normalized.endsWith(" study")
      || JOB_STUDY_AREA_CONTEXT_RE.test(context);
    if (looksLikeStudyArea) return;

    if (seen.has(normalized)) return;
    seen.add(normalized);
    cleaned.push({
      skill: rawLabel,
      jd_context: item?.jd_context || "",
      resume_context: item?.resume_context || "",
    });
  });

  return cleaned;
}
