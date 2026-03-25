import { STATUS_CONFIG } from "../lib/constants.js";

export default function StatusBadge({ status }) {
  const c = STATUS_CONFIG[status] || STATUS_CONFIG.applied;
  const Icon = c.icon;
  return (
    <span className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium ${c.color}`}>
      <Icon size={12} />{c.label}
    </span>
  );
}
