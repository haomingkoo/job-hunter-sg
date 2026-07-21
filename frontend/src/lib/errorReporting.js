import { API_BASE } from "./api.js";

const MAX_REPORTS_PER_PAGE_LOAD = 10;
let reportCount = 0;

function report(message, stack) {
  if (reportCount >= MAX_REPORTS_PER_PAGE_LOAD) return;
  reportCount += 1;
  const body = JSON.stringify({
    message: String(message || "Unknown error").slice(0, 2000),
    stack: String(stack || "").slice(0, 4000),
    url: window.location.href.slice(0, 500),
    user_agent: navigator.userAgent.slice(0, 300),
  });
  fetch(`${API_BASE}/api/client-error`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body,
    keepalive: true,
  }).catch(() => {
    // Reporting a reporting failure would risk a loop; drop it silently.
  });
}

export function installGlobalErrorReporting() {
  window.addEventListener("error", (event) => {
    report(event.message, event.error?.stack);
  });
  window.addEventListener("unhandledrejection", (event) => {
    const reason = event.reason;
    report(reason?.message || String(reason), reason?.stack);
  });
}
