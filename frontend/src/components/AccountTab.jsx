import { useState, useEffect } from "react";
import { AlertCircle, CheckCircle2, LogOut, Loader2 } from "lucide-react";
import { API_BASE, apiFetch, clearResumeDraftStorage, downloadBlob } from "../lib/api.js";
import { PRIVACY_CONTACT_EMAIL } from "../lib/constants.js";

const formatLimit = (value) => (value >= 999999 ? "Unlimited" : value?.toLocaleString?.() ?? value);
const formatLimitLabel = (value) => (value >= 999999 ? "Unlimited" : `${formatLimit(value)} limit`);
const PANEL = "rounded-[10px] border border-line bg-white p-5";
const H2 = "text-base font-semibold text-ink";
const LABEL = "mb-1 block text-sm font-medium text-ink";
const FIELD = "min-h-11 w-full rounded-md border border-field bg-white px-3 text-sm text-ink focus:border-accent";
const TEXTAREA = "w-full rounded-md border border-field bg-white px-3 py-2 text-sm text-ink focus:border-accent";
const BTN_PRIMARY = "inline-flex min-h-11 items-center justify-center gap-2 rounded-md bg-accent px-4 text-sm font-semibold text-white transition-colors hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-60";
const BTN_SECONDARY = "inline-flex min-h-11 items-center justify-center gap-2 rounded-md border border-field bg-white px-4 text-sm font-medium text-ink transition-colors hover:bg-tint disabled:cursor-not-allowed disabled:opacity-60";
const TEXT_BUTTON = "inline-flex min-h-11 items-center rounded-md px-2 text-sm font-medium text-accent transition-colors hover:bg-tint";

function Notice({ children, tone = "error" }) {
  const success = tone === "success";
  const Icon = success ? CheckCircle2 : AlertCircle;
  return (
    <div
      role={success ? "status" : "alert"}
      className={`flex items-start gap-2 rounded-md border bg-white p-3 text-sm ${success ? "border-[#166534]/30 text-[#166534]" : "border-[#b42318]/30 text-[#b42318]"}`}
    >
      <Icon size={16} className="mt-0.5 shrink-0" aria-hidden="true" />
      <span>{children}</span>
    </div>
  );
}

const defaultAlertPrefs = {
  enabled: false,
  min_score: 75,
  direct_employers_only: true,
  frequency: "daily",
  keywords: "",
  max_jobs: 5,
  last_run_at: null,
};

export default function AccountTab({ user, authMode = "password", onLogout, onAccountDeleted, setActiveTab }) {
  const [accountView, setAccountView] = useState("overview");
  const [usage, setUsage] = useState(null);
  const [usageLoading, setUsageLoading] = useState(true);
  const [adminMetrics, setAdminMetrics] = useState(null);
  const [adminLoading, setAdminLoading] = useState(false);
  const [adminError, setAdminError] = useState("");
  const [contactForm, setContactForm] = useState({ name: user?.name || "", email: user?.email || "", message: "" });
  const [contactSending, setContactSending] = useState(false);
  const [contactSent, setContactSent] = useState(false);
  const [contactError, setContactError] = useState("");
  const [alertPrefs, setAlertPrefs] = useState(defaultAlertPrefs);
  const [alertsLoading, setAlertsLoading] = useState(true);
  const [alertsSaving, setAlertsSaving] = useState(false);
  const [alertsSaved, setAlertsSaved] = useState(false);
  const [alertsError, setAlertsError] = useState("");
  const [passwordForm, setPasswordForm] = useState({ current: "", next: "", confirm: "" });
  const [passwordSaving, setPasswordSaving] = useState(false);
  const [passwordMessage, setPasswordMessage] = useState("");
  const [passwordError, setPasswordError] = useState("");
  const [deleteEmail, setDeleteEmail] = useState("");
  const [deletePassword, setDeletePassword] = useState("");
  const [deleteSending, setDeleteSending] = useState(false);
  const [deleteError, setDeleteError] = useState("");
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState("");
  const isAdmin = user?.tier === "admin";

  const handleExport = async () => {
    setExporting(true);
    setExportError("");
    try {
      const resp = await apiFetch("/api/account/export");
      downloadBlob(await resp.blob(), "job-hunter-sg-export.json");
    } catch (err) {
      setExportError(err.message || "Export failed. Please try again.");
    } finally {
      setExporting(false);
    }
  };

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const resp = await apiFetch("/api/usage");
        const data = await resp.json();
        if (!cancelled) setUsage(data);
      } catch {
        // Non-critical: usage display will show fallback
      } finally {
        if (!cancelled) setUsageLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    let cancelled = false;
    setAlertsLoading(true);
    setAlertsError("");

    (async () => {
      try {
        const resp = await apiFetch("/api/job-alerts/preferences");
        const data = await resp.json();
        if (!cancelled) setAlertPrefs({ ...defaultAlertPrefs, ...data });
      } catch (err) {
        if (!cancelled) setAlertsError(err.message || "Could not load job alerts.");
      } finally {
        if (!cancelled) setAlertsLoading(false);
      }
    })();

    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (!isAdmin) {
      setAdminMetrics(null);
      setAdminError("");
      setAdminLoading(false);
      if (accountView === "admin") setAccountView("overview");
      return;
    }

    if (accountView !== "admin") {
      return;
    }

    let cancelled = false;
    setAdminLoading(true);
    setAdminError("");

    (async () => {
      try {
        const resp = await apiFetch("/api/admin/metrics");
        const data = await resp.json();
        if (!cancelled) setAdminMetrics(data);
      } catch (err) {
        if (!cancelled) setAdminError(err.message || "Could not load admin metrics.");
      } finally {
        if (!cancelled) setAdminLoading(false);
      }
    })();

    return () => { cancelled = true; };
  }, [accountView, isAdmin]);

  const sendContact = async (e) => {
    e.preventDefault();
    if (!contactForm.message.trim()) return;
    setContactSending(true);
    setContactError("");
    try {
      await apiFetch("/api/contact", {
        method: "POST",
        body: JSON.stringify(contactForm),
      });
      setContactSent(true);
      setContactForm({ ...contactForm, message: "" });
    } catch (err) {
      setContactError(err.message);
    } finally {
      setContactSending(false);
    }
  };

  const saveAlertPrefs = async (e) => {
    e.preventDefault();
    setAlertsSaving(true);
    setAlertsSaved(false);
    setAlertsError("");
    try {
      const payload = {
        enabled: Boolean(alertPrefs.enabled),
        min_score: Number(alertPrefs.min_score) || 75,
        direct_employers_only: Boolean(alertPrefs.direct_employers_only),
        frequency: alertPrefs.frequency || "daily",
        keywords: alertPrefs.keywords || "",
        max_jobs: Number(alertPrefs.max_jobs) || 5,
      };
      const resp = await apiFetch("/api/job-alerts/preferences", {
        method: "PUT",
        body: JSON.stringify(payload),
      });
      const data = await resp.json();
      setAlertPrefs({ ...defaultAlertPrefs, ...data });
      setAlertsSaved(true);
    } catch (err) {
      setAlertsError(err.message || "Could not save job alerts.");
    } finally {
      setAlertsSaving(false);
    }
  };

  const changePassword = async (e) => {
    e.preventDefault();
    setPasswordError("");
    setPasswordMessage("");
    if (passwordForm.next !== passwordForm.confirm) {
      setPasswordError("New passwords do not match.");
      return;
    }
    setPasswordSaving(true);
    try {
      const resp = await apiFetch("/api/auth/change-password", {
        method: "POST",
        body: JSON.stringify({
          current_password: passwordForm.current,
          new_password: passwordForm.next,
        }),
      });
      const data = await resp.json();
      if (data.token) localStorage.setItem("token", data.token);
      setPasswordForm({ current: "", next: "", confirm: "" });
      setPasswordMessage(data.message || "Password updated.");
    } catch (err) {
      setPasswordError(err.message || "Could not update your password.");
    } finally {
      setPasswordSaving(false);
    }
  };

  const deleteAccount = async (e) => {
    e.preventDefault();
    setDeleteError("");
    setDeleteSending(true);
    try {
      const payload = { confirm_email: deleteEmail };
      if (authMode === "password") payload.current_password = deletePassword;
      const resp = await apiFetch("/api/account", {
        method: "DELETE",
        body: JSON.stringify(payload),
      });
      const data = await resp.json();
      localStorage.removeItem("token");
      clearResumeDraftStorage();
      if (onAccountDeleted) onAccountDeleted(data.logout_url);
      else onLogout?.();
    } catch (err) {
      setDeleteError(err.message || "Could not delete your account.");
    } finally {
      setDeleteSending(false);
    }
  };

  const accountSections = [
    { id: "overview", label: "Overview" },
    { id: "privacy", label: "Privacy" },
    ...(isAdmin ? [{ id: "admin", label: "Admin" }] : []),
  ];
  const usageItems = usage ? [
    { label: "Searches today", value: usage.searches_today ?? 0, limit: usage.searches_limit },
    { label: "AI requests today", value: usage.ai_today ?? 0, limit: usage.ai_limit },
    { label: "Tracked jobs", value: usage.tracked_jobs ?? 0, limit: usage.tracked_limit },
  ] : [];
  const adminCount = (value) => value?.toLocaleString?.() ?? value;
  const adminStat = (rows) => (
    <dl className="mt-2 space-y-1.5 text-sm text-ink">
      {rows.map(([label, value]) => (
        <div key={label} className="flex items-center justify-between gap-3">
          <dt>{label}</dt>
          <dd className="font-medium tabular-nums">{value}</dd>
        </div>
      ))}
    </dl>
  );

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-xl font-bold tracking-[-0.01em] text-ink">Account</h1>
          <p className="mt-1 text-sm text-muted">Your profile, job alerts, privacy and support.</p>
        </div>
        <div className="inline-flex self-start rounded-md border border-field bg-white p-0.5" role="group" aria-label="Account section">
          {accountSections.map(({ id, label }) => (
            <button
              key={id}
              type="button"
              onClick={() => setAccountView(id)}
              aria-pressed={accountView === id}
              className={`min-h-10 rounded px-4 text-sm transition-colors ${accountView === id ? "bg-tint font-semibold text-ink" : "text-muted hover:text-ink"}`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {accountView === "overview" && (
      <>
      <section className={PANEL} aria-labelledby="profile-title">
        <h2 id="profile-title" className={H2}>Profile</h2>
        <dl className="mt-3 grid grid-cols-1 gap-4 text-sm sm:grid-cols-3">
          <div>
            <dt className="text-xs text-muted">Name</dt>
            <dd className="mt-0.5 font-medium text-ink [overflow-wrap:anywhere]">{user?.name || "Not set"}</dd>
          </div>
          <div>
            <dt className="text-xs text-muted">Email</dt>
            <dd className="mt-0.5 text-ink [overflow-wrap:anywhere]">{user?.email || "Not set"}</dd>
          </div>
          <div>
            <dt className="text-xs text-muted">Member since</dt>
            <dd className="mt-0.5 tabular-nums text-ink">{user?.created_at ? new Date(user.created_at).toLocaleDateString("en-SG", { day: "numeric", month: "short", year: "numeric" }) : "Not recorded"}</dd>
          </div>
        </dl>
        <div className="mt-5 border-t border-line pt-4">
          <h3 className="text-sm font-semibold text-ink">Today&apos;s usage</h3>
          {usageLoading ? (
            <div className="mt-3 grid grid-cols-3 gap-4" role="status">
              <span className="sr-only">Loading usage</span>
              {[0, 1, 2].map((cell) => (
                <div key={cell}>
                  <div className="h-5 w-10 rounded bg-paper" />
                  <div className="mt-2 h-3 w-20 rounded bg-paper" />
                </div>
              ))}
            </div>
          ) : usage ? (
            <dl className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-3">
              {usageItems.map((item) => (
                <div key={item.label}>
                  <dd className="text-xl font-semibold tabular-nums text-ink">{item.value}</dd>
                  <dt className="text-xs text-muted">{item.label}</dt>
                  {item.limit != null && (
                    <dd className="text-xs tabular-nums text-muted">{formatLimitLabel(item.limit)}</dd>
                  )}
                </div>
              ))}
            </dl>
          ) : (
            <p className="mt-2 text-sm text-muted">Usage could not load. Try again later.</p>
          )}
        </div>
      </section>

      <section className={PANEL} aria-labelledby="alerts-title">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <h2 id="alerts-title" className={H2}>Job match alerts</h2>
            <p className="mt-1 text-sm text-muted">
              Get email digests for roles that match your saved resume.
            </p>
          </div>
          <button
            type="button"
            disabled={alertsLoading}
            aria-pressed={Boolean(alertPrefs.enabled)}
            onClick={() => {
              setAlertsSaved(false);
              setAlertPrefs((prev) => ({ ...prev, enabled: !prev.enabled }));
            }}
            className="inline-flex min-h-11 items-center justify-center gap-2 self-start rounded-md border border-field bg-white px-3 text-sm font-medium text-ink transition-colors hover:bg-tint disabled:opacity-60"
          >
            <span aria-hidden="true" className={`h-5 w-9 rounded-full p-0.5 transition-colors ${alertPrefs.enabled ? "bg-accent" : "bg-field"}`}>
              <span className={`block h-4 w-4 rounded-full bg-white transition-transform ${alertPrefs.enabled ? "translate-x-4" : "translate-x-0"}`} />
            </span>
            {alertPrefs.enabled ? "Enabled" : "Off"}
          </button>
        </div>

        {alertsError && <div className="mt-4"><Notice>{alertsError}</Notice></div>}
        {alertsSaved && <div className="mt-4"><Notice tone="success">Job alerts updated.</Notice></div>}

        {alertsLoading ? (
          <div className="mt-5 grid grid-cols-1 gap-4 sm:grid-cols-3" role="status">
            <span className="sr-only">Loading alert settings</span>
            {[0, 1, 2].map((cell) => (
              <div key={cell}>
                <div className="h-3 w-20 rounded bg-paper" />
                <div className="mt-2 h-11 rounded-md bg-paper" />
              </div>
            ))}
          </div>
        ) : (
          <form onSubmit={saveAlertPrefs} className="mt-5 space-y-4">
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
              <label className="block">
                <span className={LABEL}>Lowest match score</span>
                <input
                  type="number"
                  min="35"
                  max="95"
                  value={alertPrefs.min_score}
                  onChange={(e) => setAlertPrefs((prev) => ({ ...prev, min_score: e.target.value }))}
                  className={FIELD}
                />
              </label>
              <label className="block">
                <span className={LABEL}>Frequency</span>
                <select
                  value={alertPrefs.frequency}
                  onChange={(e) => setAlertPrefs((prev) => ({ ...prev, frequency: e.target.value }))}
                  className={FIELD}
                >
                  <option value="daily">Daily digest</option>
                  <option value="weekly">Weekly digest</option>
                </select>
              </label>
              <label className="block">
                <span className={LABEL}>Jobs per email</span>
                <input
                  type="number"
                  min="1"
                  max="10"
                  value={alertPrefs.max_jobs}
                  onChange={(e) => setAlertPrefs((prev) => ({ ...prev, max_jobs: e.target.value }))}
                  className={FIELD}
                />
              </label>
            </div>

            <label className="block">
              <span className={LABEL}>Keywords</span>
              <input
                value={alertPrefs.keywords || ""}
                onChange={(e) => setAlertPrefs((prev) => ({ ...prev, keywords: e.target.value }))}
                placeholder="e.g. cloud, data engineering"
                className={FIELD}
              />
            </label>

            <label className="flex items-start gap-3">
              <input
                type="checkbox"
                checked={Boolean(alertPrefs.direct_employers_only)}
                onChange={(e) => setAlertPrefs((prev) => ({ ...prev, direct_employers_only: e.target.checked }))}
                className="mt-0.5 h-5 w-5 shrink-0 accent-[#1f5f99]"
              />
              <span>
                <span className="block text-sm font-medium text-ink">Hide known recruiters</span>
                <span className="block text-xs text-muted">
                  Verified direct and unverified employers remain eligible.
                </span>
              </span>
            </label>

            <div className="flex flex-col gap-3 border-t border-line pt-4 sm:flex-row sm:items-center sm:justify-between">
              <div className="text-xs text-muted">
                {alertPrefs.last_run_at
                  ? `Last checked ${new Date(alertPrefs.last_run_at).toLocaleString("en-SG", { day: "numeric", month: "short", year: "numeric", hour: "numeric", minute: "2-digit" })}`
                  : "Alerts start after you turn them on."}
                {alertPrefs.enabled && (
                  <span className="mt-1 block">
                    By enabling alerts, you consent to receiving matched-job digests. Every alert includes an unsubscribe link.
                  </span>
                )}
              </div>
              <button type="submit" disabled={alertsSaving} className={BTN_PRIMARY}>
                {alertsSaving && <Loader2 size={14} className="animate-spin" aria-hidden="true" />}
                Save alerts
              </button>
            </div>
          </form>
        )}
      </section>

      {authMode === "password" && (
      <section className={PANEL} aria-labelledby="password-title">
        <h2 id="password-title" className={H2}>Change Password</h2>
        <p className="mt-1 text-sm text-muted">Use at least 8 characters for your new password.</p>
        {passwordError && <div className="mt-4"><Notice>{passwordError}</Notice></div>}
        {passwordMessage && <div className="mt-4"><Notice tone="success">{passwordMessage}</Notice></div>}
        <form onSubmit={changePassword} className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-3">
          <input
            type="password"
            required
            aria-label="Current password" placeholder="Current password"
            autoComplete="current-password"
            value={passwordForm.current}
            onChange={(e) => setPasswordForm({ ...passwordForm, current: e.target.value })}
            className={FIELD}
          />
          <input
            type="password"
            required
            minLength={8}
            aria-label="New password" placeholder="New password"
            autoComplete="new-password"
            value={passwordForm.next}
            onChange={(e) => setPasswordForm({ ...passwordForm, next: e.target.value })}
            className={FIELD}
          />
          <input
            type="password"
            required
            minLength={8}
            aria-label="Confirm new password" placeholder="Confirm new password"
            autoComplete="new-password"
            value={passwordForm.confirm}
            onChange={(e) => setPasswordForm({ ...passwordForm, confirm: e.target.value })}
            className={FIELD}
          />
          <button type="submit" disabled={passwordSaving} className={`${BTN_SECONDARY} sm:col-start-3`}>
            {passwordSaving && <Loader2 size={14} className="animate-spin" aria-hidden="true" />}
            Update Password
          </button>
        </form>
      </section>
      )}

      <section className={PANEL} aria-labelledby="contact-title">
        <h2 id="contact-title" className={H2}>Contact</h2>
        <p className="mt-1 text-sm text-muted">Send a message or report a problem.</p>
        {contactSent && <div className="mt-4"><Notice tone="success">Message sent. We will get back to you soon.</Notice></div>}
        {contactError && <div className="mt-4"><Notice>{contactError}</Notice></div>}
        <form onSubmit={sendContact} className="mt-4 space-y-3">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <input aria-label="Your name" placeholder="Name" value={contactForm.name} onChange={(e) => setContactForm({ ...contactForm, name: e.target.value })} className={FIELD} />
            <input aria-label="Your email" placeholder="Email" type="email" value={contactForm.email} onChange={(e) => setContactForm({ ...contactForm, email: e.target.value })} className={FIELD} />
          </div>
          <textarea aria-label="Message" placeholder="Your message" value={contactForm.message} onChange={(e) => setContactForm({ ...contactForm, message: e.target.value })} className={TEXTAREA} rows={3} />
          <button type="submit" disabled={contactSending || !contactForm.message.trim()} className={BTN_SECONDARY}>
            {contactSending && <Loader2 size={14} className="animate-spin" aria-hidden="true" />}
            Send message
          </button>
        </form>
      </section>

      <nav aria-label="Other pages" className="text-sm text-muted">
        <span className="mr-1">Go to</span>
        {[
          { label: "Resume", tab: "resume" },
          { label: "Smart Match", tab: "power" },
          { label: "Interview stories", tab: "stories" },
          { label: "Market insights", tab: "analytics" },
        ].map(({ label, tab }) => (
          <button key={tab} type="button" onClick={() => setActiveTab?.(tab)} className={TEXT_BUTTON}>
            {label}
          </button>
        ))}
      </nav>

      <section className="rounded-[10px] border border-[#b42318]/40 bg-white p-5" aria-labelledby="delete-title">
        <h2 id="delete-title" className="text-base font-semibold text-[#b42318]">Delete account</h2>
        <p className="mt-1 max-w-2xl text-sm text-muted">
          Permanently remove your saved resumes and tailored results, tracked jobs, stories,
          alerts, Agent memory and history, and usage records. Shared public job listings remain.
          This cannot be undone.
        </p>
        {deleteError && <div className="mt-4"><Notice>{deleteError}</Notice></div>}
        <form onSubmit={deleteAccount} className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-3">
          <input
            type="email"
            required
            aria-label="Type your email to confirm" placeholder={`Type ${user?.email || "your email"}`}
            value={deleteEmail}
            onChange={(e) => setDeleteEmail(e.target.value)}
            className={FIELD}
          />
          {authMode === "password" && (
            <input
              type="password"
              required
              aria-label="Current password" placeholder="Current password"
              autoComplete="current-password"
              value={deletePassword}
              onChange={(e) => setDeletePassword(e.target.value)}
              className={FIELD}
            />
          )}
          <button
            type="submit"
            disabled={deleteSending || deleteEmail !== user?.email || (authMode === "password" && !deletePassword)}
            className="inline-flex min-h-11 items-center justify-center gap-2 rounded-md border border-[#b42318] bg-white px-4 text-sm font-semibold text-[#b42318] transition-colors hover:bg-[#fef3f2] disabled:cursor-not-allowed disabled:opacity-50"
          >
            {deleteSending && <Loader2 size={14} className="animate-spin" aria-hidden="true" />}
            Delete My Account
          </button>
        </form>
      </section>
      </>
      )}

      {isAdmin && accountView === "admin" && (
        <section className={PANEL} aria-labelledby="admin-title">
          <div className="mb-4 flex items-center justify-between gap-3">
            <div>
              <h2 id="admin-title" className={H2}>Admin metrics</h2>
              <p className="mt-1 text-sm text-muted">Signups, resume activity and usage.</p>
            </div>
            <button
              type="button"
              onClick={async () => {
                setAdminLoading(true);
                setAdminError("");
                try {
                  const resp = await apiFetch("/api/admin/metrics");
                  setAdminMetrics(await resp.json());
                } catch (err) {
                  setAdminError(err.message || "Could not load admin metrics.");
                } finally {
                  setAdminLoading(false);
                }
              }}
              className={BTN_SECONDARY}
            >
              Refresh
            </button>
          </div>

          {adminLoading ? (
            <div className="flex items-center gap-2 text-sm text-muted" role="status"><Loader2 size={14} className="animate-spin" aria-hidden="true" /> Loading admin metrics...</div>
          ) : adminError ? (
            <Notice>{adminError}</Notice>
          ) : adminMetrics ? (
            <>
              <dl className="grid grid-cols-2 gap-px overflow-hidden rounded-md border border-line bg-line sm:grid-cols-4">
                {[
                  ["Total users", adminMetrics.overview.total_users],
                  ["Signups last 7 days", adminMetrics.overview.signups_7d],
                  ["Active users last 7 days", adminMetrics.overview.active_users_7d],
                  ["Saved resumes", adminMetrics.overview.total_saved_resumes],
                  ["Tailored resumes", adminMetrics.overview.tailored_resumes_total],
                  ["Tracked jobs", adminMetrics.overview.tracked_jobs_total],
                  ["Resume chat starts, 7d", adminMetrics.activity.resume_chat_starts_7d],
                  ["Resume downloads, 7d", adminMetrics.activity.resume_downloads_7d],
                ].map(([label, value]) => (
                  <div key={label} className="bg-white px-4 py-3">
                    <dd className="text-xl font-semibold tabular-nums text-ink">{adminCount(value)}</dd>
                    <dt className="mt-0.5 text-xs text-muted">{label}</dt>
                  </div>
                ))}
              </dl>

              <div className="mt-6 grid grid-cols-1 gap-x-8 gap-y-6 lg:grid-cols-2">
                <div>
                  <h3 className="text-sm font-semibold text-ink">Today</h3>
                  {adminStat([
                    ["Signups", adminMetrics.overview.signups_today],
                    ["Searches", adminMetrics.activity.searches_today],
                    ["AI calls", adminMetrics.activity.ai_today],
                    ["Anonymous AI", adminMetrics.activity.anonymous_ai_today],
                  ])}
                </div>
                <div>
                  <h3 className="text-sm font-semibold text-ink">Onboarding</h3>
                  {adminStat([
                    ["Resume chat starts, 7d", adminMetrics.activity.resume_chat_starts_7d],
                    ["Resume chat generates, 7d", adminMetrics.activity.resume_chat_generates_7d],
                    ["Resume uploads, 7d", adminMetrics.activity.resume_uploads_7d],
                    ["Resume scores, 7d", adminMetrics.activity.resume_scores_7d],
                  ])}
                </div>
                <div>
                  <h3 className="text-sm font-semibold text-ink">User funnel</h3>
                  {adminStat([
                    ["Users with saved resume", adminMetrics.funnel.users_with_saved_resume],
                    ["Users with tailored resume", adminMetrics.funnel.users_with_tailored_resume],
                    ["Users with tracked jobs", adminMetrics.funnel.users_with_tracked_jobs],
                  ])}
                </div>
                <div>
                  <h3 className="text-sm font-semibold text-ink">Resume parsing</h3>
                  {adminStat([
                    ["Uploads checked, 30d", adminMetrics.resume_parse_quality?.diagnostic_uploads_30d ?? 0],
                    ["Needs review", adminMetrics.resume_parse_quality?.needs_review_30d ?? 0],
                    ["Avg score", adminMetrics.resume_parse_quality?.avg_score ?? "n/a"],
                    ["Good / Check / Review", `${adminMetrics.resume_parse_quality?.labels?.good ?? 0} / ${adminMetrics.resume_parse_quality?.labels?.check ?? 0} / ${adminMetrics.resume_parse_quality?.labels?.review ?? 0}`],
                  ])}
                  {(adminMetrics.resume_parse_quality?.top_warnings || []).length > 0 && (
                    <div className="mt-3 space-y-1 border-t border-line pt-3 text-xs text-muted">
                      {adminMetrics.resume_parse_quality.top_warnings.slice(0, 2).map((item) => (
                        <div key={item.warning} className="flex gap-2">
                          <span className="font-semibold tabular-nums text-ink">{item.count}</span>
                          <span>{item.warning}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>

              <div className="mt-6">
                <h3 className="text-sm font-semibold text-ink">Last 14 days</h3>
                <p className="mt-0.5 text-xs text-muted">Check whether product changes improve signups and resume activity.</p>
                <div className="mt-2 overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead className="border-b border-line text-xs text-muted">
                      <tr>
                        <th scope="col" className="px-3 py-2 text-left font-semibold">Date</th>
                        <th scope="col" className="px-3 py-2 text-right font-semibold">Signups</th>
                        <th scope="col" className="px-3 py-2 text-right font-semibold">Resumes saved</th>
                        <th scope="col" className="px-3 py-2 text-right font-semibold">Downloads</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-line tabular-nums text-ink">
                      {(adminMetrics.daily || []).map((row) => (
                        <tr key={row.date}>
                          <td className="px-3 py-2">{row.date}</td>
                          <td className="px-3 py-2 text-right">{row.signups}</td>
                          <td className="px-3 py-2 text-right">{row.resumes_saved}</td>
                          <td className="px-3 py-2 text-right">{row.downloads}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </>
          ) : (
            <p className="text-sm text-muted">No admin metrics yet.</p>
          )}
        </section>
      )}

      {accountView === "privacy" && (
      <section className={PANEL} aria-labelledby="privacy-title">
        <h2 id="privacy-title" className={H2}>Legal & Privacy</h2>
        <p className="mt-1 text-sm text-muted">
          How your data is handled, and the terms for using Job Hunter SG.
        </p>
        <div className="-mx-2 mt-2 flex flex-wrap gap-1">
          <button type="button" onClick={() => window.open(`${API_BASE}/api/terms`, "_blank")} className={TEXT_BUTTON}>
            Terms of Service
          </button>
          <button type="button" onClick={() => window.open(`${API_BASE}/api/privacy`, "_blank")} className={TEXT_BUTTON}>
            Privacy Notice
          </button>
        </div>
        <div className="mt-5 border-t border-line pt-4">
          <h3 className="text-sm font-semibold text-ink">Your data</h3>
          <p className="mt-1 max-w-2xl text-sm text-muted">
            Download everything stored for your account as a JSON file. For corrections or other requests, email{" "}
            <a href={`mailto:${PRIVACY_CONTACT_EMAIL}`} className="font-medium text-accent underline underline-offset-2">{PRIVACY_CONTACT_EMAIL}</a>.
          </p>
          <button type="button" onClick={handleExport} disabled={exporting} className={`mt-3 ${BTN_PRIMARY}`}>
            {exporting && <Loader2 size={14} className="animate-spin" aria-hidden="true" />}
            Export my data
          </button>
          {exportError && <div className="mt-3"><Notice>{exportError}</Notice></div>}
        </div>
      </section>
      )}

      <button type="button" onClick={() => onLogout?.()} className={BTN_SECONDARY}>
        <LogOut size={14} aria-hidden="true" /> Sign out
      </button>
    </div>
  );
}
