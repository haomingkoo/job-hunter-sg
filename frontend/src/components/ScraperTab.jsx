import { useState, useEffect, useMemo, useCallback } from "react";
import {
  Search, Plus, ChevronRight, Clock, AlertCircle,
  ExternalLink, Filter, Loader2, FileText,
  MapPin, DollarSign, Building2, X, SlidersHorizontal,
} from "lucide-react";
import { apiFetch } from "../lib/api.js";
import { todayStr } from "../lib/helpers.js";
import { buildJobSkillDisplay, normalizeJobTermLabels } from "../lib/jobSkillHelpers.js";

export default function ScraperTab({ user, trackedJobs, onTrack, setActiveTab, setSelectedJob, onSignIn }) {
  const [query, setQuery] = useState("");
  const [submittedQuery, setSubmittedQuery] = useState("");
  const [results, setResults] = useState([]);
  const [loading, setLoading] = useState(false);
  const [levelFilter, setLevelFilter] = useState("all");
  const [employmentFilter, setEmploymentFilter] = useState(new Set());
  const [expYearsFilter, setExpYearsFilter] = useState(new Set());
  const [minSalaryFilter, setMinSalaryFilter] = useState("");
  const [filterMeta, setFilterMeta] = useState({ sources: [], employment_types: [] });
  const [sortBy, setSortBy] = useState("newest");
  const [error, setError] = useState("");
  const [trackError, setTrackError] = useState("");
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [totalLabel, setTotalLabel] = useState("");
  const [expandedJobId, setExpandedJobId] = useState(null);
  const [parsedJobMeta, setParsedJobMeta] = useState({});
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [locationFilter, setLocationFilter] = useState(new Set());
  const activeSearchQuery = submittedQuery;

  // Load cached jobs on mount (browse mode)
  useEffect(() => {
    loadJobs("");
  }, []);

  const loadJobs = async (searchQuery, pageNum = 1, nextFilters = {}) => {
    setLoading(true);
    setError("");
    try {
      const normalizedQuery = searchQuery.trim();
      const params = new URLSearchParams({ page: String(pageNum), per_page: "20" });
      const activeLevel = nextFilters.levelFilter ?? levelFilter;
      const activeEmployment = nextFilters.employmentFilter ?? employmentFilter;
      const activeMinSalary = nextFilters.minSalaryFilter ?? minSalaryFilter;

      if (normalizedQuery) params.set("q", normalizedQuery);
      if (activeLevel !== "all") params.set("seniority", activeLevel);
      if (activeEmployment instanceof Set && activeEmployment.size > 0) {
        params.set("employment_type", [...activeEmployment].join(","));
      } else if (typeof activeEmployment === "string" && activeEmployment !== "all") {
        params.set("employment_type", activeEmployment);
      }
      if (String(activeMinSalary).trim()) params.set("min_salary", String(activeMinSalary).trim());

      const resp = await apiFetch(`/api/jobs?${params}`, { method: "GET" });
      const data = await resp.json();
      if (!data || !Array.isArray(data.jobs)) {
        throw new Error("Jobs response was malformed.");
      }

      const mapped = data.jobs.map((j) => ({
        id: j.id,
        title: j.title,
        company: j.company,
        location: j.location || "",
        salary: j.salary || "",
        source: j.source,
        posted: j.posted_date || "",
        skills: j.skills || [],
        jobTermsPreview: normalizeJobTermLabels(j.job_terms_preview || []),
        jobTermsPreviewReady: Boolean(j.job_terms_preview_ready),
        description: j.description || "",
        jdSummary: j.jd_summary || "",
        jdSummaryStatus: j.jd_summary_status || "",
        type: j.employment_type || "",
        level: j.seniority || "",
        url: j.url || "",
        experienceYears: j.experience_years || "",
      }));
      setResults(mapped);
      if (pageNum === 1 && data.filter_meta && typeof data.filter_meta === "object") {
        setFilterMeta({
          sources: Array.isArray(data.filter_meta.sources) ? data.filter_meta.sources : [],
          employment_types: Array.isArray(data.filter_meta.employment_types) ? data.filter_meta.employment_types : [],
        });
      }
      setSubmittedQuery(normalizedQuery);
      setPage(pageNum);
      const totalPagesValue = Number(data.pages);
      setTotalPages(Number.isFinite(totalPagesValue) && totalPagesValue > 0 ? totalPagesValue : 1);
      setExpandedJobId(null);
      const totalCountValue = Number(data.total);
      const totalCount = Number.isFinite(totalCountValue) && totalCountValue >= 0 ? totalCountValue : mapped.length;
      const total = `${Math.max(totalCount, 0).toLocaleString()} jobs`;
      setTotalLabel(total);
    } catch (err) {
      setError(err.message || "Failed to load jobs. Please try again.");
      setResults([]);
      setTotalPages(1);
      setTotalLabel("");
      setSubmittedQuery(searchQuery.trim());
    } finally {
      setLoading(false);
    }
  };

  const handleSearch = () => {
    loadJobs(query, 1);
  };

  const filtered = useMemo(() => {
    let r = [...results];
    if (expYearsFilter.size > 0) {
      r = r.filter((job) => {
        const raw = String(job.experienceYears || "").trim();
        if (!raw) return true; // No experience stated = show (don't exclude)
        const minMatch = raw.match(/^(\d+)/);
        if (!minMatch) return true;
        const minYrs = parseInt(minMatch[1], 10);
        for (const label of expYearsFilter) {
          if (label === "0-2 yrs" && minYrs >= 0 && minYrs <= 2) return true;
          if (label === "3-5 yrs" && minYrs >= 3 && minYrs <= 5) return true;
          if (label === "6-10 yrs" && minYrs >= 6 && minYrs <= 10) return true;
          if (label === "10+ yrs" && minYrs > 10) return true;
        }
        return false;
      });
    }
    if (locationFilter.size > 0) {
      r = r.filter((job) => {
        const loc = (job.location || "").trim();
        if (!loc) return true; // No location stated = show
        return locationFilter.has(loc);
      });
    }
    if (sortBy === "salary") r.sort((a, b) => {
      const getMax = (s) => {
        const matches = String(s || "").match(/\d[\d,]*/g) || [];
        const last = matches[matches.length - 1];
        return last ? parseInt(last.replace(/,/g, ""), 10) : 0;
      };
      return getMax(b.salary) - getMax(a.salary);
    });
    return r;
  }, [results, sortBy, expYearsFilter, locationFilter]);

  const employmentTypeOptions = useMemo(
    () => filterMeta.employment_types.length > 0
      ? filterMeta.employment_types.map((t) => t.value)
      : [...new Set(results.map((job) => job.type).filter(Boolean))].sort(),
    [results, filterMeta.employment_types],
  );

  const locationOptions = useMemo(() => {
    const counts = {};
    for (const job of results) {
      const loc = (job.location || "").trim();
      if (loc) counts[loc] = (counts[loc] || 0) + 1;
    }
    return Object.entries(counts)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 12)
      .map(([loc]) => loc);
  }, [results]);

  const trackJob = async (scrapedJob) => {
    if (!user) {
      onSignIn();
      return;
    }
    setTrackError("");
    try {
      const payload = {
        company: scrapedJob.company,
        role: scrapedJob.title,
        date_applied: todayStr(),
        status: "applied",
        source: scrapedJob.source,
        follow_up_date: new Date(Date.now() + 14 * 86400000).toISOString().split("T")[0],
        notes: `Salary: ${scrapedJob.salary} | ${scrapedJob.location}`,
        scraped_job_id: scrapedJob.id,
      };
      await onTrack(payload);
    } catch (err) {
      setTrackError(err.message || "Failed to track job. Please try again.");
    }
  };

  const generateResume = (scrapedJob) => {
    setSelectedJob(scrapedJob);
    setActiveTab("resume");
  };

  const toggleExpandedJob = (jobId) => {
    setExpandedJobId((current) => (current === jobId ? null : jobId));
  };

  const fetchParsedJobMeta = useCallback(async (jobId) => {
    if (!jobId) return false;
    let shouldFetch = false;
    setParsedJobMeta((current) => {
      const existing = current[jobId];
      if (existing?.loaded || existing?.loading) return current;
      shouldFetch = true;
      return {
        ...current,
        [jobId]: {
          ...(existing || {}),
          loading: true,
          loaded: false,
          error: "",
          stalled: false,
          startedAt: Date.now(),
        },
      };
    });
    if (!shouldFetch) return false;

    const timeoutId = window.setTimeout(() => {
      setParsedJobMeta((current) => {
        const existing = current[jobId];
        if (!existing?.loading) return current;
        return {
          ...current,
          [jobId]: {
            ...existing,
            stalled: true,
          },
        };
      });
    }, 4500);

    try {
      const resp = await apiFetch(`/api/jobs/${jobId}/parsed`);
      const data = await resp.json();
      const parsed = data?.parsed_jd && typeof data.parsed_jd === "object" ? data.parsed_jd : {};
      const jobTerms = Array.isArray(data?.job_terms) ? data.job_terms : [];
      const jobTermLabels = normalizeJobTermLabels(jobTerms);
      const previewLabels = normalizeJobTermLabels(data?.job_terms_preview || []);
      const extractedTerms = normalizeJobTermLabels([
        ...(Array.isArray(parsed.required_skills) ? parsed.required_skills : []),
        ...(Array.isArray(parsed.preferred_skills) ? parsed.preferred_skills : []),
        ...(Array.isArray(parsed.single_word_skills) ? parsed.single_word_skills : []),
      ]);
      window.clearTimeout(timeoutId);
      setParsedJobMeta((current) => ({
        ...current,
        [jobId]: {
          ...(current[jobId] || {}),
          loaded: true,
          loading: false,
          error: "",
          parsed,
          jobTerms,
          jobTermLabels,
          previewLabels,
          previewReady: Boolean(data?.job_terms_preview_ready),
          extractedTerms,
          jdSummary: data?.jd_summary || "",
          jdSummaryStatus: data?.jd_summary_status || "",
          stalled: false,
          startedAt: current[jobId]?.startedAt || Date.now(),
        },
      }));
      return true;
    } catch (err) {
      window.clearTimeout(timeoutId);
      setParsedJobMeta((current) => ({
        ...current,
        [jobId]: {
          ...(current[jobId] || {}),
          loaded: true,
          loading: false,
          stalled: false,
          error: err.message || "Failed to load parsed JD cues.",
        },
      }));
      return false;
    }
  }, []);

  useEffect(() => {
    if (!expandedJobId) return;
    fetchParsedJobMeta(expandedJobId);
  }, [expandedJobId, fetchParsedJobMeta]);

  // Lazy-fetch parsed data only for the rare job missing a cached preview
  // (all jobs should have preview from backfill; this is a safety net)
  useEffect(() => {
    if (!results.length) return;
    const candidate = results.find(
      (job) => !job.jobTermsPreview?.length && (job.description || "").trim()
    );
    if (!candidate) return;

    const timeoutId = window.setTimeout(() => {
      fetchParsedJobMeta(candidate.id);
    }, 1000);

    return () => window.clearTimeout(timeoutId);
  }, [results, fetchParsedJobMeta]);

  const activeFilterCount = [
    levelFilter !== "all",
    employmentFilter.size > 0,
    expYearsFilter.size > 0,
    locationFilter.size > 0,
    String(minSalaryFilter).trim() !== "",
  ].filter(Boolean).length;

  const clearFilters = () => {
    setLevelFilter("all");
    setEmploymentFilter(new Set());
    setExpYearsFilter(new Set());
    setLocationFilter(new Set());
    setMinSalaryFilter("");
    setExpandedJobId(null);
    loadJobs(activeSearchQuery, 1, {
      levelFilter: "all",
      employmentFilter: new Set(),
      minSalaryFilter: "",
    });
  };

  const levelOptions = [
    { value: "Entry", label: "Entry Level" },
    { value: "Intern", label: "Internship" },
    { value: "Junior", label: "Junior" },
    { value: "Mid", label: "Mid" },
    { value: "Mid-Senior", label: "Mid-Senior" },
    { value: "Senior", label: "Senior" },
    { value: "Director", label: "Director+" },
  ];

  /* ── Sidebar filter panel (shared between desktop inline + mobile overlay) ── */
  const sidebarContent = (
    <div className="space-y-5">
      {/* Search */}
      <div>
        <label className="block text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1.5">Search</label>
        <div className="flex gap-2">
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Role, skill, company..."
            onKeyDown={(e) => e.key === "Enter" && handleSearch()}
            className="flex-1 border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-200 focus:border-indigo-400 bg-white"
          />
          <button
            onClick={handleSearch}
            disabled={loading}
            className="flex items-center justify-center bg-indigo-600 text-white px-3 py-2 rounded-lg text-sm hover:bg-indigo-700 disabled:opacity-40 transition"
            aria-label="Search"
          >
            {loading ? <Loader2 size={14} className="animate-spin" /> : <Search size={14} />}
          </button>
        </div>
      </div>

      {/* Experience Level */}
      <div>
        <label className="block text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1.5">Experience Level</label>
        <div className="flex flex-wrap gap-1.5">
          {levelOptions.map(({ value, label }) => {
            const active = levelFilter === value;
            return (
              <button
                key={value}
                type="button"
                onClick={() => {
                  const next = active ? "all" : value;
                  setLevelFilter(next);
                  loadJobs(activeSearchQuery, 1, { levelFilter: next });
                }}
                className={`rounded-full px-3 py-1 text-xs font-medium transition ${active ? "bg-indigo-600 text-white" : "bg-gray-100 text-gray-600 hover:bg-gray-200"}`}
              >
                {label}
              </button>
            );
          })}
        </div>
      </div>

      {/* Employment Type */}
      {employmentTypeOptions.length > 0 && (
        <div>
          <label className="block text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1.5">Job Type</label>
          <div className="flex flex-wrap gap-1.5">
            {employmentTypeOptions.map((type) => {
              const active = employmentFilter.has(type);
              return (
                <button
                  key={type}
                  type="button"
                  onClick={() => {
                    const next = new Set(employmentFilter);
                    if (active) next.delete(type); else next.add(type);
                    setEmploymentFilter(next);
                    loadJobs(activeSearchQuery, 1, { employmentFilter: next });
                  }}
                  className={`rounded-full px-3 py-1 text-xs font-medium transition ${active ? "bg-indigo-600 text-white" : "bg-gray-100 text-gray-600 hover:bg-gray-200"}`}
                >
                  {type}
                </button>
              );
            })}
          </div>
        </div>
      )}

      {/* Experience Years */}
      <div>
        <label className="block text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1.5">Experience</label>
        <div className="flex flex-wrap gap-1.5">
          {["0-2 yrs", "3-5 yrs", "6-10 yrs", "10+ yrs"].map((label) => {
            const active = expYearsFilter.has(label);
            return (
              <button
                key={label}
                type="button"
                onClick={() => {
                  const next = new Set(expYearsFilter);
                  if (active) next.delete(label); else next.add(label);
                  setExpYearsFilter(next);
                }}
                className={`rounded-full px-3 py-1 text-xs font-medium transition ${active ? "bg-indigo-600 text-white" : "bg-gray-100 text-gray-600 hover:bg-gray-200"}`}
              >
                {label}
              </button>
            );
          })}
        </div>
        {expYearsFilter.size > 0 && (
          <p className="mt-1.5 text-[11px] text-gray-400 leading-tight">
            Jobs without a stated requirement stay visible.
          </p>
        )}
      </div>

      {/* Location */}
      {locationOptions.length > 0 && (
        <div>
          <label className="block text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1.5">Location</label>
          <div className="flex flex-wrap gap-1.5">
            {locationOptions.map((loc) => {
              const active = locationFilter.has(loc);
              return (
                <button
                  key={loc}
                  type="button"
                  onClick={() => {
                    const next = new Set(locationFilter);
                    if (active) next.delete(loc); else next.add(loc);
                    setLocationFilter(next);
                  }}
                  className={`rounded-full px-3 py-1 text-xs font-medium transition ${active ? "bg-indigo-600 text-white" : "bg-gray-100 text-gray-600 hover:bg-gray-200"}`}
                >
                  {loc}
                </button>
              );
            })}
          </div>
        </div>
      )}

      {/* Min Salary */}
      <div>
        <label className="block text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1.5">Minimum Salary</label>
        <div className="flex items-center gap-2">
          <DollarSign size={14} className="text-gray-400 flex-shrink-0" />
          <input
            type="number"
            min="0"
            value={minSalaryFilter}
            onChange={(e) => setMinSalaryFilter(e.target.value)}
            onBlur={() => loadJobs(activeSearchQuery, 1, { minSalaryFilter })}
            onKeyDown={(e) => {
              if (e.key === "Enter") loadJobs(activeSearchQuery, 1, { minSalaryFilter });
            }}
            placeholder="e.g. 4000"
            className="flex-1 border border-gray-200 rounded-lg px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-indigo-200 focus:border-indigo-400"
          />
        </div>
        {minSalaryFilter && (
          <p className="mt-1.5 text-[11px] text-gray-400 leading-tight">
            Jobs with no salary posted stay visible.
          </p>
        )}
      </div>

      {/* Sort */}
      <div>
        <label className="block text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1.5">Sort By</label>
        <select
          value={sortBy}
          onChange={(e) => setSortBy(e.target.value)}
          className="w-full text-sm border border-gray-200 rounded-lg px-3 py-2 bg-white focus:outline-none focus:ring-2 focus:ring-indigo-200 focus:border-indigo-400"
        >
          <option value="newest">Newest first</option>
          <option value="salary">Salary (high to low)</option>
        </select>
      </div>

      {/* Clear all */}
      {activeFilterCount > 0 && (
        <button
          onClick={clearFilters}
          className="w-full text-sm font-medium text-gray-600 border border-gray-200 rounded-lg px-3 py-2 bg-white hover:bg-gray-50 transition"
        >
          Clear all filters ({activeFilterCount})
        </button>
      )}
    </div>
  );

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="bg-gradient-to-r from-purple-50 to-indigo-50 rounded-xl p-5">
        <h2 className="font-semibold text-gray-800 flex items-center gap-2"><Search size={18} /> Singapore Jobs</h2>
        <p className="text-sm text-gray-500 mt-1">Browse jobs from MyCareersFuture, Careers@Gov, and more across Singapore.</p>
        <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700">
          <strong>Beta</strong> - Early access. AI features are rate-limited (free tier). Data refreshes nightly.
        </div>
      </div>

      {/* Mobile filter toggle */}
      <div className="lg:hidden">
        <button
          onClick={() => setSidebarOpen(true)}
          className="flex items-center gap-2 border border-gray-200 bg-white rounded-lg px-4 py-2.5 text-sm font-medium text-gray-700 hover:bg-gray-50 transition w-full justify-center"
        >
          <SlidersHorizontal size={16} />
          Filters{activeFilterCount > 0 ? ` (${activeFilterCount})` : ""}
        </button>
      </div>

      {/* Mobile sidebar overlay */}
      {sidebarOpen && (
        <div className="fixed inset-0 z-50 lg:hidden">
          <div className="absolute inset-0 bg-black/30" onClick={() => setSidebarOpen(false)} />
          <div className="absolute inset-y-0 left-0 w-full max-w-sm bg-gray-50 shadow-xl overflow-y-auto">
            <div className="sticky top-0 bg-gray-50 border-b border-gray-200 px-5 py-3 flex items-center justify-between z-10">
              <span className="text-sm font-semibold text-gray-800 flex items-center gap-2">
                <Filter size={14} /> Filters
              </span>
              <button
                onClick={() => setSidebarOpen(false)}
                className="p-1.5 rounded-lg hover:bg-gray-200 transition text-gray-500"
                aria-label="Close filters"
              >
                <X size={18} />
              </button>
            </div>
            <div className="p-5">
              {sidebarContent}
            </div>
          </div>
        </div>
      )}

      {/* Two-column layout: sidebar + job list */}
      <div className="flex gap-6 items-start">
        {/* Desktop sidebar */}
        <aside className="hidden lg:block w-[280px] flex-shrink-0 sticky top-4">
          <div className="bg-gray-50 border border-gray-200 rounded-xl p-4 shadow-sm">
            <div className="flex items-center gap-2 mb-4 pb-3 border-b border-gray-200">
              <Filter size={14} className="text-gray-400" />
              <span className="text-sm font-semibold text-gray-800">Filters</span>
              {activeFilterCount > 0 && (
                <span className="ml-auto bg-indigo-100 text-indigo-700 text-[10px] font-bold px-1.5 py-0.5 rounded-full">
                  {activeFilterCount}
                </span>
              )}
            </div>
            {sidebarContent}
          </div>
        </aside>

        {/* Main content */}
        <div className="flex-1 min-w-0 space-y-4">
          {/* Results summary bar */}
          {totalLabel && (
            <div className="flex items-center justify-between">
              <p className="text-sm text-gray-500">
                <span className="font-medium text-gray-700">{totalLabel}</span>
                {activeSearchQuery ? ` matching "${activeSearchQuery}"` : " across Singapore"}
                {results.length > 0 && ` -- page ${page}`}
              </p>
            </div>
          )}

          {/* Loading */}
          {loading && (
            <div className="text-center py-12">
              <Loader2 size={32} className="animate-spin text-indigo-400 mx-auto" />
              <p className="text-sm text-gray-500 mt-3">Loading jobs{query ? ` for "${query}"` : ""}...</p>
            </div>
          )}

          {/* Error */}
          {!loading && error && (
            <div className="text-center py-8">
              <AlertCircle size={32} className="mx-auto mb-2 text-red-400" />
              <p className="text-sm text-red-600">{error}</p>
            </div>
          )}

          {/* Track error */}
          {trackError && (
            <div className="bg-red-50 border border-red-200 text-red-700 text-sm rounded-lg p-3 flex items-center gap-2">
              <AlertCircle size={14} className="flex-shrink-0" />{trackError}
            </div>
          )}

          {/* No results */}
          {!loading && !error && results.length === 0 && (
            <div className="text-center py-12 text-gray-400">
              <Search size={32} className="mx-auto mb-2 opacity-40" />
              <p>{query ? "No jobs matched your search. Try broader keywords." : "No jobs available yet. Please check back later."}</p>
            </div>
          )}

          {/* Results */}
          {!loading && filtered.map((job) => {
            const isExpanded = expandedJobId === job.id;
            const skillDisplay = buildJobSkillDisplay(job.jobTermsPreview?.length ? job.jobTermsPreview : job.skills, job.description);
            const parsedMeta = parsedJobMeta[job.id] || null;
            const parsedDisplay = buildJobSkillDisplay(
              parsedMeta?.jobTermLabels?.length
                ? parsedMeta.jobTermLabels
                : (parsedMeta?.previewLabels?.length ? parsedMeta.previewLabels : (parsedMeta?.extractedTerms || [])),
              job.description,
            );
            const effectiveSkillDisplay = parsedDisplay.visibleSkills.length > 0 ? parsedDisplay : skillDisplay;
            const previewSkills = effectiveSkillDisplay.visibleSkills.slice(0, 6);
            const summaryText = (parsedMeta?.jdSummary || job.jdSummary || "").trim();
            const longCueLoad = Boolean(parsedMeta?.loading && parsedMeta?.stalled);
            const cuesWereAlreadyChecked = Boolean(job.jobTermsPreviewReady || parsedMeta?.previewReady);

            return (
            <div
              key={job.id}
              onClick={() => toggleExpandedJob(job.id)}
              className="bg-white border border-gray-200 rounded-xl p-5 hover:shadow-md transition cursor-pointer"
            >
              <div className="flex justify-between items-start">
                <div className="flex-1">
                  <div className="flex items-center gap-2 mb-1">
                    <h3 className="font-semibold text-gray-800">{job.title}</h3>
                    {job.level && <span className="text-[10px] bg-gray-100 text-gray-500 px-2 py-0.5 rounded-full">{job.level}</span>}
                    <ChevronRight size={14} className={`ml-auto text-gray-400 transition-transform ${isExpanded ? "rotate-90" : ""}`} />
                  </div>
                  <div className="flex items-center gap-4 text-sm text-gray-500 mb-2 flex-wrap">
                    <span className="flex items-center gap-1"><Building2 size={13} />{job.company}</span>
                    {job.location && <span className="flex items-center gap-1"><MapPin size={13} />{job.location}</span>}
                    {job.salary && <span className="flex items-center gap-1"><DollarSign size={13} />{job.salary}</span>}
                    {job.experienceYears && <span className="flex items-center gap-1"><Clock size={13} />{job.experienceYears} yrs</span>}
                  </div>
                  {(summaryText || job.description) && !isExpanded && (
                    <p className="text-sm text-gray-600 mb-3 line-clamp-2">{summaryText || job.description}</p>
                  )}
                  {!isExpanded && previewSkills.length > 0 && (
                    <div className="flex flex-wrap gap-1.5 mb-3">
                      {previewSkills.map((skill) => (
                        <span key={skill} className="bg-indigo-50 text-indigo-700 px-2 py-0.5 rounded-full text-xs">{skill}</span>
                      ))}
                      {effectiveSkillDisplay.visibleSkills.length > previewSkills.length && <span className="text-xs text-gray-400">+{effectiveSkillDisplay.visibleSkills.length - previewSkills.length} more</span>}
                    </div>
                  )}
                </div>
              </div>
              {isExpanded && (
                <div className="mt-4 rounded-2xl border border-gray-100 bg-gray-50 p-4">
                  {summaryText && (
                    <>
                      <div className="text-xs font-semibold uppercase tracking-[0.16em] text-gray-500">AI Summary</div>
                      <p className="mt-2 text-sm leading-relaxed text-gray-700">{summaryText}</p>
                      <div className="mt-4 text-xs font-semibold uppercase tracking-[0.16em] text-gray-500">Original Description</div>
                    </>
                  )}
                  {!summaryText && <div className="text-xs font-semibold uppercase tracking-[0.16em] text-gray-500">Description</div>}
                  {job.description ? (
                    <p className="mt-2 whitespace-pre-line text-sm leading-relaxed text-gray-700">{job.description}</p>
                  ) : (
                    <p className="mt-2 text-sm text-gray-600">
                      This source did not provide a structured description in our cache.
                      {job.url && " Open the listing to inspect the full posting."}
                    </p>
                  )}

                  <div className="mt-4 text-xs font-semibold uppercase tracking-[0.16em] text-gray-500">Source Tags & Skill Cues</div>
                  {effectiveSkillDisplay.visibleSkills.length > 0 ? (
                    <>
                      <div className="mt-2 flex flex-wrap gap-1.5">
                        {effectiveSkillDisplay.visibleSkills.map((skill) => (
                          <span key={skill} className="rounded-full bg-white px-2 py-0.5 text-xs font-medium text-gray-700 ring-1 ring-gray-200">
                            {skill}
                          </span>
                        ))}
                      </div>
                      <div className="mt-3 text-xs text-gray-500">
                        {parsedDisplay.visibleSkills.length > 0
                          ? `Showing ${effectiveSkillDisplay.visibleSkills.length} practical cue${effectiveSkillDisplay.visibleSkills.length === 1 ? "" : "s"} extracted from the JD and source data.`
                          : `Showing ${effectiveSkillDisplay.visibleSkills.length} practical cue${effectiveSkillDisplay.visibleSkills.length === 1 ? "" : "s"} from ${effectiveSkillDisplay.sourceTagCount} source tag${effectiveSkillDisplay.sourceTagCount === 1 ? "" : "s"}.`}
                      </div>
                      {effectiveSkillDisplay.hiddenStudyAreas.length > 0 && (
                        <div className="mt-2 text-xs text-amber-700">
                          Hid {effectiveSkillDisplay.hiddenStudyAreas.length} broad study-area label{effectiveSkillDisplay.hiddenStudyAreas.length === 1 ? "" : "s"} like {effectiveSkillDisplay.hiddenStudyAreas.slice(0, 2).join(", ")} so this stays focused on practical fit.
                        </div>
                      )}
                    </>
                  ) : parsedMeta?.loading && !longCueLoad && !cuesWereAlreadyChecked ? (
                    <div className="mt-2 flex items-center gap-2 text-sm text-gray-600">
                      <Loader2 size={14} className="animate-spin" />
                      Extracting skill cues from the job description...
                    </div>
                  ) : parsedMeta?.loading && longCueLoad && !cuesWereAlreadyChecked ? (
                    <div className="mt-2 text-sm text-gray-600">
                      Cue extraction is taking longer than expected. Collapse and reopen the card to retry, or use the full listing if you need the original JD immediately.
                    </div>
                  ) : parsedMeta?.error ? (
                    <div className="mt-2 text-sm text-gray-600">
                      {parsedMeta.error}
                    </div>
                  ) : cuesWereAlreadyChecked ? (
                    <div className="mt-2 text-sm text-gray-600">
                      We checked this posting for practical ATS cues but did not find enough trustworthy terms to surface yet.
                    </div>
                  ) : job.skills.length > 0 ? (
                    <div className="mt-2 text-sm text-gray-600">
                      This listing only exposed broad source tags, so we did not surface them as practical skill cues.
                    </div>
                  ) : (
                    <div className="mt-2 text-sm text-gray-600">
                      No structured skills were captured from this source for this posting, and we could not confidently extract practical cues from the JD yet.
                    </div>
                  )}
                </div>
              )}
              <div className="flex flex-col sm:flex-row sm:items-center justify-between border-t border-gray-100 pt-3 mt-1 gap-2">
                <div className="flex items-center gap-3 text-xs text-gray-400">
                  {job.source && <span>{job.source}</span>}
                  {job.posted && <span>{job.posted}</span>}
                  {job.type && <span>{job.type}</span>}
                </div>
                <div className="flex flex-wrap gap-2">
                  <button onClick={(event) => { event.stopPropagation(); generateResume(job); }} className="flex items-center gap-1.5 bg-emerald-600 text-white px-3 py-1.5 rounded-lg text-xs font-medium hover:bg-emerald-700 transition">
                    <FileText size={12} /> Tailor Resume
                  </button>
                  <button onClick={(event) => { event.stopPropagation(); trackJob(job); }} className="flex items-center gap-1.5 bg-indigo-600 text-white px-3 py-1.5 rounded-lg text-xs font-medium hover:bg-indigo-700 transition">
                    <Plus size={12} /> Track
                  </button>
                  {job.url && (
                    <a href={job.url} target="_blank" rel="noreferrer" onClick={(event) => event.stopPropagation()}
                      className="flex items-center gap-1.5 border border-gray-200 text-gray-600 px-3 py-1.5 rounded-lg text-xs font-medium hover:bg-gray-50 transition">
                      <ExternalLink size={12} /> View
                    </a>
                  )}
                </div>
              </div>
            </div>
          );
          })}

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="flex justify-center gap-3">
              {page > 1 && (
                <button onClick={() => loadJobs(activeSearchQuery, page - 1)} className="px-4 py-2 text-sm border border-gray-200 rounded-lg hover:bg-gray-50">Previous</button>
              )}
              <span className="px-4 py-2 text-sm text-gray-500">Page {page} of {totalPages}</span>
              {page < totalPages && (
                <button onClick={() => loadJobs(activeSearchQuery, page + 1)} className="px-4 py-2 text-sm border border-gray-200 rounded-lg hover:bg-gray-50">Next</button>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
