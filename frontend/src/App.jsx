import { useState, useEffect, useMemo, useCallback, useRef, Fragment } from "react";
import {
  Search, Briefcase, Bell, FileText, Plus, X, ChevronRight, Clock,
  CheckCircle, AlertCircle, ExternalLink, Trash2, Edit3, Save, Filter,
  RefreshCw, Zap, Download, Copy, Star, MapPin, DollarSign, Building2,
  Loader2, User, LogOut, Mail,
  RotateCcw, Sparkles, UploadCloud,
} from "lucide-react";

// ─── API Config ────────────────────────────────────────────────────────────────
const API_BASE = import.meta.env.VITE_API_URL || "";

// ─── Constants ─────────────────────────────────────────────────────────────────

const STATUS_CONFIG = {
  applied: { label: "Applied", color: "bg-blue-100 text-blue-800", icon: Clock },
  interview: { label: "Interview", color: "bg-yellow-100 text-yellow-800", icon: AlertCircle },
  offer: { label: "Offer", color: "bg-green-100 text-green-800", icon: CheckCircle },
  rejected: { label: "Rejected", color: "bg-red-100 text-red-700", icon: X },
  withdrawn: { label: "Withdrawn", color: "bg-gray-100 text-gray-600", icon: X },
};

const SG_JOB_PORTALS = [
  { name: "MyCareersFuture", key: "mcf", type: "api" },
  { name: "Careers@Gov", key: "careersgov", type: "api" },
  { name: "Adzuna", key: "adzuna", type: "api" },
  { name: "Jooble", key: "jooble", type: "api" },
  { name: "NodeFlair", key: "nodeflair", type: "scrape" },
  { name: "Indeed SG", key: "indeed", type: "scrape" },
  { name: "JobStreet", key: "jobstreet", type: "scrape" },
];

// ─── Helpers ───────────────────────────────────────────────────────────────────

const todayStr = () => new Date().toISOString().split("T")[0];
const daysBetween = (a, b) => (a && b) ? Math.round((new Date(b) - new Date(a)) / 86400000) : 0;

function clearResumeDraftStorage() {
  try {
    sessionStorage.removeItem("jh_resume_profile");
    sessionStorage.removeItem("jh_resume_text");
    sessionStorage.removeItem("jh_resume_template");
  } catch {
    // ignore storage errors
  }
}

async function apiFetch(path, options = {}) {
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

const JOB_STUDY_AREA_TAGS = new Set([
  "computer science",
  "engineering",
  "mathematics",
  "medical study",
  "statistics",
]);

const JOB_STUDY_AREA_CONTEXT_RE = /(areas?\s+of\s+study|field[s]?\s+of\s+study|degree(?:\s+or)?\s+above|bachelor|master|phd|major(?:ing)?\s+in|equivalent work experience|disciplines?)/i;
const ALIGNMENT_TERM_BLACKLIST = new Set([
  "expects",
  "expects:",
  "required",
  "requirement",
  "requirements",
  "responsibility",
  "responsibilities",
  "common direction",
  "understand",
  "understanding",
  "deliverables",
  "programs",
  "business goals",
]);

function getJobSkillContext(description = "", skill = "") {
  const text = String(description || "");
  const phrase = String(skill || "").trim();
  if (!text || !phrase) return "";
  const lowerText = text.toLowerCase();
  const lowerPhrase = phrase.toLowerCase();
  const index = lowerText.indexOf(lowerPhrase);
  if (index === -1) return "";
  const start = Math.max(0, index - 100);
  const end = Math.min(text.length, index + phrase.length + 100);
  return text.slice(start, end);
}

function buildJobSkillDisplay(skills = [], description = "") {
  const uniqueSkills = [...new Set((Array.isArray(skills) ? skills : []).map((skill) => String(skill || "").trim()).filter(Boolean))];
  const visibleSkills = [];
  const hiddenStudyAreas = [];

  uniqueSkills.forEach((skill) => {
    const normalized = skill.toLowerCase();
    const context = getJobSkillContext(description, skill);
    const looksLikeStudyArea = JOB_STUDY_AREA_TAGS.has(normalized)
      || normalized.endsWith(" study")
      || JOB_STUDY_AREA_CONTEXT_RE.test(context);

    if (looksLikeStudyArea) hiddenStudyAreas.push(skill);
    else visibleSkills.push(skill);
  });

  return {
    sourceTagCount: uniqueSkills.length,
    visibleSkills,
    hiddenStudyAreas,
  };
}

function cleanAlignmentTerms(items = [], description = "") {
  const cleaned = [];
  const seen = new Set();

  (Array.isArray(items) ? items : []).forEach((item) => {
    const rawLabel = extractKeywordLabel(item)
      .replace(/^[\s:;,.|-]+|[\s:;,.|-]+$/g, "")
      .replace(/\s+/g, " ")
      .trim();
    if (!rawLabel || rawLabel.length < 2 || !/[a-z]/i.test(rawLabel)) return;

    const normalized = rawLabel.toLowerCase();
    if (ALIGNMENT_TERM_BLACKLIST.has(normalized)) return;

    const context = item?.jd_context || item?.resume_context || getJobSkillContext(description, rawLabel);
    const looksLikeStudyArea = JOB_STUDY_AREA_TAGS.has(normalized)
      || normalized.endsWith(" study")
      || JOB_STUDY_AREA_CONTEXT_RE.test(context);
    if (looksLikeStudyArea) return;

    if (seen.has(normalized)) return;
    seen.add(normalized);
    cleaned.push({
      skill: rawLabel,
      jd_context: item?.jd_context || "",
      resume_context: item?.resume_context || "",
    });
  });

  return cleaned;
}

// ─── Shared Components ─────────────────────────────────────────────────────────

function AuthPrompt({ onSignIn, featureName }) {
  return (
    <div className="text-center py-16">
      <User size={40} className="mx-auto mb-4 text-gray-300" />
      <h3 className="text-lg font-semibold text-gray-700 mb-2">Sign in to access {featureName}</h3>
      <p className="text-sm text-gray-500 mb-6 max-w-md mx-auto">
        Create a free account or sign in with your @aisg.sg email to unlock this feature.
      </p>
      <button onClick={onSignIn}
        className="bg-indigo-600 text-white px-6 py-2.5 rounded-lg text-sm font-medium hover:bg-indigo-700 transition">
        Sign In
      </button>
    </div>
  );
}

function StatusBadge({ status }) {
  const c = STATUS_CONFIG[status] || STATUS_CONFIG.applied;
  const Icon = c.icon;
  return (
    <span className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium ${c.color}`}>
      <Icon size={12} />{c.label}
    </span>
  );
}

function TierBadge({ tier }) {
  if (tier === "pro" || tier === "admin") {
    return <span className="bg-amber-100 text-amber-800 px-2 py-0.5 rounded-full text-xs font-semibold">Pro</span>;
  }
  return <span className="bg-gray-100 text-gray-600 px-2 py-0.5 rounded-full text-xs font-semibold">Free</span>;
}

function Nav({ active, setActive }) {
  const tabs = [
    { id: "scraper", label: "Jobs", icon: Search },
    { id: "power", label: "Power Match", icon: Sparkles },
    { id: "tracker", label: "Tracker", icon: Briefcase },
    { id: "reminders", label: "Reminders", icon: Bell },
    { id: "resume", label: "Resume", icon: FileText },
    { id: "account", label: "Account", icon: User },
  ];
  return (
    <div className="relative">
      <nav className="flex border-b border-gray-200 bg-white sticky top-0 z-10 overflow-x-auto scrollbar-hide"
        style={{ scrollbarWidth: "none", msOverflowStyle: "none", WebkitOverflowScrolling: "touch" }}>
        {tabs.map((t) => {
          const Icon = t.icon;
          return (
            <button key={t.id} onClick={() => setActive(t.id)}
              className={`flex items-center gap-1.5 px-4 py-3.5 text-sm font-medium whitespace-nowrap transition-colors border-b-2 ${active === t.id ? "border-indigo-600 text-indigo-600" : "border-transparent text-gray-500 hover:text-gray-700"}`}>
              <Icon size={15} />{t.label}
            </button>
          );
        })}
      </nav>
      {/* Scroll fade indicator for mobile */}
      <div className="absolute right-0 top-0 bottom-0 w-8 bg-gradient-to-l from-white to-transparent pointer-events-none sm:hidden" />
    </div>
  );
}

function AuthModal({ onAuth, onClose }) {
  const [mode, setMode] = useState("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const endpoint = mode === "login" ? "/api/auth/login" : "/api/auth/signup";
      const body = mode === "login" ? { email, password } : { email, password, name };
      const resp = await fetch(`${API_BASE}${endpoint}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!resp.ok) {
        const text = await resp.text();
        throw new Error(text || `Request failed (${resp.status})`);
      }
      const data = await resp.json();
      localStorage.setItem("token", data.token);
      onAuth(data.user, data.token);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-[9999] p-4 backdrop-blur-sm" onClick={(e) => { if (e.target === e.currentTarget && onClose) onClose(); }}>
      <div className="bg-white rounded-2xl shadow-xl max-w-md w-full p-8 relative">
        {onClose && <button onClick={onClose} className="absolute top-4 right-4 text-gray-400 hover:text-gray-600"><X size={20} /></button>}
        <div className="text-center mb-6">
          <div className="flex items-center justify-center gap-2 mb-2">
            <Briefcase size={24} className="text-indigo-600" />
            <h1 className="text-xl font-bold text-gray-800">Job Hunter SG</h1>
          </div>
          <p className="text-sm text-gray-500">
            {mode === "login" ? "Welcome back" : "Join with your @aisg.sg email"}
          </p>
          <p className="text-xs text-gray-400 mt-1">Save your applications, get unlimited AI reviews, and track your progress</p>
        </div>

        {error && (
          <div className="bg-red-50 border border-red-200 text-red-700 text-sm rounded-lg p-3 mb-4">
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          {mode === "signup" && (
            <input
              type="text" placeholder="Full Name" value={name}
              onChange={(e) => setName(e.target.value)} required
              className="w-full border border-gray-200 rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-200 focus:border-indigo-400"
            />
          )}
          <input
            type="email" placeholder="Email" value={email}
            onChange={(e) => setEmail(e.target.value)} required
            className="w-full border border-gray-200 rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-200 focus:border-indigo-400"
          />
          <input
            type="password" placeholder="Password" value={password}
            onChange={(e) => setPassword(e.target.value)} required minLength={8}
            className="w-full border border-gray-200 rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-200 focus:border-indigo-400"
          />
          <button type="submit" disabled={loading}
            className="w-full bg-indigo-600 text-white py-2.5 rounded-lg text-sm font-medium hover:bg-indigo-700 disabled:opacity-50 transition flex items-center justify-center gap-2">
            {loading && <Loader2 size={14} className="animate-spin" />}
            {mode === "login" ? "Sign In" : "Create Account"}
          </button>
        </form>

        {mode === "signup" && (
          <p className="text-xs text-gray-400 text-center mt-3">
            By signing up, you agree that we store your resume data solely to personalise your coaching experience. We never sell, share, or use your data for any other purpose.{" "}
            <button onClick={() => window.open(`${API_BASE}/api/privacy`, "_blank")} className="text-indigo-500 hover:underline">Privacy Notice</button>
          </p>
        )}

        <div className="text-center mt-4">
          <button onClick={() => { setMode(mode === "login" ? "signup" : "login"); setError(""); }}
            className="text-sm text-indigo-600 hover:underline">
            {mode === "login" ? "Don't have an account? Sign up" : "Already have an account? Sign in"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// TAB 1: JOB SCRAPER
// ═══════════════════════════════════════════════════════════════════════════════

function ScraperTab({ user, trackedJobs, onTrack, setActiveTab, setSelectedJob, onSignIn }) {
  const [query, setQuery] = useState("");
  const [submittedQuery, setSubmittedQuery] = useState("");
  const [results, setResults] = useState([]);
  const [loading, setLoading] = useState(false);
  const [levelFilter, setLevelFilter] = useState("all");
  const [employmentFilter, setEmploymentFilter] = useState("all");
  const [sourceFilter, setSourceFilter] = useState("all");
  const [locationFilter, setLocationFilter] = useState("all");
  const [minSalaryFilter, setMinSalaryFilter] = useState("");
  const [sortBy, setSortBy] = useState("newest");
  const [error, setError] = useState("");
  const [trackError, setTrackError] = useState("");
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [totalLabel, setTotalLabel] = useState("");
  const [expandedJobId, setExpandedJobId] = useState(null);
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
      const activeSource = nextFilters.sourceFilter ?? sourceFilter;
      const activeLocation = nextFilters.locationFilter ?? locationFilter;
      const activeMinSalary = nextFilters.minSalaryFilter ?? minSalaryFilter;

      if (normalizedQuery) params.set("q", normalizedQuery);
      if (activeLevel !== "all") params.set("seniority", activeLevel);
      if (activeEmployment !== "all") params.set("employment_type", activeEmployment);
      if (activeSource !== "all") params.set("source", activeSource);
      if (activeLocation !== "all") params.set("location", activeLocation);
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
        description: j.description || "",
        type: j.employment_type || "",
        level: j.seniority || "",
        url: j.url || "",
      }));
      setResults(mapped);
      if (pageNum === 1 && data.filter_meta && typeof data.filter_meta === "object") {
        setFilterMeta({
          sources: Array.isArray(data.filter_meta.sources) ? data.filter_meta.sources : [],
          employment_types: Array.isArray(data.filter_meta.employment_types) ? data.filter_meta.employment_types : [],
          locations: Array.isArray(data.filter_meta.locations) ? data.filter_meta.locations : [],
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
    if (sortBy === "salary") r.sort((a, b) => {
      const getMax = (s) => {
        const matches = String(s || "").match(/\d[\d,]*/g) || [];
        const last = matches[matches.length - 1];
        return last ? parseInt(last.replace(/,/g, ""), 10) : 0;
      };
      return getMax(b.salary) - getMax(a.salary);
    });
    return r;
  }, [results, sortBy]);

  const [filterMeta, setFilterMeta] = useState({ sources: [], employment_types: [], locations: [] });

  const sourceOptions = useMemo(
    () => filterMeta.sources.length > 0
      ? filterMeta.sources.map((s) => s.value)
      : [...new Set(results.map((job) => job.source).filter(Boolean))].sort(),
    [results, filterMeta.sources],
  );

  const employmentTypeOptions = useMemo(
    () => filterMeta.employment_types.length > 0
      ? filterMeta.employment_types.map((t) => t.value)
      : [...new Set(results.map((job) => job.type).filter(Boolean))].sort(),
    [results, filterMeta.employment_types],
  );

  const locationOptions = useMemo(
    () => filterMeta.locations.length > 0
      ? filterMeta.locations.map((l) => l.value).slice(0, 20)
      : [...new Set(results.map((job) => job.location).filter(Boolean))].sort().slice(0, 12),
    [results, filterMeta.locations],
  );

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

  const clearFilters = () => {
    setLevelFilter("all");
    setEmploymentFilter("all");
    setSourceFilter("all");
    setLocationFilter("all");
    setMinSalaryFilter("");
    setExpandedJobId(null);
    loadJobs(activeSearchQuery, 1, {
      levelFilter: "all",
      employmentFilter: "all",
      sourceFilter: "all",
      locationFilter: "all",
      minSalaryFilter: "",
    });
  };

  return (
    <div className="space-y-6">
      <div className="bg-gradient-to-r from-purple-50 to-indigo-50 rounded-xl p-5">
        <h2 className="font-semibold text-gray-800 flex items-center gap-2"><Search size={18} /> Singapore Jobs</h2>
        <p className="text-sm text-gray-500 mt-1">Browse jobs from MyCareersFuture, Careers@Gov, and more across Singapore.</p>
        <p className="mt-2 text-xs text-gray-500">Fields vary by source. If a site does not provide salary, employment type, or location, we show that explicitly instead of filling it in.</p>
      </div>

      {/* Search */}
      <div className="flex flex-col sm:flex-row gap-3">
        <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search by role, skill, or company..." onKeyDown={(e) => e.key === "Enter" && handleSearch()}
          className="flex-1 border border-gray-200 rounded-xl px-4 py-3 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-200 focus:border-indigo-400" />
        <button onClick={handleSearch} disabled={loading}
          className="flex items-center justify-center gap-2 bg-indigo-600 text-white px-5 py-3 rounded-xl text-sm font-medium hover:bg-indigo-700 disabled:opacity-40 transition sm:w-auto w-full">
          {loading ? <Loader2 size={16} className="animate-spin" /> : <Search size={16} />}
          {loading ? "Searching..." : "Search"}
        </button>
      </div>

      {totalLabel && (
        <p className="text-sm text-gray-500">
          <span className="font-medium text-gray-700">{totalLabel}</span>
          {activeSearchQuery ? ` matching "${activeSearchQuery}"` : " across Singapore"}
          {results.length > 0 && ` — showing ${(page - 1) * 20 + 1}-${(page - 1) * 20 + results.length}`}
        </p>
      )}

      {/* Filters */}
      {results.length > 0 && (
        <div className="rounded-2xl border border-gray-200 bg-white p-4 shadow-sm">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
            <div className="flex items-center gap-2">
              <Filter size={14} className="text-gray-400" />
              <div>
                <div className="text-sm font-semibold text-gray-800">Search Filters</div>
                <div className="text-xs text-gray-500">Refine by role level, employment type, source, pay, and location.</div>
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <select value={sortBy} onChange={(e) => setSortBy(e.target.value)} className="text-sm border border-gray-200 rounded-lg px-3 py-2 bg-white">
                <option value="newest">Sort: Newest</option>
                <option value="salary">Sort: Salary (High to Low)</option>
              </select>
              <button onClick={clearFilters} className="text-sm border border-gray-200 rounded-lg px-3 py-2 bg-white hover:bg-gray-50">
                Clear Filters
              </button>
              <span className="text-sm text-gray-400">Page {page}</span>
            </div>
          </div>

          <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-5">
            <select
              value={levelFilter}
              onChange={(e) => {
                const value = e.target.value;
                setLevelFilter(value);
                loadJobs(activeSearchQuery, 1, { levelFilter: value });
              }}
              className="text-sm border border-gray-200 rounded-xl px-3 py-2.5 bg-white"
            >
              <option value="all">All levels</option>
              <option value="Junior">Junior</option>
              <option value="Mid">Mid</option>
              <option value="Mid-Senior">Mid-Senior</option>
              <option value="Senior">Senior</option>
            </select>

            <select
              value={employmentFilter}
              onChange={(e) => {
                const value = e.target.value;
                setEmploymentFilter(value);
                loadJobs(activeSearchQuery, 1, { employmentFilter: value });
              }}
              className="text-sm border border-gray-200 rounded-xl px-3 py-2.5 bg-white"
            >
              <option value="all">All employment types</option>
              {employmentTypeOptions.map((type) => (
                <option key={type} value={type}>{type}</option>
              ))}
            </select>

            <select
              value={sourceFilter}
              onChange={(e) => {
                const value = e.target.value;
                setSourceFilter(value);
                loadJobs(activeSearchQuery, 1, { sourceFilter: value });
              }}
              className="text-sm border border-gray-200 rounded-xl px-3 py-2.5 bg-white"
            >
              <option value="all">All sources</option>
              {sourceOptions.map((source) => (
                <option key={source} value={source}>{source}</option>
              ))}
            </select>

            <select
              value={locationFilter}
              onChange={(e) => {
                const value = e.target.value;
                setLocationFilter(value);
                loadJobs(activeSearchQuery, 1, { locationFilter: value });
              }}
              className="text-sm border border-gray-200 rounded-xl px-3 py-2.5 bg-white"
            >
              <option value="all">All locations</option>
              {locationOptions.map((location) => (
                <option key={location} value={location}>{location}</option>
              ))}
            </select>

            <input
              type="number"
              min="0"
              value={minSalaryFilter}
              onChange={(e) => {
                const value = e.target.value;
                setMinSalaryFilter(value);
              }}
              onBlur={() => loadJobs(activeSearchQuery, 1, { minSalaryFilter })}
              onKeyDown={(e) => {
                if (e.key === "Enter") loadJobs(activeSearchQuery, 1, { minSalaryFilter });
              }}
              placeholder="Minimum salary"
              className="text-sm border border-gray-200 rounded-xl px-3 py-2.5 bg-white"
            />
          </div>
          {minSalaryFilter && (
            <div className="mt-3 text-xs text-gray-500">
              Jobs that explicitly list pay below your floor are hidden. Jobs with no salary posted stay visible.
            </div>
          )}
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
        const skillDisplay = buildJobSkillDisplay(job.skills, job.description);
        const previewSkills = skillDisplay.visibleSkills.slice(0, 6);

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
              </div>
              {job.description && !isExpanded && <p className="text-sm text-gray-600 mb-3 line-clamp-2">{job.description}</p>}
              {!isExpanded && previewSkills.length > 0 && (
                <div className="flex flex-wrap gap-1.5 mb-3">
                  {previewSkills.map((skill) => (
                    <span key={skill} className="bg-indigo-50 text-indigo-700 px-2 py-0.5 rounded-full text-xs">{skill}</span>
                  ))}
                  {skillDisplay.visibleSkills.length > previewSkills.length && <span className="text-xs text-gray-400">+{skillDisplay.visibleSkills.length - previewSkills.length} more</span>}
                </div>
              )}
            </div>
          </div>
          {isExpanded && (
            <div className="mt-4 rounded-2xl border border-gray-100 bg-gray-50 p-4">
              <div className="text-xs font-semibold uppercase tracking-[0.16em] text-gray-500">Description</div>
              {job.description ? (
                <p className="mt-2 whitespace-pre-line text-sm leading-relaxed text-gray-700">{job.description}</p>
              ) : (
                <p className="mt-2 text-sm text-gray-600">
                  This source did not provide a structured description in our cache.
                  {job.url && " Open the listing to inspect the full posting."}
                </p>
              )}

              <div className="mt-4 text-xs font-semibold uppercase tracking-[0.16em] text-gray-500">Source Tags & Skill Cues</div>
              {skillDisplay.visibleSkills.length > 0 ? (
                <>
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {skillDisplay.visibleSkills.map((skill) => (
                      <span key={skill} className="rounded-full bg-white px-2 py-0.5 text-xs font-medium text-gray-700 ring-1 ring-gray-200">
                        {skill}
                      </span>
                    ))}
                  </div>
                  <div className="mt-3 text-xs text-gray-500">
                    Showing {skillDisplay.visibleSkills.length} practical cue{skillDisplay.visibleSkills.length === 1 ? "" : "s"} from {skillDisplay.sourceTagCount} source tag{skillDisplay.sourceTagCount === 1 ? "" : "s"}.
                  </div>
                  {skillDisplay.hiddenStudyAreas.length > 0 && (
                    <div className="mt-2 text-xs text-amber-700">
                      Hid {skillDisplay.hiddenStudyAreas.length} broad study-area label{skillDisplay.hiddenStudyAreas.length === 1 ? "" : "s"} like {skillDisplay.hiddenStudyAreas.slice(0, 2).join(", ")} so this stays focused on practical fit.
                    </div>
                  )}
                </>
              ) : job.skills.length > 0 ? (
                <div className="mt-2 text-sm text-gray-600">
                  This listing only exposed broad source tags, so we did not surface them as practical skill cues.
                </div>
              ) : (
                <div className="mt-2 text-sm text-gray-600">
                  No structured skills were captured from this source for this posting.
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
                <FileText size={12} /> Generate Resume
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
  );
}

function PowerTab({ onTrack, setSelectedJob, setActiveTab }) {
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

// ═══════════════════════════════════════════════════════════════════════════════
// TAB 2: APPLICATION TRACKER
// ═══════════════════════════════════════════════════════════════════════════════

function TrackerTab({ user, jobs, refreshJobs }) {
  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState(null);
  const [filterStatus, setFilterStatus] = useState("all");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [form, setForm] = useState({
    company: "", role: "", date_applied: todayStr(), status: "applied",
    source: "MyCareersFuture", follow_up_date: "", notes: "",
  });

  const resetForm = () => {
    setForm({
      company: "", role: "", date_applied: todayStr(), status: "applied",
      source: "MyCareersFuture", follow_up_date: "", notes: "",
    });
    setShowForm(false);
    setEditingId(null);
    setError("");
  };

  const handleSave = async () => {
    if (!form.company || !form.role) return;
    setSaving(true);
    setError("");
    try {
      if (editingId) {
        await apiFetch(`/api/tracked/${editingId}`, {
          method: "PUT",
          body: JSON.stringify(form),
        });
      } else {
        await apiFetch("/api/tracked", {
          method: "POST",
          body: JSON.stringify(form),
        });
      }
      resetForm();
      await refreshJobs();
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  };

  const handleEdit = (job) => {
    setForm({
      company: job.company || "",
      role: job.role || "",
      date_applied: job.date_applied || todayStr(),
      status: job.status || "applied",
      source: job.source || "MyCareersFuture",
      follow_up_date: job.follow_up_date || "",
      notes: job.notes || "",
    });
    setEditingId(job.id);
    setShowForm(true);
  };

  const handleDelete = async (id) => {
    try {
      await apiFetch(`/api/tracked/${id}`, { method: "DELETE" });
      await refreshJobs();
    } catch (err) {
      setError(err.message || "Failed to delete job.");
    }
  };

  const handleExport = async () => {
    try {
      const token = localStorage.getItem("token");
      const resp = await fetch(`${API_BASE}/api/tracked/export`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!resp.ok) throw new Error(`Export failed (${resp.status})`);
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "tracked_jobs.csv";
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(err.message || "Export failed. Please try again.");
    }
  };

  const filtered = filterStatus === "all" ? jobs : jobs.filter((j) => j.status === filterStatus);
  const stats = {
    total: jobs.length,
    applied: jobs.filter((j) => j.status === "applied").length,
    interview: jobs.filter((j) => j.status === "interview").length,
    offer: jobs.filter((j) => j.status === "offer").length,
  };

  const isPro = user?.tier === "pro" || user?.tier === "admin";
  const isFree = user?.tier === "free";
  const atLimit = isFree;

  return (
    <div className="space-y-6">
      {error && !showForm && (
        <div className="bg-red-50 border border-red-200 text-red-700 text-sm rounded-lg p-3 flex items-center justify-between">
          <div className="flex items-center gap-2"><AlertCircle size={14} className="flex-shrink-0" />{error}</div>
          <button onClick={() => setError("")} className="text-red-400 hover:text-red-600"><X size={14} /></button>
        </div>
      )}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        {[
          { label: "Total", value: stats.total, bg: "bg-gray-50" },
          { label: "Applied", value: stats.applied, bg: "bg-blue-50" },
          { label: "Interviews", value: stats.interview, bg: "bg-yellow-50" },
          { label: "Offers", value: stats.offer, bg: "bg-green-50" },
        ].map((s) => (
          <div key={s.label} className={`${s.bg} rounded-xl p-4 text-center`}>
            <div className="text-2xl font-bold text-gray-800">{s.value}</div>
            <div className="text-xs text-gray-500 mt-1">{s.label}</div>
          </div>
        ))}
      </div>

      {atLimit && (
        <div className="bg-amber-50 border border-amber-200 rounded-lg p-4 text-sm text-amber-800">
          <div className="font-medium mb-1">Application tracking is unlocked on AISG Tier</div>
          <p>Upgrade to unlock unlimited tracked jobs, CSV export, and follow-up reminders.</p>
        </div>
      )}

      <div className="flex justify-between items-center">
        <div className="flex items-center gap-2">
          <Filter size={14} className="text-gray-400" />
          <select value={filterStatus} onChange={(e) => setFilterStatus(e.target.value)} className="text-sm border border-gray-200 rounded-lg px-3 py-1.5 bg-white">
            <option value="all">All statuses</option>
            {Object.entries(STATUS_CONFIG).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
          </select>
        </div>
        <div className="flex items-center gap-2">
          {isPro && (
            <button onClick={handleExport} className="flex items-center gap-2 border border-gray-200 text-gray-600 px-4 py-2 rounded-lg text-sm font-medium hover:bg-gray-50 transition">
              <Download size={14} /> Export CSV
            </button>
          )}
          <button onClick={() => refreshJobs()} className="flex items-center gap-2 border border-gray-200 text-gray-600 px-3 py-2 rounded-lg text-sm hover:bg-gray-50 transition">
            <RefreshCw size={14} />
          </button>
          <button onClick={() => { resetForm(); setShowForm(true); }} disabled={atLimit}
            className="flex items-center gap-2 bg-indigo-600 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-indigo-700 disabled:opacity-40 transition">
            <Plus size={16} /> Add
          </button>
        </div>
      </div>

      {showForm && (
        <div className="bg-white border border-gray-200 rounded-xl p-5 space-y-4 shadow-sm">
          <div className="flex justify-between items-center">
            <h3 className="font-semibold text-gray-800">{editingId ? "Edit" : "New"} Application</h3>
            <button onClick={resetForm} className="text-gray-400 hover:text-gray-600"><X size={18} /></button>
          </div>
          {error && <div className="bg-red-50 border border-red-200 text-red-700 text-sm rounded-lg p-3">{error}</div>}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <input placeholder="Company *" value={form.company} onChange={(e) => setForm({ ...form, company: e.target.value })} className="border border-gray-200 rounded-lg px-3 py-2 text-sm" />
            <input placeholder="Role *" value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })} className="border border-gray-200 rounded-lg px-3 py-2 text-sm" />
            <div>
              <label className="text-xs text-gray-500 mb-1 block">Applied</label>
              <input type="date" value={form.date_applied} onChange={(e) => setForm({ ...form, date_applied: e.target.value })} className="border border-gray-200 rounded-lg px-3 py-2 text-sm w-full" />
            </div>
            <select value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value })} className="border border-gray-200 rounded-lg px-3 py-2 text-sm">
              {Object.entries(STATUS_CONFIG).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
            </select>
            <select value={form.source} onChange={(e) => setForm({ ...form, source: e.target.value })} className="border border-gray-200 rounded-lg px-3 py-2 text-sm">
              {SG_JOB_PORTALS.map((p) => <option key={p.key} value={p.name}>{p.name}</option>)}
              <option value="Referral">Referral</option>
              <option value="Other">Other</option>
            </select>
            <div>
              <label className="text-xs text-gray-500 mb-1 block">Follow-up</label>
              <input type="date" value={form.follow_up_date || ""} onChange={(e) => setForm({ ...form, follow_up_date: e.target.value })} className="border border-gray-200 rounded-lg px-3 py-2 text-sm w-full" />
            </div>
          </div>
          <textarea placeholder="Notes" value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} className="border border-gray-200 rounded-lg px-3 py-2 text-sm w-full" rows={2} />
          <button onClick={handleSave} disabled={saving || !form.company || !form.role}
            className="flex items-center gap-2 bg-indigo-600 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-indigo-700 disabled:opacity-40 transition">
            {saving ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
            {editingId ? "Update" : "Save"}
          </button>
        </div>
      )}

      {/* Desktop table */}
      <div className="bg-white border border-gray-200 rounded-xl overflow-hidden hidden sm:block">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 text-gray-500 text-xs uppercase">
            <tr>
              <th className="text-left px-4 py-3">Company</th>
              <th className="text-left px-4 py-3">Role</th>
              <th className="text-left px-4 py-3">Applied</th>
              <th className="text-left px-4 py-3">Source</th>
              <th className="text-left px-4 py-3">Status</th>
              <th className="text-left px-4 py-3">Days</th>
              <th className="text-right px-4 py-3">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {filtered.length === 0 && (
              <tr><td colSpan={7} className="text-center py-8 text-gray-400">No applications yet</td></tr>
            )}
            {filtered.map((job) => (
              <tr key={job.id} className="hover:bg-gray-50 transition">
                <td className="px-4 py-3 font-medium text-gray-800">{job.company}</td>
                <td className="px-4 py-3 text-gray-600">{job.role}</td>
                <td className="px-4 py-3 text-gray-500">{job.date_applied}</td>
                <td className="px-4 py-3 text-gray-500">{job.source}</td>
                <td className="px-4 py-3"><StatusBadge status={job.status} /></td>
                <td className="px-4 py-3 text-gray-500">{daysBetween(job.date_applied, todayStr())}d</td>
                <td className="px-4 py-3 text-right">
                  <button onClick={() => handleEdit(job)} className="text-gray-400 hover:text-indigo-600 mr-2"><Edit3 size={14} /></button>
                  <button onClick={() => handleDelete(job.id)} className="text-gray-400 hover:text-red-500"><Trash2 size={14} /></button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Mobile card layout */}
      <div className="sm:hidden space-y-3">
        {filtered.length === 0 && (
          <div className="text-center py-8 text-gray-400 text-sm">No applications yet</div>
        )}
        {filtered.map((job) => (
          <div key={job.id} className="bg-white border border-gray-200 rounded-xl p-4 space-y-2">
            <div className="flex items-start justify-between">
              <div>
                <div className="font-semibold text-gray-800 text-sm">{job.company}</div>
                <div className="text-sm text-gray-600">{job.role}</div>
              </div>
              <StatusBadge status={job.status} />
            </div>
            <div className="flex items-center gap-3 text-xs text-gray-500">
              <span>{job.date_applied}</span>
              <span>{job.source}</span>
              <span>{daysBetween(job.date_applied, todayStr())}d ago</span>
            </div>
            {job.notes && <p className="text-xs text-gray-400">{job.notes}</p>}
            <div className="flex gap-2 pt-1">
              <button onClick={() => handleEdit(job)} className="text-xs text-indigo-600 hover:underline flex items-center gap-1"><Edit3 size={12} /> Edit</button>
              <button onClick={() => handleDelete(job.id)} className="text-xs text-red-500 hover:underline flex items-center gap-1"><Trash2 size={12} /> Delete</button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// TAB 3: REMINDERS
// ═══════════════════════════════════════════════════════════════════════════════

function RemindersTab({ jobs, onUpdateJob }) {
  const [error, setError] = useState("");
  const td = todayStr();
  const pending = jobs
    .filter((j) => j.follow_up_date && (j.status === "applied" || j.status === "interview"))
    .map((j) => ({ ...j, daysUntil: daysBetween(td, j.follow_up_date) }))
    .sort((a, b) => a.daysUntil - b.daysUntil);
  const overdue = pending.filter((j) => j.daysUntil < 0);
  const dueToday = pending.filter((j) => j.daysUntil === 0);
  const upcoming = pending.filter((j) => j.daysUntil > 0 && j.daysUntil <= 7);
  const later = pending.filter((j) => j.daysUntil > 7);

  const snooze = async (job) => {
    setError("");
    try {
      const newDate = new Date(Date.now() + 7 * 86400000).toISOString().split("T")[0];
      await onUpdateJob(job.id, { follow_up_date: newDate });
    } catch (err) {
      setError(err.message || "Failed to snooze reminder.");
    }
  };

  const markDone = async (job) => {
    setError("");
    try {
      await onUpdateJob(job.id, { follow_up_date: null });
    } catch (err) {
      setError(err.message || "Failed to update reminder.");
    }
  };

  const Card = ({ job, urgency }) => {
    const colors = {
      overdue: "border-red-300 bg-red-50",
      today: "border-yellow-300 bg-yellow-50",
      upcoming: "border-blue-200 bg-blue-50",
      later: "border-gray-200 bg-white",
    };
    return (
      <div className={`border rounded-xl p-4 ${colors[urgency]} transition hover:shadow-sm`}>
        <div className="flex justify-between items-start">
          <div>
            <div className="font-semibold text-gray-800">{job.company}</div>
            <div className="text-sm text-gray-500">{job.role}</div>
            {job.notes && <div className="text-xs text-gray-400 mt-1">{job.notes}</div>}
          </div>
          <div className="text-right">
            <StatusBadge status={job.status} />
            <div className="text-xs text-gray-500 mt-2">
              {job.daysUntil < 0 ? `${Math.abs(job.daysUntil)} days overdue` : job.daysUntil === 0 ? "Due today!" : `In ${job.daysUntil} days`}
            </div>
          </div>
        </div>
        <div className="flex gap-2 mt-3">
          <button onClick={() => snooze(job)} className="text-xs bg-white border border-gray-200 rounded-lg px-3 py-1.5 hover:bg-gray-50">Snooze 7d</button>
          <button onClick={() => markDone(job)} className="text-xs bg-white border border-gray-200 rounded-lg px-3 py-1.5 hover:bg-gray-50">Done</button>
        </div>
      </div>
    );
  };

  const Section = ({ title, items, urgency }) => items.length > 0 && (
    <div>
      <h3 className="text-sm font-semibold text-gray-500 uppercase tracking-wide mb-3">{title} ({items.length})</h3>
      <div className="space-y-3">{items.map((j) => <Card key={j.id} job={j} urgency={urgency} />)}</div>
    </div>
  );

  return (
    <div className="space-y-8">
      <div className="bg-gradient-to-r from-indigo-50 to-blue-50 rounded-xl p-5">
        <h2 className="font-semibold text-gray-800 flex items-center gap-2"><Bell size={18} /> Follow-up Reminders</h2>
        <p className="text-sm text-gray-500 mt-1">Never let an application go cold. Follow up within 14 days of applying.</p>
      </div>
      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 text-sm rounded-lg p-3 flex items-center justify-between">
          <div className="flex items-center gap-2"><AlertCircle size={14} className="flex-shrink-0" />{error}</div>
          <button onClick={() => setError("")} className="text-red-400 hover:text-red-600"><X size={14} /></button>
        </div>
      )}
      {pending.length === 0 ? (
        <div className="text-center py-12 text-gray-400">No follow-ups scheduled. Add follow-up dates in Tracker.</div>
      ) : (
        <>
          <Section title="Overdue" items={overdue} urgency="overdue" />
          <Section title="Due Today" items={dueToday} urgency="today" />
          <Section title="This Week" items={upcoming} urgency="upcoming" />
          <Section title="Later" items={later} urgency="later" />
        </>
      )}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// TAB 4: UNIFIED RESUME WORKSPACE
// ═══════════════════════════════════════════════════════════════════════════════

const DEFAULT_RESUME_TEMPLATES = [
  {
    id: "classic",
    name: "Classic",
    description: "Traditional serif layout with crisp section dividers.",
    font: "Times New Roman",
    body_size: 11,
    name_size: 16,
    margins: 1.0,
    section_order: ["summary", "education", "experience", "skills", "certifications"],
  },
  {
    id: "modern",
    name: "Modern",
    description: "Sharper hierarchy for technical and startup roles.",
    font: "Calibri",
    body_size: 10,
    name_size: 14,
    margins: 0.6,
    section_order: ["summary", "experience", "projects", "skills", "education"],
  },
  {
    id: "singapore",
    name: "SG Pro",
    description: "Polished local-market style with balanced spacing.",
    font: "Calibri",
    body_size: 11,
    name_size: 15,
    margins: 0.8,
    section_order: ["personal", "summary", "education", "experience", "activities", "skills"],
  },
  {
    id: "compact",
    name: "Compact",
    description: "Tighter layout for experienced candidates.",
    font: "Arial",
    body_size: 10,
    name_size: 14,
    margins: 0.5,
    section_order: ["summary", "experience", "skills", "education", "certifications"],
  },
];

const RESUME_TEMPLATE_STYLES = {
  classic: {
    pageClass: "text-stone-800",
    fontFamily: '"Times New Roman", Georgia, serif',
    bodySize: 11,
    nameSize: 16,
    margins: 1.0,
    lineHeight: 1.35,
    headingSize: 12,
    headingClass: "mt-4 mb-1 border-b border-stone-400 pb-1 font-bold uppercase tracking-[0.18em] text-stone-900",
    nameClass: "font-bold tracking-[0.08em] text-stone-950",
    subheadingClass: "mt-2 mb-0.5 text-stone-700",
  },
  modern: {
    pageClass: "text-slate-800",
    fontFamily: 'Calibri, "Segoe UI", sans-serif',
    bodySize: 10,
    nameSize: 14,
    margins: 0.6,
    lineHeight: 1.33,
    headingSize: 11,
    headingClass: "mt-4 mb-1 border-b border-indigo-500 pb-1 font-bold uppercase tracking-[0.18em] text-slate-900",
    nameClass: "font-bold tracking-[0.04em] text-slate-950",
    subheadingClass: "mt-2 mb-0.5 text-slate-700",
  },
  singapore: {
    pageClass: "text-slate-800",
    fontFamily: 'Calibri, "Segoe UI", sans-serif',
    bodySize: 11,
    nameSize: 15,
    margins: 0.8,
    lineHeight: 1.35,
    headingSize: 12,
    headingClass: "mt-4 mb-1 border-b-2 border-slate-700 pb-1 font-bold uppercase tracking-[0.16em] text-slate-950",
    nameClass: "font-bold tracking-[0.04em] text-slate-950",
    subheadingClass: "mt-2 mb-0.5 text-slate-700",
  },
  compact: {
    pageClass: "text-zinc-800",
    fontFamily: "Arial, Helvetica, sans-serif",
    bodySize: 10,
    nameSize: 14,
    margins: 0.5,
    lineHeight: 1.3,
    headingSize: 11,
    headingClass: "mt-4 mb-1 border-b border-zinc-400 pb-1 font-bold uppercase tracking-[0.14em] text-zinc-950",
    nameClass: "font-bold tracking-[0.03em] text-zinc-950",
    subheadingClass: "mt-2 mb-0.5 text-zinc-700",
  },
};

function buildResumeTemplateStyles(templateMeta, templateId) {
  const fallback = RESUME_TEMPLATE_STYLES[templateId] || RESUME_TEMPLATE_STYLES.modern;
  const bodySize = Number.isFinite(templateMeta?.body_size) ? templateMeta.body_size : fallback.bodySize;
  const nameSize = Number.isFinite(templateMeta?.name_size) ? templateMeta.name_size : fallback.nameSize;
  const margins = Number.isFinite(templateMeta?.margins) ? templateMeta.margins : fallback.margins;
  const requestedFont = typeof templateMeta?.font === "string" ? templateMeta.font.trim() : "";
  const fontFamily = requestedFont
    ? requestedFont.includes(",")
      ? requestedFont
      : fallback.fontFamily.toLowerCase().includes(requestedFont.toLowerCase())
        ? fallback.fontFamily
        : `${requestedFont}, ${fallback.fontFamily}`
    : fallback.fontFamily;
  const lineHeight = fallback.lineHeight;
  const headingSize = fallback.headingSize;

  return {
    pageClass: fallback.pageClass,
    pageStyle: {
      fontFamily,
      fontSize: `${bodySize}pt`,
      padding: `${margins * 25.4}mm`,
      width: "210mm",
      minHeight: "297mm",
      maxWidth: "100%",
      lineHeight: String(lineHeight),
    },
    headingClass: fallback.headingClass,
    headingStyle: {
      fontFamily,
      fontSize: `${headingSize}pt`,
      lineHeight: String(lineHeight),
    },
    nameClass: fallback.nameClass,
    nameStyle: {
      fontFamily,
      fontSize: `${nameSize}pt`,
      lineHeight: "1.15",
    },
    contactStyle: {
      fontFamily,
      fontSize: `${Math.max(bodySize - 1, 9)}pt`,
      lineHeight: String(lineHeight),
    },
    subheadingClass: fallback.subheadingClass,
    bodyStyle: {
      fontFamily,
      fontSize: `${bodySize}pt`,
      lineHeight: String(lineHeight),
    },
  };
}

const NUS_RESUME_BENCHMARKS = [
  {
    value: "490",
    label: "Average words seen across NUS resumes",
  },
  {
    value: "21",
    label: "Average bullets in stronger resume drafts",
  },
  {
    value: "16",
    label: "Action verbs often seen in 80+ scoring resumes",
  },
  {
    value: "25",
    label: "Specifics or quantified cues in stronger resumes",
  },
  {
    value: "4-5",
    label: "Section headings most resumes tend to carry",
  },
];

const RESUME_HEADINGS = new Set([
  "summary",
  "professional summary",
  "executive summary",
  "career summary",
  "professional profile",
  "profile",
  "summary of qualifications",
  "qualifications",
  "experience",
  "professional experience",
  "work experience",
  "employment history",
  "career history",
  "work and internship experience",
  "work and internship experiences",
  "internship and work experience",
  "education",
  "academic background",
  "skills",
  "skills & interests",
  "skills and interests",
  "core skills",
  "technical skills",
  "technical proficiencies",
  "core competencies",
  "competencies",
  "projects",
  "selected projects",
  "leadership",
  "activities",
  "activities & leadership",
  "certifications",
  "certification",
  "licenses",
  "licenses & certifications",
  "certifications & technical upskilling",
  "awards",
  "volunteer",
  "volunteering",
  "interests",
  "languages",
  "languages & work authorization",
  "additional information",
  "co-curricular experience",
  "extra-curriculars",
  "personal",
  "personal particulars",
]);

const RESUME_TEMPLATE_SECTION_ORDER = {
  classic: ["summary", "education", "experience", "skills", "certifications"],
  modern: ["summary", "experience", "projects", "skills", "education"],
  singapore: ["personal", "summary", "education", "experience", "activities", "skills"],
  compact: ["summary", "experience", "skills", "education", "certifications"],
};

const RESUME_ACTION_VERBS = new Set([
  "achieved", "administered", "advanced", "analyzed", "architected",
  "assembled", "assessed", "automated", "built", "calculated",
  "championed", "coached", "collaborated", "communicated", "completed",
  "conceptualized", "conducted", "consolidated", "constructed",
  "consulted", "contributed", "controlled", "converted", "coordinated",
  "created", "cultivated", "customized", "decreased", "defined",
  "delivered", "demonstrated", "deployed", "designed", "developed",
  "devised", "diagnosed", "directed", "discovered", "documented",
  "drove", "earned", "edited", "educated", "eliminated", "enabled",
  "encouraged", "engineered", "enhanced", "established", "evaluated",
  "examined", "exceeded", "executed", "expanded", "expedited",
  "facilitated", "finalized", "forecasted", "formulated", "founded",
  "generated", "governed", "guided", "headed", "identified",
  "illustrated", "implemented", "improved", "increased", "influenced",
  "initiated", "innovated", "inspected", "installed", "instituted",
  "integrated", "interpreted", "introduced", "invented", "investigated",
  "launched", "led", "leveraged", "maintained", "managed", "mapped",
  "maximized", "mentored", "merged", "migrated", "minimized",
  "modernized", "monitored", "motivated", "navigated", "negotiated",
  "operated", "optimized", "orchestrated", "organized", "originated",
  "outperformed", "overhauled", "oversaw", "partnered", "performed",
  "piloted", "pioneered", "planned", "prepared", "presented",
  "prioritized", "produced", "programmed", "promoted", "proposed",
  "provided", "published", "pursued", "reached", "realized",
  "recommended", "reconciled", "recruited", "redesigned", "reduced",
  "refined", "reformed", "regulated", "reorganized", "represented",
  "researched", "resolved", "restructured", "revamped", "reviewed",
  "scaled", "secured", "simplified", "solved", "spearheaded",
  "standardized", "streamlined", "strengthened", "structured",
  "supervised", "surpassed", "sustained", "synchronized", "targeted",
  "tested", "trained", "transformed", "translated", "troubleshot",
  "unified", "upgraded", "validated", "verified", "visualized",
]);

const RESUME_AVOIDED_PHRASES = [
  "responsible for",
  "helped",
  "assisted",
  "duties included",
  "various",
  "utilized",
  "proactively",
];

const BULLET_ACTION_SUGGESTIONS = [
  "Administered",
  "Customized",
  "Facilitated",
  "Implemented",
  "Managed",
  "Optimized",
  "Orchestrated",
  "Spearheaded",
];

const RESUME_WEAK_STARTS = ["responsible for", "helped", "assisted"];
const RESUME_BULLET_RE = /^(\s*(?:[-*o\u2022\u2023\u25E6\u2043\u2219\u25AA\u25AB\u25CF\uF0B7▪●]|\d+[.)]))\s*(.*)$/;
const RESUME_METRIC_RE = /\d+%|\$[\d,]+|\d+\s*(?:users|user|team|people|projects|systems|clients|hours|weeks|months|years)|\d+[kKmMbB]\b|\d{1,3}(?:,\d{3})+/;
const RESUME_SCALE_CUE_PATTERNS = [
  /\bteam of \d+\b/gi,
  /\b\d+\s+(?:direct|indirect)\s+reports?\b/gi,
  /\b\d+\s+(?:reports?|engineers?|specialists?|operators?|owners?|stakeholders?|people|users?|clients?|projects?|systems?|hours?|weeks?|months?|years?|sites?|fabs?|fab\s+lines?|lines?|plants?|dashboards?|sensors?|parameters?|countries?|regions?|modules?|tools?)\b/gi,
  /\b(?:across|over|under|up to|more than|less than|nearly|almost)\s+\d+(?:\.\d+)?\s+(?:sites?|fabs?|fab\s+lines?|lines?|plants?|regions?|countries?|teams?|people|users?|projects?|systems?|clients?|engineers?|specialists?|reports?|hours?|weeks?|months?|years?|dashboards?|sensors?|parameters?)\b/gi,
];
const RESUME_DATE_HINT_RE = /\b(?:19|20)\d{2}\b|present|current|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec/i;
const RESUME_CERTIFICATION_RE = /certification|certifications|certificate|certified|pmp|wsq|skillsfuture|accredited|in progress|target|gmat|upskilling|emeritus|heicoders|completed.*course|full stack development|generative ai|currently pursuing/i;
const RESUME_EDUCATION_RE = /\b(?:university|polytechnic|college|school|institute|academy|faculty|gpa|degree|diploma|bachelor|master|ph\.?d|exchange|graduated|major|minor|focus|capstone|national university|nanyang|singapore management|nus|ntu|smu|sutd|sit|suss)\b/i;
const RESUME_EDUCATION_INSTITUTION_RE = /\b(?:university|polytechnic|college|school|institute|academy|faculty|national university|nanyang|singapore management|nus|ntu|smu|sutd|sit|suss)\b/i;
const RESUME_DEGREE_RE = /\b(?:b\.?sc|m\.?sc|b\.?eng|m\.?eng|b\.?a|m\.?a|bachelor|master|ph\.?d|doctorate|diploma|advanced diploma|associate|degree|mba|certificate|cert)\b/i;
const DEGREE_START_RE = /^(M\.?Sc|B\.?Sc|B\.?Eng|MBA|M\.?Eng|Ph\.?D|B\.?A|M\.?A|Diploma|Advanced Diploma|Associate|Graduate Cert(?:ificate)?|Certificate|Cert)/i;
const RESUME_EDUCATION_DETAIL_RE = /gpa|exchange|focus|capstone|graduate certificate|graduate certificates|minor|major|distinction|honou?r/i;
const RESUME_OVERUSED_IGNORE = new Set([
  "automation", "digital", "transformation", "program", "manager", "management",
  "yield", "data", "analytics", "analysis", "operations", "engineering",
  "technology", "technologies", "quality", "process", "processes", "project",
  "projects", "stakeholder", "stakeholders", "cross", "functional", "global",
  "system", "systems", "team", "teams", "experience", "skills", "education",
  "resume", "singapore", "micron", "ai", "ml", "reliability",
]);
const RESUME_DISPLAY_ACRONYMS = new Set([
  "AI", "ML", "APAC", "ROI", "KPI", "SQL", "API", "APIs", "USD", "RCA", "SPC",
  "EQMS", "IT", "OT", "IT/OT", "DOE", "DoE", "RPA", "NPI", "NUS", "SG",
  "FEOL", "FE", "BE", "HBM3E", "LPDDR5X", "TTMCY", "RAG", "MCP", "WSQ",
  "PMP", "GMAT", "GCP",
]);
const RESUME_SMALL_TITLE_WORDS = new Set([
  "a", "an", "and", "as", "at", "by", "for", "from", "in", "into", "of",
  "on", "or", "the", "to", "with",
]);
const RESUME_SECTION_LABELS = {
  summary: "Professional Summary",
  objective: "Objective",
  experience: "Professional Experience",
  education: "Education",
  skills: "Core Skills",
  projects: "Projects",
  certifications: "Certifications",
  activities: "Volunteer & Leadership",
  personal: "Additional Information",
  languages: "Languages",
  awards: "Awards",
};
const TAILOR_STAGE_LABELS = [
  { id: "analyze", label: "Analyze" },
  { id: "strategize", label: "Strategy" },
  { id: "local_cleanup", label: "Cleanup" },
  { id: "bullet_rewrite", label: "Rewrite" },
  { id: "section_polish", label: "Polish" },
  { id: "full_polish", label: "Summary" },
  { id: "validate", label: "Validate" },
];
const ADD_SECTION_OPTIONS = [
  { id: "summary", label: "Professional Summary", heading: "PROFESSIONAL SUMMARY", starter: "Add a concise summary of your fit, scope, and focus areas here." },
  { id: "projects", label: "Projects", heading: "PROJECTS", starter: "• Add project details here" },
  { id: "certifications", label: "Certifications", heading: "CERTIFICATIONS", starter: "• Add certification or ongoing credential here" },
  { id: "languages", label: "Languages", heading: "LANGUAGES", starter: "Add languages and proficiency here." },
  { id: "volunteer", label: "Volunteer", heading: "VOLUNTEER EXPERIENCE", starter: "• Add volunteer experience here" },
  { id: "awards", label: "Awards", heading: "AWARDS", starter: "• Add award or recognition here" },
  { id: "custom", label: "Custom", heading: "", starter: "• Add details here" },
];

function getTailorChangeKey(change, index = 0) {
  if (!change) return `change-${index}`;
  if (change.type === "summary_rewrite") return "summary";
  return change.bullet_id || `${change.type || "change"}-${index}`;
}

function getAtsGapKey(gap) {
  return [
    gap?.skill || "",
    gap?.suggested_section || "",
    gap?.required ? "required" : "preferred",
    gap?.action || "",
  ].join("::");
}

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function titleCase(value) {
  return value
    .replace(/_/g, " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function stripResumeMarkdown(line) {
  return String(line || "")
    .replace(/\*\*(.*?)\*\*/g, "$1")
    .replace(/__(.*?)__/g, "$1")
    .trim();
}

function normalizeHeadingLabel(value) {
  return stripResumeMarkdown(value)
    .toLowerCase()
    .replace(/[:*]+$/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

function splitInlineHeadingContent(value) {
  const cleaned = stripResumeMarkdown(value);
  if (!cleaned) return null;

  const headingCandidates = [...RESUME_HEADINGS].sort((a, b) => b.length - a.length);
  for (const heading of headingCandidates) {
    const pattern = new RegExp(
      `^(${escapeRegExp(heading)})(?:\\s*[:|-]\\s*|\\s*\\|\\s*)(.+)$`,
      "i",
    );
    const match = cleaned.match(pattern);
    if (!match) continue;
    const bodyText = match[2].trim();
    if (!bodyText) continue;
    if (normalizeHeadingLabel(bodyText) === heading) continue;
    return {
      headingText: match[1].trim().replace(/:$/, ""),
      bodyText,
      sectionKey: getResumeSectionKey(match[1]),
    };
  }

  return null;
}

function extractKeywordLabel(item) {
  if (typeof item === "string") return item.trim();
  if (item && typeof item.skill === "string") return item.skill.trim();
  return "";
}

function getResumeSectionKey(value) {
  const normalized = normalizeHeadingLabel(value);
  if (!normalized) return "";
  if (normalized.includes("academic qualification") || normalized.includes("academic qualifications")) return "education";
  if (
    normalized.includes("summary")
    || normalized.includes("profile")
    || normalized.includes("qualification")
  ) return "summary";
  if (normalized.includes("education")) return "education";
  if (normalized.includes("academic background")) return "education";
  if (normalized.includes("experience")) {
    if (normalized.includes("co-curricular") || normalized.includes("extra-curricular") || normalized.includes("volunteer") || normalized.includes("activities")) {
      return "activities";
    }
    return "experience";
  }
  if (
    normalized.includes("employment history")
    || normalized.includes("career history")
    || normalized.includes("professional background")
  ) return "experience";
  if (normalized.includes("skill") || normalized.includes("competenc") || normalized.includes("proficienc")) return "skills";
  if (normalized.includes("project")) return "projects";
  if (
    normalized.includes("certification")
    || normalized.includes("license")
    || normalized.includes("upskilling")
  ) return "certifications";
  if (normalized.includes("activity") || normalized.includes("leadership") || normalized.includes("volunteer") || normalized.includes("club")) return "activities";
  if (normalized.includes("additional information")) return "personal";
  if (normalized.includes("language")) return "personal";
  if (normalized === "personal" || normalized.includes("personal information")) return "personal";
  return "";
}

function isAllCapsHeading(line) {
  const trimmed = stripResumeMarkdown(line);
  if (!trimmed || trimmed !== trimmed.toUpperCase() || !/[A-Z]/.test(trimmed)) return false;
  const words = trimmed.split(/\s+/);
  // Must be short (≤4 words) to avoid matching all-caps summary/body text
  if (words.length > 4) return false;
  // Reject lines that look like bullet content or certifications
  if (/^[•\-*]/.test(trimmed)) return false;
  if (/certification|in progress|target|completed|accredited/i.test(trimmed.toLowerCase())) return false;
  // Reject lines ending with period (likely sentences, not headings)
  if (trimmed.endsWith(".")) return false;
  // Reject lines with parentheses (likely descriptions, e.g. "PMP CERTIFICATION (IN PROGRESS)")
  if (/\(.*\)/.test(trimmed)) return false;
  return true;
}

function hasDateHint(value) {
  return RESUME_DATE_HINT_RE.test(stripResumeMarkdown(value));
}

function extractResumeMetricSignals(value) {
  const text = stripResumeMarkdown(value);
  if (!text) return [];

  const matches = [];
  const addMatches = (pattern) => {
    const found = text.match(pattern) || [];
    found.forEach((item) => {
      const cleaned = item.trim().replace(/\s+/g, " ");
      if (cleaned) matches.push(cleaned);
    });
  };

  addMatches(/\d+%|\$[\d,]+|\d+[kKmMbB]\b|\d{1,3}(?:,\d{3})+/g);
  RESUME_SCALE_CUE_PATTERNS.forEach(addMatches);

  return [...new Set(matches)];
}

function isResumeActionVerb(word) {
  const normalized = String(word || "").toLowerCase().replace(/[,:;.]$/, "");
  if (!normalized) return false;
  const baseVerb = normalized.includes("-") ? normalized.split("-").pop() : normalized;
  return RESUME_ACTION_VERBS.has(normalized) || RESUME_ACTION_VERBS.has(baseVerb);
}

function startsLineWithResumeActionVerb(value) {
  const words = stripResumeMarkdown(value).split(/\s+/).filter(Boolean);
  if (!words.length) return false;
  return isResumeActionVerb(words[0]);
}

function looksLikeEducationText(value) {
  return RESUME_EDUCATION_RE.test(stripResumeMarkdown(value));
}

function looksLikeEducationInstitution(value) {
  return RESUME_EDUCATION_INSTITUTION_RE.test(stripResumeMarkdown(value));
}

function looksLikeCertificationText(value) {
  return RESUME_CERTIFICATION_RE.test(stripResumeMarkdown(value));
}

function looksLikeEducationDetail(value) {
  return RESUME_EDUCATION_DETAIL_RE.test(stripResumeMarkdown(value));
}

function looksLikeEducationMain(value) {
  const trimmed = stripResumeMarkdown(value);
  if (!trimmed) return false;
  return !looksLikeEducationDetail(trimmed)
    && (
      looksLikeEducationText(trimmed)
      || looksLikeEducationInstitution(trimmed)
      || RESUME_DEGREE_RE.test(trimmed)
      || hasDateHint(trimmed)
    );
}

function startsNewEducationEntry(value) {
  const trimmed = stripResumeMarkdown(value);
  if (!trimmed) return false;
  if (DEGREE_START_RE.test(trimmed)) return true;
  return looksLikeEducationInstitution(trimmed) && !looksLikeEducationDetail(trimmed);
}

function splitEducationMeta(value) {
  const trimmed = stripResumeMarkdown(value);
  if (!trimmed) return { primary: "", secondary: "" };

  const yearRangeMatch = trimmed.match(/^(.*?)(?:,\s*|\s+)((?:19|20)\d{2}(?:\s*[–—-]\s*(?:present|(?:19|20)\d{2}))?)$/i);
  if (yearRangeMatch) {
    const primary = yearRangeMatch[1].trim().replace(/[,\s]+$/, "");
    const secondary = yearRangeMatch[2].trim();
    return { primary: primary || trimmed, secondary };
  }

  const monthRangeMatch = trimmed.match(/^(.*?)(?:,\s*|\s+)((?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+(?:19|20)\d{2}(?:\s*[–—-]\s*(?:present|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+(?:19|20)\d{2}))?)$/i);
  if (monthRangeMatch) {
    const primary = monthRangeMatch[1].trim().replace(/[,\s]+$/, "");
    const secondary = monthRangeMatch[2].trim();
    return { primary: primary || trimmed, secondary };
  }

  return { primary: trimmed, secondary: "" };
}

function getInlineResumeSegments(section) {
  if (section?.type !== "paragraph") return null;
  if (!["skills", "certifications", "personal"].includes(section.sectionKey)) return null;
  const parts = String(section.text || "").split("|").map((part) => part.trim()).filter(Boolean);
  return parts.length >= 2 ? parts : null;
}

function looksLikeDenseSkillList(parts) {
  return parts.length >= 3
    && parts.every((part) => !hasDateHint(part) && part.split(/\s+/).length <= 6);
}

function reorderParsedSections(sections, templateOrder = []) {
  void templateOrder;
  return sections;
}

function pruneEmptySectionGroups(sections) {
  const pruned = [];

  for (let index = 0; index < sections.length; index += 1) {
    const current = sections[index];

    if (current?.type !== "heading") {
      pruned.push(current);
      continue;
    }

    const groupItems = [current];
    let nextIndex = index + 1;
    let hasRenderableContent = false;

    while (nextIndex < sections.length) {
      const next = sections[nextIndex];
      if (next?.type === "heading" || next?.type === "heading_paragraph") break;
      groupItems.push(next);
      if (next?.type && next.type !== "spacer") {
        hasRenderableContent = true;
      }
      nextIndex += 1;
    }

    if (hasRenderableContent) {
      pruned.push(...groupItems);
    }

    index = nextIndex - 1;
  }

  return pruned;
}

function normalizeScoreData(data) {
  const keywordMatch = data?.keyword_match || {};
  const matched = Array.isArray(keywordMatch.matched)
    ? keywordMatch.matched
    : Array.isArray(keywordMatch.found)
      ? keywordMatch.found
      : [];
  const missing = Array.isArray(keywordMatch.missing) ? keywordMatch.missing : [];
  const total = matched.length + missing.length;
  const scorePercent = Number.isFinite(keywordMatch.score_percent)
    ? keywordMatch.score_percent
    : total > 0
      ? Math.round((matched.length / total) * 100)
      : 0;

  return {
    ...data,
    dimensions: data?.dimensions && !Array.isArray(data.dimensions) ? data.dimensions : {},
    keyword_match: {
      matched,
      missing,
      score_percent: scorePercent,
    },
  };
}

function getScoreTheme(score) {
  if (score >= 80) {
    return {
      text: "text-emerald-700",
      bar: "bg-emerald-500",
      panel: "border-emerald-200 bg-emerald-50",
      pill: "bg-emerald-100 text-emerald-800",
    };
  }
  if (score >= 50) {
    return {
      text: "text-amber-700",
      bar: "bg-amber-500",
      panel: "border-amber-200 bg-amber-50",
      pill: "bg-amber-100 text-amber-800",
    };
  }
  return {
    text: "text-rose-700",
    bar: "bg-rose-500",
    panel: "border-rose-200 bg-rose-50",
    pill: "bg-rose-100 text-rose-800",
  };
}

function getStatusMeta(score, max) {
  const ratio = max > 0 ? score / max : 1;
  if (ratio >= 0.8) {
    return {
      label: "Good Job",
      className: "bg-emerald-100 text-emerald-800",
      icon: <CheckCircle size={12} />,
    };
  }
  if (ratio >= 0.5) {
    return {
      label: "On Track",
      className: "bg-amber-100 text-amber-800",
      icon: <AlertCircle size={12} />,
    };
  }
  return {
    label: "Review",
    className: "bg-rose-100 text-rose-800",
    icon: <X size={12} />,
  };
}

function collectKeywordMatches(text, keywords) {
  const lower = text.toLowerCase();
  return keywords.filter((keyword) => keyword && lower.includes(keyword.toLowerCase()));
}

function buildResumeKeywords(selectedJob, scoreData) {
  const collected = [];
  if (Array.isArray(selectedJob?.skills)) collected.push(...selectedJob.skills);
  if (Array.isArray(scoreData?.keyword_match?.matched)) collected.push(...scoreData.keyword_match.matched.slice(0, 12));

  return [...new Set(collected
    .map(extractKeywordLabel)
    .filter((item) => item.length >= 3)
  )];
}

function buildSkillAlignment(skills, text) {
  const uniqueSkills = [...new Set(
    (Array.isArray(skills) ? skills : [])
      .map(extractKeywordLabel)
      .filter((item) => item.length >= 2),
  )];

  if (uniqueSkills.length === 0) {
    return { matched: [], missing: [] };
  }

  const resumeLower = text.toLowerCase();
  const matched = uniqueSkills.filter((skill) => resumeLower.includes(skill.toLowerCase()));
  const missing = uniqueSkills.filter((skill) => !resumeLower.includes(skill.toLowerCase()));
  return { matched, missing };
}

function isHeadingLine(line) {
  const trimmed = stripResumeMarkdown(line);
  const normalized = normalizeHeadingLabel(trimmed);
  if (!normalized) return false;
  if (RESUME_HEADINGS.has(normalized)) return true;
  if (trimmed.endsWith(":") && RESUME_HEADINGS.has(normalizeHeadingLabel(trimmed.slice(0, -1)))) return true;
  return isAllCapsHeading(trimmed);
}

function buildEducationPair(lines, lineIndex, currentSectionKey, keywords) {
  if (currentSectionKey !== "education") return null;

  const current = stripResumeMarkdown(lines[lineIndex]);
  const nextRaw = lines[lineIndex + 1];
  const thirdRaw = lines[lineIndex + 2];
  let next = stripResumeMarkdown(nextRaw);
  const third = stripResumeMarkdown(thirdRaw);

  if (!current || !next || isHeadingLine(next) || RESUME_BULLET_RE.test(nextRaw || "")) return null;

  let consumed = 1;
  const canExtendEducationMeta = third
    && !isHeadingLine(third)
    && !RESUME_BULLET_RE.test(thirdRaw || "")
    && !startsNewEducationEntry(third)
    && looksLikeEducationText(next)
    && !hasDateHint(next)
    && (hasDateHint(third) || /singapore|canada|usa|uk|australia|japan|taiwan|university|college|school|institute/i.test(third));

  if (canExtendEducationMeta) {
    next = `${next} ${third}`.replace(/\s+/g, " ").trim();
    consumed = 2;
  }

  const currentIsEducationMain = looksLikeEducationMain(current);
  const nextIsEducationMain = looksLikeEducationMain(next);
  if (currentIsEducationMain && nextIsEducationMain) {
    return {
      type: "subheading",
      left: current,
      right: next,
      variant: "education_main",
      text: `${current} | ${next}`,
      keywordMatches: collectKeywordMatches(`${current} ${next}`, keywords),
      lineIndices: Array.from({ length: consumed + 1 }, (_, offset) => lineIndex + offset),
      consumed,
    };
  }

  const currentIsEducationDetail = looksLikeEducationDetail(current);
  const nextIsEducationDetail = looksLikeEducationDetail(next);
  if (currentIsEducationDetail && nextIsEducationDetail) {
    return {
      type: "subheading",
      left: current,
      right: next,
      variant: "education_detail",
      text: `${current} | ${next}`,
      keywordMatches: collectKeywordMatches(`${current} ${next}`, keywords),
      lineIndices: Array.from({ length: consumed + 1 }, (_, offset) => lineIndex + offset),
      consumed,
    };
  }

  return null;
}

function mergeParsedParagraphRuns(sections) {
  const merged = [];

  sections.forEach((section) => {
    const previous = merged[merged.length - 1];
    const previousContext = merged.length >= 2 ? merged[merged.length - 2] : null;
    const previousLooksLikeLostBullet = previous?.type === "paragraph"
      ? inferWordBulletLines(previous.text, previous.sectionKey, previousContext)?.length > 0
      : false;
    const currentLooksLikeLostBullet = section?.type === "paragraph"
      ? inferWordBulletLines(section.text, section.sectionKey, previous)?.length > 0
      : false;
    const canMergeParagraph = previous
      && previous.type === "paragraph"
      && section.type === "paragraph"
      && previous.sectionKey === section.sectionKey
      && previous.lineIndices?.length
      && section.lineIndices?.length
      && previous.lineIndices[previous.lineIndices.length - 1] + 1 === section.lineIndices[0]
      && !previousLooksLikeLostBullet
      && !currentLooksLikeLostBullet;

    if (canMergeParagraph) {
      previous.text = `${previous.text} ${section.text}`.trim();
      previous.raw = `${previous.raw}\n${section.raw}`;
      previous.keywordMatches = [...new Set([...(previous.keywordMatches || []), ...(section.keywordMatches || [])])];
      previous.lineIndices = [...previous.lineIndices, ...section.lineIndices];
      return;
    }

    merged.push(section);
  });

  return merged;
}

function isLikelySummaryLeadParagraph(value) {
  const trimmed = stripResumeMarkdown(value);
  if (!trimmed) return false;
  if (trimmed.includes("|") || hasDateHint(trimmed) || looksLikeEducationText(trimmed) || looksLikeCertificationText(trimmed)) return false;

  const words = trimmed.split(/\s+/).filter(Boolean);
  if (words.length < 5 || words.length > 28) return false;

  const isAllCapsLine = trimmed === trimmed.toUpperCase() && /[A-Z]/.test(trimmed);
  const hasRoleCue = /\b(?:manager|leader|leadership|experience|operations|engineering|transformation|program|product|strategy|specializ(?:e|ing)|delivery|initiatives)\b/i.test(trimmed);
  return isAllCapsLine || hasRoleCue;
}

function isShoutySummaryParagraph(value, sectionKey = "") {
  const trimmed = stripResumeMarkdown(value);
  if (sectionKey !== "summary" || !trimmed) return false;
  const lettersOnly = trimmed.replace(/[^A-Za-z]/g, "");
  const words = trimmed.split(/\s+/).filter(Boolean);
  return Boolean(lettersOnly)
    && trimmed === trimmed.toUpperCase()
    && words.length >= 12;
}

function isMostlyAllCapsContent(value) {
  const trimmed = stripResumeMarkdown(value);
  const lettersOnly = trimmed.replace(/[^A-Za-z]/g, "");
  if (lettersOnly.length < 8) return false;
  return trimmed === trimmed.toUpperCase();
}

function normalizeDisplayToken(core, { mode = "sentence", sentenceStart = false, titleStart = false } = {}) {
  const sanitizedCore = core.replace(/[.,;:!?]+$/g, "");
  const normalizedCore = sanitizedCore.toLowerCase();

  if (
    !sanitizedCore
    || RESUME_DISPLAY_ACRONYMS.has(core)
    || RESUME_DISPLAY_ACRONYMS.has(sanitizedCore)
    || /\d/.test(sanitizedCore)
    || sanitizedCore.includes("/")
  ) {
    return core;
  }

  if (mode === "title") {
    if (!titleStart && RESUME_SMALL_TITLE_WORDS.has(normalizedCore)) {
      return normalizedCore;
    }
    return normalizedCore.charAt(0).toUpperCase() + normalizedCore.slice(1);
  }

  if (sentenceStart) {
    return normalizedCore.charAt(0).toUpperCase() + normalizedCore.slice(1);
  }
  return normalizedCore;
}

function toSentenceCaseDisplayText(value) {
  const tokens = String(value || "").split(/(\s+)/);
  let sentenceStart = true;

  return tokens.map((token) => {
    if (!token || /^\s+$/.test(token)) return token;

    const match = token.match(/^([^A-Za-z0-9]*)([A-Za-z0-9/&+-]+)([^A-Za-z0-9]*)$/);
    if (!match) {
      if (/[.!?]$/.test(token)) sentenceStart = true;
      return token;
    }

    const [, prefix, core, suffix] = match;
    const renderedCore = normalizeDisplayToken(core, { mode: "sentence", sentenceStart });

    sentenceStart = /[.!?]$/.test(`${core}${suffix}`);
    return `${prefix}${renderedCore}${suffix}`;
  }).join("");
}

function toTitleCaseDisplayText(value) {
  const tokens = String(value || "").split(/(\s+)/);
  let wordIndex = 0;

  return tokens.map((token) => {
    if (!token || /^\s+$/.test(token)) return token;

    const match = token.match(/^([^A-Za-z0-9]*)([A-Za-z0-9/&+-]+)([^A-Za-z0-9]*)$/);
    if (!match) return token;

    const [, prefix, core, suffix] = match;
    const renderedCore = normalizeDisplayToken(core, {
      mode: "title",
      titleStart: wordIndex === 0,
    });
    wordIndex += 1;
    return `${prefix}${renderedCore}${suffix}`;
  }).join("");
}

function getDisplayParagraphText(section) {
  if (!section?.text) return "";
  if (isShoutySummaryParagraph(section.text, section.sectionKey)) {
    return toSentenceCaseDisplayText(section.text);
  }
  if (
    isMostlyAllCapsContent(section.text)
    && (
      section.text.includes("|")
      || section.sectionKey === "skills"
      || section.sectionKey === "certifications"
      || section.sectionKey === "additional_information"
      || looksLikeCertificationText(section.text)
    )
  ) {
    return toTitleCaseDisplayText(section.text);
  }
  return section.text;
}

function getDisplayInlineSegmentText(value) {
  if (isMostlyAllCapsContent(value)) {
    return toTitleCaseDisplayText(value);
  }
  return value;
}

function getDisplaySubheadingText(value, sectionKey = "", variant = "") {
  if (!value) return "";
  if (isMostlyAllCapsContent(value) && (sectionKey === "certifications" || sectionKey === "skills" || variant.startsWith("education"))) {
    return toTitleCaseDisplayText(value);
  }
  return value;
}

function mergeSummaryLeadParagraphs(sections) {
  const merged = [];

  for (let index = 0; index < sections.length; index += 1) {
    const current = sections[index];
    if (!(current?.type === "paragraph" && current.sectionKey === "summary" && isLikelySummaryLeadParagraph(current.text))) {
      merged.push(current);
      continue;
    }

    let nextIndex = index + 1;
    while (sections[nextIndex]?.type === "spacer") nextIndex += 1;
    const next = sections[nextIndex];

    if (next?.type === "paragraph" && next.sectionKey === "summary") {
      merged.push({
        ...current,
        text: `${current.text} ${next.text}`.replace(/\s+/g, " ").trim(),
        raw: `${current.raw}\n${next.raw}`,
        keywordMatches: [...new Set([...(current.keywordMatches || []), ...(next.keywordMatches || [])])],
        lineIndices: [...(current.lineIndices || []), ...(next.lineIndices || [])],
      });
      index = nextIndex;
      continue;
    }

    merged.push(current);
  }

  return merged;
}

function parseSubheadingParts(line, sectionKey = "") {
  const trimmed = stripResumeMarkdown(line);
  if (!trimmed) return null;

  if (trimmed.includes("|")) {
    const parts = trimmed.split("|").map((part) => part.trim()).filter(Boolean);
    const lastPart = parts[parts.length - 1] || "";
    const hasDateOnRight = hasDateHint(lastPart);
    const hasEducationSignal = parts.some((part) => looksLikeEducationText(part) || RESUME_DEGREE_RE.test(part));
    const denseSkillList = looksLikeDenseSkillList(parts)
      || ((sectionKey === "skills" || sectionKey === "certifications") && parts.length >= 2 && !hasDateOnRight);

    if (denseSkillList) return null;

    if (sectionKey === "education" && parts.length >= 2 && (hasDateOnRight || hasEducationSignal)) {
      if (parts.length === 2) {
        return {
          left: parts[0],
          right: parts[1],
          variant: looksLikeEducationDetail(parts[0]) || looksLikeEducationDetail(parts[1]) ? "education_detail" : "education_main",
        };
      }
      return {
        left: parts[0],
        right: parts.slice(1).join(" | "),
        variant: "education_main",
      };
    }

    if (parts.length === 2 || hasDateOnRight) {
      const right = parts.pop();
      return {
        left: parts.join(" | "),
        right,
        variant: hasDateHint(right) ? "dated" : "company",
      };
    }
  }

  const separatorMatch = trimmed.match(/^(.*?)(?:\s+[–—-]\s+)(.*)$/);
  if (separatorMatch) {
    const left = separatorMatch[1].trim();
    const right = separatorMatch[2].trim();
    if ((sectionKey === "skills" || sectionKey === "certifications") && !hasDateHint(right)) return null;
    if (sectionKey === "education") {
      return {
        left,
        right,
        variant: looksLikeEducationDetail(left) || looksLikeEducationDetail(right) ? "education_detail" : "education_main",
      };
    }
    return {
      left,
      right,
      variant: hasDateHint(right) || hasDateHint(trimmed) ? "dated" : "company",
    };
  }

  return null;
}

function splitActionSentenceBullets(text) {
  const parts = stripResumeMarkdown(text).split(/(?<=[.;])\s+(?=[A-Z])/).map((part) => part.trim()).filter(Boolean);
  if (parts.length <= 1) return [stripResumeMarkdown(text)];
  if (!parts.every((part) => startsLineWithResumeActionVerb(part))) return [stripResumeMarkdown(text)];
  return parts.map((part) => part.replace(/[.;]+$/, "").trim()).filter(Boolean);
}

function looksLikeWordBulletLead(text) {
  const cleaned = stripResumeMarkdown(text);
  if (!cleaned) return false;
  return startsLineWithResumeActionVerb(cleaned)
    || /^(?:co-|re-)?[A-Za-z]+(?:ed|ing)\b/.test(cleaned)
    || /^(?:Built|Led|Drove|Created|Managed|Supported|Partnered|Worked|Chaired|Completed|Currently|Directed|Engineered|Developed|Standardized|Implemented|Optimized|Scaled|Reduced|Improved|Delivered)\b/i.test(cleaned);
}

function inferWordBulletLines(text, currentSectionKey, previousSection) {
  const cleaned = stripResumeMarkdown(text);
  if (!cleaned) return null;

  const bulletFriendlySection = ["experience", "projects", "activities", "certifications", "awards"].includes(currentSectionKey);
  if (!bulletFriendlySection) return null;

  if (cleaned.includes("|")) return null;
  if (parseSubheadingParts(cleaned, currentSectionKey)) return null;

  const startsWithAction = looksLikeWordBulletLead(cleaned);
  const hasMetric = RESUME_METRIC_RE.test(cleaned);
  const hasResultCue = /(?:improv|reduc|increas|deliver|achiev|saving|revenue|cost|efficien|quality|yield|launched|deployed|implemented)/i.test(cleaned);
  const wordCount = cleaned.split(/\s+/).filter(Boolean).length;
  const previousWasBullet = previousSection?.type === "bullet";
  const looksLikeAchievementSentence = wordCount >= 5
    && (
      startsWithAction
      || (hasMetric && wordCount >= 6)
      || (hasResultCue && wordCount >= 7)
      || (previousWasBullet && wordCount >= 6)
    );
  const previousCreatesBulletContext = previousSection
    && (
      previousSection.type === "subheading"
      || previousSection.type === "heading"
      || previousSection.type === "heading_paragraph"
      || previousWasBullet
      || (previousSection.type === "paragraph" && hasDateHint(previousSection.text))
    );

  if (!looksLikeAchievementSentence) return null;
  if (!previousCreatesBulletContext && !(startsWithAction && (hasMetric || hasResultCue))) return null;

  const inferredBullets = splitActionSentenceBullets(cleaned);
  if (!inferredBullets.length) return null;
  return inferredBullets;
}

function analyzeBulletFeedback(text, resumeText = "", sectionKey = "") {
  const trimmed = text.trim();
  const lowered = trimmed.toLowerCase();
  const firstWord = trimmed.split(/\s+/)[0]?.toLowerCase().replace(/[,:;.]$/, "") || "";
  const metricSignals = extractResumeMetricSignals(trimmed);
  const hasMetric = metricSignals.length > 0;
  const weakStart = RESUME_WEAK_STARTS.find((phrase) => lowered.startsWith(phrase));
  const keywordMatches = collectKeywordMatches(trimmed, []);
  const bulletLengthWords = trimmed.split(/\s+/).filter(Boolean).length;
  const bulletLengthChars = trimmed.length;
  const isTooShort = bulletLengthChars < 40 || bulletLengthWords < 7;
  const isTooLong = bulletLengthChars > 210 || bulletLengthWords > 30;
  const hasActionVerb = isResumeActionVerb(firstWord);
  const wordCounts = resumeText ? getWordCounts(resumeText) : {};
  const overusedWords = [...new Set(
    (lowered.match(/[a-z][a-z-]*/g) || []).filter((word) => (
      word.length > 4
      && !RESUME_OVERUSED_IGNORE.has(word)
      && (wordCounts[word] || 0) >= 4
    )),
  )].slice(0, 4);
  const avoidedMatches = RESUME_AVOIDED_PHRASES.filter((phrase) => lowered.includes(phrase));
  const skipAnnotation = sectionKey === "education"
    || sectionKey === "certifications"
    || looksLikeCertificationText(lowered)
    || looksLikeEducationText(lowered);

  return {
    trimmed,
    lowered,
    firstWord,
    hasMetric,
    weakStart,
    keywordMatches,
    metricSignals,
    bulletLengthWords,
    bulletLengthChars,
    isTooShort,
    isTooLong,
    hasActionVerb,
    overusedWords,
    avoidedMatches,
    skipAnnotation,
    actionIssue: Boolean(weakStart || !hasActionVerb),
    specificsIssue: !hasMetric,
    overusedIssue: overusedWords.length > 0 || avoidedMatches.length > 0,
    lengthIssue: isTooShort || isTooLong,
  };
}

function annotateBullet(text, keywords, resumeText = "", sectionKey = "") {
  const analysis = analyzeBulletFeedback(text, resumeText, sectionKey);
  if (analysis.skipAnnotation) {
    return null;
  }

  const keywordMatches = collectKeywordMatches(analysis.trimmed, keywords);
  const issueIds = [];
  if (analysis.actionIssue) issueIds.push("action_oriented");
  if (analysis.overusedIssue) issueIds.push("overused_avoided");
  if (analysis.lengthIssue) issueIds.push("bullet_length");

  if (analysis.actionIssue || analysis.overusedIssue || analysis.lengthIssue) {
    let message = "Tighten this bullet so the impact is clearer.";
    if (analysis.weakStart) message = `Replace "${analysis.weakStart}" with a stronger verb.`;
    else if (!analysis.hasActionVerb) message = "Start with a stronger action verb so the outcome lands faster.";
    else if (analysis.overusedIssue && analysis.lengthIssue) message = "This bullet is dense and repeats a few broad terms. Trim it and sharpen the language.";
    else if (analysis.overusedIssue) message = "A few repeated or filler terms are diluting the impact.";
    else if (analysis.isTooShort) message = "Add more outcome detail so this bullet feels complete.";
    else if (analysis.isTooLong) message = "Split or tighten this bullet so the strongest result lands earlier.";

    const tone = analysis.actionIssue ? "rose" : "amber";
    return {
      tone,
      label: issueIds.length > 1 ? `${issueIds.length} Issues` : "Review Bullet",
      icon: tone === "rose" ? <X size={14} /> : <AlertCircle size={14} />,
      borderClass: tone === "rose" ? "border-rose-300 bg-rose-50/70" : "border-amber-300 bg-amber-50/70",
      pillClass: tone === "rose" ? "bg-rose-100 text-rose-800" : "bg-amber-100 text-amber-800",
      message,
      keywordMatches,
      issueIds,
      issueCount: issueIds.length,
    };
  }

  return {
    tone: "emerald",
    label: analysis.hasMetric ? "Solid Impact" : "Good Start",
    icon: <CheckCircle size={14} />,
    borderClass: "border-emerald-300 bg-emerald-50/70",
    pillClass: "bg-emerald-100 text-emerald-800",
    message: analysis.hasMetric
      ? "This bullet already shows measurable impact."
      : "This bullet starts well. Add a metric if you have one.",
    keywordMatches,
    issueIds: [],
    issueCount: 0,
  };
}

function parseResumeToSections(text, keywords, templateOrder = []) {
  const parsed = [];
  let currentSectionKey = "";
  const lines = text.replace(/\r\n?/g, "\n").split("\n");

  for (let lineIndex = 0; lineIndex < lines.length; lineIndex += 1) {
    const line = lines[lineIndex];
    const normalizedLine = stripResumeMarkdown(line);
    const base = {
      id: `line-${lineIndex}`,
      lineIndex,
      lineIndices: [lineIndex],
      raw: line,
      text: normalizedLine,
    };

    if (!normalizedLine) {
      parsed.push({ ...base, type: "spacer", sectionKey: currentSectionKey });
      continue;
    }

    const inlineHeading = splitInlineHeadingContent(normalizedLine);
    if (inlineHeading) {
      currentSectionKey = inlineHeading.sectionKey || currentSectionKey;
      parsed.push({
        ...base,
        type: "heading_paragraph",
        headingText: inlineHeading.headingText,
        bodyText: inlineHeading.bodyText,
        sectionKey: inlineHeading.sectionKey,
        keywordMatches: collectKeywordMatches(inlineHeading.bodyText, keywords),
      });
      continue;
    }

    if (isHeadingLine(normalizedLine)) {
      currentSectionKey = getResumeSectionKey(normalizedLine) || currentSectionKey;
      parsed.push({
        ...base,
        type: "heading",
        text: normalizedLine.replace(/:$/, ""),
        sectionKey: currentSectionKey,
        keywordMatches: [],
      });
      continue;
    }

    const bulletMatch = line.match(RESUME_BULLET_RE);
    const subheadingParts = bulletMatch ? null : parseSubheadingParts(normalizedLine, currentSectionKey);
    if (subheadingParts) {
      parsed.push({
        ...base,
        type: "subheading",
        ...subheadingParts,
        text: normalizedLine,
        sectionKey: currentSectionKey,
        keywordMatches: collectKeywordMatches(normalizedLine, keywords),
      });
      continue;
    }

    const educationPair = bulletMatch ? null : buildEducationPair(lines, lineIndex, currentSectionKey, keywords);
    if (educationPair) {
      parsed.push({
        ...base,
        ...educationPair,
        id: `line-${lineIndex}-education-pair`,
        sectionKey: currentSectionKey,
      });
      lineIndex += educationPair.consumed;
      continue;
    }

    if (bulletMatch) {
      const textValue = stripResumeMarkdown(bulletMatch[2]);
      parsed.push({
        ...base,
        type: "bullet",
        marker: bulletMatch[1].trim(),
        text: textValue,
        sectionKey: currentSectionKey,
        annotation: annotateBullet(textValue, keywords, text, currentSectionKey),
      });
      continue;
    }

    const previousMeaningfulSection = [...parsed].reverse().find((section) => section.type !== "spacer");
    const inferredBullets = inferWordBulletLines(normalizedLine, currentSectionKey, previousMeaningfulSection);
    if (inferredBullets) {
      inferredBullets.forEach((bulletText, inferredIndex) => {
        parsed.push({
          ...base,
          id: inferredBullets.length > 1 ? `${base.id}-inferred-${inferredIndex}` : base.id,
          type: "bullet",
          marker: "",
          text: bulletText,
          sectionKey: currentSectionKey,
          annotation: annotateBullet(bulletText, keywords, text, currentSectionKey),
        });
      });
      continue;
    }

    parsed.push({
      ...base,
      type: "paragraph",
      sectionKey: currentSectionKey,
      keywordMatches: collectKeywordMatches(normalizedLine, keywords),
    });
  }

  return pruneEmptySectionGroups(
    reorderParsedSections(mergeSummaryLeadParagraphs(mergeParsedParagraphRuns(parsed)), templateOrder),
  );
}

function extractResumeHeaderMeta(text) {
  const lines = text.replace(/\r\n?/g, "\n").split("\n");
  const headerLines = [];
  const lineIndices = [];
  for (let index = 0; index < lines.length; index += 1) {
    const trimmed = stripResumeMarkdown(lines[index]);
    if (!trimmed) {
      if (headerLines.length > 0) break;
      continue;
    }
    if (isHeadingLine(trimmed)) break;
    if (splitInlineHeadingContent(trimmed)) break;
    if (RESUME_BULLET_RE.test(lines[index])) break;
    headerLines.push(trimmed);
    lineIndices.push(index);
    if (headerLines.length >= 4) break;
  }
  return { lines: headerLines, lineIndices };
}

function renderHighlightedText(text, keywords) {
  if (!keywords.length) return text;
  const sorted = [...keywords].sort((a, b) => b.length - a.length);
  const pattern = new RegExp(`(${sorted.map((keyword) => escapeRegExp(keyword)).join("|")})`, "ig");
  const parts = text.split(pattern);
  if (parts.length === 1) return text;

  return parts.map((part, index) => {
    const isMatch = sorted.some((keyword) => keyword.toLowerCase() === part.toLowerCase());
    if (!isMatch) return <span key={`${part}-${index}`}>{part}</span>;
    return (
      <span key={`${part}-${index}`} className="rounded bg-sky-100 px-0.5 text-sky-700">
        {part}
      </span>
    );
  });
}

function updateResumeLine(text, section, nextValue) {
  const lines = text.replace(/\r\n?/g, "\n").split("\n");
  const cleanValue = nextValue.replace(/\r/g, "").trim();
  const targetLines = Array.isArray(section.lineIndices) && section.lineIndices.length > 0
    ? section.lineIndices
    : [section.lineIndex];

  if (section.type === "bullet") {
    lines[section.lineIndex] = cleanValue ? `${section.marker || "•"} ${cleanValue}` : "";
    return lines.join("\n");
  }

  lines[targetLines[0]] = cleanValue;
  targetLines.slice(1).forEach((index) => {
    lines[index] = "";
  });
  return lines.join("\n");
}

function insertResumeLineAfter(text, section, nextValue) {
  const lines = text.replace(/\r\n?/g, "\n").split("\n");
  lines.splice(section.lineIndex + 1, 0, nextValue.replace(/\r/g, ""));
  return lines.join("\n");
}

function removeResumeLine(text, section) {
  const lines = text.replace(/\r\n?/g, "\n").split("\n");
  lines.splice(section.lineIndex, 1);
  return lines.join("\n");
}

function removeResumeSectionBlock(text, section, parsedSections = []) {
  if (!section || !["heading", "heading_paragraph"].includes(section.type)) {
    return removeResumeLine(text, section);
  }

  const lines = text.replace(/\r\n?/g, "\n").split("\n");
  const startIndex = section.lineIndex;
  const nextHeading = parsedSections.find(
    (candidate) => candidate.lineIndex > startIndex && ["heading", "heading_paragraph"].includes(candidate.type),
  );
  const endIndexExclusive = nextHeading ? nextHeading.lineIndex : lines.length;
  lines.splice(startIndex, Math.max(endIndexExclusive - startIndex, 1));

  const cleanedLines = [];
  lines.forEach((line) => {
    if (!stripResumeMarkdown(line) && !cleanedLines[cleanedLines.length - 1]?.trim()) {
      return;
    }
    cleanedLines.push(line);
  });

  return cleanedLines.join("\n").replace(/\n{3,}/g, "\n\n").trim();
}

function getDownloadFilename(response, fallbackName) {
  const contentDisposition = response.headers.get("Content-Disposition") || "";
  const match = contentDisposition.match(/filename="?([^"]+)"?/i);
  return match?.[1] || fallbackName;
}

function getWordCounts(text) {
  const counts = {};
  (text.toLowerCase().match(/[a-z][a-z-]*/g) || []).forEach((word) => {
    counts[word] = (counts[word] || 0) + 1;
  });
  return counts;
}

function normalizeReviewSuggestion(item, index) {
  if (!item || typeof item !== "object" || typeof item.original !== "string") return null;
  const status = item.status === "keep" ? "keep" : item.status === "improve" ? "improve" : "";
  if (!status) return null;

  return {
    id: `review-${index}-${item.original.slice(0, 24)}`,
    original: item.original.trim(),
    status,
    issue: typeof item.issue === "string" ? item.issue.trim() : "",
    suggested: typeof item.suggested === "string" ? item.suggested.trim() : "",
    reason: typeof item.reason === "string" ? item.reason.trim() : "",
  };
}

function summarizeTailoringChanges(changes = []) {
  const labels = {
    ai_phrase_cleanup: "phrase cleanup",
    bullet_rewrite: "bullet rewrite",
    verb_dedup: "section polish",
    summary_rewrite: "summary rewrite",
  };

  return changes.reduce((summary, change) => {
    const key = labels[change?.type] || "other";
    summary[key] = (summary[key] || 0) + 1;
    return summary;
  }, {});
}

function getBulletFeedbackTabs(section, resumeText) {
  if (!section?.text) return [];

  const analysis = analyzeBulletFeedback(section.text, resumeText, section.sectionKey);
  if (analysis.skipAnnotation) return [];

  const text = analysis.trimmed;
  const metricMatches = analysis.metricSignals || [];
  const lengthGood = !analysis.lengthIssue;

  return [
    {
      id: "action_oriented",
      title: "Action Oriented",
      tone: analysis.actionIssue ? "rose" : "emerald",
      status: analysis.actionIssue ? "issue" : "good",
      summary: !analysis.actionIssue
        ? `This bullet already opens with "${text.split(/\s+/)[0]}," which gives it momentum.`
        : "This bullet would read stronger if it opened with a clearer action verb.",
      chips: !analysis.actionIssue
        ? [text.split(/\s+/)[0]]
        : BULLET_ACTION_SUGGESTIONS,
      tip: !analysis.actionIssue
        ? "Keep the opening verb, then tighten the rest around the outcome."
        : "Try replacing the opening with a sharper verb that signals what you actually drove or delivered.",
    },
    {
      id: "specifics",
      title: "Specifics",
      tone: metricMatches.length > 0 ? "emerald" : "amber",
      status: metricMatches.length > 0 ? "good" : "issue",
      summary: metricMatches.length > 0
        ? "This bullet already includes measurable scope or outcomes."
        : "Add concrete scope, outcome, or scale so the reader can see the size of the work.",
      chips: metricMatches.length > 0
        ? metricMatches.slice(0, 4)
        : ["team size", "% improvement", "$ impact", "timeline"],
      tip: metricMatches.length > 0
        ? "You can still sharpen the impact by placing the strongest metric earlier in the sentence."
        : "Examples that help: team size, budget, time saved, revenue impact, coverage, quality, or time-to-launch.",
    },
    {
      id: "overused_avoided",
      title: "Overused & Avoided",
      tone: analysis.overusedIssue ? "rose" : "emerald",
      status: analysis.overusedIssue ? "issue" : "good",
      summary: analysis.overusedIssue
        ? "A few repeated or filler terms are diluting the impact of this bullet."
        : "This bullet avoids the most obvious filler phrasing.",
      chips: [...analysis.avoidedMatches, ...analysis.overusedWords].slice(0, 5),
      tip: analysis.overusedIssue
        ? "Swap repeated terms for more specific language, and remove filler phrases unless they add real meaning."
        : "Keep favoring concrete nouns and verbs over generic phrasing.",
    },
    {
      id: "bullet_length",
      title: "Bullet Length",
      tone: lengthGood ? "emerald" : "amber",
      status: lengthGood ? "good" : "issue",
      summary: lengthGood
        ? "This bullet sits in a healthy length range for scanability."
        : analysis.bulletLengthChars < 40
          ? "This bullet is too short to communicate real scope."
          : "This bullet is getting long and may be harder to scan quickly.",
      chips: [`${analysis.bulletLengthWords} words`, `${analysis.bulletLengthChars} chars`],
      tip: lengthGood
        ? "Aim to keep most bullets at roughly one to two lines in the final document."
        : analysis.bulletLengthChars < 40
          ? "Add the outcome, scale, or context so the reader understands why the work mattered."
          : "Split the detail or trim supporting clauses so the strongest result lands earlier.",
    },
  ];
}

function getBulletRewriteFocus(section, resumeText, activeTabId = "") {
  if (!section?.text) return "";

  const analysis = analyzeBulletFeedback(section.text, resumeText, section.sectionKey);
  const focus = new Set();

  if (analysis.isTooLong || activeTabId === "bullet_length") {
    focus.add("bullet_length");
    focus.add("shorten");
    focus.add("bulletize");
  }
  if (analysis.actionIssue || activeTabId === "action_oriented") {
    focus.add("action_oriented");
  }
  if (analysis.specificsIssue || activeTabId === "specifics") {
    focus.add("specifics");
  }
  if (analysis.overusedIssue || activeTabId === "overused_avoided") {
    focus.add("overused_avoided");
    focus.add("tighten");
  }

  return [...focus].join(",");
}

function getRewriteButtonLabel(activeBulletTab, selectedBullet) {
  if (!selectedBullet) return "AI Rewrite This Bullet";
  if (activeBulletTab?.id === "bullet_length" && activeBulletTab.status === "issue") {
    return "AI Shorten This Bullet";
  }
  if (activeBulletTab?.id === "overused_avoided" && activeBulletTab.status === "issue") {
    return "AI Tighten This Bullet";
  }
  if (activeBulletTab?.id === "action_oriented" && activeBulletTab.status === "issue") {
    return "AI Strengthen This Bullet";
  }
  if (activeBulletTab?.id === "specifics" && activeBulletTab.status === "issue") {
    return "AI Sharpen This Bullet";
  }
  return "AI Rewrite This Bullet";
}

function normalizeRewriteOptionText(value) {
  const cleaned = stripResumeMarkdown(String(value || ""))
    .replace(/^[•\-*o▪●\u2022\u2023\u25E6\u2043\u2219\u25AA\u25AB\u25CF\uF0B7]+\s*/, "")
    .trim();
  if (!cleaned) return "";
  return cleaned.replace(/^([^A-Za-z]*)([a-z])/, (_, prefix, char) => `${prefix}${char.toUpperCase()}`);
}

function getRewriteFocusIds(rewriteFocus = "") {
  return String(rewriteFocus).split(",").map((item) => item.trim()).filter(Boolean);
}

function getIssueLabel(issueId = "") {
  if (issueId === "action_oriented") return "action opening";
  if (issueId === "specifics") return "specifics";
  if (issueId === "overused_avoided") return "overused wording";
  if (issueId === "bullet_length") return "bullet length";
  return issueId;
}

function evaluateRewriteOption(option, section, resumeText, rewriteFocus = "") {
  const normalizedOption = normalizeRewriteOptionText(option);
  const analysis = analyzeBulletFeedback(normalizedOption, resumeText, section?.sectionKey || "");
  const issueIds = [];
  if (analysis.actionIssue) issueIds.push("action_oriented");
  if (analysis.specificsIssue) issueIds.push("specifics");
  if (analysis.overusedIssue) issueIds.push("overused_avoided");
  if (analysis.lengthIssue) issueIds.push("bullet_length");

  const focusIds = getRewriteFocusIds(rewriteFocus);
  const unresolvedFocused = issueIds.filter((issueId) => focusIds.includes(issueId));

  return {
    text: normalizedOption,
    issueIds,
    issueCount: issueIds.length,
    focusIds,
    unresolvedFocused,
    focusMisses: unresolvedFocused.length,
    clearsFocusedIssue: focusIds.length > 0 ? unresolvedFocused.length === 0 : issueIds.length === 0,
  };
}

function getRewriteOptionMeta(optionIndex, rewriteFocus = "", optionEvaluation = null) {
  const focus = new Set(getRewriteFocusIds(rewriteFocus));
  const focusLabel = focus.has("bullet_length")
    ? "shortening this bullet"
    : focus.has("overused_avoided")
      ? "tightening the wording"
      : focus.has("action_oriented")
        ? "strengthening the action verb"
        : focus.has("specifics")
          ? "adding sharper evidence"
          : "improving this bullet";

  if (optionIndex === 0) {
    const detail = optionEvaluation?.clearsFocusedIssue
      ? `Best fit for ${focusLabel}.`
      : optionEvaluation?.unresolvedFocused?.length
        ? `Closest match, but still needs work on ${optionEvaluation.unresolvedFocused.map(getIssueLabel).join(" and ")}.`
        : `Best fit for ${focusLabel}.`;
    return {
      label: optionEvaluation?.clearsFocusedIssue ? "Recommended Rewrite" : "Closest Rewrite",
      detail,
      cta: optionEvaluation?.clearsFocusedIssue ? "Use Recommended Rewrite" : "Use Closest Rewrite",
    };
  }

  if (optionIndex === 1) {
    return {
      label: focus.has("bullet_length") || focus.has("overused_avoided") ? "More Concise Rewrite" : "Alternative Rewrite",
      detail: focus.has("bullet_length") || focus.has("overused_avoided")
        ? "Leans shorter and faster to scan."
        : "A different phrasing with the same evidence.",
      cta: focus.has("bullet_length") || focus.has("overused_avoided") ? "Use Concise Rewrite" : "Use Alternative Rewrite",
    };
  }

  return {
    label: focus.has("action_oriented") || focus.has("specifics") ? "Stronger Rewrite" : "Alternative Rewrite",
    detail: focus.has("action_oriented") || focus.has("specifics")
      ? "Pushes harder on impact, verbs, or evidence."
      : "Another viable way to phrase the same point.",
    cta: focus.has("action_oriented") || focus.has("specifics") ? "Use Stronger Rewrite" : "Use Alternative Rewrite",
  };
}

function rankRewriteOptions(options, section, resumeText, rewriteFocus = "") {
  return [...options]
    .map((option, index) => {
      const evaluation = evaluateRewriteOption(option, section, resumeText, rewriteFocus);
      return {
        text: evaluation.text,
        index,
        issueCount: evaluation.issueCount,
        focusMisses: evaluation.focusMisses,
        clearsFocusedIssue: evaluation.clearsFocusedIssue,
      };
    })
    .sort((left, right) => (
      Number(right.clearsFocusedIssue) - Number(left.clearsFocusedIssue)
      || left.focusMisses - right.focusMisses
      || left.issueCount - right.issueCount
      || left.index - right.index
    ))
    .map((item) => item.text);
}

function buildFocusedFeedbackContext(activeTab, tabs = []) {
  const usableTabs = Array.isArray(tabs) ? tabs.filter(Boolean) : [];
  if (!usableTabs.length && !activeTab) return "";

  const issueTabs = usableTabs.filter((tab) => tab.status === "issue");
  const primaryTab = activeTab || issueTabs[0] || usableTabs[0] || null;
  const supportingTabs = issueTabs.filter((tab) => tab.id !== primaryTab?.id).slice(0, 2);
  const sections = [];

  if (primaryTab) {
    sections.push(`Primary issue: ${primaryTab.title}. ${primaryTab.summary} Guidance: ${primaryTab.tip}`);
    if (primaryTab.chips?.length) {
      sections.push(`Signals: ${primaryTab.chips.join(", ")}`);
    }
  }

  if (supportingTabs.length) {
    sections.push(`Also watch for: ${supportingTabs.map((tab) => `${tab.title} (${tab.summary})`).join("; ")}`);
  }

  return sections.join("\n");
}

function TemplatePreview({ templateId }) {
  const accent = templateId === "modern"
    ? "bg-indigo-500"
    : templateId === "singapore"
      ? "bg-slate-700"
      : templateId === "compact"
        ? "bg-zinc-700"
        : "bg-stone-700";

  return (
    <div className="rounded-xl border border-gray-200 bg-gradient-to-br from-white to-gray-50 p-3">
      <div className={`h-2 w-2/5 rounded-full ${accent}`} />
      <div className="mt-3 space-y-1.5">
        <div className="h-1.5 w-full rounded-full bg-gray-200" />
        <div className="h-1.5 w-11/12 rounded-full bg-gray-200" />
        <div className="h-1.5 w-10/12 rounded-full bg-gray-200" />
      </div>
      <div className="mt-4 space-y-1.5">
        <div className={`h-1.5 w-1/3 rounded-full ${accent} opacity-80`} />
        <div className="h-1.5 w-full rounded-full bg-gray-200" />
        <div className="h-1.5 w-10/12 rounded-full bg-gray-200" />
        <div className="h-1.5 w-4/5 rounded-full bg-gray-200" />
      </div>
    </div>
  );
}

function ResumeTab({ selectedJob, user, setActiveTab }) {
  const [profile, setProfile] = useState(() => {
    try {
      const saved = sessionStorage.getItem("jh_resume_profile");
      if (saved) return JSON.parse(saved);
    } catch {
      // ignore corrupt local data
    }
    return { name: "", email: "", phone: "", location: "" };
  });
  const [resumeText, setResumeText] = useState(() => {
    try {
      return sessionStorage.getItem("jh_resume_text") || "";
    } catch {
      return "";
    }
  });
  const [selectedTemplate, setSelectedTemplate] = useState(() => {
    try {
      return sessionStorage.getItem("jh_resume_template") || "modern";
    } catch {
      return "modern";
    }
  });
  const [templates, setTemplates] = useState(DEFAULT_RESUME_TEMPLATES);
  const [scoreData, setScoreData] = useState(null);
  const [jobMatchData, setJobMatchData] = useState(null);
  const [jobMatchLoading, setJobMatchLoading] = useState(false);
  const [jobMatchError, setJobMatchError] = useState("");
  const [scoring, setScoring] = useState(false);
  const [scoreError, setScoreError] = useState("");
  const [scorePhase, setScorePhase] = useState(() => (resumeText.trim() ? "opening_scored" : "opening_pending"));
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState("");
  const [dragOver, setDragOver] = useState(false);
  const [pastedText, setPastedText] = useState("");
  const [needsRescore, setNeedsRescore] = useState(false);
  const [aiStatus, setAiStatus] = useState(null);
  const [coachResponse, setCoachResponse] = useState(null);
  const [coachLoading, setCoachLoading] = useState(false);
  const [coachError, setCoachError] = useState("");
  const [sessionId, setSessionId] = useState("");
  const [formatting, setFormatting] = useState(false);
  const [formatError, setFormatError] = useState("");
  const [tailoringSessionId, setTailoringSessionId] = useState("");
  const [tailoringStatus, setTailoringStatus] = useState(null);
  const [tailoringResult, setTailoringResult] = useState(null);
  const [tailoringLoading, setTailoringLoading] = useState(false);
  const [tailoringError, setTailoringError] = useState("");
  const [reviewAllSuggestions, setReviewAllSuggestions] = useState([]);
  const [reviewAllSummary, setReviewAllSummary] = useState(null);
  const [reviewDecisions, setReviewDecisions] = useState({});
  const [rewriteResults, setRewriteResults] = useState({});
  const [rewriteLoading, setRewriteLoading] = useState({});
  const [downloading, setDownloading] = useState(false);
  const [downloadError, setDownloadError] = useState("");
  const [downloadReady, setDownloadReady] = useState(false);
  const [showSetupPanel, setShowSetupPanel] = useState(() => !resumeText.trim());
  const [workspaceView, setWorkspaceView] = useState("feedback");
  const [mobilePanel, setMobilePanel] = useState("edit");
  const [selectedBulletId, setSelectedBulletId] = useState(null);
  const [selectedSectionId, setSelectedSectionId] = useState(null);
  const [editingNodeId, setEditingNodeId] = useState(null);
  const [editingValue, setEditingValue] = useState("");
  const [annotationsOn, setAnnotationsOn] = useState(true);
  const [selectedBulletTab, setSelectedBulletTab] = useState("action_oriented");
  const [scoreChange, setScoreChange] = useState(null);
  const [error, setError] = useState("");
  const [tailorDecisionBusy, setTailorDecisionBusy] = useState({});
  const [tailorEditedTexts, setTailorEditedTexts] = useState({});
  const [tailorApplyBusy, setTailorApplyBusy] = useState(false);
  const [atsGapInputs, setAtsGapInputs] = useState({});
  const [atsGapDecisions, setAtsGapDecisions] = useState({});
  const [showAddSectionMenu, setShowAddSectionMenu] = useState(false);

  const fileInputRef = useRef(null);
  const scorePanelRef = useRef(null);
  const selectedFeedbackRef = useRef(null);
  const initialScoredRef = useRef(false);
  const previousJobDescriptionRef = useRef("");
  const tailoringPollAttemptsRef = useRef(0);

  const openMobileFeedbackPanel = useCallback((targetRef = scorePanelRef) => {
    if (typeof window === "undefined" || window.innerWidth >= 1024) return;
    setMobilePanel("feedback");
    window.requestAnimationFrame(() => {
      window.requestAnimationFrame(() => {
        targetRef?.current?.scrollIntoView({ behavior: "smooth", block: "start" });
      });
    });
  }, []);

  useEffect(() => {
    try {
      sessionStorage.setItem("jh_resume_profile", JSON.stringify(profile));
    } catch {
      // ignore quota failures
    }
  }, [profile]);

  useEffect(() => {
    try {
      sessionStorage.setItem("jh_resume_text", resumeText);
    } catch {
      // ignore quota failures
    }
  }, [resumeText]);

  useEffect(() => {
    try {
      sessionStorage.setItem("jh_resume_template", selectedTemplate);
    } catch {
      // ignore quota failures
    }
  }, [selectedTemplate]);

  useEffect(() => {
    const fetchStatus = () => fetch(`${API_BASE}/api/ai/status`)
      .then((response) => response.json())
      .then(setAiStatus)
      .catch(() => {});

    fetchStatus();
    const interval = setInterval(fetchStatus, 10000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    fetch(`${API_BASE}/api/resume/templates`)
      .then((response) => response.json())
      .then((data) => {
        if (Array.isArray(data) && data.length > 0) {
          setTemplates(data);
          setSelectedTemplate((current) => (
            data.some((template) => template.id === current)
              ? current
              : data[0].id
          ));
        }
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (!tailoringSessionId || !tailoringLoading || tailoringResult) return undefined;

    let cancelled = false;
    tailoringPollAttemptsRef.current = 0;

    const pollStatus = async () => {
      while (!cancelled && tailoringPollAttemptsRef.current < 120) {
        tailoringPollAttemptsRef.current += 1;

        try {
          const statusResponse = await apiFetch(`/api/resume/tailor/${tailoringSessionId}/status`);
          const statusData = await statusResponse.json();
          if (cancelled) return;
          setTailoringStatus(statusData);

          if (statusData?.error) {
            throw new Error(statusData.error);
          }

          if (statusData?.complete) {
            const resultResponse = await apiFetch(`/api/resume/tailor/${tailoringSessionId}/result`);
            const resultData = await resultResponse.json();
            if (cancelled) return;
            setTailoringResult(resultData);
            setTailoringLoading(false);
            openMobileFeedbackPanel();
            return;
          }

          await new Promise((resolve) => setTimeout(resolve, 2500));
        } catch (err) {
          if (cancelled) return;
          setTailoringError(
            err.message?.includes("429")
              ? "You’ve hit today’s AI tailoring limit."
              : err.message || "Full tailoring failed. Please try again.",
          );
          setTailoringLoading(false);
          return;
        }
      }

      if (!cancelled) {
        setTailoringError("The full tailor run took too long. Please try again.");
        setTailoringLoading(false);
      }
    };

    pollStatus();
    return () => {
      cancelled = true;
    };
  }, [openMobileFeedbackPanel, tailoringLoading, tailoringResult, tailoringSessionId]);

  const jobDescription = useMemo(() => {
    if (!selectedJob) return "";
    const parts = [];
    if (selectedJob.title && selectedJob.company) parts.push(`${selectedJob.title} at ${selectedJob.company}`);
    else if (selectedJob.title) parts.push(selectedJob.title);
    if (selectedJob.skills?.length) parts.push(`Required skills: ${selectedJob.skills.join(", ")}`);
    if (selectedJob.description) parts.push(selectedJob.description);
    return parts.join(". ");
  }, [selectedJob]);

  const runScore = useCallback(async (text, jd = jobDescription, { phase = "opening" } = {}) => {
    if (!text.trim() || text.trim().length < 50) {
      setScoreData(null);
      setScoreError("");
      setNeedsRescore(false);
      setScorePhase("opening_pending");
      return null;
    }

    setScoring(true);
    setScoreError("");

    try {
      const response = await apiFetch("/api/resume/score", {
        method: "POST",
        body: JSON.stringify({ resume_text: text, job_description: jd }),
      });
      const data = await response.json();
      const normalized = normalizeScoreData(data);
      setScoreData(normalized);
      setNeedsRescore(false);
      setScorePhase(phase === "final" ? "final_complete" : "opening_scored");
      return normalized;
    } catch (err) {
      setScoreError(err.message || "Resume scoring is unavailable right now. Please try again.");
      setNeedsRescore(Boolean(text.trim()));
      setScorePhase(scoreData ? "editing" : "opening_pending");
      return null;
    } finally {
      setScoring(false);
    }
  }, [jobDescription, scoreData]);

  useEffect(() => {
    if (!initialScoredRef.current && resumeText.trim().length >= 50) {
      initialScoredRef.current = true;
      runScore(resumeText, jobDescription, { phase: "opening" });
    }
  }, [resumeText, jobDescription, runScore]);

  const templateMeta = templates.find((template) => template.id === selectedTemplate)
    || DEFAULT_RESUME_TEMPLATES.find((template) => template.id === selectedTemplate)
    || DEFAULT_RESUME_TEMPLATES[1];
  const templateStyles = buildResumeTemplateStyles(templateMeta, selectedTemplate);
  const templateOrderSource = Array.isArray(templateMeta?.section_order) && templateMeta.section_order.length > 0
    ? templateMeta.section_order
    : Array.isArray(templateMeta?.order) && templateMeta.order.length > 0
      ? templateMeta.order
      : null;
  const templateOrder = templateOrderSource
    ? templateOrderSource
    : RESUME_TEMPLATE_SECTION_ORDER[selectedTemplate] || [];

  const resumeKeywords = useMemo(
    () => buildResumeKeywords(selectedJob, scoreData),
    [selectedJob, scoreData],
  );

  const parsedSections = useMemo(
    () => parseResumeToSections(resumeText, resumeKeywords, templateOrder),
    [resumeText, resumeKeywords, templateOrder],
  );

  const bulletSections = useMemo(
    () => parsedSections.filter((section) => section.type === "bullet"),
    [parsedSections],
  );

  const selectedBullet = useMemo(
    () => bulletSections.find((section) => section.id === selectedBulletId) || null,
    [bulletSections, selectedBulletId],
  );
  const selectedSection = useMemo(
    () => parsedSections.find((section) => section.id === selectedSectionId) || null,
    [parsedSections, selectedSectionId],
  );

  useEffect(() => {
    if (selectedBulletId && !bulletSections.some((section) => section.id === selectedBulletId)) {
      setSelectedBulletId(null);
    }
  }, [bulletSections, selectedBulletId]);

  useEffect(() => {
    if (selectedSectionId && !parsedSections.some((section) => section.id === selectedSectionId)) {
      setSelectedSectionId(null);
    }
  }, [parsedSections, selectedSectionId]);

  useEffect(() => {
    if (selectedBullet && selectedFeedbackRef.current) {
      selectedFeedbackRef.current.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }
  }, [selectedBullet]);

  useEffect(() => {
    if (!Array.isArray(tailoringResult?.changes)) return;
    setTailorEditedTexts((current) => {
      const next = { ...current };
      tailoringResult.changes.forEach((change, index) => {
        const key = change?.bullet_id || (change?.type === "summary_rewrite" ? "summary" : `change-${index}`);
        if (!(key in next)) {
          next[key] = change?.user_edited_text || change?.tailored || "";
        }
      });
      return next;
    });
  }, [tailoringResult]);

  useEffect(() => {
    const tabs = getBulletFeedbackTabs(selectedBullet, resumeText);
    if (!tabs.length) return;
    const firstIssue = tabs.find((tab) => tab.status === "issue");
    setSelectedBulletTab(firstIssue?.id || tabs[0].id);
  }, [selectedBullet, resumeText]);

  useEffect(() => {
    if (previousJobDescriptionRef.current !== jobDescription && scoreData) {
      setNeedsRescore(true);
      setScorePhase("editing");
    }
    previousJobDescriptionRef.current = jobDescription;
  }, [jobDescription, scoreData]);

  useEffect(() => {
    if (!selectedJob?.id || !resumeText.trim() || resumeText.trim().length < 50) {
      setJobMatchData(null);
      setJobMatchError("");
      setJobMatchLoading(false);
      return;
    }
    if (needsRescore) return;

    let cancelled = false;
    setJobMatchLoading(true);
    setJobMatchError("");

    apiFetch(`/api/jobs/${selectedJob.id}/match`, {
      method: "POST",
      body: JSON.stringify({
        resume_text: resumeText,
        job_description: jobDescription,
      }),
    })
      .then((response) => response.json())
      .then((data) => {
        if (cancelled) return;
        setJobMatchData(data);
      })
      .catch((err) => {
        if (cancelled) return;
        setJobMatchData(null);
        setJobMatchError(err.message || "Job-specific matching is unavailable right now.");
      })
      .finally(() => {
        if (!cancelled) setJobMatchLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [selectedJob?.id, scoreData, needsRescore, jobDescription, resumeText]);

  const applyResumeText = useCallback((nextText, { rescore = false, clearRewrites = false, preserveTailoringContext = false } = {}) => {
    setResumeText(nextText);
    setScoreChange(null);
    setDownloadReady(false);
    setReviewAllSuggestions([]);
    setReviewAllSummary(null);
    setReviewDecisions({});
    if (!preserveTailoringContext) {
      setTailoringSessionId("");
      setTailoringStatus(null);
      setTailoringResult(null);
      setTailoringError("");
      setTailorDecisionBusy({});
      setTailorEditedTexts({});
      setTailorApplyBusy(false);
      setAtsGapInputs({});
      setAtsGapDecisions({});
    }
    if (clearRewrites) setRewriteResults({});
    if (rescore) {
      runScore(nextText, jobDescription, { phase: "opening" });
    } else {
      setNeedsRescore(Boolean(nextText.trim()));
      if (nextText.trim()) setScorePhase("editing");
    }
  }, [jobDescription, runScore]);

  const handleProfileChange = (field, value) => {
    setProfile((current) => ({ ...current, [field]: value }));
  };

  const handleFileUpload = async (file) => {
    if (!file) return;

    const ext = file.name.split(".").pop()?.toLowerCase();
    if (!["pdf", "docx"].includes(ext)) {
      setUploadError("Please upload a PDF or DOCX file.");
      return;
    }
    if (file.size > 5 * 1024 * 1024) {
      setUploadError("File too large. Maximum size is 5 MB.");
      return;
    }

    setUploading(true);
    setUploadError("");
    setError("");

    try {
      const formData = new FormData();
      formData.append("file", file);
      const token = localStorage.getItem("token");
      const headers = {};
      if (token) headers.Authorization = `Bearer ${token}`;

      const response = await fetch(`${API_BASE}/api/resume/upload`, {
        method: "POST",
        headers,
        body: formData,
      });

      if (!response.ok) {
        throw new Error(`${response.status}: ${await response.text()}`);
      }

      const data = await response.json();
      const nextText = data.text || "";
      setProfile({
        name: data.name || "",
        email: data.email || "",
        phone: data.phone || "",
        location: "",
      });
      setPastedText("");
      setSelectedBulletId(null);
      setEditingNodeId(null);
      setCoachResponse(null);
      setCoachError("");
      setSessionId("");
      setShowSetupPanel(false);
      applyResumeText(nextText, { rescore: true, clearRewrites: true });
    } catch (err) {
      setUploadError(err.message || "Failed to upload file. Please try again.");
    } finally {
      setUploading(false);
    }
  };

  const handleDrop = (event) => {
    event.preventDefault();
    setDragOver(false);
    const file = event.dataTransfer?.files?.[0];
    if (file) handleFileUpload(file);
  };

  const handlePasteResume = () => {
    if (!pastedText.trim()) return;
    setProfile({ name: "", email: "", phone: "", location: "" });
    setSelectedBulletId(null);
    setEditingNodeId(null);
    setCoachResponse(null);
    setCoachError("");
    setSessionId("");
    setShowSetupPanel(false);
    applyResumeText(pastedText.trim(), { rescore: true, clearRewrites: true });
  };

  const handleAIReview = async () => {
    if (!resumeText.trim()) return;

    setCoachLoading(true);
    setCoachError("");
    setCoachResponse(null);
    setSessionId("");

    try {
      const response = await apiFetch("/api/ai/coach", {
        method: "POST",
        body: JSON.stringify({ resume_text: resumeText, job_description: jobDescription }),
      });
      const data = await response.json();
      setCoachResponse(data);
      if (data.session_id) setSessionId(data.session_id);
      openMobileFeedbackPanel();
    } catch (err) {
      const message = err.message?.includes("429")
        ? "You’ve reached today’s AI coaching limit."
        : "AI is busy right now. Please try again in a moment.";
      setCoachError(message);
    } finally {
      setCoachLoading(false);
    }
  };

  const handleAIFormat = async () => {
    if (!resumeText.trim()) return;

    setFormatting(true);
    setFormatError("");
    setReviewAllSuggestions([]);
    setReviewAllSummary(null);
    setReviewDecisions({});

    try {
      const response = await apiFetch("/api/ai/review-all", {
        method: "POST",
        body: JSON.stringify({ resume_text: resumeText, job_description: jobDescription }),
      });
      const data = await response.json();
      if (!data || !Array.isArray(data.suggestions)) {
        throw new Error("AI review response was malformed.");
      }
      const normalizedSuggestions = data.suggestions
        .map(normalizeReviewSuggestion)
        .filter(Boolean);
      if (!normalizedSuggestions.length) {
        throw new Error("AI review did not return any usable bullet suggestions.");
      }

      setReviewAllSuggestions(normalizedSuggestions);
      setReviewAllSummary(data.summary || null);
      openMobileFeedbackPanel();
    } catch (err) {
      setFormatError(
        err.message?.includes("429")
          ? "You’ve hit today’s AI review limit."
          : "AI Improve All review failed. Please try again.",
      );
    } finally {
      setFormatting(false);
    }
  };

  const handleFullTailorRun = async ({ resumeOverride = null, allowNoJob = false } = {}) => {
    const sourceResumeText = typeof resumeOverride === "string" ? resumeOverride : resumeText;
    const sourceJobDescription = jobDescription.trim();
    if (!sourceResumeText.trim()) return;
    if (!allowNoJob && !sourceJobDescription) return;

    setTailoringLoading(true);
    setTailoringError("");
    setTailoringSessionId("");
    setTailoringStatus(null);
    setTailoringResult(null);
    setTailorDecisionBusy({});
    setTailorEditedTexts({});
    setTailorApplyBusy(false);
    setAtsGapInputs({});
    setAtsGapDecisions({});

    try {
      const response = await apiFetch("/api/resume/tailor", {
        method: "POST",
        body: JSON.stringify({
          resume_text: sourceResumeText,
          job_id: selectedJob?.id || null,
          job_description: sourceJobDescription,
          intensity: "full",
        }),
      });
      const data = await response.json();
      if (!data?.session_id) {
        throw new Error("Tailoring session did not start correctly.");
      }

      setTailoringSessionId(data.session_id);
      setTailoringStatus({
        session_id: data.session_id,
        stage: "queued",
        stage_number: 0,
        total_stages: TAILOR_STAGE_LABELS.length,
        message: "Queued for a staged tailor run...",
        progress: { completed: 0, total: 0 },
      });
    } catch (err) {
      setTailoringError(
        err.message?.includes("429")
          ? "You’ve hit today’s AI tailoring limit."
          : err.message || "Full tailoring failed. Please try again.",
      );
      setTailoringLoading(false);
    }
  };

  const handleBulletRewrite = async (section, activeTabId = selectedBulletTab) => {
    if (!section?.text) return;

    setRewriteLoading((current) => ({ ...current, [section.id]: true }));
    setCoachError("");
    const sectionTabs = getBulletFeedbackTabs(section, resumeText);
    const activeFocusTab = sectionTabs.find((tab) => tab.id === activeTabId) || sectionTabs.find((tab) => tab.status === "issue") || sectionTabs[0] || null;
    const rewriteFocus = getBulletRewriteFocus(section, resumeText, activeTabId);
    const focusedFeedback = buildFocusedFeedbackContext(activeFocusTab, sectionTabs);
    const usedVerbs = bulletSections
      .filter((candidate) => candidate.id !== section.id && candidate.type === "bullet")
      .map((candidate) => candidate.text.split(/\s+/)[0]?.toLowerCase().replace(/[,:;.]$/, ""))
      .filter(Boolean)
      .join(", ");

    try {
      const response = await apiFetch("/api/ai/rewrite", {
        method: "POST",
        body: JSON.stringify({
          bullet: section.text,
          job_title: selectedJob?.title || "",
          job_description: jobDescription,
          session_id: sessionId,
          used_verbs: usedVerbs,
          rewrite_focus: rewriteFocus,
          focused_feedback: focusedFeedback,
        }),
      });
      const data = await response.json();
      if (!data || typeof data.original !== "string" || !Array.isArray(data.options)) {
        throw new Error("Rewrite response was malformed.");
      }
      const rankedOptions = rankRewriteOptions(data.options, section, resumeText, rewriteFocus);
      setRewriteResults((current) => ({
        ...current,
        [section.id]: {
          ...data,
          options: rankedOptions,
          rewrite_focus: rewriteFocus,
          focused_feedback: focusedFeedback,
        },
      }));
      openMobileFeedbackPanel(selectedFeedbackRef);
    } catch (err) {
      setCoachError(
        err.message?.includes("429")
          ? "You’ve reached today’s AI rewrite limit."
          : "Rewrite failed. Please try again.",
      );
    } finally {
      setRewriteLoading((current) => ({ ...current, [section.id]: false }));
    }
  };

  const acceptRewrite = (section, optionIndex = 0) => {
    const candidate = rewriteResults?.[section.id]?.options?.[optionIndex];
    if (!candidate) return;
    const nextText = updateResumeLine(resumeText, section, candidate);
    setRewriteResults((current) => {
      const copy = { ...current };
      delete copy[section.id];
      return copy;
    });
    applyResumeText(nextText);
  };

  const rejectRewrite = (sectionId) => {
    setRewriteResults((current) => {
      const copy = { ...current };
      delete copy[sectionId];
      return copy;
    });
  };

  const setReviewDecision = useCallback((suggestionId, decision) => {
    setReviewDecisions((current) => ({ ...current, [suggestionId]: decision }));
  }, []);

  const applyAcceptedReviewChanges = useCallback(async () => {
    const acceptedSuggestions = reviewAllSuggestions.filter(
      (suggestion) => suggestion.status === "improve" && reviewDecisions[suggestion.id] === "accept",
    );

    if (!acceptedSuggestions.length) {
      setReviewAllSuggestions([]);
      setReviewAllSummary(null);
      setReviewDecisions({});
      return;
    }

    const normalizeLine = (value) => value.replace(/\s+/g, " ").trim().toLowerCase();
    const lines = resumeText.replace(/\r\n?/g, "\n").split("\n");
    let appliedCount = 0;

    acceptedSuggestions.forEach((suggestion) => {
      const targetIndex = lines.findIndex((line) => {
        const match = line.match(RESUME_BULLET_RE);
        if (!match) return false;
        return normalizeLine(match[2]) === normalizeLine(suggestion.original);
      });

      if (targetIndex >= 0 && suggestion.suggested) {
        const marker = (lines[targetIndex].match(RESUME_BULLET_RE)?.[1] || "•").trim();
        lines[targetIndex] = `${marker} ${suggestion.suggested}`;
        appliedCount += 1;
      }
    });

    if (!appliedCount) {
      setFormatError("We couldn't match the accepted bullets back to the current resume text.");
      return;
    }

    const nextText = lines.join("\n");
    const previousScore = scoreData?.overall_score;
    setSelectedBulletId(null);
    setEditingNodeId(null);
    applyResumeText(nextText, { clearRewrites: true });
    const rescored = await runScore(nextText, jobDescription, { phase: "opening" });
    if (Number.isFinite(previousScore) && Number.isFinite(rescored?.overall_score)) {
      setScoreChange({ before: previousScore, after: rescored.overall_score, context: "Updated after AI Improve All review" });
    } else if (Number.isFinite(rescored?.overall_score)) {
      setScoreChange({ before: null, after: rescored.overall_score, context: "Updated after AI Improve All review" });
    }
  }, [applyResumeText, jobDescription, resumeText, reviewAllSuggestions, reviewDecisions, runScore, scoreData?.overall_score]);

  const applyTailoredDraft = useCallback(async () => {
    if (!tailoringResult?.tailored_text) return;
    const previousScore = scoreData?.overall_score;
    setSelectedBulletId(null);
    setEditingNodeId(null);
    applyResumeText(tailoringResult.tailored_text, { clearRewrites: true });
    const rescored = await runScore(tailoringResult.tailored_text, jobDescription, { phase: "opening" });
    if (Number.isFinite(previousScore) && Number.isFinite(rescored?.overall_score)) {
      setScoreChange({ before: previousScore, after: rescored.overall_score, context: "Updated after full tailor run" });
    } else if (Number.isFinite(rescored?.overall_score)) {
      setScoreChange({ before: null, after: rescored.overall_score, context: "Updated after full tailor run" });
    }
  }, [applyResumeText, jobDescription, runScore, scoreData?.overall_score, tailoringResult]);

  const submitTailorFeedback = useCallback(async (change, action) => {
    if (!tailoringSessionId || !change) return;
    const bulletId = change.type === "summary_rewrite" ? "summary" : change.bullet_id;
    const key = bulletId || change.original || change.tailored;
    if (!bulletId) return;

    setTailorDecisionBusy((current) => ({ ...current, [key]: true }));
    try {
      const payload = {
        bullet_id: bulletId,
        action,
      };
      if (action === "edit") {
        payload.edited_text = tailorEditedTexts[key] || change.tailored || "";
      }

      await apiFetch(`/api/resume/tailor/${tailoringSessionId}/feedback`, {
        method: "POST",
        body: JSON.stringify(payload),
      });

      setTailoringResult((current) => {
        if (!current) return current;
        return {
          ...current,
          changes: (current.changes || []).map((item) => {
            const itemBulletId = item.type === "summary_rewrite" ? "summary" : item.bullet_id;
            if (itemBulletId !== bulletId) return item;
            return {
              ...item,
              user_status: action,
              ...(action === "edit" ? { user_edited_text: tailorEditedTexts[key] || item.user_edited_text || item.tailored } : {}),
            };
          }),
        };
      });
    } catch (err) {
      setTailoringError(err.message || "Could not save your review decision.");
    } finally {
      setTailorDecisionBusy((current) => ({ ...current, [key]: false }));
    }
  }, [tailorEditedTexts, tailoringSessionId]);

  const applyAcceptedTailoringChanges = useCallback(async () => {
    if (!tailoringSessionId) return;
    setTailorApplyBusy(true);
    setTailoringError("");
    try {
      const response = await apiFetch(`/api/resume/tailor/${tailoringSessionId}/apply`, {
        method: "POST",
      });
      const data = await response.json();
      if (!data?.tailored_text) {
        throw new Error("Tailoring apply response was malformed.");
      }

      const previousScore = scoreData?.overall_score;
      setSelectedBulletId(null);
      setSelectedSectionId(null);
      setEditingNodeId(null);
      applyResumeText(data.tailored_text, { clearRewrites: true });
      const rescored = await runScore(data.tailored_text, jobDescription, { phase: "opening" });
      if (Number.isFinite(previousScore) && Number.isFinite(rescored?.overall_score)) {
        setScoreChange({ before: previousScore, after: rescored.overall_score, context: "Updated after accepted tailor changes" });
      } else if (Number.isFinite(rescored?.overall_score)) {
        setScoreChange({ before: null, after: rescored.overall_score, context: "Updated after accepted tailor changes" });
      }
    } catch (err) {
      setTailoringError(err.message || "Could not apply accepted tailoring changes.");
    } finally {
      setTailorApplyBusy(false);
    }
  }, [applyResumeText, jobDescription, runScore, scoreData?.overall_score, tailoringSessionId]);

  const insertSectionAtEnd = useCallback((heading, starter) => {
    const nextText = `${resumeText.replace(/\s+$/g, "")}\n\n${heading}\n${starter}\n`;
    applyResumeText(nextText);
    setShowAddSectionMenu(false);
  }, [applyResumeText, resumeText]);

  const insertSectionNearTop = useCallback((heading, starter) => {
    const lines = resumeText.replace(/\r\n?/g, "\n").split("\n");
    const headerLineIndices = extractResumeHeaderMeta(resumeText).lineIndices;
    const insertAt = headerLineIndices.length
      ? headerLineIndices[headerLineIndices.length - 1] + 1
      : 0;
    lines.splice(insertAt, 0, "", heading, starter, "");
    applyResumeText(lines.join("\n").replace(/\n{3,}/g, "\n\n").trim());
    setShowAddSectionMenu(false);
  }, [applyResumeText, resumeText]);

  const handleAddSection = useCallback((option) => {
    if (!option) return;
    if (option.id === "custom") {
      const customHeading = window.prompt("Section heading", "CUSTOM SECTION");
      if (!customHeading?.trim()) return;
      insertSectionAtEnd(customHeading.trim().toUpperCase(), option.starter);
      return;
    }
    if (option.id === "summary") {
      insertSectionNearTop(option.heading, option.starter);
      return;
    }
    insertSectionAtEnd(option.heading, option.starter);
  }, [insertSectionAtEnd, insertSectionNearTop]);

  const appendGapToSection = useCallback((sectionKey, value) => {
    const headings = parsedSections.filter((section) => section.type === "heading" && section.sectionKey === sectionKey);
    if (headings.length === 0) {
      const headingLabel = RESUME_SECTION_LABELS[sectionKey] || titleCase(sectionKey);
      return `${resumeText.replace(/\s+$/g, "")}\n\n${headingLabel.toUpperCase()}\n• ${value}\n`;
    }

    const targetHeading = headings[headings.length - 1];
    return insertResumeLineAfter(resumeText, targetHeading, `• ${value}`);
  }, [parsedSections, resumeText]);

  const handleAtsGapAction = useCallback((gap, action) => {
    if (!gap?.skill) return;
    const gapKey = getAtsGapKey(gap);
    if (action === "skip") {
      setAtsGapDecisions((current) => ({ ...current, [gapKey]: "skip" }));
      return;
    }

    const userInput = (atsGapInputs[gapKey] || "").trim();
    if (gap.needs_user_input && !userInput) {
      setTailoringError(`Add a short fact or example before placing "${gap.skill}".`);
      return;
    }

    const insertedText = action === "skills"
      ? gap.skill
      : userInput || gap.skill;
    const targetSection = action === "skills" ? "skills" : (gap.suggested_section || "experience");
    const nextText = appendGapToSection(targetSection, insertedText);
    applyResumeText(nextText, { preserveTailoringContext: true });
    setAtsGapDecisions((current) => ({ ...current, [gapKey]: action }));
    setTailoringError("");
  }, [appendGapToSection, applyResumeText, atsGapInputs]);

  const handleOptimizeSummary = useCallback(() => {
    openMobileFeedbackPanel();
    handleFullTailorRun({ allowNoJob: true });
  }, [handleFullTailorRun, openMobileFeedbackPanel]);

  const handleDownload = async () => {
    if (!resumeText.trim()) return;

    setDownloading(true);
    setDownloadError("");
    setDownloadReady(false);

    try {
      if (needsRescore) {
        await handleFinalizeScore();
      }

      const token = localStorage.getItem("token");
      const headers = { "Content-Type": "application/json" };
      if (token) headers.Authorization = `Bearer ${token}`;

      const response = await fetch(`${API_BASE}/api/resume/download`, {
        method: "POST",
        headers,
        body: JSON.stringify({
          resume_text: resumeText,
          template: selectedTemplate,
          name: profile.name,
          email: profile.email,
          phone: profile.phone,
          location: profile.location,
        }),
      });

      if (response.status === 401) {
        localStorage.removeItem("token");
        clearResumeDraftStorage();
        window.location.reload();
        return;
      }

      if (!response.ok) {
        throw new Error(`${response.status}: ${await response.text()}`);
      }

      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = getDownloadFilename(response, "resume.docx");
      anchor.click();
      URL.revokeObjectURL(url);
      setDownloadReady(true);
    } catch (err) {
      setDownloadError(err.message || "Download failed. Please try again.");
    } finally {
      setDownloading(false);
    }
  };

  const handleFinalizeScore = async () => {
    if (!resumeText.trim()) return;
    const previousScore = scoreData?.overall_score;
    const updated = await runScore(resumeText, jobDescription, { phase: "final" });
    if (Number.isFinite(previousScore) && Number.isFinite(updated?.overall_score)) {
      setScoreChange({
        before: previousScore,
        after: updated.overall_score,
        context: previousScore === updated.overall_score ? "Final score confirmed" : "Final score updated",
      });
    } else if (Number.isFinite(updated?.overall_score)) {
      setScoreChange({ before: null, after: updated.overall_score, context: "Final score updated" });
    }
  };

  const jumpToScorePanel = () => {
    openMobileFeedbackPanel();
  };

  const openEditorForSection = (section) => {
    setSelectedSectionId(section.id);
    setEditingNodeId(section.id);
    setEditingValue(section.text);
    if (section.type === "bullet") setSelectedBulletId(section.id);
    else setSelectedBulletId(null);
  };

  const commitEdit = (section) => {
    if (!section) return;
    if (editingNodeId !== section.id) return;

    const nextText = updateResumeLine(resumeText, section, editingValue);
    setEditingNodeId(null);
    setEditingValue("");
    applyResumeText(nextText);
  };

  const wordCount = resumeText.split(/\s+/).filter(Boolean).length;
  const overallScore = Number.isFinite(scoreData?.overall_score) ? scoreData.overall_score : null;
  const scoreTheme = getScoreTheme(overallScore ?? 0);
  const scorePillClass = scoreData ? scoreTheme.pill : "bg-gray-100 text-gray-600";
  const scoreDisplayValue = overallScore ?? "--";
  const matchedKeywords = scoreData?.keyword_match?.matched || [];
  const missingKeywords = scoreData?.keyword_match?.missing || [];
  const selectedJobSkillDisplay = useMemo(
    () => buildJobSkillDisplay(selectedJob?.skills, selectedJob?.description),
    [selectedJob?.skills, selectedJob?.description],
  );
  const selectedJobCanonicalTerms = useMemo(
    () => cleanAlignmentTerms(
      jobMatchData?.job_terms?.length ? jobMatchData.job_terms : selectedJobSkillDisplay.visibleSkills,
      selectedJob?.description,
    ),
    [jobMatchData?.job_terms, selectedJobSkillDisplay.visibleSkills, selectedJob?.description],
  );
  const selectedJobSkillAlignment = useMemo(
    () => buildSkillAlignment(selectedJobCanonicalTerms, resumeText),
    [selectedJobCanonicalTerms, resumeText],
  );
  const jobMatchedKeywords = useMemo(
    () => cleanAlignmentTerms(jobMatchData?.matched || [], selectedJob?.description),
    [jobMatchData?.matched, selectedJob?.description],
  );
  const jobMissingKeywords = useMemo(
    () => cleanAlignmentTerms(jobMatchData?.missing || [], selectedJob?.description),
    [jobMatchData?.missing, selectedJob?.description],
  );
  const canonicalJobMatchSets = useMemo(() => {
    const matchedBySkill = new Map(jobMatchedKeywords.map((item) => [extractKeywordLabel(item).toLowerCase(), item]));
    const missingBySkill = new Map(jobMissingKeywords.map((item) => [extractKeywordLabel(item).toLowerCase(), item]));
    const fallbackMatchedBySkill = new Map(
      cleanAlignmentTerms(selectedJobSkillAlignment.matched, selectedJob?.description)
        .map((item) => [extractKeywordLabel(item).toLowerCase(), item]),
    );
    const fallbackMissingBySkill = new Map(
      cleanAlignmentTerms(selectedJobSkillAlignment.missing, selectedJob?.description)
        .map((item) => [extractKeywordLabel(item).toLowerCase(), item]),
    );

    const usingJobMatch = jobMatchedKeywords.length + jobMissingKeywords.length > 0;
    const usingFallback = !usingJobMatch;
    const matched = [];
    const missing = [];

    selectedJobCanonicalTerms.forEach((term) => {
      const skill = extractKeywordLabel(term);
      const normalized = skill.toLowerCase();
      if (!skill) return;

      if (usingJobMatch) {
        if (matchedBySkill.has(normalized)) matched.push(matchedBySkill.get(normalized) || term);
        else missing.push(missingBySkill.get(normalized) || term);
        return;
      }

      if (fallbackMatchedBySkill.has(normalized)) matched.push(fallbackMatchedBySkill.get(normalized) || term);
      else missing.push(fallbackMissingBySkill.get(normalized) || term);
    });

    return {
      matched,
      missing,
      usingJobMatch,
      usingFallback,
    };
  }, [
    jobMatchedKeywords,
    jobMissingKeywords,
    selectedJobCanonicalTerms,
    selectedJobSkillAlignment.matched,
    selectedJobSkillAlignment.missing,
    selectedJob?.description,
  ]);
  const relevantMatchedKeywords = canonicalJobMatchSets.matched;
  const relevantMissingKeywords = canonicalJobMatchSets.missing;
  const relevantTermTotal = selectedJobCanonicalTerms.length;
  const relevantTermsMode = !jobDescription.trim()
    ? "no_job"
    : jobMatchLoading
      ? "matching"
    : relevantTermTotal > 0
      ? canonicalJobMatchSets.usingJobMatch
        ? "job_match"
        : "skills_fallback"
      : jobMatchError
        ? "match_error"
      : "empty";
  const selectedRewrite = selectedBullet ? rewriteResults[selectedBullet.id] : null;
  const reviewableSuggestions = useMemo(
    () => reviewAllSuggestions.filter((suggestion) => suggestion.status === "improve"),
    [reviewAllSuggestions],
  );
  const tailoringChangeSummary = useMemo(
    () => summarizeTailoringChanges(tailoringResult?.changes || []),
    [tailoringResult],
  );
  const tailoringChanges = Array.isArray(tailoringResult?.changes) ? tailoringResult.changes : [];
  const tailoringAcceptedCount = tailoringChanges.filter((change) => change?.user_status === "accept" || change?.user_status === "edit").length;
  const tailoringRejectedCount = tailoringChanges.filter((change) => change?.user_status === "reject").length;
  const tailoringPendingCount = tailoringChanges.filter((change) => !change?.user_status || change?.user_status === "pending").length;
  const acceptedReviewCount = reviewableSuggestions.filter((suggestion) => reviewDecisions[suggestion.id] === "accept").length;
  const pendingReviewCount = reviewableSuggestions.filter((suggestion) => !reviewDecisions[suggestion.id]).length;
  const selectedBulletTabs = useMemo(
    () => getBulletFeedbackTabs(selectedBullet, resumeText),
    [selectedBullet, resumeText],
  );
  const activeBulletTab = selectedBulletTabs.find((tab) => tab.id === selectedBulletTab) || selectedBulletTabs[0] || null;
  const selectedBulletIssueTabs = selectedBulletTabs.filter((tab) => tab.status === "issue");
  const selectedBulletBadge = useMemo(() => {
    if (!selectedBullet) return null;
    if (selectedBulletIssueTabs.length <= 1) return selectedBullet.annotation || null;
    const hasHighSeverityIssue = selectedBulletIssueTabs.some((tab) => tab.tone === "rose");
    return {
      icon: hasHighSeverityIssue ? <X size={14} /> : <AlertCircle size={14} />,
      label: `${selectedBulletIssueTabs.length} Issues`,
      pillClass: hasHighSeverityIssue ? "bg-rose-100 text-rose-800" : "bg-amber-100 text-amber-800",
    };
  }, [selectedBullet, selectedBulletIssueTabs]);
  const headerMeta = useMemo(() => extractResumeHeaderMeta(resumeText), [resumeText]);
  const fallbackHeaderLines = [profile.name, [profile.email, profile.phone, profile.location].filter(Boolean).join(" | ")].filter(Boolean);
  const displayHeaderLines = headerMeta.lines.length > 0 ? headerMeta.lines : fallbackHeaderLines;
  const displayContactLine = displayHeaderLines.slice(1).join(" | ");
  const bodySections = useMemo(
    () => parsedSections.filter((section) => !headerMeta.lineIndices.includes(section.lineIndex)),
    [parsedSections, headerMeta.lineIndices],
  );
  const hasSummarySection = useMemo(
    () => parsedSections.some((section) => ["heading", "heading_paragraph"].includes(section.type) && section.sectionKey === "summary"),
    [parsedSections],
  );
  const improvementQueue = useMemo(() => {
    const bulletItems = bulletSections
      .filter((section) => section.annotation?.tone && section.annotation.tone !== "emerald")
      .map((section) => ({
        id: section.id,
        kind: "bullet",
        title: section.text.length > 72 ? `${section.text.slice(0, 72)}...` : section.text,
        detail: section.annotation?.message || "Review this bullet.",
        tone: section.annotation?.tone || "amber",
        section,
      }));

    const suggestionItems = (scoreData?.top_suggestions || []).slice(0, 3).map((suggestion, index) => ({
      id: `suggestion-${index}`,
      kind: "suggestion",
      title: suggestion.action || "Improve resume",
      detail: suggestion.detail,
      points: suggestion.points || 0,
    }));

    return [...bulletItems, ...suggestionItems];
  }, [bulletSections, scoreData]);
  const annotationCounts = bulletSections.reduce((counts, section) => {
    if (!section.annotation?.tone) return counts;
    const tone = section.annotation.tone;
    counts[tone] = (counts[tone] || 0) + 1;
    return counts;
  }, {});
  const benchmarkRows = useMemo(() => {
    const headingCount = parsedSections.filter((section) => section.type === "heading").length;
    const actionOpenings = bulletSections.filter((section) => {
      const firstWord = section.text.split(/\s+/)[0]?.toLowerCase().replace(/[,:;.]$/, "") || "";
      return isResumeActionVerb(firstWord);
    }).length;

    // Check for missing template sections
    const foundSectionKeys = new Set(parsedSections.filter((s) => s.type === "heading").map((s) => s.sectionKey).filter(Boolean));
    const expectedSections = RESUME_TEMPLATE_SECTION_ORDER[selectedTemplate] || [];
    const missingSections = expectedSections.filter((key) => key && !foundSectionKeys.has(key));

    const rows = [
      {
        label: "Word count",
        current: String(wordCount),
        target: "~490",
        status: wordCount >= 400 && wordCount <= 650 ? "good" : "review",
        note: wordCount < 400 ? "Draft is still light." : wordCount > 650 ? "May read dense." : "Healthy range.",
      },
      {
        label: "Bullets",
        current: String(bulletSections.length),
        target: "~21",
        status: bulletSections.length >= 14 && bulletSections.length <= 28 ? "good" : "review",
        note: bulletSections.length < 14 ? "Could use more evidence." : bulletSections.length > 28 ? "Consider trimming repetition." : "Good evidence density.",
      },
      {
        label: "Sections",
        current: String(headingCount),
        target: "4-5",
        status: headingCount >= 4 && headingCount <= 6 ? "good" : "review",
        note: headingCount < 4 ? "Structure may feel sparse." : headingCount > 6 ? "Structure may feel fragmented." : "Balanced sectioning.",
      },
      {
        label: "Action-led bullets",
        current: String(actionOpenings),
        target: "Most bullets",
        status: actionOpenings >= Math.min(Math.max(bulletSections.length - 2, 0), 16) ? "good" : "review",
        note: actionOpenings < Math.min(Math.max(bulletSections.length - 2, 0), 16) ? "More bullets can start with strong verbs." : "Strong action language coverage.",
      },
    ];

    if (missingSections.length > 0) {
      const sectionLabels = {
        summary: "Professional Summary", experience: "Experience", education: "Education",
        skills: "Skills", projects: "Projects", certifications: "Certifications",
        activities: "Activities & Leadership", personal: "Personal Details",
      };
      const missingLabels = missingSections.map((key) => sectionLabels[key] || titleCase(key));
      rows.push({
        label: "Template coverage",
        current: `${expectedSections.length - missingSections.length}/${expectedSections.length} core sections`,
        target: titleCase(selectedTemplate),
        status: "review",
        note: `To suit the ${titleCase(selectedTemplate)} layout better, consider adding: ${missingLabels.join(", ")}.`,
      });
    }

    return rows;
  }, [bulletSections, parsedSections, wordCount, selectedTemplate]);
  const livePresentationOverrides = useMemo(() => {
    const liveBulletCount = bulletSections.length;
    const bulletScore = liveBulletCount >= 15 && liveBulletCount <= 25
      ? 5
      : liveBulletCount >= 10 && liveBulletCount <= 35
        ? 3
        : 1;
    const bulletSuggestions = [];
    if (liveBulletCount < 15) {
      bulletSuggestions.push(`Only ${liveBulletCount} bullets found in the current draft. Aim for 15-25 to demonstrate depth.`);
    } else if (liveBulletCount > 25) {
      bulletSuggestions.push(`${liveBulletCount} bullets found in the current draft. Trim to 15-25 for conciseness.`);
    }

    const core = new Set(["summary", "objective", "experience", "education", "skills", "certifications"]);
    const matchedSections = [...new Set(
      parsedSections
        .filter((section) => (section.type === "heading" || section.type === "heading_paragraph") && core.has(section.sectionKey))
        .map((section) => section.sectionKey),
    )];
    const sectionCount = matchedSections.length;
    const sectionScore = sectionCount >= 4 ? 5 : sectionCount >= 3 ? 3 : sectionCount >= 2 ? 2 : 1;
    const missingSections = [...core].filter((sectionKey) => !matchedSections.includes(sectionKey));
    const sectionSuggestions = [];
    if (missingSections.length > 0) {
      sectionSuggestions.push(`Current draft is missing: ${missingSections.slice(0, 3).map((item) => titleCase(item)).join(", ")}.`);
    }

    return {
      bullet_count: {
        score: bulletScore,
        max: 5,
        detail: `${liveBulletCount} bullet point${liveBulletCount === 1 ? "" : "s"} in the current draft`,
        suggestions: bulletSuggestions,
      },
      section_count: {
        score: sectionScore,
        max: 5,
        detail: `${sectionCount} standard section${sectionCount === 1 ? "" : "s"} found: ${matchedSections.length ? matchedSections.map((item) => titleCase(item)).join(", ") : "none"}`,
        suggestions: sectionSuggestions,
      },
    };
  }, [bulletSections, parsedSections]);
  const liveImpactOverrides = useMemo(() => {
    const liveBulletCount = bulletSections.length;
    const bulletAnalyses = bulletSections.map((section) => analyzeBulletFeedback(section.text, resumeText, section.sectionKey));
    const actionCount = bulletAnalyses.filter((analysis) => analysis.hasActionVerb).length;
    const metricCount = bulletAnalyses.filter((analysis) => analysis.hasMetric).length;
    const bulletsMissingMetrics = bulletSections
      .filter((section) => !analyzeBulletFeedback(section.text, resumeText, section.sectionKey).hasMetric)
      .map((section) => ({
        id: section.id,
        preview: section.text.length > 60 ? `${section.text.slice(0, 60)}...` : section.text,
        hint: "Add a %, $, timeline, team size, or scale cue.",
      }));
    const totalBullets = liveBulletCount || 1;
    const actionScore = Math.min(10, Math.round((actionCount / totalBullets) * 10));
    const specificsScore = Math.min(10, Math.round((metricCount / totalBullets) * 10));
    const actionSuggestions = [];
    const specificsSuggestions = [];

    if (liveBulletCount === 0) {
      actionSuggestions.push("Add achievement bullets under experience or projects so we can assess action-led writing.");
      specificsSuggestions.push("Add bullet points with outcomes and metrics so the draft shows measurable impact.");
    } else {
      if (actionCount / totalBullets < 0.8) {
        actionSuggestions.push("Start more bullets with strong action verbs (e.g., Led, Developed, Implemented).");
      }
      if (metricCount / totalBullets < 0.5) {
        specificsSuggestions.push("Quantify more bullets with numbers, percentages, dollar amounts, or scale cues.");
      }
    }

    return {
      action_oriented: {
        score: actionScore,
        max: 10,
        detail: `${actionCount}/${liveBulletCount} bullets start with action verbs`,
        suggestions: actionSuggestions,
      },
      specifics: {
        score: specificsScore,
        max: 10,
        detail: `${metricCount}/${liveBulletCount} bullets contain metrics/numbers`,
        suggestions: specificsSuggestions,
        missing_examples: bulletsMissingMetrics,
      },
    };
  }, [bulletSections, resumeText]);
  const issueBulletCount = bulletSections.filter((section) => section.annotation?.tone && section.annotation.tone !== "emerald").length;
  const improvementCount = issueBulletCount + (scoreData?.top_suggestions?.length || 0) + Math.min(relevantMissingKeywords.length, 6);
  const isFeedbackView = workspaceView === "feedback";
  const isEditorView = workspaceView === "editor";
  const showFeedbackPanels = isFeedbackView || mobilePanel === "feedback";
  const lowScoreWarning = scoreData && overallScore !== null && overallScore < 50;
  const setupVisible = showSetupPanel || !resumeText.trim();
  const scorePhaseLabel = !scoreData && scoreError
    ? "Scoring unavailable"
    : scorePhase === "final_complete"
      ? "Final score complete"
      : scorePhase === "editing"
        ? "Final score pending"
        : scorePhase === "opening_scored"
          ? "Opening score ready"
          : "Opening score pending";
  const workflowSteps = [
    {
      id: "intake",
      label: "Intake",
      detail: resumeText.trim() ? "Resume loaded" : "Upload a PDF, DOCX, or pasted draft",
      state: resumeText.trim() ? "complete" : "active",
    },
    {
      id: "refine",
      label: "Refine",
      detail: selectedBullet ? "Bullet-level feedback active" : "Review score, phrasing, and structure",
      state: !resumeText.trim() ? "upcoming" : scorePhase === "final_complete" ? "complete" : "active",
    },
    {
      id: "finalize",
      label: "Finalize",
      detail: scorePhase === "final_complete" ? "Final score locked for export" : "Finalize score before download",
      state: !resumeText.trim() ? "upcoming" : scorePhase === "final_complete" ? "complete" : needsRescore ? "active" : "upcoming",
    },
  ];

  const focusBullet = useCallback((sectionId) => {
    setSelectedBulletId(sectionId);
    setSelectedSectionId(sectionId);
    setMobilePanel("feedback");
    if (typeof window !== "undefined") {
      window.requestAnimationFrame(() => {
        document.getElementById(`resume-section-${sectionId}`)?.scrollIntoView({
          behavior: "smooth",
          block: "center",
        });
      });
    }
  }, []);

  const handleInsertBulletBelow = useCallback((section) => {
    if (!section || section.type !== "bullet") return;
    const nextId = `line-${section.lineIndex + 1}`;
    const nextText = insertResumeLineAfter(resumeText, section, `${section.marker || "•"} `);
    setEditingNodeId(nextId);
    setEditingValue("");
    setSelectedBulletId(nextId);
    setSelectedSectionId(nextId);
    applyResumeText(nextText);
  }, [applyResumeText, resumeText]);

  const handleDeleteSection = useCallback((section) => {
    if (!section) return;
    const nextText = removeResumeSectionBlock(resumeText, section, parsedSections);
    setEditingNodeId(null);
    setEditingValue("");
    if (selectedBulletId === section.id) setSelectedBulletId(null);
    if (selectedSectionId === section.id) setSelectedSectionId(null);
    applyResumeText(nextText);
  }, [applyResumeText, parsedSections, resumeText, selectedBulletId, selectedSectionId]);

  return (
    <div className="space-y-6 pb-24">
      <input
        ref={fileInputRef}
        type="file"
        accept=".pdf,.docx"
        className="hidden"
        onChange={(event) => {
          handleFileUpload(event.target.files?.[0]);
          event.target.value = "";
        }}
      />

      <div className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
        <div className="flex flex-col gap-5 xl:flex-row xl:items-start xl:justify-between">
          <div>
            <div className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-500">Resume Module</div>
            <h2 className="mt-2 flex items-center gap-2 text-2xl font-semibold text-slate-900">
              <FileText size={18} />
              Resume Workspace
            </h2>
            <p className="mt-2 max-w-2xl text-sm leading-relaxed text-slate-600">
              Start with an opening score, refine directly inside the document, and only lock the final score when the draft is ready to export.
            </p>
          </div>
          {selectedJob && (
            <div className="max-w-xl rounded-2xl border border-indigo-200 bg-indigo-50 px-4 py-4 shadow-sm">
              <div className="flex items-center justify-between gap-3">
                <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-indigo-600">Target Job Description</div>
                <button
                  type="button"
                  onClick={() => setActiveTab("scraper")}
                  className="text-xs font-semibold text-indigo-700 hover:text-indigo-900"
                >
                  Back to Jobs
                </button>
              </div>
              <div className="mt-2 text-lg font-semibold text-slate-900">{selectedJob.title}</div>
              <div className="mt-1 text-sm text-slate-600">{selectedJob.company}</div>
              {selectedJobCanonicalTerms.length > 0 && (
                <div className="mt-3 flex flex-wrap gap-1.5">
                  {selectedJobCanonicalTerms.map((term, index) => {
                    const label = extractKeywordLabel(term);
                    return (
                    <span key={`${label}-${index}`} className="rounded-full bg-indigo-100 px-2 py-0.5 text-[11px] font-medium text-indigo-700" title={term?.jd_context || ""}>
                      {label}
                    </span>
                  );})}
                </div>
              )}
              {selectedJob.description && (
                <div className="mt-3 max-h-40 overflow-y-auto rounded-xl bg-white/70 p-3 text-sm leading-relaxed text-slate-700">
                  {selectedJob.description}
                </div>
              )}
            </div>
          )}
        </div>

        <div className="mt-6 grid gap-3 md:grid-cols-3">
          {workflowSteps.map((step, index) => {
            const isComplete = step.state === "complete";
            const isActive = step.state === "active";
            const circleClass = isComplete
              ? "bg-emerald-600 text-white"
              : isActive
                ? "bg-indigo-600 text-white"
                : "bg-slate-100 text-slate-500";
            const cardClass = isComplete
              ? "border-emerald-200 bg-emerald-50"
              : isActive
                ? "border-indigo-200 bg-indigo-50"
                : "border-slate-200 bg-slate-50";

            return (
              <div key={step.id} className={`rounded-2xl border px-4 py-4 ${cardClass}`}>
                <div className="flex items-start gap-3">
                  <span className={`inline-flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full text-sm font-bold ${circleClass}`}>
                    {index + 1}
                  </span>
                  <div>
                    <div className="text-sm font-semibold text-slate-900">{step.label}</div>
                    <div className="mt-1 text-sm leading-relaxed text-slate-600">{step.detail}</div>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {downloadReady && (
        <div className="rounded-3xl border border-emerald-200 bg-emerald-50 p-5 shadow-sm">
          <div className="text-sm font-semibold uppercase tracking-[0.16em] text-emerald-700">Next Steps</div>
          <div className="mt-2 text-lg font-semibold text-slate-900">Your resume export is ready.</div>
          <p className="mt-2 text-sm leading-relaxed text-slate-600">
            Keep momentum by searching for matching roles or moving straight into application tracking.
          </p>
          <div className="mt-4 flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => setActiveTab("scraper")}
              className="inline-flex items-center gap-2 rounded-xl bg-indigo-600 px-4 py-2.5 text-sm font-medium text-white hover:bg-indigo-700"
            >
              <Search size={14} />
              Search Matching Jobs
            </button>
            <button
              type="button"
              onClick={() => setActiveTab("tracker")}
              className="inline-flex items-center gap-2 rounded-xl border border-gray-200 bg-white px-4 py-2.5 text-sm font-medium text-gray-700 hover:bg-gray-50"
            >
              <Plus size={14} />
              Track This Application
            </button>
          </div>
        </div>
      )}

      {setupVisible ? (
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1.35fr)_minmax(320px,0.9fr)]">
          <div className="space-y-4">
            <div className="rounded-3xl border border-gray-200 bg-white p-4 shadow-sm">
              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                onDrop={handleDrop}
                onDragOver={(event) => {
                  event.preventDefault();
                  setDragOver(true);
                }}
                onDragLeave={() => setDragOver(false)}
                className={`flex w-full flex-col items-center justify-center rounded-2xl border-2 border-dashed px-4 py-5 text-center transition ${
                  dragOver ? "border-indigo-400 bg-indigo-50" : "border-gray-300 bg-gray-50 hover:border-gray-400"
                }`}
              >
                {uploading ? (
                  <>
                    <Loader2 size={22} className="animate-spin text-indigo-600" />
                    <div className="mt-2 text-sm font-medium text-indigo-700">Uploading and extracting text...</div>
                  </>
                ) : (
                  <>
                    <UploadCloud size={24} className="text-gray-400" />
                    <div className="mt-2 text-sm font-semibold text-gray-700">Drop a PDF or DOCX here</div>
                    <div className="mt-1 text-xs text-gray-500">or click to browse</div>
                  </>
                )}
              </button>

              <div className="mt-4 rounded-2xl border border-gray-200 bg-gray-50 p-3">
                <div className="text-xs font-semibold uppercase tracking-[0.16em] text-gray-500">Paste Text</div>
                <textarea
                  value={pastedText}
                  onChange={(event) => setPastedText(event.target.value)}
                  placeholder="Paste raw resume text if you prefer to start from plain text."
                  className="mt-2 min-h-[110px] w-full resize-none rounded-xl border border-gray-200 bg-white px-3 py-2 text-sm text-gray-700 focus:outline-none focus:ring-2 focus:ring-indigo-200"
                />
                <button
                  type="button"
                  onClick={handlePasteResume}
                  disabled={!pastedText.trim()}
                  className="mt-3 inline-flex items-center gap-2 rounded-xl bg-indigo-600 px-3.5 py-2 text-sm font-medium text-white transition hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-40"
                >
                  <Edit3 size={14} />
                  Use Pasted Text
                </button>
              </div>
            </div>
            <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
              {[
                { key: "name", label: "Name", value: profile.name, placeholder: "Full name" },
                { key: "email", label: "Email", value: profile.email, placeholder: "Email address" },
                { key: "phone", label: "Phone", value: profile.phone, placeholder: "Phone number" },
                { key: "location", label: "Location", value: profile.location, placeholder: "Location" },
              ].map((field) => (
                <label key={field.key} className="rounded-3xl border border-gray-200 bg-white p-4 shadow-sm">
                  <div className="text-xs font-semibold uppercase tracking-[0.16em] text-gray-500">{field.label}</div>
                  <input
                    value={field.value}
                    placeholder={field.placeholder}
                    onChange={(event) => handleProfileChange(field.key, event.target.value)}
                    className="mt-3 w-full rounded-xl border border-gray-200 px-3 py-2.5 text-sm text-gray-800 focus:outline-none focus:ring-2 focus:ring-indigo-200"
                  />
                </label>
              ))}
            </div>
          </div>

          <div className="rounded-3xl border border-slate-200 bg-slate-50 p-5 shadow-sm">
            <div className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">Reference Cues</div>
            <div className="mt-2 text-lg font-semibold text-slate-900">NUS benchmark signals</div>
            <p className="mt-2 text-sm leading-relaxed text-slate-600">
              These are calibration cues drawn from NUS career-centre benchmarks. They are guide rails, not hard rules.
            </p>

            <div className="mt-5 grid gap-3 sm:grid-cols-2">
              {NUS_RESUME_BENCHMARKS.map((benchmark) => (
                <div key={benchmark.label} className="rounded-2xl border border-white bg-white px-4 py-3 shadow-sm">
                  <div className="text-2xl font-semibold text-slate-900">{benchmark.value}</div>
                  <div className="mt-1 text-sm leading-relaxed text-slate-600">{benchmark.label}</div>
                </div>
              ))}
            </div>

            <div className="mt-5 rounded-2xl border border-indigo-200 bg-indigo-50 px-4 py-4">
              <div className="text-sm font-semibold text-indigo-900">Scoring rhythm</div>
              <div className="mt-2 text-sm leading-relaxed text-indigo-800">
                We score once when the resume arrives, then again only at the end when you finalize or download.
              </div>
            </div>
          </div>
        </div>
      ) : (
        <div className="rounded-3xl border border-gray-200 bg-white p-4 shadow-sm">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
            <div>
              <div className="text-xs font-semibold uppercase tracking-[0.16em] text-gray-500">Setup Complete</div>
              <div className="mt-1 text-sm text-gray-700">
                {profile.name || "Resume loaded"}{profile.email ? ` • ${profile.email}` : ""}{profile.phone ? ` • ${profile.phone}` : ""}
              </div>
              <div className="mt-1 text-xs text-gray-500">
                {wordCount} words • {scorePhaseLabel}
              </div>
            </div>
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                onClick={() => setShowSetupPanel(true)}
                className="inline-flex items-center gap-2 rounded-xl border border-gray-200 bg-white px-3.5 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
              >
                <Edit3 size={14} />
                Edit Setup
              </button>
              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                className="inline-flex items-center gap-2 rounded-xl bg-indigo-600 px-3.5 py-2 text-sm font-medium text-white hover:bg-indigo-700"
              >
                <UploadCloud size={14} />
                Replace Resume
              </button>
            </div>
          </div>
        </div>
      )}

      {(uploadError || scoreError || coachError || formatError || downloadError || error) && (
        <div className="space-y-2">
          {[uploadError, scoreError, coachError, formatError, downloadError, error].filter(Boolean).map((message, index) => (
            <div key={`${message}-${index}`} className="flex items-center gap-2 rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
              <AlertCircle size={14} className="flex-shrink-0" />
              <span>{message}</span>
            </div>
          ))}
        </div>
      )}

      <div className="rounded-3xl border border-gray-200 bg-white p-5 shadow-sm">
        <div className="flex items-center justify-between gap-4">
          <div>
            <div className="text-sm font-semibold text-gray-800">Templates</div>
            <div className="text-xs text-gray-500">Pick the export layout early so editing and download stay aligned.</div>
          </div>
          <div className="hidden lg:flex items-center gap-2 rounded-full bg-gray-100 px-3 py-1 text-xs font-medium text-gray-600">
            <span>{templateMeta?.name || "Modern"}</span>
          </div>
        </div>
        <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {templates.map((template) => {
            const selected = selectedTemplate === template.id;
            return (
              <button
                key={template.id}
                type="button"
                onClick={() => setSelectedTemplate(template.id)}
                className={`rounded-2xl border p-3 text-left transition ${
                  selected
                    ? "border-indigo-400 bg-indigo-50 shadow-[0_10px_30px_rgba(79,70,229,0.12)] ring-2 ring-indigo-100"
                    : "border-gray-200 bg-white hover:border-gray-300 hover:shadow-sm"
                }`}
              >
                <TemplatePreview templateId={template.id} />
                <div className="mt-3 flex items-center gap-2 text-sm font-semibold text-gray-800">
                  <span>{template.name}</span>
                  {template.id === "singapore" && (
                    <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-600">
                      NUS-ready
                    </span>
                  )}
                </div>
                <div className="mt-1 text-xs leading-relaxed text-gray-500">{template.description}</div>
              </button>
            );
          })}
        </div>
      </div>

      <div className="rounded-3xl border border-gray-200 bg-white p-3 shadow-sm">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div className="inline-flex rounded-2xl bg-gray-100 p-1">
            <button
              type="button"
              onClick={() => setWorkspaceView("feedback")}
              className={`rounded-xl px-4 py-2 text-sm font-semibold transition ${isFeedbackView ? "bg-white text-gray-900 shadow-sm" : "text-gray-600"}`}
            >
              Resume Feedback
            </button>
            <button
              type="button"
              onClick={() => setWorkspaceView("editor")}
              className={`rounded-xl px-4 py-2 text-sm font-semibold transition ${isEditorView ? "bg-white text-gray-900 shadow-sm" : "text-gray-600"}`}
            >
              Smart Editor
            </button>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <div className="inline-flex items-center gap-2 rounded-2xl bg-gray-50 px-3 py-2 text-sm text-gray-600">
              <span className={`inline-flex h-8 min-w-8 items-center justify-center rounded-xl px-2 text-base font-bold ${scorePillClass}`}>
                {scoreDisplayValue}
              </span>
              <div>
                <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-gray-500">Resume Score</div>
                <div className="text-xs">{scorePhaseLabel}</div>
              </div>
            </div>

            <div className="inline-flex items-center gap-2 rounded-2xl bg-indigo-50 px-3 py-2 text-sm text-indigo-700">
              <span className="inline-flex h-8 min-w-8 items-center justify-center rounded-xl bg-indigo-600 px-2 text-sm font-bold text-white">
                {improvementCount}
              </span>
              <div>
                <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-indigo-500">Open Improvements</div>
                <div className="text-xs">{issueBulletCount} bullet issues, {relevantMissingKeywords.length} missing keywords</div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div className="lg:hidden">
        <div className="inline-flex rounded-2xl border border-gray-200 bg-white p-1 shadow-sm">
          <button
            type="button"
            onClick={() => setMobilePanel("edit")}
            className={`rounded-xl px-4 py-2 text-sm font-medium transition ${mobilePanel === "edit" ? "bg-gray-900 text-white" : "text-gray-600"}`}
          >
            Edit
          </button>
          <button
            type="button"
            onClick={() => openMobileFeedbackPanel()}
            className={`rounded-xl px-4 py-2 text-sm font-medium transition ${mobilePanel === "feedback" ? "bg-gray-900 text-white" : "text-gray-600"}`}
          >
            Feedback
          </button>
        </div>
      </div>

      <div className={`grid gap-6 ${isEditorView ? "lg:grid-cols-[minmax(0,65%)_minmax(320px,35%)]" : "lg:grid-cols-[minmax(320px,35%)_minmax(0,65%)]"}`}>
        <aside className={`${mobilePanel === "feedback" ? "block max-h-[calc(100vh-10rem)] overflow-y-auto pr-1" : "hidden"} space-y-4 ${isEditorView ? "lg:order-2" : "lg:order-1"} lg:block lg:sticky lg:top-16 lg:self-start lg:max-h-[calc(100vh-5rem)] lg:overflow-y-auto`}>
          {isEditorView && (
            <div className="rounded-3xl border border-gray-200 bg-white p-5 shadow-sm">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <div className="text-sm font-semibold text-gray-800">Improvement Queue</div>
                  <div className="mt-1 text-xs text-gray-500">Pick the next fix without leaving the document.</div>
                </div>
                <span className="inline-flex h-9 min-w-9 items-center justify-center rounded-2xl bg-indigo-600 px-2 text-sm font-bold text-white">
                  {improvementCount}
                </span>
              </div>
              <div className="mt-4 space-y-2">
                {improvementQueue.length > 0 ? improvementQueue.slice(0, 6).map((item) => {
                  if (item.kind === "bullet") {
                    const toneClass = item.tone === "rose"
                      ? "border-rose-200 bg-rose-50"
                      : "border-amber-200 bg-amber-50";
                    const label = item.tone === "rose" ? "Verb check" : "Review";
                    return (
                      <button
                        key={item.id}
                        type="button"
                        onClick={() => focusBullet(item.section.id)}
                        className={`w-full rounded-2xl border px-3 py-3 text-left transition hover:shadow-sm ${toneClass}`}
                      >
                        <div className="flex items-start justify-between gap-3">
                          <div>
                            <div className="text-sm font-semibold text-gray-800">{item.title}</div>
                            <div className="mt-1 text-xs leading-relaxed text-gray-600">{item.detail}</div>
                          </div>
                          <span className="rounded-full bg-white px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.12em] text-gray-600">
                            {label}
                          </span>
                        </div>
                      </button>
                    );
                  }

                  return (
                    <div key={item.id} className="rounded-2xl border border-slate-200 bg-slate-50 px-3 py-3">
                      <div className="flex items-center justify-between gap-3">
                        <div className="text-sm font-semibold text-gray-800">{item.title}</div>
                        {item.points > 0 && (
                          <span className="rounded-full bg-indigo-100 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.12em] text-indigo-700">
                            +{item.points}
                          </span>
                        )}
                      </div>
                      <div className="mt-1 text-xs leading-relaxed text-gray-600">{item.detail}</div>
                    </div>
                  );
                }) : (
                  <div className="rounded-2xl border border-emerald-200 bg-emerald-50 px-3 py-3 text-sm text-emerald-800">
                    No flagged bullets right now. Keep tightening content and finalize when ready.
                  </div>
                )}
              </div>
            </div>
          )}
          <div ref={scorePanelRef} className={`rounded-3xl border p-5 shadow-sm ${scoreData ? scoreTheme.panel : "border-gray-200 bg-white"}`}>
            <div className="flex items-start justify-between gap-3">
              <div>
                <div className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500">Score</div>
                <div className={`mt-2 text-4xl font-bold ${scoreData ? scoreTheme.text : "text-gray-500"}`}>
                  {scoring ? "..." : scoreDisplayValue}
                  <span className="ml-1 text-base font-medium text-gray-400">{scoreData ? "/100" : ""}</span>
                </div>
                <div className="mt-1 text-sm text-gray-600">
                  {scoreData
                    ? "Guidance snapshot based on structure, phrasing, and evidence cues."
                    : scoreError
                      ? "Resume scoring is unavailable right now. Please retry when the API is healthy."
                      : "Upload or paste a resume to begin"}
                </div>
              </div>
              {scoring && <Loader2 size={18} className="animate-spin text-indigo-500" />}
            </div>
            <div className="mt-4 h-2.5 overflow-hidden rounded-full bg-white/80">
              <div className={`h-full rounded-full transition-all ${scoreTheme.bar}`} style={{ width: `${scoreData && overallScore !== null ? overallScore : 0}%` }} />
            </div>

            <div className="mt-4 grid grid-cols-3 gap-2">
              <div className="rounded-2xl bg-white/85 px-3 py-2">
                <div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-gray-500">Solid</div>
                <div className="mt-1 text-lg font-semibold text-emerald-700">{annotationCounts.emerald || 0}</div>
              </div>
              <div className="rounded-2xl bg-white/85 px-3 py-2">
                <div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-gray-500">Review</div>
                <div className="mt-1 text-lg font-semibold text-amber-700">{annotationCounts.amber || 0}</div>
              </div>
              <div className="rounded-2xl bg-white/85 px-3 py-2">
                <div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-gray-500">Verb Check</div>
                <div className="mt-1 text-lg font-semibold text-rose-700">{annotationCounts.rose || 0}</div>
              </div>
            </div>
          </div>

          {showFeedbackPanels && scoreData && Object.keys(scoreData.dimensions || {}).length > 0 && (
            <div className="space-y-3">
              {Object.entries(scoreData.dimensions).map(([name, dimension]) => {
                const displayItems = Object.fromEntries(
                  Object.entries(dimension.items || {}).map(([itemName, item]) => [
                    itemName,
                    name === "presentation" && livePresentationOverrides[itemName]
                      ? { ...item, ...livePresentationOverrides[itemName] }
                      : name === "impact" && liveImpactOverrides[itemName]
                        ? { ...item, ...liveImpactOverrides[itemName] }
                        : item,
                  ]),
                );
                const displayDimensionScore = Object.values(displayItems).reduce(
                  (sum, item) => sum + (Number.isFinite(item?.score) ? item.score : 0),
                  0,
                );
                const statusMeta = getStatusMeta(displayDimensionScore, dimension.max);
                return (
                  <details key={name} open className="overflow-hidden rounded-3xl border border-gray-200 bg-white shadow-sm">
                    <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-5 py-4">
                      <div>
                        <div className="text-sm font-semibold text-gray-800">{titleCase(name)}</div>
                        <div className="text-xs text-gray-500">{displayDimensionScore}/{dimension.max}</div>
                      </div>
                      <span className={`inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-xs font-semibold ${statusMeta.className}`}>
                        {statusMeta.icon}
                        {statusMeta.label}
                      </span>
                    </summary>
                    <div className="border-t border-gray-100 px-5 py-4">
                      <div className="mb-4 h-2 overflow-hidden rounded-full bg-gray-100">
                        <div
                          className={`h-full rounded-full ${getScoreTheme(Math.round((displayDimensionScore / dimension.max) * 100)).bar}`}
                          style={{ width: `${dimension.max > 0 ? (displayDimensionScore / dimension.max) * 100 : 0}%` }}
                        />
                      </div>
                      <div className="space-y-3">
                        {Object.entries(displayItems).map(([itemName, item]) => {
                          const itemStatus = getStatusMeta(item.score, item.max);
                          return (
                            <details key={itemName} className="rounded-2xl bg-gray-50">
                              <summary className="cursor-pointer list-none p-3">
                                <div className="flex items-start justify-between gap-2">
                                  <div>
                                    <div className="text-sm font-medium text-gray-800">{titleCase(itemName)}</div>
                                    <div className="mt-1 text-xs text-gray-500">{item.detail}</div>
                                  </div>
                                  <span className={`inline-flex items-center gap-1 rounded-full px-2 py-1 text-[11px] font-semibold ${itemStatus.className}`}>
                                    {itemStatus.icon}
                                    {item.score}/{item.max}
                                  </span>
                                </div>
                                {item.suggestions?.length > 0 && (
                                  <div className="mt-2 text-xs leading-relaxed text-gray-600">
                                    {item.suggestions[0]}
                                  </div>
                                )}
                                {Array.isArray(item.missing_examples) && item.missing_examples.length > 0 && (
                                  <div className="mt-3 rounded-xl border border-amber-200 bg-amber-50 px-3 py-3">
                                    <div className="text-[10px] font-semibold uppercase tracking-[0.16em] text-amber-800">
                                      Bullets Missing Metrics
                                    </div>
                                    <div className="mt-2 max-h-40 space-y-2 overflow-y-auto pr-1">
                                      {item.missing_examples.map((example) => (
                                        <div key={example.id} className="rounded-lg bg-white px-2.5 py-2 text-xs leading-relaxed text-amber-900">
                                          <div className="font-medium">{example.preview}</div>
                                          <div className="mt-1 text-[11px] text-amber-800">{example.hint}</div>
                                        </div>
                                      ))}
                                    </div>
                                  </div>
                                )}
                              </summary>
                              <div className="border-t border-gray-200 px-3 pb-3 pt-2">
                                {item.matched_keywords?.length > 0 && (
                                  <div className="mb-2">
                                    <div className="text-[10px] font-semibold uppercase tracking-wider text-gray-400 mb-1">Matched</div>
                                    <div className="flex flex-wrap gap-1">
                                      {item.matched_keywords.map((kw) => (
                                        <span key={kw} className="rounded-full bg-emerald-50 px-2 py-0.5 text-[11px] text-emerald-700">{kw}</span>
                                      ))}
                                    </div>
                                  </div>
                                )}
                                {item.missing_keywords?.length > 0 && (
                                  <div>
                                    <div className="text-[10px] font-semibold uppercase tracking-wider text-gray-400 mb-1">Try adding</div>
                                    <div className="flex flex-wrap gap-1">
                                      {item.missing_keywords.map((kw) => (
                                        <span key={kw} className="rounded-full bg-rose-50 px-2 py-0.5 text-[11px] text-rose-600">{kw}</span>
                                      ))}
                                    </div>
                                  </div>
                                )}
                              </div>
                            </details>
                          );
                        })}
                      </div>
                    </div>
                  </details>
                );
              })}
            </div>
          )}

          <div
            ref={selectedBullet ? selectedFeedbackRef : null}
            className={`rounded-3xl border p-5 shadow-sm ${selectedBullet ? "border-indigo-200 bg-indigo-50" : "border-gray-200 bg-white"}`}
          >
            <div className="flex items-center justify-between gap-3">
              <div>
                <div className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500">Selected Bullet</div>
                <div className="mt-1 text-sm font-semibold text-gray-800">
                  {selectedBullet ? "Focused feedback" : "Choose a highlighted bullet"}
                </div>
              </div>
              {selectedBulletBadge && (
                <span className={`inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-xs font-semibold ${selectedBulletBadge.pillClass}`}>
                  {selectedBulletBadge.icon}
                  {selectedBulletBadge.label}
                </span>
              )}
            </div>

            {selectedBullet ? (
              <div className="mt-4 space-y-4">
                <div className="rounded-2xl border border-white/80 bg-white p-4 text-sm leading-relaxed text-gray-700 shadow-sm">
                  {selectedBullet.text}
                </div>
                {selectedBulletTabs.length > 0 && (
                  <>
                    <div className="grid grid-cols-2 gap-2">
                      {selectedBulletTabs.map((tab) => {
                        const selected = activeBulletTab?.id === tab.id;
                        const icon = tab.status === "good" ? <CheckCircle size={13} /> : <AlertCircle size={13} />;
                        const toneClass = tab.status === "good"
                          ? selected
                            ? "border-emerald-200 bg-emerald-50 text-emerald-800"
                            : "border-gray-200 bg-white text-gray-700"
                          : tab.tone === "amber"
                            ? selected
                              ? "border-amber-200 bg-amber-50 text-amber-800"
                              : "border-amber-100 bg-amber-50/70 text-amber-800"
                            : selected
                              ? "border-rose-200 bg-rose-50 text-rose-800"
                              : "border-rose-100 bg-rose-50/70 text-rose-800";

                        return (
                          <button
                            key={tab.id}
                            type="button"
                            onClick={() => setSelectedBulletTab(tab.id)}
                            className={`rounded-2xl border px-3 py-2 text-left text-xs font-semibold transition ${toneClass}`}
                          >
                            <span className="inline-flex items-center gap-1.5">
                              {icon}
                              {tab.title}
                            </span>
                          </button>
                        );
                      })}
                    </div>

                    {activeBulletTab && (
                      <div className="rounded-2xl border border-white/80 bg-white p-4 shadow-sm">
                        <div className="flex items-start justify-between gap-3">
                          <div>
                            <div className="text-sm font-semibold text-gray-800">{activeBulletTab.title}</div>
                            <div className="mt-1 text-sm leading-relaxed text-gray-600">{activeBulletTab.summary}</div>
                          </div>
                          <span className={`rounded-full px-2.5 py-1 text-[11px] font-semibold ${
                            activeBulletTab.status === "good"
                              ? "bg-emerald-100 text-emerald-800"
                              : activeBulletTab.tone === "amber"
                                ? "bg-amber-100 text-amber-800"
                                : "bg-rose-100 text-rose-800"
                          }`}>
                            {activeBulletTab.status === "good" ? "Good" : "Review"}
                          </span>
                        </div>

                        {activeBulletTab.chips?.length > 0 && (
                          <div className="mt-4 flex flex-wrap gap-2">
                            {activeBulletTab.chips.map((chip) => (
                              <span
                                key={chip}
                                className={`rounded-full px-2.5 py-1 text-xs font-medium ${
                                  activeBulletTab.status === "good"
                                    ? "bg-emerald-50 text-emerald-700"
                                    : activeBulletTab.tone === "amber"
                                      ? "bg-amber-50 text-amber-800"
                                      : "bg-rose-50 text-rose-800"
                                }`}
                              >
                                {chip}
                              </span>
                            ))}
                          </div>
                        )}

                        <div className={`mt-4 rounded-2xl px-3 py-3 text-sm leading-relaxed ${
                          activeBulletTab.status === "good"
                            ? "bg-emerald-50 text-emerald-900"
                            : activeBulletTab.tone === "amber"
                              ? "bg-amber-50 text-amber-900"
                              : "bg-rose-50 text-rose-900"
                        }`}>
                          {activeBulletTab.tip}
                        </div>

                        {selectedBullet.annotation?.keywordMatches?.length > 0 && (
                          <div className="mt-4">
                            <div className="text-xs font-semibold uppercase tracking-[0.16em] text-gray-500">Matched Keywords</div>
                            <div className="mt-2 flex flex-wrap gap-1.5">
                              {selectedBullet.annotation.keywordMatches.map((keyword) => (
                                <span key={keyword} className="rounded-full bg-sky-100 px-2 py-0.5 text-[11px] font-medium text-sky-700">
                                  {keyword}
                                </span>
                              ))}
                            </div>
                          </div>
                        )}
                      </div>
                    )}
                  </>
                )}
                <button
                  type="button"
                  onClick={() => handleBulletRewrite(selectedBullet, activeBulletTab?.id)}
                  disabled={rewriteLoading[selectedBullet.id]}
                  className="inline-flex w-full items-center justify-center gap-2 rounded-2xl bg-gray-900 px-4 py-2.5 text-sm font-medium text-white transition hover:bg-black disabled:opacity-50"
                >
                  {rewriteLoading[selectedBullet.id] ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />}
                  {rewriteLoading[selectedBullet.id] ? "Rewriting..." : getRewriteButtonLabel(activeBulletTab, selectedBullet)}
                </button>
                <div className="rounded-2xl bg-gray-50 px-3 py-3 text-xs leading-relaxed text-gray-600">
                  {activeBulletTab?.id === "bullet_length" && activeBulletTab.status === "issue"
                    ? "This will ask AI for a tighter bullet that keeps the existing facts, numbers, and scope but lands the result earlier."
                    : "Keep only claims, numbers, and scope that you can defend in interview. Treat rewrites as drafting help, not fact generation."}
                </div>

                <div className="grid grid-cols-2 gap-2">
                  <button
                    type="button"
                    onClick={() => handleInsertBulletBelow(selectedBullet)}
                    className="inline-flex items-center justify-center gap-2 rounded-2xl border border-gray-200 bg-white px-4 py-2.5 text-sm font-medium text-gray-700 transition hover:bg-gray-50"
                  >
                    <Plus size={14} />
                    Add Bullet Below
                  </button>
                  <button
                    type="button"
                    onClick={() => handleDeleteSection(selectedBullet)}
                    className="inline-flex items-center justify-center gap-2 rounded-2xl border border-rose-200 bg-rose-50 px-4 py-2.5 text-sm font-medium text-rose-700 transition hover:bg-rose-100"
                  >
                    <Trash2 size={14} />
                    Delete Bullet
                  </button>
                </div>

                {selectedRewrite && (
                  <div className="space-y-3 rounded-2xl border border-indigo-200 bg-white p-4">
                    <div className="text-xs font-semibold uppercase tracking-[0.16em] text-gray-500">Suggested Rewrite</div>
                    {selectedRewrite.no_change ? (
                      <>
                        <div className="rounded-xl bg-amber-50 p-3 text-sm leading-relaxed text-amber-900">
                          {selectedRewrite.message || "No stronger rewrite was suggested for this bullet."}
                        </div>
                        <button
                          type="button"
                          onClick={() => rejectRewrite(selectedBullet.id)}
                          className="inline-flex w-full items-center justify-center gap-2 rounded-xl border border-gray-200 bg-white px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
                        >
                          <X size={14} />
                          Close
                        </button>
                      </>
                    ) : (
                      <>
                        <div className="space-y-2">
                          {(selectedRewrite.options || []).map((option, optionIndex) => (
                            (() => {
                              const optionEvaluation = evaluateRewriteOption(option, selectedBullet, resumeText, selectedRewrite.rewrite_focus);
                              const optionMeta = getRewriteOptionMeta(optionIndex, selectedRewrite.rewrite_focus, optionEvaluation);
                              return (
                                <div key={`${selectedBullet.id}-rewrite-${optionIndex}`} className="rounded-xl border border-gray-200 bg-gray-50 p-3">
                                  <div className="text-[11px] font-semibold uppercase tracking-[0.16em] text-gray-500">
                                    {optionMeta.label}
                                  </div>
                                  <div className="mt-1 text-[11px] leading-relaxed text-gray-500">
                                    {optionMeta.detail}
                                  </div>
                                  <div className="mt-2 text-sm leading-relaxed text-gray-700">{option}</div>
                                  {optionEvaluation.unresolvedFocused.length > 0 && (
                                    <div className="mt-2 text-xs leading-relaxed text-amber-700">
                                      Still flags: {optionEvaluation.unresolvedFocused.map(getIssueLabel).join(", ")}.
                                    </div>
                                  )}
                                  <button
                                    type="button"
                                    onClick={() => acceptRewrite(selectedBullet, optionIndex)}
                                    className="mt-3 inline-flex items-center gap-2 rounded-xl bg-indigo-600 px-3 py-2 text-sm font-medium text-white hover:bg-indigo-700"
                                  >
                                    <CheckCircle size={14} />
                                    {optionMeta.cta}
                                  </button>
                                </div>
                              );
                            })()
                          ))}
                        </div>
                        <button
                          type="button"
                          onClick={() => rejectRewrite(selectedBullet.id)}
                          className="inline-flex w-full items-center justify-center gap-2 rounded-xl border border-gray-200 bg-white px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
                        >
                          <X size={14} />
                          Dismiss
                        </button>
                      </>
                    )}
                  </div>
                )}
              </div>
            ) : (
              <div className="mt-4 text-sm leading-relaxed text-gray-600">
                Click a bullet in the document to review its annotation here, then rewrite it or edit the line directly on the page.
              </div>
            )}
          </div>

          {showFeedbackPanels && (
          <div className="rounded-3xl border border-gray-200 bg-white p-5 shadow-sm">
            <div className="text-sm font-semibold text-gray-800">Benchmark Snapshot</div>
            <div className="mt-1 text-xs text-gray-500">Compared against the NUS cues you shared with me.</div>
            <div className="mt-4 space-y-2">
              {benchmarkRows.map((row) => (
                <div key={row.label} className="rounded-2xl border border-gray-100 bg-gray-50 px-3 py-3">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="text-sm font-semibold text-gray-800">{row.label}</div>
                      <div className="mt-1 text-xs text-gray-500">{row.note}</div>
                    </div>
                    <div className="text-right">
                      <div className="text-sm font-semibold text-gray-900">{row.current}</div>
                      <div className="text-[11px] text-gray-500">Target {row.target}</div>
                    </div>
                  </div>
                  <div className="mt-3">
                    <span className={`inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-[11px] font-semibold ${
                      row.status === "good" ? "bg-emerald-100 text-emerald-800" : "bg-amber-100 text-amber-800"
                    }`}>
                      {row.status === "good" ? <CheckCircle size={12} /> : <AlertCircle size={12} />}
                      {row.status === "good" ? "In Range" : "Review"}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </div>
          )}

          {showFeedbackPanels && (
          <div className="rounded-3xl border border-gray-200 bg-white p-5 shadow-sm">
            <div className="text-sm font-semibold text-gray-800">Relevant Terms</div>
            {scoreData ? (
              <>
                {relevantTermsMode === "no_job" && (
                  <div className="mt-2 rounded-2xl border border-gray-200 bg-gray-50 px-3 py-3 text-sm leading-relaxed text-gray-600">
                    Attach a job or open this workspace from a selected role to see matched and missing terms.
                  </div>
                )}
                {relevantTermsMode === "matching" && (
                  <div className="mt-2 flex items-center gap-2 rounded-2xl border border-indigo-200 bg-indigo-50 px-3 py-3 text-sm leading-relaxed text-indigo-700">
                    <Loader2 size={15} className="animate-spin" />
                    Matching your resume against this specific job now...
                  </div>
                )}
                {relevantTermsMode !== "no_job" && (
                  <>
                    <div className="mt-2 text-sm text-gray-600">
                      Matched {relevantMatchedKeywords.length} term{relevantMatchedKeywords.length === 1 ? "" : "s"}{relevantTermTotal > 0 ? ` of ${relevantTermTotal}` : ""}.
                    </div>
                    <div className="mt-2 text-xs leading-relaxed text-gray-500">
                      {relevantTermsMode === "job_match"
                        ? "Using this job's canonical term list with job-specific match context."
                        : relevantTermsMode === "skills_fallback"
                            ? "Using the same canonical job terms above, with local resume matching until richer JD matching is available."
                            : relevantTermsMode === "match_error"
                              ? "Job-specific matching is unavailable right now, so this panel is falling back to the same visible job terms above."
                              : "Use these as alignment cues, not as a keyword-stuffing checklist."}
                    </div>
                  </>
                )}
                {(relevantTermsMode === "empty" || relevantTermsMode === "match_error") && (
                  <div className="mt-3 rounded-2xl border border-gray-200 bg-gray-50 px-3 py-3 text-sm leading-relaxed text-gray-600">
                    {relevantTermsMode === "match_error"
                      ? (jobMatchError || "We couldn't load job-specific alignment terms right now.")
                      : "We couldn’t extract reliable alignment terms from this job yet. Try another role or rescore after the JD loads fully."}
                  </div>
                )}
                {relevantMatchedKeywords.length > 0 && (
                  <div className="mt-3 flex flex-wrap gap-1.5">
                    {relevantMatchedKeywords.map((keyword, idx) => {
                      const label = keyword?.skill || "";
                      return (
                        <span key={label || idx} className="rounded-full bg-emerald-100 px-2 py-0.5 text-[11px] font-medium text-emerald-700" title={keyword?.resume_context || ""}>
                          {label}
                        </span>
                      );
                    })}
                  </div>
                )}
                {relevantMissingKeywords.length > 0 && (
                  <>
                    <div className="mt-4 text-xs font-semibold uppercase tracking-[0.16em] text-gray-500">Missing</div>
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      {relevantMissingKeywords.slice(0, 12).map((keyword, idx) => {
                        const label = keyword?.skill || "";
                        return (
                          <span key={label || idx} className="rounded-full bg-rose-100 px-2 py-0.5 text-[11px] font-medium text-rose-700 cursor-pointer hover:bg-rose-200" title={keyword?.jd_context || "Missing from this role's JD context"}>
                            {label}
                          </span>
                        );
                      })}
                    </div>
                  </>
                )}
              </>
            ) : (
              <div className="mt-2 text-sm text-gray-500">Score the resume to see matched and missing keywords.</div>
            )}
          </div>
          )}

          <div className="rounded-3xl border border-gray-200 bg-white p-5 shadow-sm">
            <div className="text-sm font-semibold text-gray-800">Action Buttons</div>
            <div className="mt-4 space-y-2.5">
              <button
                type="button"
                onClick={handleFinalizeScore}
                disabled={scoring || !resumeText.trim()}
                className="inline-flex w-full items-center justify-center gap-2 rounded-2xl border border-gray-200 bg-white px-4 py-2.5 text-sm font-medium text-gray-800 transition hover:bg-gray-50 disabled:opacity-40"
              >
                {scoring ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
                {scoring ? "Scoring..." : "Finalize Score"}
              </button>
              <button
                type="button"
                onClick={handleAIFormat}
                disabled={formatting || !resumeText.trim()}
                className="inline-flex w-full items-center justify-center gap-2 rounded-2xl bg-indigo-600 px-4 py-2.5 text-sm font-medium text-white transition hover:bg-indigo-700 disabled:opacity-40"
              >
                {formatting ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />}
                {formatting ? "Improving..." : "AI Improve All"}
              </button>
              <button
                type="button"
                onClick={handleFullTailorRun}
                disabled={tailoringLoading || !resumeText.trim() || !jobDescription.trim()}
                className="inline-flex w-full items-center justify-center gap-2 rounded-2xl bg-violet-700 px-4 py-2.5 text-sm font-medium text-white transition hover:bg-violet-800 disabled:opacity-40"
              >
                {tailoringLoading ? <Loader2 size={14} className="animate-spin" /> : <Zap size={14} />}
                {tailoringLoading ? "Tailoring..." : "Run Full Tailor"}
              </button>
              {(selectedSection?.sectionKey === "summary" || !hasSummarySection) && (
                <button
                  type="button"
                  onClick={handleOptimizeSummary}
                  disabled={tailoringLoading || !resumeText.trim()}
                  className="inline-flex w-full items-center justify-center gap-2 rounded-2xl border border-violet-200 bg-violet-50 px-4 py-2.5 text-sm font-medium text-violet-800 transition hover:bg-violet-100 disabled:opacity-40"
                >
                  {tailoringLoading ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />}
                  {hasSummarySection ? "Optimize Summary" : "Generate Summary"}
                </button>
              )}
              {selectedSection && ["heading", "heading_paragraph"].includes(selectedSection.type) && (
                <button
                  type="button"
                  onClick={() => handleDeleteSection(selectedSection)}
                  disabled={!resumeText.trim()}
                  className="inline-flex w-full items-center justify-center gap-2 rounded-2xl border border-rose-200 bg-rose-50 px-4 py-2.5 text-sm font-medium text-rose-700 transition hover:bg-rose-100 disabled:opacity-40"
                >
                  <Trash2 size={14} />
                  Delete Section
                </button>
              )}
              <button
                type="button"
                onClick={handleAIReview}
                disabled={coachLoading || !resumeText.trim()}
                className="inline-flex w-full items-center justify-center gap-2 rounded-2xl bg-gray-900 px-4 py-2.5 text-sm font-medium text-white transition hover:bg-black disabled:opacity-40"
              >
                {coachLoading ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />}
                {coachLoading ? "Opening Coach..." : "AI Coach"}
              </button>
            </div>
            {needsRescore && (
              <div className="mt-3 rounded-2xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
                You’ve made edits since the opening score. We’ll score the final version when you finalize or download.
              </div>
            )}
            {scoreChange && (
              <div className="mt-3 rounded-2xl border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs text-emerald-800">
                {scoreChange.context}: {Number.isFinite(scoreChange.before) ? `${scoreChange.before} → ` : ""}{scoreChange.after}
              </div>
            )}
            {!jobDescription.trim() && (
              <div className="mt-3 rounded-2xl border border-gray-200 bg-gray-50 px-3 py-2 text-xs text-gray-600">
                Select a job first if you want the full tailor run to rewrite bullets, sections, and the summary against a specific JD. Summary generation can still run without one.
              </div>
            )}
            {aiStatus && (
              <div className="mt-4 inline-flex items-center gap-2 rounded-full bg-gray-100 px-3 py-1 text-xs font-medium text-gray-600">
                <span className={`inline-block h-2 w-2 rounded-full ${aiStatus.status === "ready" ? "bg-emerald-500" : aiStatus.status === "busy" ? "bg-amber-500" : "bg-rose-500"}`} />
                {aiStatus.status === "ready" ? "AI ready" : aiStatus.status === "busy" ? "AI busy" : `Wait about ${Math.round(aiStatus.wait_seconds || 0)}s`}
              </div>
            )}
          </div>

          {(tailoringLoading || tailoringStatus || tailoringResult || tailoringError) && (
            <div className="rounded-3xl border border-violet-200 bg-violet-50 p-5 shadow-sm">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <div className="text-sm font-semibold text-gray-900">Full Tailor Run</div>
                  <div className="mt-1 text-xs leading-relaxed text-gray-600">
                    This staged run works bullet-by-bullet, then checks section coherence, refreshes the summary, and validates the final draft against the attached JD.
                  </div>
                </div>
                {tailoringSessionId && (
                  <span className="rounded-full bg-white px-2.5 py-1 text-[11px] font-semibold text-violet-700">
                    {tailoringLoading ? "Running" : tailoringResult ? "Ready" : "Queued"}
                  </span>
                )}
              </div>

              {tailoringError && (
                <div className="mt-4 rounded-2xl border border-rose-200 bg-white px-3 py-3 text-sm leading-relaxed text-rose-700">
                  {tailoringError}
                </div>
              )}

              {tailoringStatus && (
                <div className="mt-4 rounded-2xl border border-violet-200 bg-white p-4">
                  <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-7">
                    {TAILOR_STAGE_LABELS.map((stage, stageIndex) => {
                      const currentStageNumber = Number.isFinite(tailoringStatus?.stage_number) ? tailoringStatus.stage_number : 0;
                      const isComplete = tailoringResult ? true : currentStageNumber > stageIndex;
                      const isActive = !tailoringResult && tailoringStatus?.stage === stage.id;
                      const pillClass = isComplete
                        ? "border-emerald-200 bg-emerald-50 text-emerald-800"
                        : isActive
                          ? "border-violet-200 bg-violet-50 text-violet-800"
                          : "border-gray-200 bg-gray-50 text-gray-500";
                      const activeLabel = stage.id === "bullet_rewrite" && tailoringStatus?.progress?.total
                        ? `${stage.label} ${tailoringStatus.progress.completed}/${tailoringStatus.progress.total}`
                        : stage.label;
                      return (
                        <div key={stage.id} className={`rounded-xl border px-3 py-2 text-xs font-semibold ${pillClass}`}>
                          <div className="flex items-center gap-2">
                            <span className="inline-flex h-5 w-5 items-center justify-center rounded-full bg-white text-[11px] font-bold">
                              {isComplete ? "✓" : isActive ? "●" : stageIndex + 1}
                            </span>
                            <span>{isActive ? activeLabel : stage.label}</span>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                  <div className="mt-4 flex items-center justify-between gap-3">
                    <div>
                      <div className="text-xs font-semibold uppercase tracking-[0.16em] text-gray-500">Stage</div>
                      <div className="mt-1 text-sm font-semibold text-gray-900">
                        {titleCase(String(tailoringStatus.stage || "queued").replace(/_/g, " "))}
                      </div>
                    </div>
                    <div className="text-right">
                      <div className="text-xs font-semibold uppercase tracking-[0.16em] text-gray-500">Progress</div>
                      <div className="mt-1 text-sm font-semibold text-gray-900">
                        {tailoringStatus.progress?.total
                          ? `${tailoringStatus.progress.completed}/${tailoringStatus.progress.total}`
                          : `${Math.max((tailoringStatus.stage_number || 0) + 1, 1)}/${tailoringStatus.total_stages || TAILOR_STAGE_LABELS.length}`}
                      </div>
                    </div>
                  </div>
                  <div className="mt-3 text-sm leading-relaxed text-gray-700">{tailoringStatus.message}</div>
                </div>
              )}

              {tailoringResult && (
                <div className="mt-4 space-y-4">
                  {tailoringResult.degraded && (
                    <div className="rounded-2xl border border-amber-200 bg-white px-4 py-3 text-sm leading-relaxed text-amber-900">
                      This tailor run completed, but at least one AI planning step degraded to a simpler local fallback. Review the notes below before applying the draft.
                    </div>
                  )}

                  <div className="grid gap-3 sm:grid-cols-2">
                    <div className="rounded-2xl border border-violet-200 bg-white p-4">
                      <div className="text-xs font-semibold uppercase tracking-[0.16em] text-gray-500">Score Lift</div>
                      <div className="mt-2 text-sm leading-relaxed text-gray-700">
                        {Number.isFinite(tailoringResult?.score?.before) ? tailoringResult.score.before : "--"} → {Number.isFinite(tailoringResult?.score?.after) ? tailoringResult.score.after : "--"}
                      </div>
                    </div>
                    <div className="rounded-2xl border border-violet-200 bg-white p-4">
                      <div className="text-xs font-semibold uppercase tracking-[0.16em] text-gray-500">Tailor Changes</div>
                      <div className="mt-2 text-sm leading-relaxed text-gray-700">
                        {tailoringResult.total_changes || 0} updates across bullets, sections, and summary.
                      </div>
                    </div>
                  </div>

                  {Object.keys(tailoringChangeSummary).length > 0 && (
                    <div className="flex flex-wrap gap-2">
                      {Object.entries(tailoringChangeSummary).map(([label, count]) => (
                        <span key={label} className="rounded-full bg-white px-2.5 py-1 text-xs font-semibold text-violet-700">
                          {count} {label}{count === 1 ? "" : "s"}
                        </span>
                      ))}
                    </div>
                  )}

                  {Array.isArray(tailoringResult.pipeline_notes) && tailoringResult.pipeline_notes.length > 0 && (
                    <div className="space-y-2 rounded-2xl border border-amber-200 bg-white p-4">
                      <div className="text-xs font-semibold uppercase tracking-[0.16em] text-gray-500">Pipeline Notes</div>
                      {tailoringResult.pipeline_notes.map((note, index) => (
                        <div key={`${note.type || "note"}-${index}`} className="rounded-xl bg-amber-50 px-3 py-2 text-sm leading-relaxed text-amber-900">
                          {note.message}
                        </div>
                      ))}
                    </div>
                  )}

                  {tailoringResult.skill_match && (
                    <div className="rounded-2xl border border-violet-200 bg-white p-4">
                      <div className="text-xs font-semibold uppercase tracking-[0.16em] text-gray-500">JD Alignment Snapshot</div>
                      <div className="mt-2 text-sm leading-relaxed text-gray-700">
                        Matched {tailoringResult.skill_match.before} JD skill cue{tailoringResult.skill_match.before === 1 ? "" : "s"} before rewrite.
                        {tailoringResult.skill_match.injectable?.length > 0
                          ? ` ${tailoringResult.skill_match.injectable.length} missing cue${tailoringResult.skill_match.injectable.length === 1 ? "" : "s"} looked safe to weave into existing experience.`
                          : ""}
                      </div>
                    </div>
                  )}

                  {tailoringChanges.length > 0 && (
                    <div className="space-y-3 rounded-2xl border border-violet-200 bg-white p-4">
                      <div className="flex flex-wrap items-center justify-between gap-3">
                        <div>
                          <div className="text-xs font-semibold uppercase tracking-[0.16em] text-gray-500">Review Tailor Changes</div>
                          <div className="mt-1 text-sm text-gray-700">Accept, reject, or edit each proposed change before applying them to the draft.</div>
                        </div>
                        <div className="flex flex-wrap gap-2 text-xs">
                          <span className="rounded-full bg-emerald-100 px-2.5 py-1 font-semibold text-emerald-800">Accepted {tailoringAcceptedCount}</span>
                          <span className="rounded-full bg-rose-100 px-2.5 py-1 font-semibold text-rose-800">Rejected {tailoringRejectedCount}</span>
                          <span className="rounded-full bg-gray-100 px-2.5 py-1 font-semibold text-gray-700">Pending {tailoringPendingCount}</span>
                        </div>
                      </div>
                      <div className="max-h-[34rem] space-y-3 overflow-y-auto pr-1">
                        {tailoringChanges.map((change, index) => {
                          const bulletId = change.type === "summary_rewrite" ? "summary" : change.bullet_id;
                          const changeKey = bulletId || `${change.type}-${index}`;
                          const userStatus = change.user_status || "pending";
                          return (
                            <div key={`${changeKey}-${index}`} className="rounded-2xl border border-gray-200 bg-gray-50 p-4">
                              <div className="flex flex-wrap items-center justify-between gap-2">
                                <div className="text-xs font-semibold uppercase tracking-[0.16em] text-gray-500">
                                  {titleCase(String(change.type || "change").replace(/_/g, " "))}
                                </div>
                                <span className={`rounded-full px-2.5 py-1 text-[11px] font-semibold ${
                                  userStatus === "accept" || userStatus === "edit"
                                    ? "bg-emerald-100 text-emerald-800"
                                    : userStatus === "reject"
                                      ? "bg-rose-100 text-rose-800"
                                      : "bg-amber-100 text-amber-800"
                                }`}>
                                  {userStatus === "pending" ? "Pending review" : userStatus === "edit" ? "Edited" : titleCase(userStatus)}
                                </span>
                              </div>
                              <div className="mt-3 grid gap-3 lg:grid-cols-2">
                                <div className="rounded-xl border border-gray-200 bg-white p-3">
                                  <div className="text-[10px] font-semibold uppercase tracking-[0.16em] text-gray-500">Original</div>
                                  <div className="mt-2 text-sm leading-relaxed text-gray-700">{change.original}</div>
                                </div>
                                <div className="rounded-xl border border-violet-200 bg-violet-50 p-3">
                                  <div className="text-[10px] font-semibold uppercase tracking-[0.16em] text-violet-700">Tailored</div>
                                  <div className="mt-2 text-sm leading-relaxed text-violet-950">{change.tailored}</div>
                                </div>
                              </div>
                              <textarea
                                value={tailorEditedTexts[changeKey] || ""}
                                onChange={(event) => setTailorEditedTexts((current) => ({ ...current, [changeKey]: event.target.value }))}
                                rows={3}
                                className="mt-3 w-full rounded-xl border border-gray-200 bg-white px-3 py-2 text-sm leading-relaxed text-gray-700"
                                placeholder="Optional: edit this tailored text before applying it"
                              />
                              <div className="mt-3 flex flex-wrap gap-2">
                                <button
                                  type="button"
                                  disabled={tailorDecisionBusy[changeKey]}
                                  onClick={() => submitTailorFeedback(change, "accept")}
                                  className="inline-flex items-center gap-2 rounded-xl bg-emerald-600 px-3 py-2 text-sm font-medium text-white hover:bg-emerald-700 disabled:opacity-40"
                                >
                                  {tailorDecisionBusy[changeKey] ? <Loader2 size={13} className="animate-spin" /> : <CheckCircle size={13} />}
                                  Accept
                                </button>
                                <button
                                  type="button"
                                  disabled={tailorDecisionBusy[changeKey]}
                                  onClick={() => submitTailorFeedback(change, "reject")}
                                  className="inline-flex items-center gap-2 rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-sm font-medium text-rose-700 hover:bg-rose-100 disabled:opacity-40"
                                >
                                  <X size={13} />
                                  Reject
                                </button>
                                <button
                                  type="button"
                                  disabled={tailorDecisionBusy[changeKey] || !(tailorEditedTexts[changeKey] || "").trim()}
                                  onClick={() => submitTailorFeedback(change, "edit")}
                                  className="inline-flex items-center gap-2 rounded-xl border border-violet-200 bg-white px-3 py-2 text-sm font-medium text-violet-700 hover:bg-violet-50 disabled:opacity-40"
                                >
                                  <Edit3 size={13} />
                                  Edit
                                </button>
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  )}

                  {Array.isArray(tailoringResult.ats_gaps) && tailoringResult.ats_gaps.length > 0 && (
                    <div className="space-y-3 rounded-2xl border border-violet-200 bg-white p-4">
                      <div>
                        <div className="text-xs font-semibold uppercase tracking-[0.16em] text-gray-500">ATS Gap Report</div>
                        <div className="mt-1 text-sm text-gray-700">These skills are still missing or underrepresented after the tailor run.</div>
                      </div>
                      <div className="space-y-3">
                        {tailoringResult.ats_gaps.map((gap, index) => {
                          const gapKey = getAtsGapKey(gap);
                          const gapDecision = atsGapDecisions[gapKey] || "";
                          return (
                            <div key={`${gapKey}-${index}`} className="rounded-2xl border border-gray-200 bg-gray-50 p-4">
                              <div className="flex flex-wrap items-center gap-2">
                                <div className="text-sm font-semibold text-gray-900">{gap.skill}</div>
                                <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${gap.required ? "bg-rose-100 text-rose-800" : "bg-amber-100 text-amber-800"}`}>
                                  {gap.required ? "Required" : "Preferred"}
                                </span>
                              </div>
                              <div className="mt-2 text-sm leading-relaxed text-gray-600">
                                Suggested placement: <span className="font-medium text-gray-800">{RESUME_SECTION_LABELS[gap.suggested_section] || titleCase(gap.suggested_section || "experience")}</span>
                              </div>
                              {gap.action && (
                                <div className="mt-1 text-sm leading-relaxed text-gray-600">
                                  Suggested action: {gap.action}
                                </div>
                              )}
                              {gap.needs_user_input && (
                                <textarea
                                  rows={2}
                                  value={atsGapInputs[gapKey] || ""}
                                  onChange={(event) => setAtsGapInputs((current) => ({ ...current, [gapKey]: event.target.value }))}
                                  placeholder={`Add a real example or fact for ${gap.skill}`}
                                  className="mt-3 w-full rounded-xl border border-gray-200 bg-white px-3 py-2 text-sm leading-relaxed text-gray-700"
                                />
                              )}
                              <div className="mt-3 flex flex-wrap gap-2">
                                <button
                                  type="button"
                                  onClick={() => handleAtsGapAction(gap, "skills")}
                                  className="inline-flex items-center gap-2 rounded-xl border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm font-medium text-emerald-800 hover:bg-emerald-100"
                                >
                                  <Plus size={13} />
                                  Add to Skills
                                </button>
                                <button
                                  type="button"
                                  onClick={() => handleAtsGapAction(gap, "bullet")}
                                  className="inline-flex items-center gap-2 rounded-xl border border-violet-200 bg-violet-50 px-3 py-2 text-sm font-medium text-violet-800 hover:bg-violet-100"
                                >
                                  <Plus size={13} />
                                  Add to Bullet
                                </button>
                                <button
                                  type="button"
                                  onClick={() => handleAtsGapAction(gap, "skip")}
                                  className="inline-flex items-center gap-2 rounded-xl border border-gray-200 bg-white px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
                                >
                                  <X size={13} />
                                  Skip
                                </button>
                                {gapDecision && (
                                  <span className="inline-flex items-center rounded-full bg-gray-100 px-2.5 py-1 text-[11px] font-semibold text-gray-700">
                                    {titleCase(gapDecision)}
                                  </span>
                                )}
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  )}

                  <div className="flex flex-wrap gap-2">
                    <button
                      type="button"
                      onClick={applyAcceptedTailoringChanges}
                      disabled={tailorApplyBusy || tailoringAcceptedCount === 0}
                      className="inline-flex items-center gap-2 rounded-2xl bg-violet-700 px-4 py-2.5 text-sm font-medium text-white transition hover:bg-violet-800 disabled:opacity-40"
                    >
                      {tailorApplyBusy ? <Loader2 size={14} className="animate-spin" /> : <CheckCircle size={14} />}
                      {tailorApplyBusy ? "Applying..." : "Apply Accepted Changes"}
                    </button>
                    <button
                      type="button"
                      onClick={applyTailoredDraft}
                      className="inline-flex items-center gap-2 rounded-2xl border border-violet-200 bg-white px-4 py-2.5 text-sm font-medium text-violet-700 transition hover:bg-violet-50"
                    >
                      <Zap size={14} />
                      Apply All Suggested Changes
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        setTailoringSessionId("");
                        setTailoringStatus(null);
                        setTailoringResult(null);
                        setTailoringError("");
                        setTailorDecisionBusy({});
                        setTailorEditedTexts({});
                        setTailorApplyBusy(false);
                        setAtsGapInputs({});
                        setAtsGapDecisions({});
                      }}
                      className="inline-flex items-center gap-2 rounded-2xl border border-gray-200 bg-white px-4 py-2.5 text-sm font-medium text-gray-700 transition hover:bg-gray-50"
                    >
                      <X size={14} />
                      Dismiss
                    </button>
                  </div>
                </div>
              )}
            </div>
          )}

          {reviewAllSuggestions.length > 0 && (
            <div className="rounded-3xl border border-indigo-200 bg-indigo-50 p-5 shadow-sm">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <div className="text-sm font-semibold text-gray-900">AI Improve All Review</div>
                  <div className="mt-1 text-xs leading-relaxed text-gray-600">
                    {reviewAllSummary?.message || `${reviewAllSuggestions.length} bullet suggestions ready for review.`}
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => {
                    setReviewAllSuggestions([]);
                    setReviewAllSummary(null);
                    setReviewDecisions({});
                  }}
                  className="rounded-full bg-white px-2.5 py-1 text-xs font-medium text-gray-600 hover:bg-gray-50"
                >
                  Close
                </button>
              </div>

              <div className="mt-4 flex flex-wrap gap-2 text-xs">
                <span className="rounded-full bg-emerald-100 px-2.5 py-1 font-semibold text-emerald-800">
                  Keep {reviewAllSummary?.keep ?? reviewAllSuggestions.filter((item) => item.status === "keep").length}
                </span>
                <span className="rounded-full bg-amber-100 px-2.5 py-1 font-semibold text-amber-800">
                  Improve {reviewAllSummary?.improve ?? reviewableSuggestions.length}
                </span>
                <span className="rounded-full bg-white px-2.5 py-1 font-semibold text-slate-700">
                  Pending {pendingReviewCount}
                </span>
                <span className="rounded-full bg-white px-2.5 py-1 font-semibold text-slate-700">
                  Accepted {acceptedReviewCount}
                </span>
              </div>

              <div className="mt-4 max-h-[32rem] space-y-3 overflow-y-auto pr-1">
                {reviewAllSuggestions.map((suggestion) => {
                  if (suggestion.status === "keep") {
                    return (
                      <div key={suggestion.id} className="rounded-2xl border border-emerald-200 bg-white p-4">
                        <div className="flex items-center gap-2 text-sm font-semibold text-emerald-800">
                          <CheckCircle size={15} />
                          Keep
                        </div>
                        <div className="mt-3 text-xs font-semibold uppercase tracking-[0.16em] text-gray-500">Current bullet</div>
                        <div className="mt-1 text-sm leading-relaxed text-gray-700">{suggestion.original}</div>
                        {suggestion.reason && (
                          <div className="mt-3 rounded-xl bg-emerald-50 px-3 py-2 text-xs leading-relaxed text-emerald-800">
                            {suggestion.reason}
                          </div>
                        )}
                      </div>
                    );
                  }

                  const decision = reviewDecisions[suggestion.id];
                  return (
                    <div key={suggestion.id} className="rounded-2xl border border-amber-200 bg-white p-4">
                      <div className="flex items-center gap-2 text-sm font-semibold text-amber-800">
                        <Sparkles size={15} />
                        Improve
                      </div>
                      <div className="mt-3 text-xs font-semibold uppercase tracking-[0.16em] text-gray-500">Current bullet</div>
                      <div className="mt-1 text-sm leading-relaxed text-gray-700">{suggestion.original}</div>
                      {suggestion.issue && (
                        <>
                          <div className="mt-3 text-xs font-semibold uppercase tracking-[0.16em] text-gray-500">Issue</div>
                          <div className="mt-1 text-sm leading-relaxed text-amber-800">{suggestion.issue}</div>
                        </>
                      )}
                      {suggestion.suggested && (
                        <>
                          <div className="mt-3 text-xs font-semibold uppercase tracking-[0.16em] text-gray-500">Suggested rewrite</div>
                          <div className="mt-1 text-sm leading-relaxed text-gray-900">{suggestion.suggested}</div>
                        </>
                      )}
                      {suggestion.reason && (
                        <div className="mt-3 rounded-xl bg-amber-50 px-3 py-2 text-xs leading-relaxed text-amber-900">
                          {suggestion.reason}
                        </div>
                      )}
                      <div className="mt-4 flex flex-wrap gap-2">
                        <button
                          type="button"
                          onClick={() => setReviewDecision(suggestion.id, "accept")}
                          className={`inline-flex items-center gap-2 rounded-xl px-3 py-2 text-sm font-medium transition ${
                            decision === "accept"
                              ? "bg-emerald-600 text-white"
                              : "border border-emerald-200 bg-white text-emerald-700 hover:bg-emerald-50"
                          }`}
                        >
                          <CheckCircle size={14} />
                          {decision === "accept" ? "Accepted" : "Accept"}
                        </button>
                        <button
                          type="button"
                          onClick={() => setReviewDecision(suggestion.id, "skip")}
                          className={`inline-flex items-center gap-2 rounded-xl px-3 py-2 text-sm font-medium transition ${
                            decision === "skip"
                              ? "bg-slate-700 text-white"
                              : "border border-gray-200 bg-white text-gray-700 hover:bg-gray-50"
                          }`}
                        >
                          <X size={14} />
                          {decision === "skip" ? "Skipped" : "Skip"}
                        </button>
                      </div>
                    </div>
                  );
                })}
              </div>

              <div className="mt-4 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                <div className="text-xs leading-relaxed text-gray-600">
                  {pendingReviewCount > 0
                    ? `Review ${pendingReviewCount} more suggestion${pendingReviewCount === 1 ? "" : "s"} before applying accepted changes.`
                    : acceptedReviewCount > 0
                      ? `${acceptedReviewCount} accepted change${acceptedReviewCount === 1 ? "" : "s"} ready to apply.`
                      : "All suggested changes were skipped. You can close this review or rerun it later."}
                </div>
                <button
                  type="button"
                  onClick={applyAcceptedReviewChanges}
                  disabled={pendingReviewCount > 0}
                  className="inline-flex items-center justify-center gap-2 rounded-2xl bg-indigo-600 px-4 py-2.5 text-sm font-medium text-white transition hover:bg-indigo-700 disabled:opacity-40"
                >
                  <CheckCircle size={14} />
                  Apply All Accepted Changes
                </button>
              </div>
            </div>
          )}

          {showFeedbackPanels && (
          <div className="rounded-3xl border border-gray-200 bg-white p-5 shadow-sm">
            <div className="text-sm font-semibold text-gray-800">Singapore Tips</div>
            <ul className="mt-3 space-y-2">
              {(scoreData?.sg_tips?.length ? scoreData.sg_tips : [
                "Mention residency status if it meaningfully improves your fit.",
                "List concrete tools and platforms. Skills-based matching matters.",
                "Keep the final layout ATS-friendly and easy to scan on mobile.",
              ]).map((tip, index) => (
                <li key={`${tip}-${index}`} className="flex items-start gap-2 text-sm leading-relaxed text-gray-600">
                  <ChevronRight size={14} className="mt-0.5 flex-shrink-0 text-indigo-500" />
                  <span>{tip}</span>
                </li>
              ))}
            </ul>
          </div>
          )}

          {(coachLoading || coachResponse) && (
            <details open className="overflow-hidden rounded-3xl border border-purple-200 bg-purple-50 shadow-sm">
              <summary className="cursor-pointer list-none px-5 py-4">
                <div className="flex items-center gap-2 text-sm font-semibold text-purple-900">
                  <Sparkles size={15} />
                  AI Coach
                </div>
              </summary>
              <div className="border-t border-purple-100 px-5 py-4">
                {coachLoading ? (
                  <div className="flex items-center gap-2 text-sm text-purple-700">
                    <Loader2 size={16} className="animate-spin" />
                    Reviewing your resume...
                  </div>
                ) : (
                  <>
                    <div className="whitespace-pre-line rounded-2xl bg-white p-4 text-sm leading-relaxed text-gray-700">
                      {coachResponse?.coaching}
                    </div>
                    {sessionId && (
                      <div className="mt-3 text-xs text-purple-700">
                        Session active. Bullet rewrites in this review stay on the same coaching session.
                      </div>
                    )}
                  </>
                )}
              </div>
            </details>
          )}
        </aside>

        <section className={`${mobilePanel === "edit" ? "block" : "hidden"} ${isEditorView ? "lg:order-1" : "lg:order-2"} lg:block`}>
          <div className="rounded-[2rem] border border-slate-200 bg-[#f3f5f8] p-4 shadow-sm sm:p-5">
            <div className="flex flex-col gap-3 border-b border-gray-200/70 px-1 pb-4 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <div className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500">Document Preview</div>
                <div className="mt-1 text-sm text-gray-600">
                  {wordCount} words
                  {resumeText.trim() ? " • click any line to edit inline" : " • upload or paste a resume to begin"}
                </div>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  onClick={() => setAnnotationsOn((current) => !current)}
                  className={`inline-flex items-center gap-2 rounded-full px-3 py-1.5 text-xs font-medium transition ${annotationsOn ? "bg-gray-900 text-white" : "bg-white text-gray-600 ring-1 ring-gray-200"}`}
                >
                  <Zap size={12} />
                  {annotationsOn ? "Annotations On" : "Annotations Off"}
                </button>
                <button
                  type="button"
                  onClick={jumpToScorePanel}
                  className={`inline-flex items-center gap-2 rounded-full px-3 py-1.5 text-xs font-semibold ${scorePillClass}`}
                >
                  <Star size={12} />
                  Score {scoreDisplayValue}
                </button>
              </div>
            </div>

            <div
              className={`mx-auto mt-5 bg-white shadow-[0_2px_20px_rgba(0,0,0,0.1)] border border-gray-200 ${templateStyles.pageClass}`}
              style={templateStyles.pageStyle}
            >
              {resumeText.trim() ? (
                <>
                  {displayHeaderLines.length > 0 && (
                    <div className="mb-4 border-b border-gray-300 pb-2 text-center">
                      <div className={templateStyles.nameClass} style={templateStyles.nameStyle}>{displayHeaderLines[0]}</div>
                      {displayContactLine && <div className="mx-auto mt-0.5 max-w-[34rem] text-gray-600" style={templateStyles.contactStyle}>{displayContactLine}</div>}
                    </div>
                  )}

                  <div className="space-y-0.5" style={templateStyles.bodyStyle}>
                    {bodySections.map((section) => {
                      if (section.type === "spacer") return <div key={section.id} className="h-3" />;

                      const isEditing = editingNodeId === section.id;
                      const isSelectedBullet = selectedBulletId === section.id;
                      const isSelectedSection = selectedSectionId === section.id;
                      const annotation = section.annotation;
                      const wrapperClasses = section.type === "bullet" && annotationsOn
                        ? `${annotation?.borderClass || "border-transparent bg-transparent"} border-l-[3px]`
                        : (isSelectedBullet || isSelectedSection)
                          ? "border-l-[3px] border-indigo-300 bg-indigo-50/60"
                          : "border-l-[3px] border-transparent";

                      const lineContent = isEditing ? (
                        <textarea
                          autoFocus
                          rows={section.type === "paragraph" ? 3 : 2}
                          value={editingValue}
                          onChange={(event) => setEditingValue(event.target.value)}
                          onBlur={() => commitEdit(section)}
                          onKeyDown={(event) => {
                            if (event.key === "Escape") {
                              setEditingNodeId(null);
                              setEditingValue("");
                            }
                            if (event.key === "Enter" && !event.shiftKey) {
                              event.preventDefault();
                              commitEdit(section);
                            }
                          }}
                          className="w-full resize-none rounded-xl border border-indigo-200 bg-white px-3 py-2 text-inherit leading-relaxed text-gray-800 focus:outline-none focus:ring-2 focus:ring-indigo-200"
                          style={{
                            fontSize: "16px",
                            lineHeight: templateStyles.bodyStyle.lineHeight,
                            fontFamily: templateStyles.bodyStyle.fontFamily,
                          }}
                        />
                      ) : (
                        <button
                          type="button"
                          onClick={() => openEditorForSection(section)}
                          className="w-full text-left"
                        >
                          {section.type === "heading" && (
                            <h3 className={templateStyles.headingClass} style={templateStyles.headingStyle}>
                              {renderHighlightedText(section.text, section.keywordMatches || [])}
                            </h3>
                          )}
                          {section.type === "heading_paragraph" && (
                            <div>
                              <h3 className={templateStyles.headingClass} style={templateStyles.headingStyle}>
                                {section.headingText}
                              </h3>
                              <p className="mb-4 text-gray-700" style={templateStyles.bodyStyle}>
                                {renderHighlightedText(
                                  isShoutySummaryParagraph(section.bodyText, section.sectionKey)
                                    ? toSentenceCaseDisplayText(section.bodyText)
                                    : section.bodyText,
                                  section.keywordMatches || [],
                                )}
                              </p>
                            </div>
                          )}
                          {section.type === "subheading" && (
                            section.variant === "education_main" ? (
                              <div className={`mb-2 grid grid-cols-[minmax(0,1.05fr)_minmax(0,1fr)] items-start gap-x-4 gap-y-1 ${templateStyles.subheadingClass}`}>
                                <div className="font-semibold leading-snug text-gray-900">
                                  {renderHighlightedText(
                                    getDisplaySubheadingText(section.left, section.sectionKey, section.variant),
                                    section.keywordMatches || [],
                                  )}
                                </div>
                                {(() => {
                                  const meta = splitEducationMeta(
                                    getDisplaySubheadingText(section.right, section.sectionKey, section.variant),
                                  );
                                  return (
                                    <div className="text-right text-[0.98em] leading-snug text-gray-500 break-words">
                                      <div>{meta.primary}</div>
                                      {meta.secondary && <div className="mt-0.5 text-[0.94em] text-gray-400">{meta.secondary}</div>}
                                    </div>
                                  );
                                })()}
                              </div>
                            ) : section.variant === "education_detail" ? (
                              <div className="mb-3 grid grid-cols-[minmax(0,0.64fr)_minmax(0,1fr)] items-start gap-x-4 gap-y-1 text-[0.93em] text-gray-600">
                                <div className="leading-snug">
                                  {renderHighlightedText(
                                    getDisplaySubheadingText(section.left, section.sectionKey, section.variant),
                                    section.keywordMatches || [],
                                  )}
                                </div>
                                <div className="text-right leading-snug break-words">
                                  {getDisplaySubheadingText(section.right, section.sectionKey, section.variant)}
                                </div>
                              </div>
                            ) : (
                              <div className={`flex flex-col gap-1 sm:flex-row sm:items-baseline sm:justify-between ${templateStyles.subheadingClass}`}>
                                <div className={section.variant === "dated" ? "font-semibold text-gray-900" : "font-normal text-gray-800"}>
                                  {renderHighlightedText(
                                    getDisplaySubheadingText(section.left, section.sectionKey, section.variant),
                                    section.keywordMatches || [],
                                  )}
                                </div>
                                <div className="text-sm text-gray-500">
                                  {getDisplaySubheadingText(section.right, section.sectionKey, section.variant)}
                                </div>
                              </div>
                            )
                          )}
                          {section.type === "paragraph" && (
                            (() => {
                              const inlineSegments = getInlineResumeSegments(section);
                              if (inlineSegments) {
                                return (
                                  <div className="mb-4 flex flex-wrap items-baseline gap-x-2 gap-y-1 text-gray-700" style={templateStyles.bodyStyle}>
                                    {inlineSegments.map((segment, index) => (
                                      <Fragment key={`${section.id}-segment-${index}`}>
                                        {index > 0 && <span className="text-gray-300">|</span>}
                                        <span className="font-medium text-gray-700">
                                          {renderHighlightedText(getDisplayInlineSegmentText(segment), section.keywordMatches || [])}
                                        </span>
                                      </Fragment>
                                    ))}
                                  </div>
                                );
                              }

                              return (
                                <p
                                  className={`mb-4 text-gray-700 ${section.sectionKey === "summary" && isLikelySummaryLeadParagraph(section.text) && !isShoutySummaryParagraph(section.text, section.sectionKey) ? "font-semibold tracking-[0.03em] text-gray-900" : ""}`}
                                  style={templateStyles.bodyStyle}
                                >
                                  {renderHighlightedText(getDisplayParagraphText(section), section.keywordMatches || [])}
                                </p>
                              );
                            })()
                          )}
                          {section.type === "bullet" && (
                            <div className="flex gap-3">
                              <div className="pt-1 text-[1rem] text-gray-400">•</div>
                              <div className="flex-1">
                                <p className="text-gray-700" style={templateStyles.bodyStyle}>
                                  {renderHighlightedText(section.text, annotation?.keywordMatches || [])}
                                </p>
                                {annotationsOn && annotation && (
                                  <div className="mt-2 flex flex-wrap items-center gap-2">
                                    <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold ${annotation.pillClass}`}>
                                      {annotation.icon}
                                      {annotation.label}
                                    </span>
                                    {annotation.keywordMatches?.length > 0 && (
                                      <span className="rounded-full bg-sky-100 px-2 py-0.5 text-[11px] font-semibold text-sky-700">
                                        {annotation.keywordMatches.length} keyword{annotation.keywordMatches.length === 1 ? "" : "s"}
                                      </span>
                                    )}
                                  </div>
                                )}
                              </div>
                            </div>
                          )}
                        </button>
                      );

                      return (
                        <div id={`resume-section-${section.id}`} key={section.id} className={`rounded-2xl px-3 py-2 transition ${wrapperClasses}`}>
                          {lineContent}
                        </div>
                      );
                    })}
                    <div className="mt-3 rounded-2xl border border-dashed border-indigo-200 bg-indigo-50/70 p-4">
                      <div className="flex flex-wrap items-center justify-between gap-3">
                        <div>
                          <div className="text-sm font-semibold text-slate-900">Need another section?</div>
                          <div className="mt-1 text-xs leading-relaxed text-slate-600">
                            Add Projects, Volunteer, Awards, or a custom section directly into the draft.
                          </div>
                        </div>
                        <button
                          type="button"
                          onClick={() => setShowAddSectionMenu((current) => !current)}
                          className="inline-flex items-center gap-2 rounded-xl border border-indigo-200 bg-white px-3 py-2 text-sm font-medium text-indigo-700 hover:bg-indigo-50"
                        >
                          <Plus size={14} />
                          Add Section
                        </button>
                      </div>
                      {showAddSectionMenu && (
                        <div className="mt-3 flex flex-wrap gap-2">
                          {ADD_SECTION_OPTIONS.map((option) => (
                            <button
                              key={option.id}
                              type="button"
                              onClick={() => handleAddSection(option)}
                              className="inline-flex items-center gap-2 rounded-full bg-white px-3 py-2 text-sm font-medium text-slate-700 ring-1 ring-gray-200 hover:bg-gray-50"
                            >
                              <Plus size={13} />
                              {option.label}
                            </button>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>
                </>
              ) : (
                <div className="flex min-h-[700px] flex-col items-center justify-center rounded-[1.5rem] border border-dashed border-gray-200 bg-gray-50 px-8 text-center">
                  <FileText size={36} className="text-gray-300" />
                  <div className="mt-4 text-lg font-semibold text-gray-700">Your resume document will appear here</div>
                  <p className="mt-2 max-w-md text-sm leading-relaxed text-gray-500">
                    Upload a PDF or DOCX, or paste your resume text above. Once it lands here, you’ll be able to edit line by line and review feedback beside it.
                  </p>
                </div>
              )}
            </div>
          </div>
        </section>
      </div>

      <div className="fixed inset-x-0 bottom-4 z-20 px-4">
        <div className="mx-auto flex w-full items-center justify-between gap-3 rounded-2xl border border-gray-200 bg-white/95 px-4 py-3 shadow-[0_16px_40px_rgba(15,23,42,0.18)] backdrop-blur">
          <button
            type="button"
            onClick={jumpToScorePanel}
            className={`inline-flex items-center gap-2 rounded-full px-3 py-2 text-sm font-semibold ${scorePillClass}`}
          >
            <Star size={14} />
            Score {scoreDisplayValue}
          </button>

          <div className="hidden lg:flex items-center gap-2">
            <span className="text-xs font-semibold uppercase tracking-[0.14em] text-gray-500">Template</span>
            <select
              value={selectedTemplate}
              onChange={(event) => setSelectedTemplate(event.target.value)}
              className="rounded-xl border border-gray-200 bg-white px-3 py-2 text-sm text-gray-700 focus:outline-none focus:ring-2 focus:ring-indigo-200"
            >
              {templates.map((template) => (
                <option key={template.id} value={template.id}>{template.name}</option>
              ))}
            </select>
          </div>

          <div className="flex items-center gap-3">
            {lowScoreWarning && (
              <div className="hidden text-xs text-rose-600 sm:block">
                This draft may still struggle in ATS or recruiter screens.
              </div>
            )}
            {needsRescore && (
              <button
                type="button"
                onClick={handleFinalizeScore}
                disabled={scoring || !resumeText.trim()}
                className="hidden sm:inline-flex items-center gap-2 rounded-xl border border-gray-200 bg-white px-4 py-2.5 text-sm font-medium text-gray-700 transition hover:bg-gray-50 disabled:opacity-40"
              >
                {scoring ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
                {scoring ? "Scoring..." : "Finalize Score"}
              </button>
            )}
            <button
              type="button"
              onClick={handleDownload}
              disabled={downloading || !resumeText.trim()}
              className="inline-flex items-center gap-2 rounded-xl bg-emerald-600 px-4 py-2.5 text-sm font-medium text-white transition hover:bg-emerald-700 disabled:opacity-40"
            >
              {downloading ? <Loader2 size={14} className="animate-spin" /> : <Download size={14} />}
              {downloading ? "Preparing..." : "Download DOCX"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// TAB 6: ACCOUNT
// ═══════════════════════════════════════════════════════════════════════════════

function AccountTab({ user, onLogout }) {
  const [usage, setUsage] = useState(null);
  const [usageLoading, setUsageLoading] = useState(true);
  const [contactForm, setContactForm] = useState({ name: user?.name || "", email: user?.email || "", message: "" });
  const [contactSending, setContactSending] = useState(false);
  const [contactSent, setContactSent] = useState(false);
  const [contactError, setContactError] = useState("");

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

  const isPro = user?.tier === "pro" || user?.tier === "admin";

  return (
    <div className="space-y-6">
      <div className="bg-gradient-to-r from-indigo-50 to-purple-50 rounded-xl p-5">
        <h2 className="font-semibold text-gray-800 flex items-center gap-2"><User size={18} /> Account</h2>
        <p className="text-sm text-gray-500 mt-1">Manage your account, view usage, and upgrade your plan.</p>
      </div>

      {/* User Info */}
      <div className="bg-white border border-gray-200 rounded-xl p-5">
        <h3 className="font-semibold text-gray-800 mb-4">Profile</h3>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-sm">
          <div>
            <div className="text-gray-500 text-xs uppercase tracking-wide mb-1">Name</div>
            <div className="text-gray-800 font-medium">{user?.name || "—"}</div>
          </div>
          <div>
            <div className="text-gray-500 text-xs uppercase tracking-wide mb-1">Email</div>
            <div className="text-gray-800">{user?.email || "—"}</div>
          </div>
          <div>
            <div className="text-gray-500 text-xs uppercase tracking-wide mb-1">Tier</div>
            <TierBadge tier={user?.tier} />
          </div>
          <div>
            <div className="text-gray-500 text-xs uppercase tracking-wide mb-1">Member Since</div>
            <div className="text-gray-800">{user?.created_at ? new Date(user.created_at).toLocaleDateString() : "—"}</div>
          </div>
        </div>
      </div>

      {/* Usage Stats */}
      <div className="bg-white border border-gray-200 rounded-xl p-5">
        <h3 className="font-semibold text-gray-800 mb-4">Usage</h3>
        {usageLoading ? (
          <div className="flex items-center gap-2 text-sm text-gray-500"><Loader2 size={14} className="animate-spin" /> Loading usage...</div>
        ) : usage ? (
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <div className="bg-blue-50 rounded-xl p-4 text-center">
              <div className="text-2xl font-bold text-gray-800">{usage.searches_today ?? 0}</div>
              <div className="text-xs text-gray-500 mt-1">Searches Today</div>
              {usage.searches_limit != null && (
                <div className="text-xs text-gray-400 mt-0.5">/ {usage.searches_limit} limit</div>
              )}
            </div>
            <div className="bg-purple-50 rounded-xl p-4 text-center">
              <div className="text-2xl font-bold text-gray-800">{usage.tracked_jobs ?? 0}</div>
              <div className="text-xs text-gray-500 mt-1">Tracked Jobs</div>
              {usage.tracked_limit != null && (
                <div className="text-xs text-gray-400 mt-0.5">/ {usage.tracked_limit >= 999999 ? "Unlimited" : usage.tracked_limit} limit</div>
              )}
            </div>
            <div className="bg-green-50 rounded-xl p-4 text-center">
              <div className="text-2xl font-bold text-gray-800 capitalize">{usage.tier || user?.tier || "free"}</div>
              <div className="text-xs text-gray-500 mt-1">Current Tier</div>
            </div>
          </div>
        ) : (
          <div className="text-sm text-gray-400">Could not load usage data.</div>
        )}
      </div>

      {/* Tier Comparison */}
      <div className="bg-white border border-gray-200 rounded-xl p-5">
        <h3 className="font-semibold text-gray-800 mb-4">Plan Comparison</h3>
        <div className="overflow-hidden rounded-lg border border-gray-200">
          <table className="w-full text-sm">
            <thead className="bg-gray-50">
              <tr>
                <th className="text-left px-4 py-3 text-gray-500 text-xs uppercase">Feature</th>
                <th className="text-center px-4 py-3 text-gray-500 text-xs uppercase">Free</th>
                <th className="text-center px-4 py-3 text-xs uppercase text-indigo-600">AISG (Free)</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              <tr>
                <td className="px-4 py-3 text-gray-700">Job Searching</td>
                <td className="px-4 py-3 text-center text-gray-600">Unlimited</td>
                <td className="px-4 py-3 text-center text-indigo-700 font-medium">Unlimited</td>
              </tr>
              <tr>
                <td className="px-4 py-3 text-gray-700">AI Reviews / day</td>
                <td className="px-4 py-3 text-center text-gray-600">3</td>
                <td className="px-4 py-3 text-center text-indigo-700 font-medium">50</td>
              </tr>
              <tr>
                <td className="px-4 py-3 text-gray-700">Tracked jobs</td>
                <td className="px-4 py-3 text-center text-gray-600">Upgrade required</td>
                <td className="px-4 py-3 text-center text-indigo-700 font-medium">Unlimited</td>
              </tr>
              <tr>
                <td className="px-4 py-3 text-gray-700">CSV Export</td>
                <td className="px-4 py-3 text-center text-gray-400"><X size={14} className="mx-auto" /></td>
                <td className="px-4 py-3 text-center text-green-600"><CheckCircle size={14} className="mx-auto" /></td>
              </tr>
              <tr>
                <td className="px-4 py-3 text-gray-700">ATS Checker</td>
                <td className="px-4 py-3 text-center text-gray-600">Basic</td>
                <td className="px-4 py-3 text-center text-indigo-700 font-medium">Full</td>
              </tr>
            </tbody>
          </table>
        </div>

        {!isPro && (
          <div className="mt-4 bg-gradient-to-r from-indigo-50 to-purple-50 border border-indigo-200 rounded-xl p-5">
            <div className="flex items-center gap-3 mb-2">
              <Star size={20} className="text-indigo-600" />
              <h4 className="font-semibold text-gray-800">Upgrade to AISG Tier</h4>
            </div>
            <p className="text-sm text-gray-600 mb-3">
              Upgrade to get 50 AI reviews/day, unlimited tracked jobs, CSV export, and full ATS analysis.
            </p>
            <p className="text-sm text-gray-500">
              Have questions? Send us a message below or reach out directly.
            </p>
          </div>
        )}
      </div>

      {/* Contact */}
      <div className="bg-white border border-gray-200 rounded-xl p-5">
        <h3 className="font-semibold text-gray-800 mb-4">Get in Touch</h3>

        <div className="flex flex-wrap gap-3 mb-5">
          <span className="text-sm text-gray-500">Send us a message below or email us through the contact form.</span>
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
              className="border border-gray-200 rounded-lg px-3 py-2 text-sm" />
            <input placeholder="Email" type="email" value={contactForm.email} onChange={(e) => setContactForm({ ...contactForm, email: e.target.value })}
              className="border border-gray-200 rounded-lg px-3 py-2 text-sm" />
          </div>
          <textarea placeholder="Your message..." value={contactForm.message} onChange={(e) => setContactForm({ ...contactForm, message: e.target.value })}
            className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm" rows={3} />
          <button type="submit" disabled={contactSending || !contactForm.message.trim()}
            className="flex items-center gap-2 bg-indigo-600 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-indigo-700 disabled:opacity-40 transition">
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

// ═══════════════════════════════════════════════════════════════════════════════
// MAIN APP
// ═══════════════════════════════════════════════════════════════════════════════

export default function JobHunterSG() {
  const [activeTab, setActiveTab] = useState("scraper");
  const [trackedJobs, setTrackedJobs] = useState([]);
  const [selectedJob, setSelectedJob] = useState(null);

  // Auth state
  const [user, setUser] = useState(null);
  const [token, setToken] = useState(() => localStorage.getItem("token"));
  const [authLoading, setAuthLoading] = useState(true);
  const [showAuthModal, setShowAuthModal] = useState(false);

  // Validate token on mount
  useEffect(() => {
    if (!token) {
      setAuthLoading(false);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const resp = await apiFetch("/api/auth/me");
        const data = await resp.json();
        if (!cancelled) setUser(data);
      } catch {
        localStorage.removeItem("token");
        if (!cancelled) setToken(null);
      } finally {
        if (!cancelled) setAuthLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [token]);

  // Load tracked jobs once authenticated
  const refreshJobs = useCallback(async () => {
    try {
      const resp = await apiFetch("/api/tracked");
      const data = await resp.json();
      setTrackedJobs(Array.isArray(data) ? data : data.jobs || []);
    } catch {
      // Non-critical: tracked jobs will be empty for unauthenticated users
      setTrackedJobs([]);
    }
  }, []);

  useEffect(() => {
    if (user) refreshJobs();
  }, [user, refreshJobs]);

  // Usage meter (item 7)
  const [usageData, setUsageData] = useState(null);
  useEffect(() => {
    if (!user) return;
    let cancelled = false;
    (async () => {
      try {
        const resp = await apiFetch("/api/usage");
        const data = await resp.json();
        if (!cancelled) setUsageData(data);
      } catch { /* silent */ }
    })();
    return () => { cancelled = true; };
  }, [user]);

  const handleAuth = (authUser, authToken) => {
    setUser(authUser);
    setToken(authToken);
  };

  const handleLogout = () => {
    localStorage.removeItem("token");
    clearResumeDraftStorage();
    setUser(null);
    setToken(null);
    setTrackedJobs([]);
    setActiveTab("scraper");
  };

  const handleTrackJob = async (payload) => {
    await apiFetch("/api/tracked", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    await refreshJobs();
  };

  const handleUpdateJob = async (id, updates) => {
    await apiFetch(`/api/tracked/${id}`, {
      method: "PUT",
      body: JSON.stringify(updates),
    });
    await refreshJobs();
  };

  // Loading state
  if (authLoading) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <div className="text-center">
          <Loader2 size={32} className="animate-spin text-indigo-600 mx-auto" />
          <p className="text-sm text-gray-500 mt-3">Loading...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="w-full px-4 sm:px-6 lg:px-10">
        {/* Header */}
        <div className="bg-gradient-to-r from-indigo-600 to-purple-600 text-white px-6 py-5">
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-xl font-bold flex items-center gap-2"><Briefcase size={22} /> Job Hunter SG</h1>
              <p className="text-indigo-100 text-sm mt-1">Search SG jobs, track applications, and get AI-powered resume coaching.</p>
            </div>
            <div className="flex items-center gap-3">
              {user ? (
                <>
                  {usageData && (
                    <div className="bg-white/15 rounded-lg px-3 py-1.5 text-xs text-indigo-100 hidden sm:block">
                      {usageData.tracked_jobs} tracked{usageData.can_export ? " | Pro" : ""}
                    </div>
                  )}
                  <div className="text-right">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium">{user.name}</span>
                      <TierBadge tier={user.tier} />
                    </div>
                    <div className="text-indigo-200 text-xs">{user.email}</div>
                  </div>
                  <button onClick={handleLogout} className="text-indigo-200 hover:text-white transition" title="Sign out">
                    <LogOut size={18} />
                  </button>
                </>
              ) : (
                <button onClick={() => setShowAuthModal(true)}
                  className="bg-white/20 hover:bg-white/30 text-white px-4 py-2 rounded-lg text-sm font-medium transition">
                  Sign In
                </button>
              )}
            </div>
          </div>
        </div>

        {showAuthModal && (
          <AuthModal onAuth={(authUser, authToken) => { handleAuth(authUser, authToken); setShowAuthModal(false); }} onClose={() => setShowAuthModal(false)} />
        )}

        <Nav active={activeTab} setActive={setActiveTab} />

        <div className="p-6">
          {activeTab === "scraper" && (
            <ScraperTab
              user={user}
              trackedJobs={trackedJobs}
              onTrack={handleTrackJob}
              setActiveTab={setActiveTab}
              setSelectedJob={setSelectedJob}
              onSignIn={() => setShowAuthModal(true)}
            />
          )}
          {activeTab === "power" && (
            user ? (
              <PowerTab
                onTrack={handleTrackJob}
                setSelectedJob={setSelectedJob}
                setActiveTab={setActiveTab}
              />
            ) : (
              <AuthPrompt onSignIn={() => setShowAuthModal(true)} featureName="Power Match" />
            )
          )}
          {activeTab === "tracker" && (
            user ? (
              <TrackerTab
                user={user}
                jobs={trackedJobs}
                refreshJobs={refreshJobs}
              />
            ) : (
              <AuthPrompt onSignIn={() => setShowAuthModal(true)} featureName="Application Tracker" />
            )
          )}
          {activeTab === "reminders" && (
            user ? (
              <RemindersTab
                jobs={trackedJobs}
                onUpdateJob={handleUpdateJob}
              />
            ) : (
              <AuthPrompt onSignIn={() => setShowAuthModal(true)} featureName="Follow-up Reminders" />
            )
          )}
          {activeTab === "resume" && <ResumeTab selectedJob={selectedJob} user={user} setActiveTab={setActiveTab} />}
          {activeTab === "account" && (
            user ? (
              <AccountTab user={user} onLogout={handleLogout} />
            ) : (
              <AuthPrompt onSignIn={() => setShowAuthModal(true)} featureName="Account Settings" />
            )
          )}
        </div>
      </div>
    </div>
  );
}
