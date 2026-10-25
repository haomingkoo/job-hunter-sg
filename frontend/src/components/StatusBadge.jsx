import { STATUS_CONFIG } from "../lib/constants.js";

// Status colours are reserved for outcomes: green for an offer, red for a rejection.
const STATUS_TONE = {
  offer: "text-[#166534]",
  accepted: "text-[#166534]",
  rejected: "text-[#b42318]",
};

export default function StatusBadge({ status }) {
  const c = STATUS_CONFIG[status] || STATUS_CONFIG.applied;
  return (
    <span className={`text-sm font-medium ${STATUS_TONE[status] || "text-ink"}`}>{c.label}</span>
  );
}
