export const todayStr = () => new Date().toISOString().split("T")[0];
export const daysBetween = (a, b) => (a && b) ? Math.round((new Date(b) - new Date(a)) / 86400000) : 0;

export function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

export function titleCase(value) {
  return value
    .replace(/_/g, " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

export function extractKeywordLabel(item) {
  if (typeof item === "string") return item.trim();
  if (item && typeof item.skill === "string") return item.skill.trim();
  return "";
}

export function collectKeywordMatches(text, keywords) {
  const lower = text.toLowerCase();
  return keywords.filter((keyword) => keyword && lower.includes(keyword.toLowerCase()));
}

export function getScoreTheme(score) {
  if (score >= 80) {
    return {
      text: "text-emerald-700",
      bar: "bg-emerald-500",
      panel: "border-emerald-200 bg-emerald-50",
      pill: "bg-emerald-100 text-emerald-800",
    };
  }
  if (score >= 50) {
    return {
      text: "text-amber-700",
      bar: "bg-amber-500",
      panel: "border-amber-200 bg-amber-50",
      pill: "bg-amber-100 text-amber-800",
    };
  }
  return {
    text: "text-rose-700",
    bar: "bg-rose-500",
    panel: "border-rose-200 bg-rose-50",
    pill: "bg-rose-100 text-rose-800",
  };
}
