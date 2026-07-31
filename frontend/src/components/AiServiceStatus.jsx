import { useEffect, useState } from "react";

import { apiFetch } from "../lib/api.js";

/**
 * Whether the model service is answering, shown where a long run starts.
 *
 * Reads /api/ai/status, which reports readiness and queue pressure only. It
 * carries no key count, model name, endpoint or vendor, so putting it in front
 * of a candidate adds no surface an attacker could use.
 */
const POLL_MS = 60000;

const TONE = {
  ready: { dot: "bg-emerald-500", text: "text-[#4A6785]" },
  busy: { dot: "bg-amber-500", text: "text-amber-800" },
  down: { dot: "bg-rose-500", text: "text-rose-800" },
};

export default function AiServiceStatus() {
  const [status, setStatus] = useState(null);

  useEffect(() => {
    let cancelled = false;
    let timer = null;

    const read = async () => {
      try {
        const response = await apiFetch("/api/ai/status");
        const next = await response.json();
        if (!cancelled) setStatus(next);
      } catch {
        // A failed status read is itself a signal the service is unreachable.
        if (!cancelled) setStatus({ status: "down", message: "Cannot reach the AI service right now." });
      }
    };

    read();
    timer = setInterval(read, POLL_MS);
    return () => { cancelled = true; clearInterval(timer); };
  }, []);

  // Silent while healthy: a permanent green dot is noise, and the point is to
  // explain a slow or failed run, not to decorate a working one.
  if (!status || status.status === "ready") return null;

  const tone = TONE[status.status] || TONE.busy;
  return (
    <p role="status" className={`mt-2 flex items-center gap-2 text-xs ${tone.text}`}>
      <span aria-hidden="true" className={`h-1.5 w-1.5 shrink-0 rounded-full ${tone.dot}`} />
      {status.message}
    </p>
  );
}
