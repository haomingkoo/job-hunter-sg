import { useState, useEffect } from "react";
import {
  User, LogOut, Mail, Star, CheckCircle, Loader2, Bell, Save, ShieldCheck,
  FileText, Sparkles, BookOpen, BarChart2,
} from "lucide-react";
import { API_BASE, apiFetch } from "../lib/api.js";
import TierBadge from "./TierBadge.jsx";

const formatLimit = (value) => (value >= 999999 ? "Unlimited" : value?.toLocaleString?.() ?? value);
const defaultAlertPrefs = {
  enabled: false,
  min_score: 75,
  direct_employers_only: true,
  frequency: "daily",
  keywords: "",
  max_jobs: 5,
  last_run_at: null,
};

export default function AccountTab({ user, onLogout, setActiveTab }) {
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
  const isAdmin = user?.tier === "admin";

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
  }, [isAdmin]);

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

  const isPro = user?.tier === "pro" || user?.tier === "admin";

  return (
    <div className="space-y-6">
      <div className="rounded-xl border border-[#BDDDFC]/30 bg-white p-5 shadow-sm">
        <h2 className="font-semibold text-[#384959] flex items-center gap-2"><User size={18} /> Account</h2>
        <p className="text-sm text-[#6A89A7] mt-1">Manage your account, usage, saved work, and support requests.</p>
      </div>

      {/* User Info */}
      <div className="bg-white border border-[#BDDDFC]/30 rounded-xl p-5">
        <h3 className="font-semibold text-[#384959] mb-4">Profile</h3>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-sm">
          <div>
            <div className="text-[#6A89A7] text-xs uppercase tracking-wide mb-1">Name</div>
            <div className="text-[#384959] font-medium">{user?.name || "\u2014"}</div>
          </div>
          <div>
            <div className="text-[#6A89A7] text-xs uppercase tracking-wide mb-1">Email</div>
            <div className="text-[#384959]">{user?.email || "\u2014"}</div>
          </div>
          <div>
            <div className="text-[#6A89A7] text-xs uppercase tracking-wide mb-1">Tier</div>
            <TierBadge tier={user?.tier} />
          </div>
          <div>
            <div className="text-[#6A89A7] text-xs uppercase tracking-wide mb-1">Member Since</div>
            <div className="text-[#384959]">{user?.created_at ? new Date(user.created_at).toLocaleDateString() : "\u2014"}</div>
          </div>
        </div>
      </div>

      {/* Usage Stats */}
      <div className="bg-white border border-[#BDDDFC]/30 rounded-xl p-5">
        <h3 className="font-semibold text-[#384959] mb-4">Usage</h3>
        {usageLoading ? (
          <div className="flex items-center gap-2 text-sm text-[#6A89A7]"><Loader2 size={14} className="animate-spin" /> Loading usage...</div>
        ) : usage ? (
          <div className="grid grid-cols-1 sm:grid-cols-4 gap-4">
            <div className="bg-blue-50 rounded-xl p-4 text-center">
              <div className="text-2xl font-bold text-[#384959]">{usage.searches_today ?? 0}</div>
              <div className="text-xs text-[#6A89A7] mt-1">Searches Today</div>
              {usage.searches_limit != null && (
                <div className="text-xs text-[#6A89A7] mt-0.5">/ {formatLimit(usage.searches_limit)} limit</div>
              )}
            </div>
            <div className="bg-emerald-50 rounded-xl p-4 text-center">
              <div className="text-2xl font-bold text-[#384959]">{usage.ai_today ?? 0}</div>
              <div className="text-xs text-[#6A89A7] mt-1">AI Requests Today</div>
              {usage.ai_limit != null && (
                <div className="text-xs text-[#6A89A7] mt-0.5">/ {formatLimit(usage.ai_limit)} limit</div>
              )}
            </div>
            <div className="bg-purple-50 rounded-xl p-4 text-center">
              <div className="text-2xl font-bold text-[#384959]">{usage.tracked_jobs ?? 0}</div>
              <div className="text-xs text-[#6A89A7] mt-1">Tracked Jobs</div>
              {usage.tracked_limit != null && (
                <div className="text-xs text-[#6A89A7] mt-0.5">/ {formatLimit(usage.tracked_limit)} limit</div>
              )}
            </div>
            <div className="bg-green-50 rounded-xl p-4 text-center">
              <div className="text-2xl font-bold text-[#384959] capitalize">{usage.tier || user?.tier || "free"}</div>
              <div className="text-xs text-[#6A89A7] mt-1">Current Tier</div>
            </div>
          </div>
        ) : (
          <div className="text-sm text-[#6A89A7]">Could not load usage data.</div>
        )}
      </div>

      <div className="bg-white border border-[#BDDDFC]/30 rounded-xl p-5">
        <h3 className="font-semibold text-[#384959] mb-4">Quick Actions</h3>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {[
            { label: "Review Resume", detail: "Check parse quality and export.", icon: FileText, tab: "resume" },
            { label: "Smart Match", detail: "Refresh fit and course gaps.", icon: Sparkles, tab: "power" },
            { label: "Story Bank", detail: "Prepare interview examples.", icon: BookOpen, tab: "stories" },
            { label: "Market Insights", detail: "Explore sector skill demand.", icon: BarChart2, tab: "analytics" },
          ].map(({ label, detail, icon: Icon, tab }) => (
            <button
              key={label}
              type="button"
              onClick={() => setActiveTab?.(tab)}
              className="rounded-xl border border-[#BDDDFC]/30 bg-[#f0f4f8] px-4 py-3 text-left transition hover:bg-white hover:shadow-sm active:scale-[0.99]"
            >
              <div className="flex items-center gap-2 text-sm font-semibold text-[#384959]">
                <Icon size={15} />
                {label}
              </div>
              <div className="mt-1 text-xs leading-relaxed text-[#6A89A7]">{detail}</div>
            </button>
          ))}
        </div>
      </div>

      <div className="bg-white border border-[#BDDDFC]/30 rounded-xl p-5">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <h3 className="font-semibold text-[#384959] flex items-center gap-2">
              <Bell size={17} /> Job Match Alerts
            </h3>
            <p className="mt-1 text-sm text-[#6A89A7]">
              Email digests for new roles that clear your saved resume match threshold.
            </p>
          </div>
          <button
            type="button"
            disabled={alertsLoading}
            onClick={() => {
              setAlertsSaved(false);
              setAlertPrefs((prev) => ({ ...prev, enabled: !prev.enabled }));
            }}
            className={`inline-flex items-center justify-center gap-2 rounded-lg border px-3 py-2 text-sm font-medium transition active:scale-[0.98] disabled:opacity-50 ${
              alertPrefs.enabled
                ? "border-emerald-200 bg-emerald-50 text-emerald-700"
                : "border-[#BDDDFC]/40 bg-[#f0f4f8] text-[#384959] hover:bg-white"
            }`}
          >
            <span className={`h-5 w-9 rounded-full p-0.5 transition ${alertPrefs.enabled ? "bg-emerald-600" : "bg-[#BDDDFC]"}`}>
              <span className={`block h-4 w-4 rounded-full bg-white transition-transform ${alertPrefs.enabled ? "translate-x-4" : "translate-x-0"}`} />
            </span>
            {alertPrefs.enabled ? "Enabled" : "Off"}
          </button>
        </div>

        {alertsError && (
          <div className="mt-4 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
            {alertsError}
          </div>
        )}
        {alertsSaved && (
          <div className="mt-4 rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-700">
            Job alerts updated.
          </div>
        )}

        {alertsLoading ? (
          <div className="mt-4 flex items-center gap-2 text-sm text-[#6A89A7]">
            <Loader2 size={14} className="animate-spin" /> Loading alert settings...
          </div>
        ) : (
          <form onSubmit={saveAlertPrefs} className="mt-5 space-y-4">
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <label className="block">
                <span className="mb-1.5 block text-xs font-semibold uppercase tracking-wide text-[#6A89A7]">Minimum Score</span>
                <input
                  type="number"
                  min="35"
                  max="95"
                  value={alertPrefs.min_score}
                  onChange={(e) => setAlertPrefs((prev) => ({ ...prev, min_score: e.target.value }))}
                  className="w-full rounded-lg border border-[#BDDDFC]/30 px-3 py-2 text-sm text-[#384959]"
                />
              </label>
              <label className="block">
                <span className="mb-1.5 block text-xs font-semibold uppercase tracking-wide text-[#6A89A7]">Frequency</span>
                <select
                  value={alertPrefs.frequency}
                  onChange={(e) => setAlertPrefs((prev) => ({ ...prev, frequency: e.target.value }))}
                  className="w-full rounded-lg border border-[#BDDDFC]/30 px-3 py-2 text-sm text-[#384959]"
                >
                  <option value="daily">Daily digest</option>
                  <option value="weekly">Weekly digest</option>
                </select>
              </label>
              <label className="block">
                <span className="mb-1.5 block text-xs font-semibold uppercase tracking-wide text-[#6A89A7]">Max Jobs</span>
                <input
                  type="number"
                  min="1"
                  max="10"
                  value={alertPrefs.max_jobs}
                  onChange={(e) => setAlertPrefs((prev) => ({ ...prev, max_jobs: e.target.value }))}
                  className="w-full rounded-lg border border-[#BDDDFC]/30 px-3 py-2 text-sm text-[#384959]"
                />
              </label>
              <label className="flex items-center justify-between gap-3 rounded-lg border border-[#BDDDFC]/30 bg-[#f0f4f8] px-3 py-2">
                <span>
                  <span className="block text-sm font-medium text-[#384959]">Direct employers only</span>
                  <span className="block text-xs text-[#6A89A7]">Default for cleaner alerts.</span>
                </span>
                <input
                  type="checkbox"
                  checked={Boolean(alertPrefs.direct_employers_only)}
                  onChange={(e) => setAlertPrefs((prev) => ({ ...prev, direct_employers_only: e.target.checked }))}
                  className="h-4 w-4 accent-[#384959]"
                />
              </label>
            </div>

            <label className="block">
              <span className="mb-1.5 block text-xs font-semibold uppercase tracking-wide text-[#6A89A7]">Keywords</span>
              <input
                value={alertPrefs.keywords || ""}
                onChange={(e) => setAlertPrefs((prev) => ({ ...prev, keywords: e.target.value }))}
                placeholder="Optional: semicon, cloud, data engineering"
                className="w-full rounded-lg border border-[#BDDDFC]/30 px-3 py-2 text-sm text-[#384959]"
              />
            </label>

            <div className="flex flex-col gap-3 border-t border-[#BDDDFC]/20 pt-4 sm:flex-row sm:items-center sm:justify-between">
              <div className="text-xs text-[#6A89A7]">
                {alertPrefs.last_run_at
                  ? `Last checked ${new Date(alertPrefs.last_run_at).toLocaleString()}`
                  : "Alerts start checking from the moment you enable them."}
                {alertPrefs.enabled && (
                  <span className="mt-1 block">
                    By enabling alerts, you consent to receiving matched-job digests. Every alert includes an unsubscribe link.
                  </span>
                )}
              </div>
              <button
                type="submit"
                disabled={alertsSaving}
                className="inline-flex items-center justify-center gap-2 rounded-lg bg-[#384959] px-4 py-2 text-sm font-medium text-white transition hover:bg-[#2d3a47] active:scale-[0.98] disabled:opacity-50"
              >
                {alertsSaving ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
                Save Alerts
              </button>
            </div>
          </form>
        )}
      </div>

      {isAdmin && (
        <div className="bg-white border border-[#BDDDFC]/30 rounded-xl p-5">
          <div className="flex items-center justify-between gap-3 mb-4">
            <div>
              <h3 className="font-semibold text-[#384959]">Admin Snapshot</h3>
              <p className="text-sm text-[#6A89A7] mt-1">Site-wide signups, resume activity, and onboarding signals.</p>
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
              className="rounded-lg border border-[#BDDDFC]/30 px-3 py-1.5 text-xs text-[#6A89A7] hover:bg-[#f0f4f8]"
            >
              Refresh
            </button>
          </div>

          {adminLoading ? (
            <div className="flex items-center gap-2 text-sm text-[#6A89A7]"><Loader2 size={14} className="animate-spin" /> Loading admin metrics...</div>
          ) : adminError ? (
            <div className="bg-red-50 border border-red-200 text-red-700 text-sm rounded-lg p-3">
              {adminError}
            </div>
          ) : adminMetrics ? (
            <>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
                <div className="rounded-xl bg-slate-50 p-4">
                  <div className="text-2xl font-bold text-[#384959]">{adminMetrics.overview.total_users?.toLocaleString?.() ?? adminMetrics.overview.total_users}</div>
                  <div className="text-xs text-[#6A89A7] mt-1">Total users</div>
                </div>
                <div className="rounded-xl bg-blue-50 p-4">
                  <div className="text-2xl font-bold text-[#384959]">{adminMetrics.overview.signups_7d?.toLocaleString?.() ?? adminMetrics.overview.signups_7d}</div>
                  <div className="text-xs text-[#6A89A7] mt-1">Signups last 7 days</div>
                </div>
                <div className="rounded-xl bg-emerald-50 p-4">
                  <div className="text-2xl font-bold text-[#384959]">{adminMetrics.overview.active_users_7d?.toLocaleString?.() ?? adminMetrics.overview.active_users_7d}</div>
                  <div className="text-xs text-[#6A89A7] mt-1">Active users last 7 days</div>
                </div>
                <div className="rounded-xl bg-violet-50 p-4">
                  <div className="text-2xl font-bold text-[#384959]">{adminMetrics.overview.total_saved_resumes?.toLocaleString?.() ?? adminMetrics.overview.total_saved_resumes}</div>
                  <div className="text-xs text-[#6A89A7] mt-1">Saved resumes</div>
                </div>
                <div className="rounded-xl bg-amber-50 p-4">
                  <div className="text-2xl font-bold text-[#384959]">{adminMetrics.overview.tailored_resumes_total?.toLocaleString?.() ?? adminMetrics.overview.tailored_resumes_total}</div>
                  <div className="text-xs text-[#6A89A7] mt-1">Tailored resumes</div>
                </div>
                <div className="rounded-xl bg-cyan-50 p-4">
                  <div className="text-2xl font-bold text-[#384959]">{adminMetrics.overview.tracked_jobs_total?.toLocaleString?.() ?? adminMetrics.overview.tracked_jobs_total}</div>
                  <div className="text-xs text-[#6A89A7] mt-1">Tracked jobs</div>
                </div>
                <div className="rounded-xl bg-rose-50 p-4">
                  <div className="text-2xl font-bold text-[#384959]">{adminMetrics.activity.resume_chat_starts_7d?.toLocaleString?.() ?? adminMetrics.activity.resume_chat_starts_7d}</div>
                  <div className="text-xs text-[#6A89A7] mt-1">Resume chat starts, 7d</div>
                </div>
                <div className="rounded-xl bg-indigo-50 p-4">
                  <div className="text-2xl font-bold text-[#384959]">{adminMetrics.activity.resume_downloads_7d?.toLocaleString?.() ?? adminMetrics.activity.resume_downloads_7d}</div>
                  <div className="text-xs text-[#6A89A7] mt-1">Resume downloads, 7d</div>
                </div>
              </div>

              <div className="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-4 gap-4 mt-5">
                <div className="rounded-xl border border-[#BDDDFC]/30 bg-[#f0f4f8] p-4">
                  <div className="text-sm font-semibold text-[#384959]">Today</div>
                  <div className="mt-3 space-y-2 text-sm text-[#384959]">
                    <div className="flex items-center justify-between"><span>Signups</span><span className="font-medium">{adminMetrics.overview.signups_today}</span></div>
                    <div className="flex items-center justify-between"><span>Searches</span><span className="font-medium">{adminMetrics.activity.searches_today}</span></div>
                    <div className="flex items-center justify-between"><span>AI calls</span><span className="font-medium">{adminMetrics.activity.ai_today}</span></div>
                    <div className="flex items-center justify-between"><span>Anonymous AI</span><span className="font-medium">{adminMetrics.activity.anonymous_ai_today}</span></div>
                  </div>
                </div>

                <div className="rounded-xl border border-[#BDDDFC]/30 bg-[#f0f4f8] p-4">
                  <div className="text-sm font-semibold text-[#384959]">Onboarding Signals</div>
                  <div className="mt-3 space-y-2 text-sm text-[#384959]">
                    <div className="flex items-center justify-between"><span>Resume chat starts, 7d</span><span className="font-medium">{adminMetrics.activity.resume_chat_starts_7d}</span></div>
                    <div className="flex items-center justify-between"><span>Resume chat generates, 7d</span><span className="font-medium">{adminMetrics.activity.resume_chat_generates_7d}</span></div>
                    <div className="flex items-center justify-between"><span>Resume uploads, 7d</span><span className="font-medium">{adminMetrics.activity.resume_uploads_7d}</span></div>
                    <div className="flex items-center justify-between"><span>Resume scores, 7d</span><span className="font-medium">{adminMetrics.activity.resume_scores_7d}</span></div>
                  </div>
                </div>

                <div className="rounded-xl border border-[#BDDDFC]/30 bg-[#f0f4f8] p-4">
                  <div className="text-sm font-semibold text-[#384959]">User Funnel</div>
                  <div className="mt-3 space-y-2 text-sm text-[#384959]">
                    <div className="flex items-center justify-between"><span>Users with saved resume</span><span className="font-medium">{adminMetrics.funnel.users_with_saved_resume}</span></div>
                    <div className="flex items-center justify-between"><span>Users with tailored resume</span><span className="font-medium">{adminMetrics.funnel.users_with_tailored_resume}</span></div>
                    <div className="flex items-center justify-between"><span>Users with tracked jobs</span><span className="font-medium">{adminMetrics.funnel.users_with_tracked_jobs}</span></div>
                  </div>
                </div>

                <div className="rounded-xl border border-[#BDDDFC]/30 bg-[#f0f4f8] p-4">
                  <div className="text-sm font-semibold text-[#384959]">Resume Parse Quality</div>
                  <div className="mt-3 space-y-2 text-sm text-[#384959]">
                    <div className="flex items-center justify-between"><span>Diagnostics, 30d</span><span className="font-medium">{adminMetrics.resume_parse_quality?.diagnostic_uploads_30d ?? 0}</span></div>
                    <div className="flex items-center justify-between"><span>Needs review</span><span className="font-medium">{adminMetrics.resume_parse_quality?.needs_review_30d ?? 0}</span></div>
                    <div className="flex items-center justify-between"><span>Avg score</span><span className="font-medium">{adminMetrics.resume_parse_quality?.avg_score ?? "n/a"}</span></div>
                    <div className="flex items-center justify-between"><span>Good / Check / Review</span><span className="font-medium">{adminMetrics.resume_parse_quality?.labels?.good ?? 0} / {adminMetrics.resume_parse_quality?.labels?.check ?? 0} / {adminMetrics.resume_parse_quality?.labels?.review ?? 0}</span></div>
                  </div>
                  {(adminMetrics.resume_parse_quality?.top_warnings || []).length > 0 && (
                    <div className="mt-3 space-y-1 border-t border-[#BDDDFC]/30 pt-3 text-xs text-[#6A89A7]">
                      {adminMetrics.resume_parse_quality.top_warnings.slice(0, 2).map((item) => (
                        <div key={item.warning} className="flex gap-2">
                          <span className="font-semibold text-[#384959]">{item.count}</span>
                          <span>{item.warning}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>

              <div className="mt-5 rounded-xl border border-[#BDDDFC]/30 bg-white overflow-hidden">
                <div className="px-4 py-3 border-b border-[#BDDDFC]/20">
                  <div className="text-sm font-semibold text-[#384959]">Last 14 Days</div>
                  <div className="text-xs text-[#6A89A7] mt-1">Use this to sanity-check whether onboarding changes improve signup and resume activity.</div>
                </div>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead className="bg-[#f0f4f8]">
                      <tr>
                        <th className="text-left px-4 py-2 text-[#6A89A7] text-xs uppercase">Date</th>
                        <th className="text-right px-4 py-2 text-[#6A89A7] text-xs uppercase">Signups</th>
                        <th className="text-right px-4 py-2 text-[#6A89A7] text-xs uppercase">Resumes Saved</th>
                        <th className="text-right px-4 py-2 text-[#6A89A7] text-xs uppercase">Downloads</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-[#BDDDFC]/20">
                      {(adminMetrics.daily || []).map((row) => (
                        <tr key={row.date}>
                          <td className="px-4 py-2 text-[#384959]">{row.date}</td>
                          <td className="px-4 py-2 text-right text-[#384959]">{row.signups}</td>
                          <td className="px-4 py-2 text-right text-[#384959]">{row.resumes_saved}</td>
                          <td className="px-4 py-2 text-right text-[#384959]">{row.downloads}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </>
          ) : (
            <div className="text-sm text-[#6A89A7]">No admin metrics yet.</div>
          )}
        </div>
      )}

      <div className="bg-white border border-[#BDDDFC]/30 rounded-xl p-5">
        <h3 className="font-semibold text-[#384959] mb-3 flex items-center gap-2">
          <ShieldCheck size={17} /> Legal & Privacy
        </h3>
        <p className="text-sm text-[#6A89A7] mb-4">
          Job Hunter SG is a hobby project. Review the service limits, privacy handling, and alert consent terms here.
        </p>
        <div className="flex flex-col gap-3 sm:flex-row">
          <button
            type="button"
            onClick={() => window.open(`${API_BASE}/api/terms`, "_blank")}
            className="inline-flex items-center justify-center rounded-lg border border-[#BDDDFC]/30 bg-[#f0f4f8] px-4 py-2 text-sm font-medium text-[#384959] transition hover:bg-white active:scale-[0.98]"
          >
            Terms of Service
          </button>
          <button
            type="button"
            onClick={() => window.open(`${API_BASE}/api/privacy`, "_blank")}
            className="inline-flex items-center justify-center rounded-lg border border-[#BDDDFC]/30 bg-[#f0f4f8] px-4 py-2 text-sm font-medium text-[#384959] transition hover:bg-white active:scale-[0.98]"
          >
            Privacy Notice
          </button>
        </div>
      </div>

      {/* Tier Comparison */}
      <div className="bg-white border border-[#BDDDFC]/30 rounded-xl p-5">
        <h3 className="font-semibold text-[#384959] mb-4">Plan Comparison</h3>
        <div className="overflow-hidden rounded-lg border border-[#BDDDFC]/30">
          <table className="w-full text-sm">
            <thead className="bg-[#f0f4f8]">
              <tr>
                <th className="text-left px-4 py-3 text-[#6A89A7] text-xs uppercase">Feature</th>
                <th className="text-center px-4 py-3 text-[#6A89A7] text-xs uppercase">Free</th>
                <th className="text-center px-4 py-3 text-xs uppercase text-[#384959]">Pro / AISG</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#BDDDFC]/20">
              <tr>
                <td className="px-4 py-3 text-[#384959]">Job Searching</td>
                <td className="px-4 py-3 text-center text-[#6A89A7]">Unlimited</td>
                <td className="px-4 py-3 text-center text-[#384959] font-medium">Unlimited</td>
              </tr>
              <tr>
                <td className="px-4 py-3 text-[#384959]">AI Requests / day</td>
                <td className="px-4 py-3 text-center text-[#6A89A7]">500</td>
                <td className="px-4 py-3 text-center text-[#384959] font-medium">Unlimited</td>
              </tr>
              <tr>
                <td className="px-4 py-3 text-[#384959]">Resume Builder Chat</td>
                <td className="px-4 py-3 text-center text-green-600"><CheckCircle size={14} className="mx-auto" /></td>
                <td className="px-4 py-3 text-center text-green-600"><CheckCircle size={14} className="mx-auto" /></td>
              </tr>
              <tr>
                <td className="px-4 py-3 text-[#384959]">Cover Letter Generator</td>
                <td className="px-4 py-3 text-center text-green-600"><CheckCircle size={14} className="mx-auto" /></td>
                <td className="px-4 py-3 text-center text-green-600"><CheckCircle size={14} className="mx-auto" /></td>
              </tr>
              <tr>
                <td className="px-4 py-3 text-[#384959]">Smart Match (RAG)</td>
                <td className="px-4 py-3 text-center text-green-600"><CheckCircle size={14} className="mx-auto" /></td>
                <td className="px-4 py-3 text-center text-green-600"><CheckCircle size={14} className="mx-auto" /></td>
              </tr>
              <tr>
                <td className="px-4 py-3 text-[#384959]">Tracked Jobs</td>
                <td className="px-4 py-3 text-center text-[#6A89A7]">Sign in required</td>
                <td className="px-4 py-3 text-center text-[#384959] font-medium">Unlimited</td>
              </tr>
              <tr>
                <td className="px-4 py-3 text-[#384959]">ATS Scoring</td>
                <td className="px-4 py-3 text-center text-green-600"><CheckCircle size={14} className="mx-auto" /></td>
                <td className="px-4 py-3 text-center text-green-600"><CheckCircle size={14} className="mx-auto" /></td>
              </tr>
            </tbody>
          </table>
        </div>

        {!isPro && (
          <div className="mt-4 bg-gradient-to-r from-indigo-50 to-purple-50 border border-[#BDDDFC]/30 rounded-xl p-5">
            <div className="flex items-center gap-3 mb-2">
              <Star size={20} className="text-[#384959]" />
              <h4 className="font-semibold text-[#384959]">Upgrade to AISG Tier</h4>
            </div>
            <p className="text-sm text-[#6A89A7] mb-3">
              Sign in with an AISG account for unlimited AI requests, job tracking, and saved resume versions.
            </p>
            <p className="text-sm text-[#6A89A7]">
              Have questions? Send us a message below or reach out directly.
            </p>
          </div>
        )}
      </div>

      {/* Contact */}
      <div className="bg-white border border-[#BDDDFC]/30 rounded-xl p-5">
        <h3 className="font-semibold text-[#384959] mb-4">Get in Touch</h3>

        <div className="flex flex-wrap gap-3 mb-5">
          <span className="text-sm text-[#6A89A7]">Send us a message below or email us through the contact form.</span>
        </div>

        {contactSent && (
          <div className="bg-green-50 border border-green-200 text-green-700 text-sm rounded-lg p-3 mb-4">
            Message sent! We will get back to you soon.
          </div>
        )}
        {contactError && (
          <div className="bg-red-50 border border-red-200 text-red-700 text-sm rounded-lg p-3 mb-4">
            {contactError}
          </div>
        )}

        <form onSubmit={sendContact} className="space-y-3">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <input placeholder="Name" value={contactForm.name} onChange={(e) => setContactForm({ ...contactForm, name: e.target.value })}
              className="border border-[#BDDDFC]/30 rounded-lg px-3 py-2 text-sm" />
            <input placeholder="Email" type="email" value={contactForm.email} onChange={(e) => setContactForm({ ...contactForm, email: e.target.value })}
              className="border border-[#BDDDFC]/30 rounded-lg px-3 py-2 text-sm" />
          </div>
          <textarea placeholder="Your message..." value={contactForm.message} onChange={(e) => setContactForm({ ...contactForm, message: e.target.value })}
            className="w-full border border-[#BDDDFC]/30 rounded-lg px-3 py-2 text-sm" rows={3} />
          <button type="submit" disabled={contactSending || !contactForm.message.trim()}
            className="flex items-center gap-2 bg-[#384959] text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-[#2d3a47] disabled:opacity-40 transition">
            {contactSending ? <Loader2 size={14} className="animate-spin" /> : <Mail size={14} />}
            Send Message
          </button>
        </form>
      </div>

      {/* Logout */}
      <button onClick={onLogout}
        className="flex items-center gap-2 border border-red-200 text-red-600 px-4 py-2 rounded-lg text-sm font-medium hover:bg-red-50 transition w-full justify-center">
        <LogOut size={14} /> Sign Out
      </button>
    </div>
  );
}
