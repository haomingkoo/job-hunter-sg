export const API_BASE = import.meta.env.VITE_API_URL || "";
export const AUTH_EXPIRED_EVENT = "jobhunter:auth-expired";
export const AUTH_SYNC_KEY = "jobhunter:auth-change";
const RESUME_DRAFT_OWNER_KEY = "jh_resume_owner";

export function broadcastAuthChange(kind) {
  try {
    const nonce = globalThis.crypto?.randomUUID?.() || `${Date.now()}:${Math.random()}`;
    localStorage.setItem(AUTH_SYNC_KEY, `${kind}:${nonce}`);
  } catch {
    // A storage event is a best-effort safety net for other tabs.
  }
}

export function clearResumeDraftStorage() {
  try {
    sessionStorage.removeItem("jh_resume_profile");
    sessionStorage.removeItem("jh_resume_text");
    sessionStorage.removeItem("jh_resume_template");
    sessionStorage.removeItem("jh_wizard_step");
    sessionStorage.removeItem("jh_resume_agent_session");
    sessionStorage.removeItem(RESUME_DRAFT_OWNER_KEY);
  } catch {
    // ignore storage errors
  }
}

export function bindResumeDraftStorageToUser(userId) {
  try {
    const currentOwner = sessionStorage.getItem(RESUME_DRAFT_OWNER_KEY);
    if (userId == null) {
      if (currentOwner) clearResumeDraftStorage();
      return;
    }

    const nextOwner = String(userId);
    if (currentOwner && currentOwner !== nextOwner) clearResumeDraftStorage();
    sessionStorage.setItem(RESUME_DRAFT_OWNER_KEY, nextOwner);
  } catch {
    // ignore storage errors
  }
}

async function readApiError(resp) {
  const raw = await resp.text();
  const text = raw.trim();
  const contentType = resp.headers.get("content-type") || "";
  let payload = null;
  if (contentType.includes("application/json") && text) {
    try {
      payload = JSON.parse(text);
    } catch {
      // fall through to status and plain-text handling
    }
  }

  if (resp.status === 524) {
    return new Error("The server took too long to build this result. Please try again in a minute.");
  }
  if ([502, 503, 504].includes(resp.status)) {
    const detail = payload?.detail;
    if (
      detail
      && typeof detail === "object"
      && typeof detail.code === "string"
      && typeof detail.message === "string"
      && detail.message.trim()
    ) {
      const error = new Error(detail.message.trim());
      error.detail = detail;
      return error;
    }
    return new Error("The server is temporarily unavailable. Please try again shortly.");
  }

  if (payload) {
    const detail = payload.detail || payload.message || payload.error;
    if (typeof detail === "string" && detail.trim()) return new Error(detail.trim());
    if (detail && typeof detail === "object") {
      const error = new Error(detail.message || `Request failed (${resp.status})`);
      error.detail = detail;
      return error;
    }
  }

  if (/^<!doctype html/i.test(text) || /<html[\s>]/i.test(text)) {
    return new Error(`Request failed (${resp.status}). The server returned an HTML error page.`);
  }

  return new Error(text ? `${resp.status}: ${text.slice(0, 300)}` : `Request failed (${resp.status})`);
}

export async function apiFetch(path, options = {}) {
  const { timeoutMs, headers: optionHeaders, ...fetchOptions } = options;
  const token = localStorage.getItem("token");
  const headers = { ...optionHeaders };
  if (typeof FormData === "undefined" || !(fetchOptions.body instanceof FormData)) {
    headers["Content-Type"] ||= "application/json";
  }
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const controller = timeoutMs ? new AbortController() : null;
  const timeoutId = controller
    ? window.setTimeout(() => controller.abort(), timeoutMs)
    : null;

  let resp;
  try {
    resp = await fetch(`${API_BASE}${path}`, {
      credentials: "include",
      ...fetchOptions,
      headers,
      signal: controller?.signal || fetchOptions.signal,
    });
  } catch (err) {
    if (err?.name === "AbortError") {
      throw new Error("The request timed out. Please try again shortly.");
    }
    if (err instanceof TypeError || err?.message === "Failed to fetch") {
      throw new Error("Could not reach the backend. Make sure the backend server is running, then try again.");
    }
    throw err;
  } finally {
    if (timeoutId) window.clearTimeout(timeoutId);
  }

  if (resp.status === 401) {
    if (!token) {
      window.dispatchEvent(new CustomEvent(AUTH_EXPIRED_EVENT, {
        detail: { reason: "required" },
      }));
      throw new Error("Please sign in to use this feature.");
    }
    localStorage.removeItem("token");
    clearResumeDraftStorage();
    broadcastAuthChange("logout");
    window.dispatchEvent(new CustomEvent(AUTH_EXPIRED_EVENT, {
      detail: { reason: "expired" },
    }));
    throw new Error("Session expired. Please sign in again.");
  }
  if (!resp.ok) throw await readApiError(resp);
  return resp;
}

export function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
  URL.revokeObjectURL(url);
}
