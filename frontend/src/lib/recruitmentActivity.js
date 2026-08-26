export const ACTIVITY_HISTORY_LIMIT = 200;

export function normalizeActivityEvents(events) {
  const bySequence = new Map();
  for (const event of events || []) {
    const sequence = Number(event?.sequence);
    if (!Number.isFinite(sequence)) continue;
    bySequence.set(sequence, event);
  }
  return [...bySequence.values()].sort(
    (left, right) => Number(left.sequence) - Number(right.sequence),
  ).slice(-ACTIVITY_HISTORY_LIMIT);
}


export function activityDetail(event) {
  const detail = event?.detail || {};
  if (detail.tool_name) return detail;

  // Compatibility for persisted events written before tool_name became the
  // structured display contract. New events never depend on summary wording.
  const prefix = `${event?.team_member || ""} called `;
  const summary = String(event?.summary || "");
  if (!summary.startsWith(prefix)) return detail;
  const legacyTool = summary.slice(prefix.length);
  const toolName = legacyTool.endsWith(".") ? legacyTool.slice(0, -1) : legacyTool;
  return toolName ? { ...detail, tool_name: toolName, stage: "call" } : detail;
}
