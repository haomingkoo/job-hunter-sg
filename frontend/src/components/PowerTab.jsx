import { useState, useEffect, useCallback } from "react";
import {
  Plus, AlertCircle, ExternalLink, RefreshCw,
  Loader2, Sparkles, FileText, MapPin, DollarSign, Building2,
} from "lucide-react";
import { apiFetch } from "../lib/api.js";
import { todayStr, getScoreTheme } from "../lib/helpers.js";

export default function PowerTab({ onTrack, setSelectedJob, setActiveTab }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [trackError, setTrackError] = useState("");

  const loadPowerMatches = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const resp = await apiFetch("/api/jobs/power-match?limit=8");
      const payload = await resp.json();
      setData(payload);
    } catch (err) {
      setError(err.message || "Failed to load power matches.");
      setData(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadPowerMatches();
  }, [loadPowerMatches]);

  const trackJob = async (item) => {
    setTrackError("");
    try {
      await onTrack({
        company: item.job.company,
        role: item.job.title,
        date_applied: todayStr(),
        status: "applied",
        source: item.job.source,
        follow_up_date: new Date(Date.now() + 14 * 86400000).toISOString().split("T")[0],
        notes: `Power Match ${item.suitability_score}/100 | Missing: ${(item.missing_skills || []).join(", ")}`,
        scraped_job_id: item.job.id,
      });
    } catch (err) {
      setTrackError(err.message || "Failed to track job.");
    }
  };

  const tailorResume = (item) => {
    setSelectedJob({
      id: item.job.id,
      title: item.job.title,
      company: item.job.company,
      location: item.job.location || "",
      salary: item.job.salary || "",
      source: item.job.source || "",
      posted: item.job.posted_date || "",
      skills: item.job.skills || [],
      description: item.job.description || "",
      type: item.job.employment_type || "",
      level: item.job.seniority || "",
      url: item.job.url || "",
    });
    setActiveTab("resume");
  };

  return (
    <div className="space-y-6">
      <div className="rounded-3xl border border-indigo-200 bg-[linear-gradient(135deg,_rgba(238,242,255,1)_0%,_rgba(255,255,255,1)_42%,_rgba(243,232,255,1)_100%)] p-6 shadow-sm">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <div className="text-xs font-semibold uppercase tracking-[0.2em] text-indigo-500">Power Match</div>
            <h2 className="mt-2 flex items-center gap-2 text-2xl font-semibold text-gray-900">
              <Sparkles size={20} />
              Suitability, gaps, and bridge paths
            </h2>
            <p className="mt-2 max-w-3xl text-sm leading-relaxed text-gray-600">
              This view uses the latest stored version of your resume. We show what matched, what is missing, and where the job data itself is incomplete instead of guessing.
            </p>
          </div>
          <button
            type="button"
            onClick={loadPowerMatches}
            className="inline-flex items-center gap-2 rounded-xl border border-white bg-white px-4 py-2.5 text-sm font-medium text-gray-700 shadow-sm hover:bg-gray-50"
          >
            <RefreshCw size={14} />
            Refresh Matches
          </button>
        </div>
      </div>

      {trackError && (
        <div className="bg-red-50 border border-red-200 text-red-700 text-sm rounded-lg p-3 flex items-center gap-2">
          <AlertCircle size={14} className="flex-shrink-0" />{trackError}
        </div>
      )}

      {loading && (
        <div className="text-center py-12">
          <Loader2 size={32} className="animate-spin text-indigo-500 mx-auto" />
          <p className="mt-3 text-sm text-gray-500">Building power matches from your stored resume...</p>
        </div>
      )}

      {!loading && error && (
        <div className="rounded-2xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          {error}
        </div>
      )}

      {!loading && !error && data && !data.resume_ready && (
        <div className="rounded-3xl border border-gray-200 bg-white p-6 shadow-sm">
          <div className="text-lg font-semibold text-gray-900">Resume needed for Power Match</div>
          <p className="mt-2 max-w-2xl text-sm leading-relaxed text-gray-600">
            Upload or score a resume first. Once we have that version on file, we can shortlist roles, score suitability, and show the gaps worth bridging.
          </p>
          <button
            type="button"
            onClick={() => setActiveTab("resume")}
            className="mt-4 inline-flex items-center gap-2 rounded-xl bg-indigo-600 px-4 py-2.5 text-sm font-medium text-white hover:bg-indigo-700"
          >
            <FileText size={14} />
            Go To Resume Workspace
          </button>
        </div>
      )}

      {!loading && !error && data?.resume_ready && (
        <>
          <div className="grid gap-4 xl:grid-cols-[minmax(0,1.2fr)_minmax(320px,0.8fr)]">
            <div className="rounded-3xl border border-gray-200 bg-white p-5 shadow-sm">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <div className="text-sm font-semibold text-gray-800">Detected Resume Skills</div>
                  <div className="mt-1 text-xs text-gray-500">
                    {data.resume_signal_mode === "skill_corpus"
                      ? "Skills were matched against the roles in our current job dataset."
                      : "Skills were extracted directly from your latest stored resume."}
                  </div>
                </div>
                <span className="inline-flex h-10 min-w-10 items-center justify-center rounded-2xl bg-indigo-600 px-2 text-sm font-bold text-white">
                  {data.resume_skills?.length || 0}
                </span>
              </div>
              <div className="mt-4 flex flex-wrap gap-2">
                {(data.resume_skills || []).map((skill) => (
                  <span key={skill} className="rounded-full bg-indigo-50 px-2.5 py-1 text-xs font-medium text-indigo-700">
                    {skill}
                  </span>
                ))}
              </div>
            </div>

            <div className="rounded-3xl border border-gray-200 bg-white p-5 shadow-sm">
              <div className="text-sm font-semibold text-gray-800">Repeated Gaps</div>
              <div className="mt-1 text-xs text-gray-500">These appear most often across the better-fit roles.</div>
              <div className="mt-4 space-y-2">
                {(data.top_gaps || []).length > 0 ? data.top_gaps.map((gap) => (
                  <div key={gap.skill} className="flex items-center justify-between rounded-2xl bg-gray-50 px-3 py-2">
                    <span className="text-sm font-medium text-gray-800">{gap.skill}</span>
                    <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[11px] font-semibold text-amber-800">
                      {gap.count} role{gap.count === 1 ? "" : "s"}
                    </span>
                  </div>
                )) : (
                  <div className="rounded-2xl bg-emerald-50 px-3 py-3 text-sm text-emerald-800">
                    No repeated gap is dominating your strongest matches right now.
                  </div>
                )}
              </div>
            </div>
          </div>

          {data.recommended_queries?.length > 0 && (
            <div className="rounded-3xl border border-gray-200 bg-white p-5 shadow-sm">
              <div className="text-sm font-semibold text-gray-800">Suggested Role Directions</div>
              <div className="mt-1 text-xs text-gray-500">Useful titles to explore further while searching.</div>
              <div className="mt-4 flex flex-wrap gap-2">
                {data.recommended_queries.map((query) => (
                  <span key={query} className="rounded-full bg-gray-100 px-3 py-1 text-sm text-gray-700">
                    {query}
                  </span>
                ))}
              </div>
            </div>
          )}

          <div className="space-y-4">
            {(data.recommendations || []).map((item) => {
              const theme = getScoreTheme(item.suitability_score || 0);
              return (
                <div key={item.job.id} className="rounded-3xl border border-gray-200 bg-white p-5 shadow-sm">
                  <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
                    <div className="flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <h3 className="text-lg font-semibold text-gray-900">{item.job.title}</h3>
                        <span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${theme.pill}`}>
                          {item.suitability_label}
                        </span>
                      </div>
                      <div className="mt-2 flex flex-wrap items-center gap-4 text-sm text-gray-500">
                        <span className="flex items-center gap-1"><Building2 size={13} />{item.job.company}</span>
                        <span className="flex items-center gap-1"><MapPin size={13} />{item.job.location || "Location unavailable"}</span>
                        <span className="flex items-center gap-1"><DollarSign size={13} />{item.job.salary || "Salary unavailable"}</span>
                        <span>{item.job.employment_type || "Employment type unavailable"}</span>
                        {item.job.seniority && <span>{item.job.seniority}</span>}
                      </div>
                      <div className="mt-3 text-sm leading-relaxed text-gray-600">{item.why}</div>
                    </div>

                    <div className={`rounded-2xl border px-4 py-3 text-center shadow-sm ${theme.panel}`}>
                      <div className="text-[11px] font-semibold uppercase tracking-[0.16em] text-gray-500">Suitability</div>
                      <div className={`mt-1 text-3xl font-bold ${theme.text}`}>{item.suitability_score}</div>
                      <div className="mt-2 h-2 w-36 overflow-hidden rounded-full bg-white/80">
                        <div className={`h-full rounded-full ${theme.bar}`} style={{ width: `${item.suitability_score}%` }} />
                      </div>
                    </div>
                  </div>

                  <div className="mt-5 grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(320px,0.95fr)]">
                    <div className="space-y-4">
                      <div>
                        <div className="text-xs font-semibold uppercase tracking-[0.16em] text-gray-500">Matched Skills</div>
                        <div className="mt-2 flex flex-wrap gap-2">
                          {(item.matched_skills || []).length > 0 ? item.matched_skills.map((skill) => (
                            <span key={skill} className="rounded-full bg-emerald-100 px-2.5 py-1 text-xs font-medium text-emerald-700">
                              {skill}
                            </span>
                          )) : (
                            <span className="text-sm text-gray-500">No strong overlap detected yet.</span>
                          )}
                        </div>
                      </div>

                      <div>
                        <div className="text-xs font-semibold uppercase tracking-[0.16em] text-gray-500">Missing Skills</div>
                        <div className="mt-2 flex flex-wrap gap-2">
                          {(item.missing_skills || []).length > 0 ? item.missing_skills.map((skill) => (
                            <span key={skill} className="rounded-full bg-rose-100 px-2.5 py-1 text-xs font-medium text-rose-700">
                              {skill}
                            </span>
                          )) : (
                            <span className="text-sm text-gray-500">No clear named gap surfaced on this role.</span>
                          )}
                        </div>
                      </div>
                    </div>

                    <div className="rounded-2xl border border-gray-100 bg-gray-50 p-4">
                      <div className="text-sm font-semibold text-gray-800">Bridge Path</div>
                      <div className="mt-3 space-y-3">
                        {(item.bridge_plan || []).length > 0 ? item.bridge_plan.map((bridge) => (
                          <div key={`${item.job.id}-${bridge.skill}`} className="rounded-2xl bg-white px-3 py-3 shadow-sm">
                            <div className="flex items-center justify-between gap-3">
                              <div className="text-sm font-semibold text-gray-800">{bridge.skill}</div>
                              <span className="rounded-full bg-indigo-100 px-2 py-0.5 text-[11px] font-semibold text-indigo-700">
                                {bridge.pathway}
                              </span>
                            </div>
                            <div className="mt-2 text-sm leading-relaxed text-gray-600">{bridge.suggestion}</div>
                          </div>
                        )) : (
                          <div className="text-sm text-gray-500">
                            No specific bridge path needed yet. This one already looks relatively aligned.
                          </div>
                        )}
                      </div>
                    </div>
                  </div>

                  <div className="mt-5 flex flex-wrap gap-2 border-t border-gray-100 pt-4">
                    <button
                      type="button"
                      onClick={() => tailorResume(item)}
                      className="inline-flex items-center gap-2 rounded-xl bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-700"
                    >
                      <FileText size={14} />
                      Tailor Resume
                    </button>
                    <button
                      type="button"
                      onClick={() => trackJob(item)}
                      className="inline-flex items-center gap-2 rounded-xl bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700"
                    >
                      <Plus size={14} />
                      Track Job
                    </button>
                    {item.job.url && (
                      <a
                        href={item.job.url}
                        target="_blank"
                        rel="noreferrer"
                        className="inline-flex items-center gap-2 rounded-xl border border-gray-200 bg-white px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
                      >
                        <ExternalLink size={14} />
                        View Posting
                      </a>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}
