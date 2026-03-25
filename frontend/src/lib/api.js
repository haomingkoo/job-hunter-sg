// ─── API Config ────────────────────────────────────────────────────────────────
export const API_BASE = import.meta.env.VITE_API_URL || "";

export function clearResumeDraftStorage() {
  try {
    sessionStorage.removeItem("jh_resume_profile");
    sessionStorage.removeItem("jh_resume_text");
    sessionStorage.removeItem("jh_resume_template");
  } catch {
    // ignore storage errors
  }
}

export async function apiFetch(path, options = {}) {
  const token = localStorage.getItem("token");
  const headers = { "Content-Type": "application/json", ...options.headers };
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const resp = await fetch(`${API_BASE}${path}`, { ...options, headers });
  if (resp.status === 401) {
    localStorage.removeItem("token");
    clearResumeDraftStorage();
    window.location.reload();
    throw new Error("Session expired. Please sign in again.");
  }
  if (!resp.ok) throw new Error(`${resp.status}: ${await resp.text()}`);
  return resp;
}
