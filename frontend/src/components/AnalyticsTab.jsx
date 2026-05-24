import { useState, useEffect, useMemo, useCallback } from "react";
import {
  Search, X, Loader2, BarChart2, Building2, Briefcase, Tags,
  TrendingUp, Clock, BadgeDollarSign, Layers, Target, ShieldCheck,
} from "lucide-react";
import { apiFetch } from "../lib/api.js";

const formatNumber = (value) => Number(value || 0).toLocaleString();
const formatPercent = (value) => Number(value || 0).toLocaleString(undefined, { maximumFractionDigits: 1 });
const formatMoney = (value) => (value ? `S$${formatNumber(value)}` : "n/a");
const formatSalaryRange = (salary) => {
  if (salary?.median_floor && salary?.median_midpoint) {
    return `${formatMoney(salary.median_floor)} floor / ${formatMoney(salary.median_midpoint)} mid`;
  }
  return formatMoney(salary?.median_floor);
};

function StatTile({ icon: Icon, label, value }) {
  return (
    <div className="rounded-xl border border-[#BDDDFC]/30 bg-white px-4 py-3 shadow-sm">
      <div className="flex items-center justify-between gap-3">
        <div>
          <div className="text-xs font-medium uppercase text-[#6A89A7]">{label}</div>
          <div className="mt-1 text-2xl font-semibold text-[#384959]">{value}</div>
        </div>
        <Icon size={18} className="text-[#88BDF2]" />
      </div>
    </div>
  );
}

function SignalBlock({ icon: Icon, label, value, detail }) {
  return (
    <div className="rounded-xl border border-[#BDDDFC]/30 bg-white px-4 py-3 shadow-sm">
      <div className="flex items-start gap-3">
        <div className="mt-0.5 rounded-lg bg-[#BDDDFC]/15 p-2 text-[#384959]">
          <Icon size={16} />
        </div>
        <div className="min-w-0">
          <div className="text-xs font-medium uppercase text-[#6A89A7]">{label}</div>
          <div className="mt-1 text-lg font-semibold text-[#384959]">{value}</div>
          {detail && <div className="mt-1 text-xs leading-relaxed text-[#6A89A7]">{detail}</div>}
        </div>
      </div>
    </div>
  );
}

function BarRow({ rank, label, count, maxCount, active = false, color = "bg-[#88BDF2]", onClick }) {
  const pct = maxCount > 0 ? Math.max(3, (count / maxCount) * 100) : 0;
  const content = (
    <>
      <div className="w-7 shrink-0 text-right font-mono text-xs text-[#6A89A7]">{rank}</div>
      <div className="min-w-0 flex-1">
        <div className="mb-1 flex items-center justify-between gap-3">
          <span className="truncate text-sm font-medium text-[#384959]">{label}</span>
          <span className="shrink-0 font-mono text-xs text-[#6A89A7]">{formatNumber(count)}</span>
        </div>
        <div className="h-2.5 overflow-hidden rounded-full bg-[#f0f4f8]">
          <div className={`h-full rounded-full ${active ? "bg-[#384959]" : color}`} style={{ width: `${pct}%` }} />
        </div>
      </div>
    </>
  );

  if (!onClick) {
    return <div className="flex items-center gap-3 rounded-lg px-2 py-1.5">{content}</div>;
  }

  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      title={`Filter by ${label}`}
      className={`flex w-full cursor-pointer items-center gap-3 rounded-lg px-2 py-1.5 text-left transition hover:bg-[#f0f4f8] active:scale-[0.99] ${active ? "bg-[#BDDDFC]/15 ring-1 ring-[#BDDDFC]" : ""}`}
    >
      {content}
    </button>
  );
}

export default function AnalyticsTab() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [sectorFilter, setSectorFilter] = useState("");
  const [companyFilter, setCompanyFilter] = useState("");
  const [companyDraft, setCompanyDraft] = useState("");
  const [titleFilter, setTitleFilter] = useState("");
  const [sourceFilter, setSourceFilter] = useState("");
  const [directEmployersOnly, setDirectEmployersOnly] = useState(false);
  const [showCount, setShowCount] = useState(30);
  const [skillSearch, setSkillSearch] = useState("");

  const loadData = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const params = new URLSearchParams({ limit: "200" });
      if (sectorFilter) params.set("sector", sectorFilter);
      if (companyFilter) params.set("company", companyFilter);
      if (titleFilter) params.set("title", titleFilter);
      if (sourceFilter) params.set("source", sourceFilter);
      if (directEmployersOnly) params.set("direct_employers_only", "true");
      const resp = await apiFetch(`/api/analytics/skills?${params}`);
      if (!resp.ok) throw new Error("Failed to load analytics");
      setData(await resp.json());
    } catch (err) {
      setError(err.message);
    }
    setLoading(false);
  }, [sectorFilter, companyFilter, titleFilter, sourceFilter, directEmployersOnly]);

  useEffect(() => { loadData(); }, [loadData]);

  // Client-side skill search filter
  const filteredSkills = useMemo(() => {
    const skills = data?.top_skills || [];
    if (!skillSearch.trim()) return skills;
    const q = skillSearch.trim().toLowerCase();
    return skills.filter((s) => s.skill.toLowerCase().includes(q));
  }, [data?.top_skills, skillSearch]);

  const maxCount = filteredSkills[0]?.count || 1;
  const visibleSkills = filteredSkills.slice(0, showCount);

  const titlesMaxCount = data?.top_titles?.[0]?.count || 1;
  const sectorsMaxCount = data?.sectors?.[0]?.count || 1;
  const sourcesMaxCount = data?.sources?.[0]?.count || 1;
  const companiesMaxCount = data?.top_companies?.[0]?.count || 1;
  const hardSkillsMaxCount = data?.hard_skills?.[0]?.count || 1;
  const seniorityMaxCount = Math.max(...(data?.seniority_mix || []).map((item) => item.count || 0), 1);
  const selectedSource = (data?.sources || []).find((item) => item.source === sourceFilter);
  const activeFilters = [
    selectedSource?.label || sourceFilter,
    sectorFilter,
    titleFilter,
    companyFilter,
    directEmployersOnly ? "Direct employers" : "",
  ].filter(Boolean);
  const salary = data?.salary_insights || {};
  const freshness = data?.freshness || {};
  const movers = data?.market_movers || {};
  const companyMovers = data?.company_movers || {};
  const ssicCoverage = data?.ssic_coverage || {};
  const sectorSourceMix = data?.sector_source_mix || [];
  const industryMappedCount = (ssicCoverage.official_count || 0) + (ssicCoverage.inferred_count || 0);
  const industryMappedPercent = data?.total_jobs_with_terms
    ? formatPercent((industryMappedCount / data.total_jobs_with_terms) * 100)
    : "0";
  const sectorSourceLabels = {
    acra: "official company matches",
    inferred: "inferred from postings",
    unavailable: "uncategorised",
  };

  const chartColors = ["bg-[#88BDF2]", "bg-emerald-500", "bg-violet-500", "bg-amber-500", "bg-rose-500", "bg-cyan-500"];
  const applyCompanyFilter = (value) => {
    const next = String(value || "").trim();
    setCompanyFilter(next);
    setCompanyDraft(next);
  };
  const clearAllFilters = () => {
    setSourceFilter("");
    setSectorFilter("");
    setTitleFilter("");
    setCompanyFilter("");
    setCompanyDraft("");
    setDirectEmployersOnly(false);
  };

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <div>
        <h2 className="flex items-center gap-2 text-2xl font-semibold text-[#384959]">
          <BarChart2 size={20} />
          Market Insights
        </h2>
        <p className="mt-1 text-sm text-[#6A89A7]">
          Skill and salary trends from {data?.total_jobs_with_terms?.toLocaleString() || "..."} Singapore job listings.
        </p>
      </div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatTile icon={Briefcase} label="Roles analysed" value={data?.total_jobs_with_terms ? formatNumber(data.total_jobs_with_terms) : "..."} />
        <StatTile icon={Tags} label="Skill terms" value={data?.skill_signal_count ? formatNumber(data.skill_signal_count) : "..."} />
        <StatTile icon={Building2} label="Hiring orgs" value={data?.company_count ? formatNumber(data.company_count) : "..."} />
        <StatTile icon={ShieldCheck} label="Industry mapped" value={`${industryMappedPercent}%`} />
      </div>

      <div className="rounded-2xl border border-[#BDDDFC]/30 bg-white p-4 shadow-sm">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="text-xs text-[#6A89A7]">
            {activeFilters.length > 0 ? (
              <>Filtered by <span className="font-semibold text-[#384959]">{activeFilters.join(" + ")}</span></>
            ) : (
              <>Click a source, industry/sector, hiring org, or title to drill into skill demand.</>
            )}
          </div>
          {(sourceFilter || sectorFilter || titleFilter || companyFilter || directEmployersOnly) && (
            <button
              type="button"
              onClick={clearAllFilters}
              className="rounded-lg border border-[#BDDDFC]/30 px-3 py-1.5 text-xs text-[#6A89A7] hover:bg-[#f0f4f8]"
            >
              Clear All Filters
            </button>
          )}
        </div>
      </div>

      {!loading && !error && sectorSourceMix.length > 0 && (
        <div className="rounded-2xl border border-[#BDDDFC]/30 bg-white p-4 text-xs leading-relaxed text-[#6A89A7] shadow-sm">
          Industry labels: {sectorSourceMix.map((item) => `${formatNumber(item.count)} ${sectorSourceLabels[item.source] || item.label}`).join(" / ")}.
          Most listings do not publish SSIC directly, so inferred labels keep the market view usable.
          Careers@Gov postings are normalised to ministries and agencies where possible.
        </div>
      )}

      {!loading && !error && data && (
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-4">
          <SignalBlock
            icon={Clock}
            label="Hiring freshness"
            value={`${formatNumber(freshness.last_30)} roles`}
            detail={`${freshness.last_30_percent || 0}% of dated postings were listed in the last 30 days.`}
          />
          <SignalBlock
            icon={BadgeDollarSign}
            label="Listed salary range"
            value={formatSalaryRange(salary)}
            detail={`${salary.coverage_percent || 0}% of analysed roles expose salary data. Floor is the advertised lower bound, midpoint is the range middle.`}
          />
          <SignalBlock
            icon={Layers}
            label="Largest seniority segment"
            value={data.seniority_mix?.[0]?.label || "n/a"}
            detail={data.seniority_mix?.[0] ? `${data.seniority_mix[0].percent}% of this view sits here.` : "Seniority is inferred from titles when posting metadata is weak."}
          />
          <SignalBlock
            icon={ShieldCheck}
            label="Skill signal"
            value={data.overindexed_skills?.length ? "Niche signals found" : "Market baseline"}
            detail={data.overindexed_skills?.length ? "These terms appear unusually often in the selected slice." : "Filter by industry/sector or title to see what over-indexes."}
          />
        </div>
      )}

      {!loading && !error && data && (
        <div className="rounded-2xl border border-[#BDDDFC]/30 bg-white p-5 shadow-sm">
          <div className="flex flex-col gap-1 sm:flex-row sm:items-end sm:justify-between">
            <div>
              <div className="text-sm font-semibold text-[#384959]">Explore Market</div>
              <div className="text-xs leading-relaxed text-[#6A89A7]">
                Pick a source, industry/sector, hiring org, or job title to refresh skills, salary, freshness, and seniority.
              </div>
            </div>
            <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
              <div className="inline-flex overflow-hidden rounded-lg border border-[#BDDDFC]/40 bg-[#f0f4f8] p-0.5 text-xs font-medium">
                <button
                  type="button"
                  onClick={() => setDirectEmployersOnly(false)}
                  className={`rounded-md px-2.5 py-1.5 transition ${!directEmployersOnly ? "bg-white text-[#384959] shadow-sm" : "text-[#6A89A7] hover:text-[#384959]"}`}
                >
                  All orgs
                </button>
                <button
                  type="button"
                  onClick={() => setDirectEmployersOnly(true)}
                  className={`rounded-md px-2.5 py-1.5 transition ${directEmployersOnly ? "bg-white text-[#384959] shadow-sm" : "text-[#6A89A7] hover:text-[#384959]"}`}
                >
                  Direct employers
                </button>
              </div>
              {(sourceFilter || sectorFilter || titleFilter || companyFilter || directEmployersOnly) && (
                <button
                  type="button"
                  onClick={clearAllFilters}
                  className="self-start rounded-lg border border-[#BDDDFC]/30 px-3 py-1.5 text-xs font-medium text-[#384959] hover:bg-[#f0f4f8] sm:self-auto"
                >
                  Clear Filters
                </button>
              )}
            </div>
          </div>
          <div className="mt-4 grid gap-4 xl:grid-cols-4">
            <div>
              <div className="mb-2 text-[11px] font-semibold uppercase tracking-[0.14em] text-[#6A89A7]">Sources</div>
              <div className="grid grid-cols-1 gap-1.5 sm:grid-cols-2 xl:grid-cols-1">
                {(data.sources || []).slice(0, 6).map((item, index) => (
                  <BarRow
                    key={`drill-source-${item.source}`}
                    rank={index + 1}
                    label={item.label || item.source}
                    count={item.count}
                    maxCount={sourcesMaxCount}
                    color="bg-violet-500"
                    active={sourceFilter === item.source}
                    onClick={() => setSourceFilter(sourceFilter === item.source ? "" : item.source)}
                  />
                ))}
              </div>
              <div className="mt-2 text-[11px] leading-relaxed text-[#6A89A7]">
                Use this to isolate a job source before checking departments, industries, and skills.
              </div>
            </div>
            <div>
              <div className="mb-2 text-[11px] font-semibold uppercase tracking-[0.14em] text-[#6A89A7]">Industry / Sector</div>
              <div className="grid grid-cols-1 gap-1.5 sm:grid-cols-2 xl:grid-cols-1">
                {(data.sectors || []).slice(0, 8).map((item, index) => (
                  <BarRow
                    key={`drill-sector-${item.sector}`}
                    rank={index + 1}
                    label={item.sector}
                    count={item.count}
                    maxCount={sectorsMaxCount}
                    color={chartColors[index % chartColors.length]}
                    active={sectorFilter === item.sector}
                    onClick={() => setSectorFilter(sectorFilter === item.sector ? "" : item.sector)}
                  />
                ))}
              </div>
              {(data.sectors || []).some((item) => item.sector === "Other") && (
                <div className="mt-2 text-[11px] leading-relaxed text-[#6A89A7]">
                  Other means the listing could not be mapped to a clear industry.
                </div>
              )}
            </div>
            <div>
              <div className="mb-2 text-[11px] font-semibold uppercase tracking-[0.14em] text-[#6A89A7]">Hiring Orgs</div>
              <form
                className="relative mb-2"
                onSubmit={(event) => {
                  event.preventDefault();
                  applyCompanyFilter(companyDraft);
                }}
              >
                <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-[#6A89A7]" />
                <input
                  type="text"
                  value={companyDraft}
                  onChange={(event) => setCompanyDraft(event.target.value)}
                  placeholder="Filter org or agency..."
                  className="w-full rounded-lg border border-[#BDDDFC]/30 bg-[#f0f4f8] py-1.5 pl-8 pr-8 text-xs text-[#384959] placeholder-[#6A89A7] focus:border-[#88BDF2] focus:outline-none focus:ring-1 focus:ring-[#BDDDFC]"
                />
                {companyDraft && (
                  <button
                    type="button"
                    onClick={() => applyCompanyFilter("")}
                    className="absolute right-2 top-1/2 -translate-y-1/2 text-[#6A89A7] hover:text-[#384959]"
                  >
                    <X size={12} />
                  </button>
                )}
              </form>
              <div className="grid grid-cols-1 gap-1.5 sm:grid-cols-2 xl:grid-cols-1">
                {(data.top_companies || []).slice(0, 8).map((item, index) => (
                  <BarRow
                    key={`drill-company-${item.company}`}
                    rank={index + 1}
                    label={item.company}
                    count={item.count}
                    maxCount={companiesMaxCount}
                    color="bg-violet-500"
                    active={companyFilter === item.company}
                    onClick={() => applyCompanyFilter(companyFilter === item.company ? "" : item.company)}
                  />
                ))}
              </div>
              <div className="mt-2 text-[11px] leading-relaxed text-[#6A89A7]">
                Govt rows use resolved ministries or agencies when the source exposes enough signal.
              </div>
            </div>
            <div>
              <div className="mb-2 text-[11px] font-semibold uppercase tracking-[0.14em] text-[#6A89A7]">Job Titles</div>
              <div className="grid grid-cols-1 gap-1.5 sm:grid-cols-2 xl:grid-cols-1">
                {(data.top_titles || []).slice(0, 8).map((item, index) => (
                  <BarRow
                    key={`drill-title-${item.title}`}
                    rank={index + 1}
                    label={item.title}
                    count={item.count}
                    maxCount={titlesMaxCount}
                    color="bg-emerald-500"
                    active={titleFilter === item.title}
                    onClick={() => setTitleFilter(titleFilter === item.title ? "" : item.title)}
                  />
                ))}
              </div>
            </div>
          </div>
        </div>
      )}

      {!loading && !error && data && ((movers.rising || []).length > 0 || (movers.cooling || []).length > 0) && (
        <div className="rounded-2xl border border-[#BDDDFC]/30 bg-white p-5 shadow-sm">
          <div className="flex flex-col gap-1 sm:flex-row sm:items-end sm:justify-between">
            <div>
              <div className="flex items-center gap-2 text-sm font-semibold text-[#384959]">
                <TrendingUp size={16} />
                Market Movers
              </div>
              <div className="mt-1 text-xs leading-relaxed text-[#6A89A7]">
                Recent postings are compared with older dated postings in this view.
              </div>
            </div>
            <div className="text-[11px] text-[#6A89A7]">
              {formatNumber(movers.recent_total)} recent / {formatNumber(movers.older_total)} older
            </div>
          </div>
          <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
            <div>
              <div className="mb-2 text-[11px] font-semibold uppercase tracking-[0.14em] text-emerald-700">Rising recently</div>
              <div className="space-y-2">
                {(movers.rising || []).length > 0 ? (
                  movers.rising.slice(0, 6).map((item) => (
                    <div key={`rising-${item.skill}`} className="rounded-xl bg-emerald-50 px-3 py-2">
                      <div className="flex items-center justify-between gap-3">
                        <span className="truncate text-sm font-medium text-[#384959]">{item.skill}</span>
                        <span className="shrink-0 rounded-full bg-emerald-100 px-2 py-0.5 text-[11px] font-semibold text-emerald-800">{item.lift}x</span>
                      </div>
                      <div className="mt-1 text-xs text-[#6A89A7]">
                        {item.recent_rate_percent}% recent vs {item.older_rate_percent}% older
                      </div>
                    </div>
                  ))
                ) : (
                  <div className="rounded-xl bg-[#f0f4f8] px-3 py-3 text-sm text-[#6A89A7]">No recent over-index signal in this slice yet.</div>
                )}
              </div>
            </div>
            <div>
              <div className="mb-2 text-[11px] font-semibold uppercase tracking-[0.14em] text-rose-700">Cooling in recent postings</div>
              <div className="space-y-2">
                {(movers.cooling || []).length > 0 ? (
                  movers.cooling.slice(0, 6).map((item) => (
                    <div key={`cooling-${item.skill}`} className="rounded-xl bg-rose-50 px-3 py-2">
                      <div className="flex items-center justify-between gap-3">
                        <span className="truncate text-sm font-medium text-[#384959]">{item.skill}</span>
                        <span className="shrink-0 rounded-full bg-rose-100 px-2 py-0.5 text-[11px] font-semibold text-rose-800">{item.drop}x</span>
                      </div>
                      <div className="mt-1 text-xs text-[#6A89A7]">
                        {item.recent_rate_percent}% recent vs {item.older_rate_percent}% older
                      </div>
                    </div>
                  ))
                ) : (
                  <div className="rounded-xl bg-[#f0f4f8] px-3 py-3 text-sm text-[#6A89A7]">No cooling signal in this slice yet.</div>
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      {!loading && !error && data && ((data.top_companies || []).length > 0 || (companyMovers.rising || []).length > 0 || (companyMovers.cooling || []).length > 0) && (
        <div className="rounded-2xl border border-[#BDDDFC]/30 bg-white p-5 shadow-sm">
          <div className="flex flex-col gap-1 sm:flex-row sm:items-end sm:justify-between">
            <div>
              <div className="flex items-center gap-2 text-sm font-semibold text-[#384959]">
                <Building2 size={16} />
                Hiring Org Snapshot
              </div>
              <div className="mt-1 text-xs leading-relaxed text-[#6A89A7]">
                Top ministries, agencies, and companies in this view. Use direct-employer mode to remove recruitment firms from this snapshot.
              </div>
            </div>
            <div className="text-[11px] text-[#6A89A7]">
              {formatNumber(companyMovers.recent_total)} recent / {formatNumber(companyMovers.older_total)} older
            </div>
          </div>
          <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-3">
            <div>
              <div className="mb-2 text-[11px] font-semibold uppercase tracking-[0.14em] text-[#6A89A7]">Most active</div>
              <div className="space-y-1.5">
                {(data.top_companies || []).slice(0, 6).map((item, index) => (
                  <BarRow
                    key={`org-snapshot-${item.company}`}
                    rank={index + 1}
                    label={item.company}
                    count={item.count}
                    maxCount={companiesMaxCount}
                    color="bg-violet-500"
                    active={companyFilter === item.company}
                    onClick={() => applyCompanyFilter(companyFilter === item.company ? "" : item.company)}
                  />
                ))}
              </div>
            </div>
            <div>
              <div className="mb-2 text-[11px] font-semibold uppercase tracking-[0.14em] text-emerald-700">Hiring more recently</div>
              <div className="space-y-2">
                {(companyMovers.rising || []).length > 0 ? (
                  companyMovers.rising.slice(0, 6).map((item) => (
                    <div key={`company-rising-${item.company}`} className="rounded-xl bg-emerald-50 px-3 py-2">
                      <div className="flex items-center justify-between gap-3">
                        <span className="truncate text-sm font-medium text-[#384959]">{item.company}</span>
                        <span className="shrink-0 rounded-full bg-emerald-100 px-2 py-0.5 text-[11px] font-semibold text-emerald-800">{item.lift}x</span>
                      </div>
                      <div className="mt-1 text-xs text-[#6A89A7]">
                        {formatNumber(item.recent_count)} recent vs {formatNumber(item.older_count)} older
                      </div>
                    </div>
                  ))
                ) : (
                  <div className="rounded-xl bg-[#f0f4f8] px-3 py-3 text-sm text-[#6A89A7]">No hiring spike in this slice yet.</div>
                )}
              </div>
            </div>
            <div>
              <div className="mb-2 text-[11px] font-semibold uppercase tracking-[0.14em] text-rose-700">Hiring less recently</div>
              <div className="space-y-2">
                {(companyMovers.cooling || []).length > 0 ? (
                  companyMovers.cooling.slice(0, 6).map((item) => (
                    <div key={`company-cooling-${item.company}`} className="rounded-xl bg-rose-50 px-3 py-2">
                      <div className="flex items-center justify-between gap-3">
                        <span className="truncate text-sm font-medium text-[#384959]">{item.company}</span>
                        <span className="shrink-0 rounded-full bg-rose-100 px-2 py-0.5 text-[11px] font-semibold text-rose-800">{item.drop}x</span>
                      </div>
                      <div className="mt-1 text-xs text-[#6A89A7]">
                        {formatNumber(item.recent_count)} recent vs {formatNumber(item.older_count)} older
                      </div>
                    </div>
                  ))
                ) : (
                  <div className="rounded-xl bg-[#f0f4f8] px-3 py-3 text-sm text-[#6A89A7]">No slowdown in this slice yet.</div>
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      {!loading && !error && data && (
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1.1fr)_minmax(320px,0.9fr)]">
          <div className="rounded-2xl border border-[#BDDDFC]/30 bg-white p-5 shadow-sm">
            <div className="mb-4 flex items-center gap-2 text-sm font-semibold text-[#384959]">
              <Target size={16} />
              Hard Skills
            </div>
            <div className="grid grid-cols-1 gap-1.5 lg:grid-cols-2">
              {(data.hard_skills || []).length > 0 ? (
                data.hard_skills.slice(0, 10).map((item, index) => (
                  <BarRow
                    key={item.skill}
                    rank={index + 1}
                    label={item.skill}
                    count={item.count}
                    maxCount={hardSkillsMaxCount}
                    color="bg-cyan-500"
                  />
                ))
              ) : (
                <div className="rounded-xl bg-[#f0f4f8] px-3 py-3 text-sm text-[#6A89A7]">
                  No hard-skill signal is available for this slice yet.
                </div>
              )}
            </div>
            <div className="mt-4 rounded-xl bg-[#f0f4f8] px-3 py-2 text-xs leading-relaxed text-[#6A89A7]">
              Common terms like communication and customer service appear everywhere. Stronger resume alignment usually comes from exact tools, certifications, and domain terms.
            </div>
          </div>

          <div className="rounded-2xl border border-[#BDDDFC]/30 bg-white p-5 shadow-sm">
            <div className="mb-4 flex items-center gap-2 text-sm font-semibold text-[#384959]">
              <TrendingUp size={16} />
              Standout Skills
            </div>
            {(data.overindexed_skills || []).length > 0 ? (
              <div className="space-y-2">
                {data.overindexed_skills.slice(0, 8).map((item) => (
                  <div key={item.skill} className="rounded-xl bg-[#f0f4f8] px-3 py-2">
                    <div className="flex items-center justify-between gap-3">
                      <span className="truncate text-sm font-medium text-[#384959]">{item.skill}</span>
                      <span className="shrink-0 rounded-full bg-emerald-100 px-2 py-0.5 text-[11px] font-semibold text-emerald-800">
                        {item.lift}x
                      </span>
                    </div>
                    <div className="mt-1 text-xs text-[#6A89A7]">
                      {item.rate_percent}% in this view vs {item.market_rate_percent}% market-wide
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="rounded-xl bg-[#f0f4f8] px-3 py-3 text-sm leading-relaxed text-[#6A89A7]">
                Pick an industry/sector or job title to reveal skills that appear unusually often compared with the overall market.
              </div>
            )}
          </div>
        </div>
      )}

      {!loading && !error && data?.seniority_mix?.length > 0 && (
        <div className="rounded-2xl border border-[#BDDDFC]/30 bg-white p-5 shadow-sm">
          <div className="mb-4 text-sm font-semibold text-[#384959]">Seniority Mix</div>
          <div className="grid grid-cols-1 gap-1.5 lg:grid-cols-2">
            {data.seniority_mix.map((item, index) => (
              <BarRow
                key={item.label}
                rank={index + 1}
                label={`${item.label} (${item.percent}%)`}
                count={item.count}
                maxCount={seniorityMaxCount}
                color={chartColors[index % chartColors.length]}
              />
            ))}
          </div>
        </div>
      )}

      {!loading && !error && data?.salary_insights?.by_sector?.length > 0 && (
        <div className="rounded-2xl border border-[#BDDDFC]/30 bg-white p-5 shadow-sm">
          <div className="mb-4 text-sm font-semibold text-[#384959]">Listed Salary by Industry / Sector</div>
          <div className="grid grid-cols-1 gap-2 lg:grid-cols-2">
            {data.salary_insights.by_sector.map((item) => (
              <div key={item.sector} className="flex items-center justify-between gap-3 rounded-xl bg-[#f0f4f8] px-3 py-2">
                <div className="min-w-0">
                  <div className="truncate text-sm font-medium text-[#384959]">{item.sector}</div>
                  <div className="text-xs text-[#6A89A7]">{formatNumber(item.count)} salary-listed roles</div>
                </div>
                <div className="shrink-0 text-right">
                  <div className="text-sm font-semibold text-[#384959]">{formatMoney(item.median_floor)}</div>
                  <div className="text-[11px] text-[#6A89A7]">median floor</div>
                  {item.median_midpoint ? (
                    <div className="mt-0.5 text-[11px] font-medium text-[#384959]">
                      {formatMoney(item.median_midpoint)} midpoint
                    </div>
                  ) : null}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {loading && (
        <div className="flex items-center gap-2 py-12 justify-center text-[#6A89A7]">
          <Loader2 size={18} className="animate-spin" />
          Loading analytics...
        </div>
      )}

      {error && (
        <div className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
          {error}
        </div>
      )}

      {/* Sectors */}
      {!loading && !error && data?.sectors?.length > 0 && (
        <div className="rounded-2xl border border-[#BDDDFC]/30 bg-white p-5 shadow-sm">
          <div className="mb-4 flex items-center justify-between">
            <div className="text-sm font-semibold text-[#384959]">Industry / Sector Demand</div>
            {sectorFilter && (
              <button type="button" onClick={() => setSectorFilter("")} className="text-xs text-[#88BDF2] hover:text-[#384959]">
                Clear sector
              </button>
            )}
          </div>
          <div className="grid grid-cols-1 gap-1.5 lg:grid-cols-2">
            {data.sectors.map((item, index) => (
              <BarRow
                key={item.sector}
                rank={index + 1}
                label={item.sector}
                count={item.count}
                maxCount={sectorsMaxCount}
                color={chartColors[index % chartColors.length]}
                active={sectorFilter === item.sector}
                onClick={() => setSectorFilter(sectorFilter === item.sector ? "" : item.sector)}
              />
            ))}
          </div>
        </div>
      )}

      {/* Top Job Titles */}
      {!loading && !error && data?.top_titles?.length > 0 && (
        <div className="rounded-2xl border border-[#BDDDFC]/30 bg-white p-5 shadow-sm">
          <div className="flex items-center justify-between mb-4">
            <div className="text-sm font-semibold text-[#384959]">
              Top {data.top_titles.length} Job Titles
            </div>
            {titleFilter && (
              <button type="button" onClick={() => setTitleFilter("")} className="text-xs text-[#88BDF2] hover:text-[#384959]">
                Clear title filter
              </button>
            )}
          </div>
          {titleFilter && (
            <div className="mb-3 rounded-lg bg-[#BDDDFC]/15 px-3 py-2 text-xs text-[#384959]">
              Showing skills for: <strong>{titleFilter}</strong>
            </div>
          )}
          <div className="grid grid-cols-1 gap-1.5 lg:grid-cols-2">
            {data.top_titles.map((item, index) => (
              <BarRow
                key={item.title}
                rank={index + 1}
                label={item.title}
                count={item.count}
                maxCount={titlesMaxCount}
                color="bg-emerald-500"
                active={titleFilter === item.title}
                onClick={() => setTitleFilter(titleFilter === item.title ? "" : item.title)}
              />
            ))}
          </div>
        </div>
      )}

      {/* Top Companies */}
      {!loading && !error && data?.top_companies?.length > 0 && (
        <div className="rounded-2xl border border-[#BDDDFC]/30 bg-white p-5 shadow-sm">
          <div className="mb-4 flex items-center justify-between gap-3">
            <div className="text-sm font-semibold text-[#384959]">Top Hiring Agencies / Companies</div>
            {companyFilter && (
              <button type="button" onClick={() => applyCompanyFilter("")} className="text-xs text-[#88BDF2] hover:text-[#384959]">
                Clear company
              </button>
            )}
          </div>
          <div className="grid grid-cols-1 gap-1.5 lg:grid-cols-2">
            {data.top_companies.slice(0, 16).map((item, index) => (
              <BarRow
                key={item.company}
                rank={index + 1}
                label={item.company}
                count={item.count}
                maxCount={companiesMaxCount}
                color="bg-violet-500"
                active={companyFilter === item.company}
                onClick={() => applyCompanyFilter(companyFilter === item.company ? "" : item.company)}
              />
            ))}
          </div>
        </div>
      )}

      {/* Skills with search filter */}
      {!loading && !error && (data?.top_skills?.length || 0) > 0 && (
        <div className="rounded-2xl border border-[#BDDDFC]/30 bg-white p-5 shadow-sm">
          <div className="flex items-center justify-between mb-4">
            <div className="text-sm font-semibold text-[#384959]">
              Top In-Demand Skills
            </div>
            <div className="relative">
              <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-[#6A89A7]" />
              <input
                type="text"
                value={skillSearch}
                onChange={(e) => { setSkillSearch(e.target.value); setShowCount(30); }}
                placeholder="Filter skills..."
                className="rounded-lg border border-[#BDDDFC]/30 bg-[#f0f4f8] py-1.5 pl-8 pr-3 text-xs text-[#384959] placeholder-[#6A89A7] focus:border-[#88BDF2] focus:outline-none focus:ring-1 focus:ring-[#BDDDFC] w-48"
              />
              {skillSearch && (
                <button
                  type="button"
                  onClick={() => setSkillSearch("")}
                  className="absolute right-2 top-1/2 -translate-y-1/2 text-[#6A89A7] hover:text-[#384959]"
                >
                  <X size={12} />
                </button>
              )}
            </div>
          </div>
          {skillSearch && (
            <div className="text-xs text-[#6A89A7] mb-3">
              {filteredSkills.length} skill{filteredSkills.length !== 1 ? "s" : ""} matching "{skillSearch}"
            </div>
          )}
          {visibleSkills.length > 0 ? (
            <>
              <div className="grid grid-cols-1 gap-1.5 lg:grid-cols-2">
                {visibleSkills.map((item, index) => (
                  <BarRow
                    key={item.skill}
                    rank={index + 1}
                    label={item.skill}
                    count={item.count}
                    maxCount={maxCount}
                    color="bg-[#88BDF2]"
                  />
                ))}
              </div>
              {filteredSkills.length > showCount && (
                <button
                  type="button"
                  onClick={() => setShowCount((c) => c + 30)}
                  className="mt-4 text-xs font-medium text-[#384959] hover:text-[#2d3a47]"
                >
                  Show more ({filteredSkills.length - showCount} remaining)...
                </button>
              )}
            </>
          ) : (
            <div className="py-6 text-center text-sm text-[#6A89A7]">
              No skills match "{skillSearch}"
            </div>
          )}
        </div>
      )}

      {!loading && !error && (data?.top_skills?.length || 0) === 0 && (
        <div className="text-center py-12 text-[#6A89A7]">
          <BarChart2 size={32} className="mx-auto mb-2 opacity-40" />
          <p>No skill data available yet. Skills are extracted as jobs are processed.</p>
        </div>
      )}
    </div>
  );
}
