import { useState, useEffect, useMemo, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Search, Plus, ChevronRight, Clock, AlertCircle,
  ExternalLink, Filter, Loader2, FileText,
  MapPin, DollarSign, Building2, X, SlidersHorizontal,
  PanelLeftClose, PanelLeftOpen, CheckCircle2,
} from "lucide-react";
import { apiFetch } from "../lib/api.js";
import { todayStr } from "../lib/helpers.js";
import { buildJobSkillDisplay, normalizeJobTermLabels } from "../lib/jobSkillHelpers.js";
import JobCardSkeleton from "./JobCardSkeleton.jsx";
import InterviewPrep from "./InterviewPrep.jsx";

const ARCHETYPE_COLORS = {
  Builder: "bg-amber-50 text-amber-700 border-amber-200",
  Scaler: "bg-blue-50 text-blue-700 border-blue-200",
  Operator: "bg-slate-100 text-slate-700 border-slate-200",
  Specialist: "bg-purple-50 text-purple-700 border-purple-200",
  Leader: "bg-emerald-50 text-emerald-700 border-emerald-200",
};

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
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [locationFilter, setLocationFilter] = useState(new Set());
  const [sectorFilter, setSectorFilter] = useState("");
  const [directEmployersOnly, setDirectEmployersOnly] = useState(false);
  const activeSearchQuery = submittedQuery;

  // Track which jobs are already tracked (Feature 3)
  const trackedJobIds = useMemo(() => {
    const ids = new Set();
    for (const tj of (trackedJobs || [])) {
      if (tj.scraped_job_id) ids.add(tj.scraped_job_id);
      // Also match by title+company for jobs tracked without ID
      if (tj.company && tj.role) ids.add(`${tj.role}|${tj.company}`.toLowerCase());
    }
    return ids;
  }, [trackedJobs]);

  // Cover letter state
  const [coverLetterModal, setCoverLetterModal] = useState(null); // { job } or null
  const [coverLetterDirection, setCoverLetterDirection] = useState("");
  const [coverLetterText, setCoverLetterText] = useState("");
  const [coverLetterLoading, setCoverLetterLoading] = useState(false);
  const [coverLetterError, setCoverLetterError] = useState("");
  const [coverLetterCopied, setCoverLetterCopied] = useState(false);

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
      const activeDirectEmployersOnly = nextFilters.directEmployersOnly ?? directEmployersOnly;

      if (normalizedQuery) params.set("q", normalizedQuery);
      if (activeLevel !== "all") params.set("seniority", activeLevel);
      if (activeDirectEmployersOnly) params.set("direct_employers_only", "true");
      if (activeEmployment instanceof Set && activeEmployment.size > 0) {
        params.set("employment_type", [...activeEmployment].join(","));
      } else if (typeof activeEmployment === "string" && activeEmployment !== "all") {
        params.set("employment_type", activeEmployment);
      }
      if (String(activeMinSalary).trim()) params.set("min_salary", String(activeMinSalary).trim());
      const activeSector = nextFilters.sectorFilter ?? sectorFilter;
      if (activeSector) params.set("sector", activeSector);

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
        sector: j.sector || "",
        companySsicCode: j.company_ssic_code || "",
        companySsicDescription: j.company_ssic_description || "",
        companySsicSource: j.company_ssic_source || "",
        archetype: j.archetype || "",
      }));
      setResults(mapped);
      if (pageNum === 1 && data.filter_meta && typeof data.filter_meta === "object") {
        setFilterMeta({
          sources: Array.isArray(data.filter_meta.sources) ? data.filter_meta.sources : [],
          employment_types: Array.isArray(data.filter_meta.employment_types) ? data.filter_meta.employment_types : [],
          sectors: Array.isArray(data.filter_meta.sectors) ? data.filter_meta.sectors : [],
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

  const openCoverLetterModal = (job) => {
    setCoverLetterModal({ job });
    setCoverLetterDirection("");
    setCoverLetterText("");
    setCoverLetterError("");
    setCoverLetterCopied(false);
  };

  const closeCoverLetterModal = () => {
    setCoverLetterModal(null);
    setCoverLetterText("");
    setCoverLetterDirection("");
    setCoverLetterError("");
    setCoverLetterLoading(false);
    setCoverLetterCopied(false);
  };

  const generateCoverLetter = async () => {
    const resumeText = sessionStorage.getItem("jh_resume_text") || "";
    if (!resumeText || resumeText.length < 50) {
      setCoverLetterError("Please upload or paste your resume in the Resume tab first (at least 50 characters).");
      return;
    }
    const job = coverLetterModal?.job;
    if (!job) return;

    setCoverLetterLoading(true);
    setCoverLetterError("");
    setCoverLetterText("");
    setCoverLetterCopied(false);

    try {
      const resp = await apiFetch("/api/ai/cover-letter", {
        method: "POST",
        body: JSON.stringify({
          resume_text: resumeText,
          job_id: job.id || null,
          job_title: job.title || "",
          job_company: job.company || "",
          job_description: job.description || "",
          user_direction: coverLetterDirection.trim() || null,
        }),
      });
      const data = await resp.json();
      setCoverLetterText(data.cover_letter || "");
    } catch (err) {
      setCoverLetterError(err.message || "Failed to generate cover letter. Please try again.");
    } finally {
      setCoverLetterLoading(false);
    }
  };

  const copyCoverLetter = async () => {
    try {
      await navigator.clipboard.writeText(coverLetterText);
      setCoverLetterCopied(true);
      setTimeout(() => setCoverLetterCopied(false), 2000);
    } catch {
      setCoverLetterError("Failed to copy. Please select the text and copy manually.");
    }
  };

  const downloadCoverLetter = () => {
    const blob = new Blob([coverLetterText], { type: "text/plain;charset=utf-8" });
    const jobTitle = coverLetterModal?.job?.title || "position";
    const company = coverLetterModal?.job?.company || "company";
    const filename = `Cover_Letter_${company.replace(/\s+/g, "_")}_${jobTitle.replace(/\s+/g, "_")}.txt`;
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
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
          error: err.message || "Failed to load job terms.",
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
    sectorFilter !== "",
    directEmployersOnly,
  ].filter(Boolean).length;

  const clearFilters = () => {
    setLevelFilter("all");
    setEmploymentFilter(new Set());
    setExpYearsFilter(new Set());
    setLocationFilter(new Set());
    setMinSalaryFilter("");
    setSectorFilter("");
    setDirectEmployersOnly(false);
    setExpandedJobId(null);
    loadJobs(activeSearchQuery, 1, {
      levelFilter: "all",
      employmentFilter: new Set(),
      minSalaryFilter: "",
      sectorFilter: "",
      directEmployersOnly: false,
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
        <label className="block text-xs font-semibold text-[#6A89A7] uppercase tracking-wide mb-1.5">Search</label>
        <div className="flex gap-2">
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Role, skill, company..."
            onKeyDown={(e) => e.key === "Enter" && handleSearch()}
            className="flex-1 border border-[#BDDDFC]/30 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[#BDDDFC] focus:border-[#88BDF2] bg-white"
          />
          <button
            onClick={handleSearch}
            disabled={loading}
            className="flex items-center justify-center bg-[#384959] text-white px-3 py-2 rounded-lg text-sm hover:bg-[#2d3a47] disabled:opacity-40 transition"
            aria-label="Search"
          >
            {loading ? <Loader2 size={14} className="animate-spin" /> : <Search size={14} />}
          </button>
        </div>
      </div>

      {/* Employer Type */}
      <div>
        <label className="block text-xs font-semibold text-[#6A89A7] uppercase tracking-wide mb-2">Employer Type</label>
        <button
          type="button"
          onClick={() => {
            const next = !directEmployersOnly;
            setDirectEmployersOnly(next);
            loadJobs(activeSearchQuery, 1, { directEmployersOnly: next });
          }}
          aria-pressed={directEmployersOnly}
          className={`flex w-full items-center justify-between gap-3 rounded-xl border px-3 py-2.5 text-left text-sm font-medium transition active:scale-[0.99] ${
            directEmployersOnly
              ? "border-emerald-200 bg-emerald-50 text-emerald-800"
              : "border-[#BDDDFC]/30 bg-white text-[#384959] hover:bg-[#f0f4f8]"
          }`}
        >
          <span>Direct employers only</span>
          <span className={`h-5 w-9 rounded-full p-0.5 transition ${directEmployersOnly ? "bg-emerald-600" : "bg-[#BDDDFC]"}`}>
            <span className={`block h-4 w-4 rounded-full bg-white transition-transform ${directEmployersOnly ? "translate-x-4" : "translate-x-0"}`} />
          </span>
        </button>
        <p className="mt-1.5 text-[11px] leading-tight text-[#6A89A7]">
          Hides recruitment and staffing firms so results focus on companies hiring directly.
        </p>
      </div>

      {/* Experience Level */}
      <div>
        <label className="block text-xs font-semibold text-[#6A89A7] uppercase tracking-wide mb-2">Seniority</label>
        <div className="space-y-0.5">
          {levelOptions.map(({ value, label }) => {
            const active = levelFilter === value;
            return (
              <label
                key={value}
                className={`flex items-center gap-2.5 px-2.5 py-1.5 rounded-lg cursor-pointer transition text-sm ${active ? "bg-[#BDDDFC]/20 text-[#384959] font-medium" : "text-[#384959] hover:bg-[#BDDDFC]/10"}`}
              >
                <input
                  type="radio"
                  name="level"
                  checked={active}
                  onChange={() => {
                    const next = active ? "all" : value;
                    setLevelFilter(next);
                    loadJobs(activeSearchQuery, 1, { levelFilter: next });
                  }}
                  className="w-3.5 h-3.5 accent-[#384959]"
                />
                {label}
              </label>
            );
          })}
        </div>
      </div>

      {/* Employment Type */}
      {employmentTypeOptions.length > 0 && (
        <div>
          <label className="block text-xs font-semibold text-[#6A89A7] uppercase tracking-wide mb-2">Job Type</label>
          <div className="space-y-0.5">
            {employmentTypeOptions.map((type) => {
              const active = employmentFilter.has(type);
              return (
                <label
                  key={type}
                  className={`flex items-center gap-2.5 px-2.5 py-1.5 rounded-lg cursor-pointer transition text-sm ${active ? "bg-[#BDDDFC]/20 text-[#384959] font-medium" : "text-[#384959] hover:bg-[#BDDDFC]/10"}`}
                >
                  <input
                    type="checkbox"
                    checked={active}
                    onChange={() => {
                      const next = new Set(employmentFilter);
                      if (active) next.delete(type); else next.add(type);
                      setEmploymentFilter(next);
                      loadJobs(activeSearchQuery, 1, { employmentFilter: next });
                    }}
                    className="w-3.5 h-3.5 accent-[#384959] rounded"
                  />
                  {type}
                </label>
              );
            })}
          </div>
        </div>
      )}

      {/* Sector / Industry */}
      {(filterMeta.sectors || []).length > 0 && (
        <div>
          <label className="block text-xs font-semibold text-[#6A89A7] uppercase tracking-wide mb-2">Industry</label>
          <div className="space-y-0.5">
            <label
              className={`flex items-center gap-2.5 px-2.5 py-1.5 rounded-lg cursor-pointer transition text-sm ${!sectorFilter ? "bg-[#BDDDFC]/20 text-[#384959] font-medium" : "text-[#384959] hover:bg-[#BDDDFC]/10"}`}
            >
              <input type="radio" name="sector" checked={!sectorFilter} onChange={() => { setSectorFilter(""); loadJobs(activeSearchQuery, 1, { sectorFilter: "" }); }} className="w-3.5 h-3.5 accent-[#384959]" />
              All Industries
            </label>
            {filterMeta.sectors.slice(0, 12).map((s) => (
              <label
                key={s.value}
                className={`flex items-center gap-2.5 px-2.5 py-1.5 rounded-lg cursor-pointer transition text-sm ${sectorFilter === s.value ? "bg-[#BDDDFC]/20 text-[#384959] font-medium" : "text-[#384959] hover:bg-[#BDDDFC]/10"}`}
              >
                <input type="radio" name="sector" checked={sectorFilter === s.value} onChange={() => { setSectorFilter(s.value); loadJobs(activeSearchQuery, 1, { sectorFilter: s.value }); }} className="w-3.5 h-3.5 accent-[#384959]" />
                {s.value}
              </label>
            ))}
          </div>
        </div>
      )}

      {/* Experience Years */}
      <div>
        <label className="block text-xs font-semibold text-[#6A89A7] uppercase tracking-wide mb-2">Experience</label>
        <div className="space-y-0.5">
          {["0-2 yrs", "3-5 yrs", "6-10 yrs", "10+ yrs"].map((label) => {
            const active = expYearsFilter.has(label);
            return (
              <label
                key={label}
                className={`flex items-center gap-2.5 px-2.5 py-1.5 rounded-lg cursor-pointer transition text-sm ${active ? "bg-[#BDDDFC]/20 text-[#384959] font-medium" : "text-[#384959] hover:bg-[#BDDDFC]/10"}`}
              >
                <input
                  type="checkbox"
                  checked={active}
                  onChange={() => {
                    const next = new Set(expYearsFilter);
                    if (active) next.delete(label); else next.add(label);
                    setExpYearsFilter(next);
                  }}
                  className="w-3.5 h-3.5 accent-[#384959] rounded"
                />
                {label}
              </label>
            );
          })}
        </div>
        {expYearsFilter.size > 0 && (
          <p className="mt-1.5 text-[11px] text-[#6A89A7] leading-tight">
            Jobs without a stated requirement stay visible.
          </p>
        )}
      </div>

      {/* Min Salary */}
      <div>
        <label className="block text-xs font-semibold text-[#6A89A7] uppercase tracking-wide mb-1.5">Minimum Salary</label>
        <div className="flex items-center gap-2">
          <DollarSign size={14} className="text-[#6A89A7] flex-shrink-0" />
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
            className="flex-1 border border-[#BDDDFC]/30 rounded-lg px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-[#BDDDFC] focus:border-[#88BDF2]"
          />
        </div>
        {minSalaryFilter && (
          <p className="mt-1.5 text-[11px] text-[#6A89A7] leading-tight">
            Jobs with no salary posted stay visible.
          </p>
        )}
      </div>

      {/* Sort */}
      <div>
        <label className="block text-xs font-semibold text-[#6A89A7] uppercase tracking-wide mb-1.5">Sort By</label>
        <select
          value={sortBy}
          onChange={(e) => setSortBy(e.target.value)}
          className="w-full text-sm border border-[#BDDDFC]/30 rounded-lg px-3 py-2 bg-white focus:outline-none focus:ring-2 focus:ring-[#BDDDFC] focus:border-[#88BDF2]"
        >
          <option value="newest">Newest first</option>
          <option value="salary">Salary (high to low)</option>
        </select>
      </div>

      {/* Clear all */}
      {activeFilterCount > 0 && (
        <button
          onClick={clearFilters}
          className="w-full text-sm font-medium text-[#6A89A7] border border-[#BDDDFC]/30 rounded-lg px-3 py-2 bg-white hover:bg-[#f0f4f8] transition"
        >
          Clear all filters ({activeFilterCount})
        </button>
      )}
    </div>
  );

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="rounded-2xl bg-white border border-[#BDDDFC]/25 p-6 shadow-sm">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-[#384959]">
            <Search size={18} className="text-white" />
          </div>
          <div>
            <h2 className="font-bold text-[#384959] text-lg">Singapore Jobs</h2>
            <p className="text-sm text-[#6A89A7]">Browse jobs from MyCareersFuture and Careers@Gov.</p>
          </div>
        </div>
        <div className="mt-4 rounded-lg border border-[#88BDF2]/20 bg-[#BDDDFC]/10 px-3 py-2 text-xs text-[#384959]">
          <strong>Beta</strong> -- Free to use with 500 AI requests/day to help fund hosting and API costs. Data refreshes nightly.
        </div>
      </div>

      {/* Mobile filter toggle */}
      <div className="lg:hidden">
        <button
          onClick={() => setSidebarOpen(true)}
          className="flex items-center gap-2 border border-[#BDDDFC]/30 bg-white rounded-lg px-4 py-2.5 text-sm font-medium text-[#384959] hover:bg-[#f0f4f8] transition w-full justify-center"
        >
          <SlidersHorizontal size={16} />
          Filters{activeFilterCount > 0 ? ` (${activeFilterCount})` : ""}
        </button>
      </div>

      {/* Mobile sidebar overlay */}
      {sidebarOpen && (
        <div className="fixed inset-0 z-50 lg:hidden">
          <div className="absolute inset-0 bg-black/30" onClick={() => setSidebarOpen(false)} />
          <div className="absolute inset-y-0 left-0 w-full max-w-sm bg-[#f0f4f8] shadow-xl overflow-y-auto">
            <div className="sticky top-0 bg-[#f0f4f8] border-b border-[#BDDDFC]/30 px-5 py-3 flex items-center justify-between z-10">
              <span className="text-sm font-semibold text-[#384959] flex items-center gap-2">
                <Filter size={14} /> Filters
              </span>
              <button
                onClick={() => setSidebarOpen(false)}
                className="p-1.5 rounded-lg hover:bg-[#BDDDFC]/20 transition text-[#6A89A7]"
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
        <aside className={`hidden lg:block flex-shrink-0 sticky top-4 transition-all duration-200 ${sidebarCollapsed ? "w-12" : "w-[280px]"}`}>
          {sidebarCollapsed ? (
            <div className="bg-[#f0f4f8] border border-[#BDDDFC]/30 rounded-xl p-2 shadow-sm flex flex-col items-center gap-3">
              <button
                onClick={() => setSidebarCollapsed(false)}
                className="p-2 rounded-lg hover:bg-[#BDDDFC]/20 transition text-[#6A89A7]"
                aria-label="Expand filters"
              >
                <PanelLeftOpen size={16} />
              </button>
              <Filter size={14} className="text-[#6A89A7]" />
              {activeFilterCount > 0 && (
                <span className="bg-[#BDDDFC]/30 text-[#384959] text-[10px] font-bold px-1.5 py-0.5 rounded-full">
                  {activeFilterCount}
                </span>
              )}
            </div>
          ) : (
            <div className="bg-[#f0f4f8] border border-[#BDDDFC]/30 rounded-xl p-4 shadow-sm">
              <div className="flex items-center gap-2 mb-4 pb-3 border-b border-[#BDDDFC]/30">
                <Filter size={14} className="text-[#6A89A7]" />
                <span className="text-sm font-semibold text-[#384959]">Filters</span>
                {activeFilterCount > 0 && (
                  <span className="ml-auto bg-[#BDDDFC]/30 text-[#384959] text-[10px] font-bold px-1.5 py-0.5 rounded-full">
                    {activeFilterCount}
                  </span>
                )}
                <button
                  onClick={() => setSidebarCollapsed(true)}
                  className="ml-auto p-1 rounded-lg hover:bg-[#BDDDFC]/20 transition text-[#6A89A7]"
                  aria-label="Collapse filters"
                >
                  <PanelLeftClose size={14} />
                </button>
              </div>
              {sidebarContent}
            </div>
          )}
        </aside>

        {/* Main content */}
        <div className="flex-1 min-w-0 space-y-4">
          {/* Results summary bar */}
          {totalLabel && (
            <div className="flex items-center justify-between">
              <p className="text-sm text-[#6A89A7]">
                <span className="font-medium text-[#384959]">{totalLabel}</span>
                {activeSearchQuery ? ` matching "${activeSearchQuery}"` : " across Singapore"}
                {results.length > 0 && ` -- page ${page}`}
              </p>
            </div>
          )}

          {/* Loading */}
          {loading && <JobCardSkeleton count={5} />}

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
            <div className="text-center py-12 text-[#6A89A7]">
              <Search size={32} className="mx-auto mb-2 opacity-40" />
              <p>{query ? "No jobs matched your search. Try broader keywords." : "No jobs available yet. Please check back later."}</p>
            </div>
          )}

          {/* Results */}
          {!loading && (
          <motion.div
            initial="hidden"
            animate="visible"
            variants={{ visible: { transition: { staggerChildren: 0.04 } } }}
            className="space-y-4"
          >
          {filtered.map((job, index) => {
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
            <motion.div
              key={job.id}
              variants={{ hidden: { opacity: 0, y: 16 }, visible: { opacity: 1, y: 0 } }}
              whileHover={{ y: -2, boxShadow: "0 8px 24px rgba(56,73,89,0.08)" }}
              transition={{ duration: 0.25 }}
              onClick={() => toggleExpandedJob(job.id)}
              className="bg-white border border-[#BDDDFC]/30 rounded-xl p-5 transition cursor-pointer"
            >
              <div className="flex justify-between items-start">
                <div className="flex-1">
                  <div className="flex items-center gap-2 mb-1">
                    <h3 className="font-semibold text-[#384959]">{job.title}</h3>
                    {job.level && <span className="text-[10px] bg-[#f0f4f8] text-[#6A89A7] px-2 py-0.5 rounded-full">{job.level}</span>}
                    {job.sector && job.sector !== "Other" && (
                      <span
                        title={job.companySsicSource === "acra" ? `${job.companySsicCode} ${job.companySsicDescription}` : "Inferred sector"}
                        className={`text-[10px] border px-2 py-0.5 rounded-full ${job.companySsicSource === "acra" ? "bg-emerald-50 text-emerald-700 border-emerald-200" : "bg-violet-50 text-violet-700 border-violet-200"}`}
                      >
                        {job.sector}
                      </span>
                    )}
                    {job.archetype && job.archetype !== "Generalist" && <span className={`text-[10px] border px-2 py-0.5 rounded-full ${ARCHETYPE_COLORS[job.archetype] || "bg-gray-50 text-gray-600 border-gray-200"}`}>{job.archetype}</span>}
                    {(trackedJobIds.has(job.id) || trackedJobIds.has(`${job.title}|${job.company}`.toLowerCase())) && <span className="text-[10px] bg-emerald-50 text-emerald-700 border border-emerald-200 px-1.5 py-0.5 rounded-full flex items-center gap-0.5"><CheckCircle2 size={10} />Tracked</span>}
                    <ChevronRight size={14} className={`ml-auto text-[#6A89A7] transition-transform ${isExpanded ? "rotate-90" : ""}`} />
                  </div>
                  <div className="flex items-center gap-4 text-sm text-[#6A89A7] mb-2 flex-wrap">
                    <span className="flex items-center gap-1"><Building2 size={13} />{job.company}</span>
                    {job.location && <span className="flex items-center gap-1"><MapPin size={13} />{job.location}</span>}
                    {job.salary && <span className="flex items-center gap-1"><DollarSign size={13} />{job.salary}</span>}
                    {job.experienceYears && <span className="flex items-center gap-1"><Clock size={13} />{job.experienceYears} yrs</span>}
                  </div>
                  {(summaryText || job.description) && !isExpanded && (
                    <p className="text-sm text-[#6A89A7] mb-3 line-clamp-2">{summaryText || job.description}</p>
                  )}
                  {!isExpanded && previewSkills.length > 0 && (
                    <div className="flex flex-wrap gap-1.5 mb-3">
                      {previewSkills.map((skill) => (
                        <span key={skill} className="bg-[#BDDDFC]/15 text-[#384959] px-2 py-0.5 rounded-full text-xs">{skill}</span>
                      ))}
                      {effectiveSkillDisplay.visibleSkills.length > previewSkills.length && <span className="text-xs text-[#6A89A7]">+{effectiveSkillDisplay.visibleSkills.length - previewSkills.length} more</span>}
                    </div>
                  )}
                </div>
              </div>
              <AnimatePresence>
              {isExpanded && (
                <motion.div
                  initial={{ opacity: 0, height: 0 }}
                  animate={{ opacity: 1, height: "auto" }}
                  exit={{ opacity: 0, height: 0 }}
                  transition={{ duration: 0.25 }}
                  className="overflow-hidden"
                >
                <div className="mt-4 rounded-2xl border border-[#BDDDFC]/20 bg-[#f0f4f8] p-4">
                  {summaryText && (
                    <>
                      <div className="text-xs font-semibold uppercase tracking-[0.16em] text-[#6A89A7]">Job Summary</div>
                      <p className="mt-2 text-sm leading-relaxed text-[#384959]">{summaryText}</p>
                      <div className="mt-4 text-xs font-semibold uppercase tracking-[0.16em] text-[#6A89A7]">Full Description</div>
                    </>
                  )}
                  {!summaryText && <div className="text-xs font-semibold uppercase tracking-[0.16em] text-[#6A89A7]">Description</div>}
                  {job.description ? (
                    <p className="mt-2 whitespace-pre-line text-sm leading-relaxed text-[#384959]">{job.description}</p>
                  ) : (
                    <p className="mt-2 text-sm text-[#6A89A7]">
                      This source did not provide a structured description in our cache.
                      {job.url && " Open the listing to inspect the full posting."}
                    </p>
                  )}

                  <div className="mt-4 text-xs font-semibold uppercase tracking-[0.16em] text-[#6A89A7]">Skills Found</div>
                  {effectiveSkillDisplay.visibleSkills.length > 0 ? (
                    <>
                      <div className="mt-2 flex flex-wrap gap-1.5">
                        {effectiveSkillDisplay.visibleSkills.map((skill) => (
                          <span key={skill} className="rounded-full bg-white px-2 py-0.5 text-xs font-medium text-[#384959] ring-1 ring-[#BDDDFC]/30">
                            {skill}
                          </span>
                        ))}
                      </div>
                      <div className="mt-3 text-xs text-[#6A89A7]">
                        {parsedDisplay.visibleSkills.length > 0
                          ? `${effectiveSkillDisplay.visibleSkills.length} useful term${effectiveSkillDisplay.visibleSkills.length === 1 ? "" : "s"} found in the job description.`
                          : `${effectiveSkillDisplay.visibleSkills.length} useful term${effectiveSkillDisplay.visibleSkills.length === 1 ? "" : "s"} found in ${effectiveSkillDisplay.sourceTagCount} source tag${effectiveSkillDisplay.sourceTagCount === 1 ? "" : "s"}.`}
                      </div>
                      {effectiveSkillDisplay.hiddenStudyAreas.length > 0 && (
                        <div className="mt-2 text-xs text-amber-700">
                          Hidden: {effectiveSkillDisplay.hiddenStudyAreas.length} broad category label{effectiveSkillDisplay.hiddenStudyAreas.length === 1 ? "" : "s"} like {effectiveSkillDisplay.hiddenStudyAreas.slice(0, 2).join(", ")}.
                        </div>
                      )}
                    </>
                  ) : parsedMeta?.loading && !longCueLoad && !cuesWereAlreadyChecked ? (
                    <div className="mt-2 flex items-center gap-2 text-sm text-[#6A89A7]">
                      <Loader2 size={14} className="animate-spin" />
                      Reading job description...
                    </div>
                  ) : parsedMeta?.loading && longCueLoad && !cuesWereAlreadyChecked ? (
                    <div className="mt-2 text-sm text-[#6A89A7]">
                      Skill extraction is taking longer than expected. Collapse and reopen the card to retry, or open the full listing.
                    </div>
                  ) : parsedMeta?.error ? (
                    <div className="mt-2 text-sm text-[#6A89A7]">
                      {parsedMeta.error}
                    </div>
                  ) : cuesWereAlreadyChecked ? (
                    <div className="mt-2 text-sm text-[#6A89A7]">
                      We checked this posting but did not find enough reliable skill terms to show yet.
                    </div>
                  ) : job.skills.length > 0 ? (
                    <div className="mt-2 text-sm text-[#6A89A7]">
                      This listing only exposed broad tags, so no focused skill terms are shown.
                    </div>
                  ) : (
                    <div className="mt-2 text-sm text-[#6A89A7]">
                      No reliable skill terms were found for this posting yet.
                    </div>
                  )}
                </div>
                </motion.div>
              )}
              </AnimatePresence>
              <div className="flex flex-col sm:flex-row sm:items-center justify-between border-t border-[#BDDDFC]/20 pt-3 mt-1 gap-2">
                <div className="flex items-center gap-3 text-xs text-[#6A89A7]">
                  {job.source && <span>{job.source}</span>}
                  {job.posted && <span>{job.posted}</span>}
                  {job.type && <span>{job.type}</span>}
                </div>
                {/* Interview Prep suggestions */}
                {user && isExpanded && (
                  <div className="mb-3" onClick={(e) => e.stopPropagation()}>
                    <InterviewPrep jobId={job.id} user={user} onNavigateToStories={() => setActiveTab("stories")} />
                  </div>
                )}

                <div className="flex flex-wrap gap-2">
                  <button onClick={(event) => { event.stopPropagation(); generateResume(job); }} className="flex items-center gap-1.5 bg-emerald-600 text-white px-3 py-1.5 rounded-lg text-xs font-medium hover:bg-emerald-700 transition">
                    <FileText size={12} /> Tailor Resume
                  </button>
                  <button onClick={(event) => { event.stopPropagation(); openCoverLetterModal(job); }} className="flex items-center gap-1.5 bg-blue-600 text-white px-3 py-1.5 rounded-lg text-xs font-medium hover:bg-blue-700 transition">
                    <FileText size={12} /> Cover Letter
                  </button>
                  {(trackedJobIds.has(job.id) || trackedJobIds.has(`${job.title}|${job.company}`.toLowerCase())) ? (
                    <span className="flex items-center gap-1.5 bg-emerald-50 text-emerald-700 border border-emerald-200 px-3 py-1.5 rounded-lg text-xs font-medium">
                      <CheckCircle2 size={12} /> Tracked
                    </span>
                  ) : (
                    <button onClick={(event) => { event.stopPropagation(); trackJob(job); }} className="flex items-center gap-1.5 bg-[#384959] text-white px-3 py-1.5 rounded-lg text-xs font-medium hover:bg-[#2d3a47] transition">
                      <Plus size={12} /> Track
                    </button>
                  )}
                  {job.url && (
                    <a href={job.url} target="_blank" rel="noreferrer" onClick={(event) => event.stopPropagation()}
                      className="flex items-center gap-1.5 border border-[#BDDDFC]/30 text-[#6A89A7] px-3 py-1.5 rounded-lg text-xs font-medium hover:bg-[#f0f4f8] transition">
                      <ExternalLink size={12} /> View
                    </a>
                  )}
                </div>
              </div>
            </motion.div>
          );
          })}
          </motion.div>
          )}

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="flex justify-center gap-3">
              {page > 1 && (
                <button onClick={() => loadJobs(activeSearchQuery, page - 1)} className="px-4 py-2 text-sm border border-[#BDDDFC]/30 rounded-lg text-[#384959] hover:bg-[#BDDDFC]/10 transition-colors">Previous</button>
              )}
              <span className="px-4 py-2 text-sm text-[#6A89A7]">Page {page} of {totalPages}</span>
              {page < totalPages && (
                <button onClick={() => loadJobs(activeSearchQuery, page + 1)} className="px-4 py-2 text-sm border border-[#BDDDFC]/30 rounded-lg text-[#384959] hover:bg-[#BDDDFC]/10 transition-colors">Next</button>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Cover Letter Modal */}
      <AnimatePresence>
        {coverLetterModal && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4"
            onClick={closeCoverLetterModal}
          >
            <motion.div
              initial={{ scale: 0.95, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.95, opacity: 0 }}
              className="bg-white rounded-xl shadow-2xl w-full max-w-2xl max-h-[90vh] flex flex-col overflow-hidden"
              onClick={(e) => e.stopPropagation()}
            >
              {/* Header */}
              <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200">
                <div>
                  <h3 className="text-lg font-semibold text-[#384959]">Generate Cover Letter</h3>
                  <p className="text-sm text-[#6A89A7] mt-0.5">
                    {coverLetterModal.job?.title} at {coverLetterModal.job?.company}
                  </p>
                </div>
                <button onClick={closeCoverLetterModal} className="p-1 hover:bg-gray-100 rounded-lg transition">
                  <X size={20} className="text-[#6A89A7]" />
                </button>
              </div>

              {/* Body */}
              <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
                {!coverLetterText && !coverLetterLoading && (
                  <>
                    <div>
                      <label className="block text-sm font-medium text-[#384959] mb-1.5">
                        Optional direction
                      </label>
                      <input
                        type="text"
                        value={coverLetterDirection}
                        onChange={(e) => setCoverLetterDirection(e.target.value)}
                        placeholder="e.g. 'emphasize leadership experience' or 'keep it concise'"
                        className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none"
                        maxLength={500}
                      />
                    </div>
                    {!sessionStorage.getItem("jh_resume_text") && (
                      <p className="text-sm text-amber-600 bg-amber-50 px-3 py-2 rounded-lg">
                        No resume found in this session. Upload or paste your resume in the Resume tab first.
                      </p>
                    )}
                  </>
                )}

                {coverLetterError && (
                  <div className="flex items-start gap-2 text-sm text-red-600 bg-red-50 px-3 py-2 rounded-lg">
                    <AlertCircle size={16} className="mt-0.5 flex-shrink-0" />
                    {coverLetterError}
                  </div>
                )}

                {coverLetterLoading && (
                  <div className="flex flex-col items-center justify-center py-12 gap-3">
                    <Loader2 size={28} className="animate-spin text-blue-600" />
                    <p className="text-sm text-[#6A89A7]">Generating your cover letter...</p>
                  </div>
                )}

                {coverLetterText && (
                  <textarea
                    value={coverLetterText}
                    onChange={(e) => setCoverLetterText(e.target.value)}
                    className="w-full h-80 px-4 py-3 border border-gray-200 rounded-lg text-sm leading-relaxed resize-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none font-[system-ui]"
                  />
                )}
              </div>

              {/* Footer */}
              <div className="flex items-center justify-between px-6 py-4 border-t border-gray-200 bg-gray-50">
                {coverLetterText ? (
                  <>
                    <span className="text-xs text-[#6A89A7]">
                      {coverLetterText.split(/\s+/).length} words
                    </span>
                    <div className="flex gap-2">
                      <button
                        onClick={downloadCoverLetter}
                        className="px-4 py-2 text-sm border border-gray-300 rounded-lg text-[#384959] hover:bg-gray-100 transition"
                      >
                        Download .txt
                      </button>
                      <button
                        onClick={copyCoverLetter}
                        className="px-4 py-2 text-sm bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition font-medium"
                      >
                        {coverLetterCopied ? "Copied!" : "Copy"}
                      </button>
                    </div>
                  </>
                ) : (
                  <>
                    <div />
                    <button
                      onClick={generateCoverLetter}
                      disabled={coverLetterLoading}
                      className="px-5 py-2 text-sm bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition font-medium disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      {coverLetterLoading ? "Generating..." : "Generate"}
                    </button>
                  </>
                )}
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
