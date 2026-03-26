import { useState, useEffect, useMemo, useCallback } from "react";
import { Search, X, Loader2, BarChart2 } from "lucide-react";
import { apiFetch } from "../lib/api.js";

export default function AnalyticsTab() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [sectorFilter, setSectorFilter] = useState("");
  const [companyFilter, setCompanyFilter] = useState("");
  const [titleFilter, setTitleFilter] = useState("");
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
      const resp = await apiFetch(`/api/analytics/skills?${params}`);
      if (!resp.ok) throw new Error("Failed to load analytics");
      setData(await resp.json());
    } catch (err) {
      setError(err.message);
    }
    setLoading(false);
  }, [sectorFilter, companyFilter, titleFilter]);

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

  // Sector color palette
  const sectorColors = [
    "bg-blue-100 text-blue-800", "bg-emerald-100 text-emerald-800",
    "bg-violet-100 text-violet-800", "bg-amber-100 text-amber-800",
    "bg-rose-100 text-rose-800", "bg-cyan-100 text-cyan-800",
    "bg-pink-100 text-pink-800", "bg-lime-100 text-lime-800",
    "bg-orange-100 text-orange-800", "bg-teal-100 text-teal-800",
    "bg-indigo-100 text-indigo-800", "bg-fuchsia-100 text-fuchsia-800",
    "bg-[#BDDDFC]/10 text-[#384959]",
  ];

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <div>
        <h2 className="flex items-center gap-2 text-2xl font-semibold text-[#384959]">
          <BarChart2 size={20} />
          Market Insights
        </h2>
        <p className="mt-1 text-sm text-[#6A89A7]">
          Job market breakdown across {data?.total_jobs_with_terms?.toLocaleString() || "..."} listings with extracted ATS terms.
        </p>
      </div>

      <div className="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
        <strong>Beta</strong> — Free to use with 500 AI requests/day to help fund hosting and API costs. Data refreshes nightly.
      </div>

      <div className="rounded-2xl border border-[#BDDDFC]/30 bg-white p-4 shadow-sm">
        <div className="flex items-center justify-between">
          <div className="text-xs text-[#6A89A7]">Click any sector or job title below to filter skills</div>
          {(sectorFilter || titleFilter) && (
            <button
              type="button"
              onClick={() => { setSectorFilter(""); setTitleFilter(""); }}
              className="rounded-lg border border-[#BDDDFC]/30 px-3 py-1.5 text-xs text-[#6A89A7] hover:bg-[#f0f4f8]"
            >
              Clear All Filters
            </button>
          )}
        </div>
      </div>

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
          <div className="text-sm font-semibold text-[#384959] mb-3">
            Job Sectors
          </div>
          <div className="flex flex-wrap gap-2">
            {data.sectors.map((s, i) => (
              <button
                key={s.sector}
                type="button"
                onClick={() => setSectorFilter(sectorFilter === s.sector ? "" : s.sector)}
                className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-semibold transition ${sectorFilter === s.sector ? "ring-2 ring-[#88BDF2] ring-offset-1" : ""} ${sectorColors[i % sectorColors.length]}`}
              >
                {s.sector}
                <span className="font-mono opacity-70">{s.count.toLocaleString()}</span>
              </button>
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
            <div className="mb-3 rounded-lg bg-[#BDDDFC]/15 px-3 py-2 text-xs text-[#88BDF2]">
              Showing skills for: <strong>{titleFilter}</strong>
            </div>
          )}
          <div className="space-y-1.5">
            {data.top_titles.map((item, index) => (
              <button
                key={item.title}
                type="button"
                onClick={() => setTitleFilter(titleFilter === item.title ? "" : item.title)}
                className={`flex w-full items-center gap-3 rounded-lg px-1 py-0.5 text-left transition hover:bg-[#f0f4f8] ${titleFilter === item.title ? "bg-[#BDDDFC]/15 ring-1 ring-[#BDDDFC]" : ""}`}
              >
                <div className="w-5 text-right text-xs text-[#6A89A7] font-mono">{index + 1}</div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <div
                      className={`h-5 rounded-md ${titleFilter === item.title ? "bg-[#88BDF2]/80" : "bg-emerald-500/70"}`}
                      style={{ width: `${Math.max(4, (item.count / titlesMaxCount) * 100)}%` }}
                    />
                    <span className="text-sm font-medium text-[#384959] whitespace-nowrap">{item.title}</span>
                  </div>
                </div>
                <div className="text-xs text-[#6A89A7] font-mono w-12 text-right">{item.count.toLocaleString()}</div>
              </button>
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
              <div className="space-y-2">
                {visibleSkills.map((item, index) => (
                  <div key={item.skill} className="flex items-center gap-3">
                    <div className="w-5 text-right text-xs text-[#6A89A7] font-mono">{index + 1}</div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <div
                          className="h-6 rounded-md bg-[#88BDF2]/80"
                          style={{ width: `${Math.max(4, (item.count / maxCount) * 100)}%` }}
                        />
                        <span className="text-sm font-medium text-[#384959] whitespace-nowrap">{item.skill}</span>
                      </div>
                    </div>
                    <div className="text-xs text-[#6A89A7] font-mono w-12 text-right">{item.count.toLocaleString()}</div>
                  </div>
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
