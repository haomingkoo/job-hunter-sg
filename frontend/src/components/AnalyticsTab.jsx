import { useState, useEffect, useMemo, useCallback } from "react";
import { Search, X, AlertCircle, RefreshCw } from "lucide-react";
import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
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
const AGENCY_SUBSET_OPTIONS = [
  { id: "public_sector", label: "Public sector" },
  { id: "ministries", label: "Ministries" },
  { id: "stat_boards", label: "Stat boards" },
  { id: "digital_gov", label: "Digital Gov" },
  { id: "defence_home", label: "Defence / Home Team" },
  { id: "transport", label: "Transport" },
  { id: "education_research", label: "Education / Research" },
  { id: "healthcare", label: "Healthcare" },
];

const PANEL = "rounded-[10px] border border-line bg-white p-5";
const H2 = "text-base font-semibold text-ink";
const H3 = "mb-2 text-sm font-semibold text-ink";
const NOTE = "mt-2 text-xs leading-relaxed text-muted";
const TEXT_BUTTON = "inline-flex min-h-10 items-center rounded-md px-2 text-sm font-medium text-accent transition-colors hover:bg-tint";
const SEARCH_FIELD = "min-h-10 w-full rounded-md border border-field bg-white pl-8 pr-9 text-sm text-ink focus:border-accent";

function BarRow({ rank, label, count, maxCount, active = false, onClick }) {
  const pct = maxCount > 0 ? Math.max(3, (count / maxCount) * 100) : 0;
  const content = (
    <>
      <div className="w-6 shrink-0 text-right text-xs tabular-nums text-muted">{rank}</div>
      <div className="min-w-0 flex-1">
        <div className="mb-1 flex items-center justify-between gap-3">
          <span className={`truncate text-sm text-ink ${active ? "font-semibold" : "font-medium"}`}>{label}</span>
          <span className="shrink-0 text-xs tabular-nums text-muted">{formatNumber(count)}</span>
        </div>
        <div className="h-2 overflow-hidden rounded-full bg-paper">
          <div className={`h-full rounded-full ${active ? "bg-ink" : "bg-accent"}`} style={{ width: `${pct}%` }} />
        </div>
      </div>
    </>
  );

  if (!onClick) {
    return <div className="flex items-center gap-3 px-2 py-1.5">{content}</div>;
  }

  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      title={`Filter by ${label}`}
      className={`flex min-h-11 w-full cursor-pointer items-center gap-3 rounded-md px-2 py-1.5 text-left transition-colors hover:bg-tint ${active ? "bg-tint" : ""}`}
    >
      {content}
    </button>
  );
}

function ChangeList({ items, nameKey, valueKey, suffix, detail, empty }) {
  if (!items?.length) return <p className="text-sm text-muted">{empty}</p>;
  return (
    <ul className="divide-y divide-line border-y border-line">
      {items.slice(0, 6).map((item) => (
        <li key={item[nameKey]} className="py-2">
          <div className="flex items-baseline justify-between gap-3">
            <span className="truncate text-sm font-medium text-ink">{item[nameKey]}</span>
            <span className="shrink-0 text-sm tabular-nums text-ink">{item[valueKey]}x {suffix}</span>
          </div>
          <div className="mt-0.5 text-xs tabular-nums text-muted">{detail(item)}</div>
        </li>
      ))}
    </ul>
  );
}

function HiringTrendTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  const count = payload.find((item) => item.dataKey === "count")?.value || 0;
  return (
    <div className="rounded-md border border-line bg-white px-3 py-2 shadow-lg">
      <div className="text-xs font-semibold text-ink">{label}</div>
      <div className="mt-1 text-xs tabular-nums text-muted">{formatNumber(count)} postings</div>
    </div>
  );
}

function HiringTrendChart({ trend }) {
  const series = trend?.series || [];
  const peak = trend?.peak;
  const latest = series[series.length - 1];

  return (
    <section className={PANEL} aria-labelledby="hiring-trend-title">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h2 id="hiring-trend-title" className={H2}>Hiring trend</h2>
          <p className="mt-1 text-sm text-muted">
            Postings per week for the current filters.
          </p>
        </div>
        <dl className="flex gap-6 text-xs text-muted sm:text-right">
          <div>
            <dd className="text-base font-semibold tabular-nums text-ink">{formatNumber(latest?.count)}</dd>
            <dt>latest week</dt>
          </div>
          <div>
            <dd className="text-base font-semibold tabular-nums text-ink">{formatNumber(peak?.count)}</dd>
            <dt>peak {peak?.label || ""}</dt>
          </div>
        </dl>
      </div>

      <div className="mt-4 h-64">
        {series.length > 0 ? (
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={series} margin={{ top: 12, right: 12, bottom: 8, left: 0 }}>
              <CartesianGrid stroke="#d3dde7" vertical={false} />
              <XAxis
                dataKey="label"
                interval="preserveStartEnd"
                minTickGap={24}
                tickMargin={8}
                padding={{ left: 24, right: 8 }}
                tick={{ fill: "#4f6b85", fontSize: 12 }}
                tickLine={false}
                axisLine={{ stroke: "#d3dde7" }}
              />
              <YAxis
                allowDecimals={false}
                tick={{ fill: "#4f6b85", fontSize: 12 }}
                tickLine={false}
                axisLine={false}
              />
              <Tooltip content={<HiringTrendTooltip />} cursor={{ fill: "rgba(31, 95, 153, 0.08)" }} />
              <Bar dataKey="count" name="Postings" fill="#c3d6ea" radius={[3, 3, 0, 0]} barSize={10} />
              <Line
                type="monotone"
                dataKey="count"
                name="Trend"
                stroke="#1f5f99"
                strokeWidth={2}
                dot={false}
                activeDot={{ r: 4, fill: "#1f5f99", stroke: "#ffffff", strokeWidth: 2 }}
              />
            </ComposedChart>
          </ResponsiveContainer>
        ) : (
          <div className="flex h-full items-center justify-center rounded-md border border-dashed border-line text-sm text-muted">No dated postings in this view yet.</div>
        )}
      </div>

      <div className="mt-5 grid grid-cols-1 gap-x-8 gap-y-5 lg:grid-cols-2">
        <div>
          <h3 className={H3}>Recent role mix</h3>
          {(trend?.recent_top_titles || []).slice(0, 6).map((item, index) => (
            <BarRow key={`trend-title-${item.title}`} rank={index + 1} label={item.title} count={item.count} maxCount={trend.recent_top_titles?.[0]?.count || 1} />
          ))}
        </div>
        <div>
          <h3 className={H3}>Recent ATS terms</h3>
          {(trend?.recent_ats_terms || []).slice(0, 6).map((item, index) => (
            <BarRow key={`trend-skill-${item.skill}`} rank={index + 1} label={item.skill} count={item.count} maxCount={trend.recent_ats_terms?.[0]?.count || 1} />
          ))}
        </div>
      </div>
    </section>
  );
}

export default function AnalyticsTab() {
  const [data, setData] = useState(null);
  const [trend, setTrend] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [sectorFilter, setSectorFilter] = useState("");
  const [companyFilter, setCompanyFilter] = useState("");
  const [companyDraft, setCompanyDraft] = useState("");
  const [titleFilter, setTitleFilter] = useState("");
  const [sourceFilter, setSourceFilter] = useState("");
  const [agencySubset, setAgencySubset] = useState("");
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
      if (agencySubset) params.set("agency_subset", agencySubset);
      if (directEmployersOnly) params.set("direct_employers_only", "true");
      const trendParams = new URLSearchParams(params);
      trendParams.delete("limit");
      trendParams.set("weeks", "52");
      const [resp, trendResp] = await Promise.all([
        apiFetch(`/api/analytics/skills?${params}`),
        // The trend chart is optional; a busy trend query must not hide the rest.
        apiFetch(`/api/analytics/trends?${trendParams}`).catch(() => null),
      ]);
      if (!resp.ok) throw new Error("Failed to load analytics");
      setData(await resp.json());
      setTrend(trendResp?.ok ? await trendResp.json() : null);
    } catch (err) {
      setError(err.message);
      setTrend(null);
    }
    setLoading(false);
  }, [sectorFilter, companyFilter, titleFilter, sourceFilter, agencySubset, directEmployersOnly]);

  useEffect(() => { loadData(); }, [loadData]);

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
  const agencySubsetOptions = data?.agency_subsets?.length ? data.agency_subsets : AGENCY_SUBSET_OPTIONS;
  const selectedAgencySubset = agencySubsetOptions.find((item) => item.id === agencySubset);
  const activeFilters = [
    selectedSource?.label || sourceFilter,
    sectorFilter,
    titleFilter,
    companyFilter,
    selectedAgencySubset?.label,
    directEmployersOnly ? "Hide known recruiters" : "",
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
    setAgencySubset("");
    setDirectEmployersOnly(false);
  };

  const hasFilters = Boolean(sourceFilter || sectorFilter || titleFilter || companyFilter || agencySubset || directEmployersOnly);
  const ready = !loading && !error && data;
  const summary = [
    { label: data?.partial ? "Sample roles analysed" : "Roles analysed", value: formatNumber(data?.total_jobs_with_terms) },
    { label: "Skill terms", value: formatNumber(data?.skill_signal_count) },
    { label: "Hiring orgs", value: formatNumber(data?.company_count) },
    { label: "Industry mapped", value: `${industryMappedPercent}%` },
  ];

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <div>
        <h1 className="text-xl font-bold tracking-[-0.01em] text-ink">Market insights</h1>
        <p className="mt-1 max-w-3xl text-sm text-muted">
          Skills, salaries and hiring activity from {data?.total_jobs_with_terms ? `${data.total_jobs_with_terms.toLocaleString()} listings` : "listings"} where skills could be read. This is not the live Jobs total.
        </p>
        {!loading && !error && data?.partial && (
          <p className="mt-1 max-w-3xl text-xs text-muted">
            Showing the latest {data.sampled_jobs?.toLocaleString()} matching listings for faster loading. Applying a filter rebuilds this sample from all matching listings, so a filtered count may be higher.
          </p>
        )}
      </div>

      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <p className="text-sm text-muted">
          {activeFilters.length > 0 ? (
            <>Filtered by <span className="font-semibold text-ink">{activeFilters.join(" + ")}</span></>
          ) : (
            <>Choose a source, sector, hiring org or title below to narrow every figure on this page.</>
          )}
        </p>
        {hasFilters && (
          <button type="button" onClick={clearAllFilters} className={`${TEXT_BUTTON} self-start sm:self-auto`}>
            Clear all filters
          </button>
        )}
      </div>

      {loading && (
        <div className="space-y-4" role="status">
          <span className="sr-only">Loading market insights</span>
          <div className="grid grid-cols-2 gap-px overflow-hidden rounded-[10px] border border-line bg-line sm:grid-cols-4">
            {[0, 1, 2, 3].map((cell) => (
              <div key={cell} className="bg-white px-4 py-3">
                <div className="h-5 w-16 rounded bg-paper" />
                <div className="mt-2 h-3 w-24 rounded bg-paper" />
              </div>
            ))}
          </div>
          <div className={`${PANEL} h-72`}>
            <div className="h-4 w-32 rounded bg-paper" />
            <div className="mt-6 h-48 rounded bg-paper" />
          </div>
        </div>
      )}

      {!loading && error && (
        <div className={`${PANEL} px-6 py-10 text-center`} role="alert">
          <AlertCircle size={24} aria-hidden="true" className="mx-auto mb-3 text-[#b42318]" />
          <p className="font-semibold text-ink">Market insights could not load</p>
          <p className="mx-auto mt-1 max-w-md text-sm text-muted">
            {/internal server error|bad gateway|service unavailable|gateway timeout|temporarily unavailable|failed to load analytics/i.test(error)
              ? "The figures are not available right now."
              : error}
          </p>
          {hasFilters && <p className="mx-auto mt-1 max-w-md text-sm text-muted">Your filters are kept.</p>}
          <button
            type="button"
            onClick={loadData}
            className="mt-5 inline-flex min-h-11 items-center gap-2 rounded-md bg-accent px-5 text-sm font-semibold text-white transition-colors hover:bg-accent-hover"
          >
            <RefreshCw size={14} aria-hidden="true" /> Try again
          </button>
        </div>
      )}

      {ready && (
        <dl className="grid grid-cols-2 gap-px overflow-hidden rounded-[10px] border border-line bg-line sm:grid-cols-4">
          {summary.map((item) => (
            <div key={item.label} className="bg-white px-4 py-3">
              <dd className="text-xl font-semibold tabular-nums text-ink">{item.value}</dd>
              <dt className="mt-0.5 text-xs text-muted">{item.label}</dt>
            </div>
          ))}
        </dl>
      )}

      {ready && (
        <section className={PANEL} aria-labelledby="market-signals-title">
          <h2 id="market-signals-title" className="sr-only">Market signals</h2>
          <dl className="grid grid-cols-1 gap-x-8 gap-y-5 md:grid-cols-2 xl:grid-cols-4">
            <div>
              <dt className="text-xs text-muted">Hiring freshness</dt>
              <dd className="mt-0.5 text-base font-semibold tabular-nums text-ink">{`${formatNumber(freshness.last_30)} roles`}</dd>
              <dd className="mt-1 text-xs leading-relaxed text-muted">{`${freshness.last_30_percent || 0}% of dated postings were listed in the last 30 days.`}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted">Listed salary range</dt>
              <dd className="mt-0.5 text-base font-semibold tabular-nums text-ink">{formatSalaryRange(salary)}</dd>
              <dd className="mt-1 text-xs leading-relaxed text-muted">{`${salary.coverage_percent || 0}% of analysed roles list a salary. Floor is the advertised lower bound; mid is the middle of the range.`}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted">Largest seniority segment</dt>
              <dd className="mt-0.5 text-base font-semibold text-ink">{data.seniority_mix?.[0]?.label || "n/a"}</dd>
              <dd className="mt-1 text-xs leading-relaxed text-muted">{data.seniority_mix?.[0] ? `${data.seniority_mix[0].percent}% of this view sits here.` : "Seniority is read from job titles when the posting does not state it."}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted">Skill signal</dt>
              <dd className="mt-0.5 text-base font-semibold text-ink">{data.overindexed_skills?.length ? "Niche signals found" : "Market baseline"}</dd>
              <dd className="mt-1 text-xs leading-relaxed text-muted">{data.overindexed_skills?.length ? "These terms appear unusually often in the selected slice." : "Filter by sector or title to see which skills stand out."}</dd>
            </div>
          </dl>
          {sectorSourceMix.length > 0 && (
            <p className="mt-5 border-t border-line pt-4 text-xs leading-relaxed text-muted">
              Industry labels: {sectorSourceMix.map((item) => `${formatNumber(item.count)} ${sectorSourceLabels[item.source] || item.label}`).join(" / ")}.
              Most listings do not publish SSIC directly, so inferred labels keep the market view usable.
              Careers@Gov postings are normalised to ministries and agencies where possible.
            </p>
          )}
        </section>
      )}

      {ready && trend && <HiringTrendChart trend={trend} />}

      {ready && (
        <section className={PANEL} aria-labelledby="explore-market-title">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <h2 id="explore-market-title" className={H2}>Explore the market</h2>
              <p className="mt-1 text-sm text-muted">
                Pick a source, sector, hiring org or job title to refresh skills, salary, freshness and seniority.
              </p>
            </div>
            <div>
              <div className="inline-flex rounded-md border border-field bg-white p-0.5" role="group" aria-label="Employers to include">
                {[[false, "All orgs"], [true, "Hide known recruiters"]].map(([value, label]) => (
                  <button
                    key={label}
                    type="button"
                    onClick={() => setDirectEmployersOnly(value)}
                    aria-pressed={directEmployersOnly === value}
                    className={`min-h-10 whitespace-nowrap rounded px-3 text-sm transition-colors ${directEmployersOnly === value ? "bg-tint font-semibold text-ink" : "text-muted hover:text-ink"}`}
                  >
                    {label}
                  </button>
                ))}
              </div>
              <p className="mt-1 text-xs text-muted">
                Verified direct and unverified employers remain eligible.
              </p>
            </div>
          </div>
          <div className="mt-5">
            <h3 className={H3}>Agency subsets</h3>
            <div className="flex flex-wrap gap-2">
              {agencySubsetOptions.map((item) => {
                const active = agencySubset === item.id;
                return (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => setAgencySubset(active ? "" : item.id)}
                    aria-pressed={active}
                    className={`inline-flex min-h-10 items-center gap-1.5 rounded-md border px-3 text-sm transition-colors ${active ? "border-accent bg-tint font-semibold text-ink" : "border-field bg-white text-ink hover:bg-tint"}`}
                  >
                    <span>{item.label}</span>
                    {!agencySubset && Number.isFinite(Number(item.count)) && (
                      <span className="text-xs tabular-nums text-muted">{formatNumber(item.count)}</span>
                    )}
                  </button>
                );
              })}
            </div>
          </div>
          <div className="mt-6 grid gap-x-6 gap-y-6 xl:grid-cols-4">
            <div>
              <h3 className={H3}>{data?.partial ? "Sources in analysed sample" : "Sources"}</h3>
              <div className="grid grid-cols-1 gap-x-4 sm:grid-cols-2 xl:grid-cols-1">
                {(data.sources || []).slice(0, 6).map((item, index) => (
                  <BarRow
                    key={`drill-source-${item.source}`}
                    rank={index + 1}
                    label={item.label || item.source}
                    count={item.count}
                    maxCount={sourcesMaxCount}
                    active={sourceFilter === item.source}
                    onClick={() => setSourceFilter(sourceFilter === item.source ? "" : item.source)}
                  />
                ))}
              </div>
              <p className={NOTE}>
                Use this to isolate a job source before checking departments, industries and skills.
              </p>
            </div>
            <div>
              <h3 className={H3}>Industry / Sector</h3>
              <div className="grid grid-cols-1 gap-x-4 sm:grid-cols-2 xl:grid-cols-1">
                {(data.sectors || []).slice(0, 8).map((item, index) => (
                  <BarRow
                    key={`drill-sector-${item.sector}`}
                    rank={index + 1}
                    label={item.sector}
                    count={item.count}
                    maxCount={sectorsMaxCount}
                    active={sectorFilter === item.sector}
                    onClick={() => setSectorFilter(sectorFilter === item.sector ? "" : item.sector)}
                  />
                ))}
              </div>
              {(data.sectors || []).some((item) => item.sector === "Other") && (
                <p className={NOTE}>
                  Other means the listing could not be mapped to a clear industry.
                </p>
              )}
            </div>
            <div>
              <h3 className={H3}>Hiring orgs</h3>
              <form
                className="relative mb-2"
                role="search"
                onSubmit={(event) => {
                  event.preventDefault();
                  applyCompanyFilter(companyDraft);
                }}
              >
                <Search size={14} aria-hidden="true" className="absolute left-2.5 top-1/2 -translate-y-1/2 text-muted" />
                <input
                  type="text"
                  value={companyDraft}
                  onChange={(event) => setCompanyDraft(event.target.value)}
                  aria-label="Filter by org or agency"
                  placeholder="Filter org or agency..."
                  className={SEARCH_FIELD}
                />
                {companyDraft && (
                  <button
                    type="button"
                    onClick={() => applyCompanyFilter("")}
                    aria-label="Clear org filter"
                    className="absolute right-1 top-1/2 inline-flex h-8 w-8 -translate-y-1/2 items-center justify-center rounded text-muted hover:text-ink"
                  >
                    <X size={14} aria-hidden="true" />
                  </button>
                )}
              </form>
              <div className="grid grid-cols-1 gap-x-4 sm:grid-cols-2 xl:grid-cols-1">
                {(data.top_companies || []).slice(0, 8).map((item, index) => (
                  <BarRow
                    key={`drill-company-${item.company}`}
                    rank={index + 1}
                    label={item.company}
                    count={item.count}
                    maxCount={companiesMaxCount}
                    active={companyFilter === item.company}
                    onClick={() => applyCompanyFilter(companyFilter === item.company ? "" : item.company)}
                  />
                ))}
              </div>
              <p className={NOTE}>
                Government rows use the ministry or agency when the source names it.
              </p>
            </div>
            <div>
              <h3 className={H3}>Job titles</h3>
              <div className="grid grid-cols-1 gap-x-4 sm:grid-cols-2 xl:grid-cols-1">
                {(data.top_titles || []).slice(0, 8).map((item, index) => (
                  <BarRow
                    key={`drill-title-${item.title}`}
                    rank={index + 1}
                    label={item.title}
                    count={item.count}
                    maxCount={titlesMaxCount}
                    active={titleFilter === item.title}
                    onClick={() => setTitleFilter(titleFilter === item.title ? "" : item.title)}
                  />
                ))}
              </div>
            </div>
          </div>
        </section>
      )}

      {ready && ((movers.rising || []).length > 0 || (movers.cooling || []).length > 0) && (
        <section className={PANEL} aria-labelledby="market-movers-title">
          <div className="flex flex-col gap-1 sm:flex-row sm:items-end sm:justify-between">
            <div>
              <h2 id="market-movers-title" className={H2}>Skills on the move</h2>
              <p className="mt-1 text-sm text-muted">
                Recent postings compared with older dated postings in this view.
              </p>
            </div>
            <p className="text-xs tabular-nums text-muted">
              {formatNumber(movers.recent_total)} recent / {formatNumber(movers.older_total)} older
            </p>
          </div>
          <div className="mt-4 grid grid-cols-1 gap-x-8 gap-y-5 lg:grid-cols-2">
            <div>
              <h3 className={H3}>Rising recently</h3>
              <ChangeList
                items={movers.rising}
                nameKey="skill"
                valueKey="lift"
                suffix="more"
                detail={(item) => `${item.recent_rate_percent}% recent vs ${item.older_rate_percent}% older`}
                empty="No recent over-index signal in this slice yet."
              />
            </div>
            <div>
              <h3 className={H3}>Cooling in recent postings</h3>
              <ChangeList
                items={movers.cooling}
                nameKey="skill"
                valueKey="drop"
                suffix="less"
                detail={(item) => `${item.recent_rate_percent}% recent vs ${item.older_rate_percent}% older`}
                empty="No cooling signal in this slice yet."
              />
            </div>
          </div>
        </section>
      )}

      {ready && ((data.top_companies || []).length > 0 || (companyMovers.rising || []).length > 0 || (companyMovers.cooling || []).length > 0) && (
        <section className={PANEL} aria-labelledby="org-snapshot-title">
          <div className="flex flex-col gap-1 sm:flex-row sm:items-end sm:justify-between">
            <div>
              <h2 id="org-snapshot-title" className={H2}>Who is hiring</h2>
              <p className="mt-1 max-w-3xl text-sm text-muted">
                Top ministries, agencies and companies in this view. Hide known recruiters to remove recognised recruitment firms; unverified employers remain.
              </p>
            </div>
            <p className="text-xs tabular-nums text-muted">
              {formatNumber(companyMovers.recent_total)} recent / {formatNumber(companyMovers.older_total)} older
            </p>
          </div>
          <div className="mt-4 grid grid-cols-1 gap-x-8 gap-y-5 xl:grid-cols-3">
            <div>
              <h3 className={H3}>Most active</h3>
              {(data.top_companies || []).slice(0, 6).map((item, index) => (
                <BarRow
                  key={`org-snapshot-${item.company}`}
                  rank={index + 1}
                  label={item.company}
                  count={item.count}
                  maxCount={companiesMaxCount}
                  active={companyFilter === item.company}
                  onClick={() => applyCompanyFilter(companyFilter === item.company ? "" : item.company)}
                />
              ))}
            </div>
            <div>
              <h3 className={H3}>Hiring more recently</h3>
              <ChangeList
                items={companyMovers.rising}
                nameKey="company"
                valueKey="lift"
                suffix="more"
                detail={(item) => `${formatNumber(item.recent_count)} recent vs ${formatNumber(item.older_count)} older`}
                empty="No hiring spike in this slice yet."
              />
            </div>
            <div>
              <h3 className={H3}>Hiring less recently</h3>
              <ChangeList
                items={companyMovers.cooling}
                nameKey="company"
                valueKey="drop"
                suffix="less"
                detail={(item) => `${formatNumber(item.recent_count)} recent vs ${formatNumber(item.older_count)} older`}
                empty="No slowdown in this slice yet."
              />
            </div>
          </div>
        </section>
      )}

      {ready && (
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1.1fr)_minmax(320px,0.9fr)]">
          <section className={PANEL} aria-labelledby="hard-skills-title">
            <h2 id="hard-skills-title" className={`${H2} mb-3`}>Hard skills</h2>
            {(data.hard_skills || []).length > 0 ? (
              <div className="grid grid-cols-1 gap-x-4 lg:grid-cols-2">
                {data.hard_skills.slice(0, 10).map((item, index) => (
                  <BarRow
                    key={item.skill}
                    rank={index + 1}
                    label={item.skill}
                    count={item.count}
                    maxCount={hardSkillsMaxCount}
                  />
                ))}
              </div>
            ) : (
              <p className="text-sm text-muted">No hard-skill signal is available for this slice yet.</p>
            )}
            <p className={`${NOTE} mt-4`}>
              Common terms like communication and customer service appear everywhere. Stronger resume alignment usually comes from exact tools, certifications and domain terms.
            </p>
          </section>

          <section className={PANEL} aria-labelledby="standout-skills-title">
            <h2 id="standout-skills-title" className={`${H2} mb-3`}>Standout skills</h2>
            {(data.overindexed_skills || []).length > 0 ? (
              <ChangeList
                items={data.overindexed_skills.slice(0, 8)}
                nameKey="skill"
                valueKey="lift"
                suffix="the market rate"
                detail={(item) => `${item.rate_percent}% in this view vs ${item.market_rate_percent}% market-wide`}
              />
            ) : (
              <p className="text-sm leading-relaxed text-muted">
                Pick a sector or job title to see skills that appear unusually often compared with the overall market.
              </p>
            )}
          </section>
        </div>
      )}

      {ready && data?.seniority_mix?.length > 0 && (
        <section className={PANEL} aria-labelledby="seniority-title">
          <h2 id="seniority-title" className={`${H2} mb-3`}>Seniority mix</h2>
          <div className="grid grid-cols-1 gap-x-4 lg:grid-cols-2">
            {data.seniority_mix.map((item, index) => (
              <BarRow
                key={item.label}
                rank={index + 1}
                label={`${item.label} (${item.percent}%)`}
                count={item.count}
                maxCount={seniorityMaxCount}
              />
            ))}
          </div>
        </section>
      )}

      {ready && data?.salary_insights?.by_sector?.length > 0 && (
        <section className={PANEL} aria-labelledby="salary-sector-title">
          <h2 id="salary-sector-title" className={`${H2} mb-3`}>Listed salary by industry</h2>
          <ul className="grid grid-cols-1 gap-x-8 lg:grid-cols-2">
            {data.salary_insights.by_sector.map((item) => (
              <li key={item.sector} className="flex items-center justify-between gap-3 border-b border-line py-2">
                <div className="min-w-0">
                  <div className="truncate text-sm font-medium text-ink">{item.sector}</div>
                  <div className="text-xs tabular-nums text-muted">{formatNumber(item.count)} salary-listed roles</div>
                </div>
                <div className="shrink-0 text-right">
                  <div className="text-sm font-semibold tabular-nums text-ink">{formatMoney(item.median_floor)}</div>
                  <div className="text-xs text-muted">median floor</div>
                  {item.median_midpoint ? (
                    <div className="text-xs tabular-nums text-ink">
                      {formatMoney(item.median_midpoint)} midpoint
                    </div>
                  ) : null}
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}

      {ready && data?.sectors?.length > 0 && (
        <section className={PANEL} aria-labelledby="sector-demand-title">
          <div className="mb-3 flex items-center justify-between gap-3">
            <h2 id="sector-demand-title" className={H2}>Demand by industry</h2>
            {sectorFilter && (
              <button type="button" onClick={() => setSectorFilter("")} className={TEXT_BUTTON}>
                Clear sector
              </button>
            )}
          </div>
          <div className="grid grid-cols-1 gap-x-4 lg:grid-cols-2">
            {data.sectors.map((item, index) => (
              <BarRow
                key={item.sector}
                rank={index + 1}
                label={item.sector}
                count={item.count}
                maxCount={sectorsMaxCount}
                active={sectorFilter === item.sector}
                onClick={() => setSectorFilter(sectorFilter === item.sector ? "" : item.sector)}
              />
            ))}
          </div>
        </section>
      )}

      {ready && data?.top_titles?.length > 0 && (
        <section className={PANEL} aria-labelledby="top-titles-title">
          <div className="mb-3 flex items-center justify-between gap-3">
            <h2 id="top-titles-title" className={H2}>
              Top {data.top_titles.length} job titles
            </h2>
            {titleFilter && (
              <button type="button" onClick={() => setTitleFilter("")} className={TEXT_BUTTON}>
                Clear title filter
              </button>
            )}
          </div>
          {titleFilter && (
            <p className="mb-3 text-sm text-ink">
              Showing skills for: <strong>{titleFilter}</strong>
            </p>
          )}
          <div className="grid grid-cols-1 gap-x-4 lg:grid-cols-2">
            {data.top_titles.map((item, index) => (
              <BarRow
                key={item.title}
                rank={index + 1}
                label={item.title}
                count={item.count}
                maxCount={titlesMaxCount}
                active={titleFilter === item.title}
                onClick={() => setTitleFilter(titleFilter === item.title ? "" : item.title)}
              />
            ))}
          </div>
        </section>
      )}

      {ready && data?.top_companies?.length > 0 && (
        <section className={PANEL} aria-labelledby="top-companies-title">
          <div className="mb-3 flex items-center justify-between gap-3">
            <h2 id="top-companies-title" className={H2}>Top hiring agencies and companies</h2>
            {companyFilter && (
              <button type="button" onClick={() => applyCompanyFilter("")} className={TEXT_BUTTON}>
                Clear company
              </button>
            )}
          </div>
          <div className="grid grid-cols-1 gap-x-4 lg:grid-cols-2">
            {data.top_companies.slice(0, 16).map((item, index) => (
              <BarRow
                key={item.company}
                rank={index + 1}
                label={item.company}
                count={item.count}
                maxCount={companiesMaxCount}
                active={companyFilter === item.company}
                onClick={() => applyCompanyFilter(companyFilter === item.company ? "" : item.company)}
              />
            ))}
          </div>
        </section>
      )}

      {ready && (data?.top_skills?.length || 0) > 0 && (
        <section className={PANEL} aria-labelledby="top-skills-title">
          <div className="mb-3 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <h2 id="top-skills-title" className={H2}>
              Most requested skills
            </h2>
            <div className="relative sm:w-56">
              <Search size={14} aria-hidden="true" className="absolute left-2.5 top-1/2 -translate-y-1/2 text-muted" />
              <input
                type="text"
                value={skillSearch}
                onChange={(e) => { setSkillSearch(e.target.value); setShowCount(30); }}
                aria-label="Filter skills"
                placeholder="Filter skills..."
                className={SEARCH_FIELD}
              />
              {skillSearch && (
                <button
                  type="button"
                  onClick={() => setSkillSearch("")}
                  aria-label="Clear skill filter"
                  className="absolute right-1 top-1/2 inline-flex h-8 w-8 -translate-y-1/2 items-center justify-center rounded text-muted hover:text-ink"
                >
                  <X size={14} aria-hidden="true" />
                </button>
              )}
            </div>
          </div>
          {skillSearch && (
            <p className="mb-3 text-xs text-muted">
              {filteredSkills.length} skill{filteredSkills.length !== 1 ? "s" : ""} matching "{skillSearch}"
            </p>
          )}
          {visibleSkills.length > 0 ? (
            <>
              <div className="grid grid-cols-1 gap-x-4 lg:grid-cols-2">
                {visibleSkills.map((item, index) => (
                  <BarRow
                    key={item.skill}
                    rank={index + 1}
                    label={item.skill}
                    count={item.count}
                    maxCount={maxCount}
                  />
                ))}
              </div>
              {filteredSkills.length > showCount && (
                <button
                  type="button"
                  onClick={() => setShowCount((c) => c + 30)}
                  className={`mt-3 ${TEXT_BUTTON}`}
                >
                  Show more ({filteredSkills.length - showCount} remaining)
                </button>
              )}
            </>
          ) : (
            <p className="py-6 text-center text-sm text-muted">
              No skills match "{skillSearch}"
            </p>
          )}
        </section>
      )}

      {ready && (data?.top_skills?.length || 0) === 0 && (
        <div className={`${PANEL} px-6 py-12 text-center`}>
          <p className="font-semibold text-ink">No skill data for this view yet</p>
          <p className="mx-auto mt-1 max-w-md text-sm text-muted">
            Skills are read from each posting as it is added.{hasFilters ? " Try removing a filter." : " Check back tomorrow."}
          </p>
          {hasFilters && (
            <button type="button" onClick={clearAllFilters} className={`mt-3 ${TEXT_BUTTON}`}>
              Clear all filters
            </button>
          )}
        </div>
      )}
    </div>
  );
}
