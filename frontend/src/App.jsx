import { useState, useEffect, useMemo, useCallback, useRef } from "react";
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

const ATS_KEYWORDS_BY_ROLE = {
  "Software Engineer": ["agile", "CI/CD", "microservices", "REST API", "cloud", "AWS", "Docker", "Kubernetes", "Git", "unit testing", "system design", "scalable"],
  "Frontend Developer": ["React", "TypeScript", "JavaScript", "CSS", "responsive design", "accessibility", "performance optimization", "webpack", "testing", "UI/UX"],
  "Full Stack Engineer": ["React", "Node.js", "SQL", "NoSQL", "REST API", "GraphQL", "Docker", "AWS", "agile", "CI/CD", "TypeScript"],
  "Data Analyst": ["SQL", "Python", "Tableau", "Power BI", "Excel", "data visualization", "statistical analysis", "ETL", "data modeling"],
  "Product Manager": ["roadmap", "stakeholder management", "agile", "user research", "metrics", "KPIs", "cross-functional", "prioritization", "A/B testing"],
  "DevOps Engineer": ["AWS", "Docker", "Kubernetes", "CI/CD", "Terraform", "Linux", "monitoring", "Git", "Python", "microservices"],
  default: ["communication", "teamwork", "problem-solving", "leadership", "analytical", "project management", "detail-oriented", "results-driven"],
};

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
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4" onClick={(e) => { if (e.target === e.currentTarget && onClose) onClose(); }}>
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
  const [results, setResults] = useState([]);
  const [loading, setLoading] = useState(false);
  const [levelFilter, setLevelFilter] = useState("all");
  const [employmentFilter, setEmploymentFilter] = useState("all");
  const [sourceFilter, setSourceFilter] = useState("all");
  const [locationFilter, setLocationFilter] = useState("all");
  const [minSalaryFilter, setMinSalaryFilter] = useState("");
  const [sortBy, setSortBy] = useState("relevance");
  const [error, setError] = useState("");
  const [trackError, setTrackError] = useState("");
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [totalLabel, setTotalLabel] = useState("");
  const [expandedJobId, setExpandedJobId] = useState(null);

  // Load cached jobs on mount (browse mode)
  useEffect(() => {
    loadJobs("");
  }, []);

  const loadJobs = async (searchQuery, pageNum = 1, nextFilters = {}) => {
    setLoading(true);
    setError("");
    try {
      const params = new URLSearchParams({ page: String(pageNum), per_page: "20" });
      const activeLevel = nextFilters.levelFilter ?? levelFilter;
      const activeEmployment = nextFilters.employmentFilter ?? employmentFilter;
      const activeSource = nextFilters.sourceFilter ?? sourceFilter;
      const activeLocation = nextFilters.locationFilter ?? locationFilter;
      const activeMinSalary = nextFilters.minSalaryFilter ?? minSalaryFilter;

      if (searchQuery.trim()) params.set("q", searchQuery.trim());
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
      setPage(pageNum);
      setTotalPages(data.pages || 1);
      setExpandedJobId(null);
      const total = data.total || mapped.length;
      setTotalLabel(`${total.toLocaleString()} jobs`);
    } catch (err) {
      setError(err.message || "Failed to load jobs. Please try again.");
      setResults([]);
      setTotalPages(1);
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

  const sourceOptions = useMemo(
    () => [...new Set(results.map((job) => job.source).filter(Boolean))].sort(),
    [results],
  );

  const locationOptions = useMemo(
    () => [...new Set(results.map((job) => job.location).filter(Boolean))].sort().slice(0, 12),
    [results],
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
    loadJobs(query, 1, {
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
          {query ? ` matching "${query}"` : " across Singapore"}
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
                <option value="relevance">Sort: Relevance</option>
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
                loadJobs(query, 1, { levelFilter: value });
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
                loadJobs(query, 1, { employmentFilter: value });
              }}
              className="text-sm border border-gray-200 rounded-xl px-3 py-2.5 bg-white"
            >
              <option value="all">All employment types</option>
              <option value="Full">Full Time</option>
              <option value="Part">Part Time</option>
              <option value="Contract">Contract</option>
              <option value="Temporary">Temporary</option>
              <option value="Intern">Internship</option>
            </select>

            <select
              value={sourceFilter}
              onChange={(e) => {
                const value = e.target.value;
                setSourceFilter(value);
                loadJobs(query, 1, { sourceFilter: value });
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
                loadJobs(query, 1, { locationFilter: value });
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
              onBlur={() => loadJobs(query, 1, { minSalaryFilter })}
              onKeyDown={(e) => {
                if (e.key === "Enter") loadJobs(query, 1, { minSalaryFilter });
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
      {!loading && filtered.map((job) => (
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
                <ChevronRight size={14} className={`ml-auto text-gray-400 transition-transform ${expandedJobId === job.id ? "rotate-90" : ""}`} />
              </div>
              <div className="flex items-center gap-4 text-sm text-gray-500 mb-2 flex-wrap">
                <span className="flex items-center gap-1"><Building2 size={13} />{job.company}</span>
                {job.location && <span className="flex items-center gap-1"><MapPin size={13} />{job.location}</span>}
                {job.salary && <span className="flex items-center gap-1"><DollarSign size={13} />{job.salary}</span>}
              </div>
              {job.description && expandedJobId !== job.id && <p className="text-sm text-gray-600 mb-3 line-clamp-2">{job.description}</p>}
              {job.skills.length > 0 && (
                <div className="flex flex-wrap gap-1.5 mb-3">
                  {job.skills.slice(0, 8).map((s) => (
                    <span key={s} className="bg-indigo-50 text-indigo-700 px-2 py-0.5 rounded-full text-xs">{s}</span>
                  ))}
                  {job.skills.length > 8 && <span className="text-xs text-gray-400">+{job.skills.length - 8} more</span>}
                </div>
              )}
            </div>
          </div>
          {expandedJobId === job.id && (
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

              <div className="mt-4 text-xs font-semibold uppercase tracking-[0.16em] text-gray-500">Required Skills Analysis</div>
              {job.skills.length > 0 ? (
                <>
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {job.skills.map((skill) => (
                      <span key={skill} className="rounded-full bg-white px-2 py-0.5 text-xs font-medium text-gray-700 ring-1 ring-gray-200">
                        {skill}
                      </span>
                    ))}
                  </div>
                  <div className="mt-3 text-xs text-gray-500">
                    We captured {job.skills.length} structured skill cue{job.skills.length === 1 ? "" : "s"} from this listing.
                  </div>
                </>
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
      ))}

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex justify-center gap-3">
          {page > 1 && (
            <button onClick={() => loadJobs(query, page - 1)} className="px-4 py-2 text-sm border border-gray-200 rounded-lg hover:bg-gray-50">Previous</button>
          )}
          <span className="px-4 py-2 text-sm text-gray-500">Page {page} of {totalPages}</span>
          {page < totalPages && (
            <button onClick={() => loadJobs(query, page + 1)} className="px-4 py-2 text-sm border border-gray-200 rounded-lg hover:bg-gray-50">Next</button>
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
  },
  {
    id: "modern",
    name: "Modern",
    description: "Sharper hierarchy for technical and startup roles.",
  },
  {
    id: "singapore",
    name: "SG Pro",
    description: "Polished local-market style with balanced spacing.",
  },
  {
    id: "compact",
    name: "Compact",
    description: "Tighter layout for experienced candidates.",
  },
];

const RESUME_TEMPLATE_STYLES = {
  classic: {
    pageClass: "text-stone-800",
    pageStyle: {
      fontFamily: 'Georgia, "Times New Roman", serif',
      fontSize: "11pt",
      padding: "25.4mm",
      width: "210mm",
      minHeight: "297mm",
      maxWidth: "100%",
      lineHeight: "1.35",
    },
    headingClass: "mt-4 mb-1 border-b border-stone-400 pb-1 text-[11pt] font-bold uppercase tracking-[0.18em] text-stone-900",
    nameClass: "text-[16pt] font-bold tracking-[0.08em] text-stone-950",
    subheadingClass: "mt-2 mb-0.5 text-stone-700",
    bodyStyle: { fontSize: "1em", lineHeight: "1.35" },
  },
  modern: {
    pageClass: "text-slate-800",
    pageStyle: {
      fontFamily: 'Calibri, "Segoe UI", sans-serif',
      fontSize: "10pt",
      padding: "15.2mm",
      width: "210mm",
      minHeight: "297mm",
      maxWidth: "100%",
      lineHeight: "1.33",
    },
    headingClass: "mt-4 mb-1 border-l-4 border-indigo-500 pl-3 text-[11pt] font-bold uppercase tracking-[0.18em] text-slate-900",
    nameClass: "text-[15pt] font-semibold tracking-[0.04em] text-slate-950",
    subheadingClass: "mt-2 mb-0.5 text-slate-700",
    bodyStyle: { fontSize: "1em", lineHeight: "1.33" },
  },
  singapore: {
    pageClass: "text-slate-800",
    pageStyle: {
      fontFamily: 'Calibri, "Segoe UI", sans-serif',
      fontSize: "11pt",
      padding: "20.3mm",
      width: "210mm",
      minHeight: "297mm",
      maxWidth: "100%",
      lineHeight: "1.35",
    },
    headingClass: "mt-4 mb-1 border-b-2 border-slate-700 pb-1 text-[11pt] font-bold uppercase tracking-[0.16em] text-slate-950",
    nameClass: "text-[15pt] font-semibold tracking-[0.04em] text-slate-950",
    subheadingClass: "mt-2 mb-0.5 text-slate-700",
    bodyStyle: { fontSize: "1em", lineHeight: "1.35" },
  },
  compact: {
    pageClass: "text-zinc-800",
    pageStyle: {
      fontFamily: "Arial, Helvetica, sans-serif",
      fontSize: "10pt",
      padding: "12.7mm",
      width: "210mm",
      minHeight: "297mm",
      maxWidth: "100%",
      lineHeight: "1.3",
    },
    headingClass: "mt-4 mb-1 text-[0.92rem] font-bold uppercase tracking-[0.14em] text-zinc-950",
    nameClass: "text-[14pt] font-bold tracking-[0.03em] text-zinc-950",
    subheadingClass: "mt-2 mb-0.5 text-zinc-700",
    bodyStyle: { fontSize: "1em", lineHeight: "1.3" },
  },
};

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
  "experience",
  "professional experience",
  "work experience",
  "education",
  "skills",
  "technical skills",
  "core competencies",
  "projects",
  "leadership",
  "activities",
  "certifications",
  "awards",
  "volunteer",
  "interests",
  "languages",
]);

const RESUME_ACTION_VERBS = new Set([
  "achieved", "analyzed", "architected", "automated", "built", "championed",
  "collaborated", "created", "defined", "delivered", "deployed", "designed",
  "developed", "drove", "enabled", "engineered", "enhanced", "established",
  "executed", "expanded", "facilitated", "generated", "guided", "identified",
  "implemented", "improved", "increased", "initiated", "integrated", "launched",
  "led", "leveraged", "managed", "mapped", "mentored", "modernized",
  "optimized", "orchestrated", "organized", "partnered", "piloted", "planned",
  "presented", "prioritized", "produced", "proposed", "redesigned", "reduced",
  "refined", "restructured", "revamped", "scaled", "simplified", "solved",
  "spearheaded", "streamlined", "strengthened", "supervised", "supported",
  "tested", "trained", "transformed", "upgraded",
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
const RESUME_BULLET_RE = /^(\s*(?:[-*\u2022\u2023\u25E6\u2043\u2219]|\d+[.)]))\s*(.*)$/;
const RESUME_METRIC_RE = /\d+%|\$[\d,]+|\d+\s*(?:users|user|team|people|projects|systems|clients|hours|weeks|months|years)|\d+[kKmMbB]\b|\d{1,3}(?:,\d{3})+/;
const RESUME_DATE_HINT_RE = /\b(?:19|20)\d{2}\b|present|current|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec/i;

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function titleCase(value) {
  return value
    .replace(/_/g, " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());
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
    .map((item) => String(item || "").trim())
    .filter((item) => item.length >= 3)
  )];
}

function isHeadingLine(line) {
  const trimmed = line.trim();
  if (!trimmed) return false;
  const lowered = trimmed.toLowerCase().replace(/:$/, "");
  if (RESUME_HEADINGS.has(lowered)) return true;
  return (
    trimmed === trimmed.toUpperCase()
    && /[A-Z]/.test(trimmed)
    && trimmed.split(/\s+/).length <= 5
  );
}

function parseSubheadingParts(line) {
  const trimmed = line.trim();
  if (!trimmed || !RESUME_DATE_HINT_RE.test(trimmed)) return null;

  if (trimmed.includes("|")) {
    const parts = trimmed.split("|").map((part) => part.trim()).filter(Boolean);
    if (parts.length >= 2) {
      const right = parts.pop();
      return { left: parts.join(" | "), right };
    }
  }

  const dashMatch = trimmed.match(/^(.*?)(?:\s+[–—-]\s+)(.*(?:\d{4}|Present|Current).*)$/i);
  if (dashMatch) {
    return { left: dashMatch[1].trim(), right: dashMatch[2].trim() };
  }

  return null;
}

function annotateBullet(text, keywords) {
  const trimmed = text.trim();
  const lowered = trimmed.toLowerCase();
  const firstWord = trimmed.split(/\s+/)[0]?.toLowerCase().replace(/[,:;.]$/, "") || "";
  const hasMetric = RESUME_METRIC_RE.test(trimmed);
  const weakStart = RESUME_WEAK_STARTS.find((phrase) => lowered.startsWith(phrase));
  const keywordMatches = collectKeywordMatches(trimmed, keywords);
  const isTooShort = trimmed.length < 40;
  const isTooLong = trimmed.length > 200;
  // Handle hyphenated verbs: "Co-led" → check "co-led" AND "led"
  const baseVerb = firstWord.includes("-") ? firstWord.split("-").pop() : firstWord;
  const hasActionVerb = RESUME_ACTION_VERBS.has(firstWord) || RESUME_ACTION_VERBS.has(baseVerb);

  // Skip annotation for certifications, education entries, and short labels
  const looksLikeCert = /certification|certifications|certificate|certified|pmp|wsq|skillsfuture|accredited|in progress|target|gmat|upskilling/i.test(lowered);
  const looksLikeEducation = /university|polytechnic|gpa|degree|diploma|bachelor|master|phd|exchange|graduated|major|minor|focus|capstone/i.test(lowered);
  if (looksLikeCert || looksLikeEducation) {
    return null;
  }

  if (weakStart || isTooShort || isTooLong) {
    let message = "Tighten this bullet so the impact is clearer.";
    if (weakStart) message = `Replace "${weakStart}" with a stronger verb.`;
    if (isTooShort) message = "Add more outcome detail so this bullet feels complete.";
    if (isTooLong) message = "Split or tighten this bullet so the result lands faster.";
    return {
      tone: "amber",
      label: "Review Bullet",
      icon: <AlertCircle size={14} />,
      borderClass: "border-amber-300 bg-amber-50/70",
      pillClass: "bg-amber-100 text-amber-800",
      message,
      keywordMatches,
    };
  }

  if (!hasActionVerb) {
    return {
      tone: "rose",
      label: "Review Opening",
      icon: <X size={14} />,
      borderClass: "border-rose-300 bg-rose-50/70",
      pillClass: "bg-rose-100 text-rose-800",
      message: "Start with a stronger action verb to make the outcome scan faster.",
      keywordMatches,
    };
  }

  return {
    tone: "emerald",
    label: hasMetric ? "Solid Impact" : "Good Start",
    icon: <CheckCircle size={14} />,
    borderClass: "border-emerald-300 bg-emerald-50/70",
    pillClass: "bg-emerald-100 text-emerald-800",
    message: hasMetric
      ? "This bullet already shows measurable impact."
      : "This bullet starts well. Add a metric if you have one.",
    keywordMatches,
  };
}

function parseResumeToSections(text, keywords) {
  return text.replace(/\r\n?/g, "\n").split("\n").map((line, lineIndex) => {
    const trimmed = line.trim();
    const base = {
      id: `line-${lineIndex}`,
      lineIndex,
      raw: line,
      text: trimmed,
    };

    if (!trimmed) {
      return { ...base, type: "spacer" };
    }

    const bulletMatch = line.match(RESUME_BULLET_RE);
    if (bulletMatch) {
      const textValue = bulletMatch[2].trim();
      return {
        ...base,
        type: "bullet",
        marker: bulletMatch[1].trim(),
        text: textValue,
        annotation: annotateBullet(textValue, keywords),
      };
    }

    if (isHeadingLine(trimmed)) {
      return { ...base, type: "heading", keywordMatches: collectKeywordMatches(trimmed, keywords) };
    }

    const subheadingParts = parseSubheadingParts(trimmed);
    if (subheadingParts) {
      return {
        ...base,
        type: "subheading",
        ...subheadingParts,
        keywordMatches: collectKeywordMatches(trimmed, keywords),
      };
    }

    return {
      ...base,
      type: "paragraph",
      keywordMatches: collectKeywordMatches(trimmed, keywords),
    };
  });
}

function extractResumeHeaderLines(text) {
  const lines = text.replace(/\r\n?/g, "\n").split("\n");
  const headerLines = [];
  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed) {
      if (headerLines.length > 0) break;
      continue;
    }
    if (isHeadingLine(trimmed)) break;
    if (RESUME_BULLET_RE.test(line)) break;
    headerLines.push(trimmed);
    if (headerLines.length >= 4) break;
  }
  return headerLines;
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

  if (section.type === "bullet") {
    lines[section.lineIndex] = cleanValue ? `${section.marker || "•"} ${cleanValue}` : "";
    return lines.join("\n");
  }

  lines[section.lineIndex] = cleanValue;
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

function getBulletFeedbackTabs(section, resumeText) {
  if (!section?.text || !section.annotation) return [];

  const text = section.text.trim();
  const lower = text.toLowerCase();
  const firstWord = text.split(/\s+/)[0]?.toLowerCase().replace(/[,:;.]$/, "") || "";
  const hasActionVerb = RESUME_ACTION_VERBS.has(firstWord);
  const metricMatches = text.match(/\d+%|\$[\d,]+|\d+\s*(?:users|user|team|people|projects|systems|clients|hours|weeks|months|years)|\d+[kKmMbB]\b|\d{1,3}(?:,\d{3})+/g) || [];
  const wordCounts = getWordCounts(resumeText);
  const overusedWords = [...new Set(
    (lower.match(/[a-z][a-z-]*/g) || []).filter((word) => word.length > 4 && (wordCounts[word] || 0) >= 3),
  )].slice(0, 4);
  const avoidedMatches = RESUME_AVOIDED_PHRASES.filter((phrase) => lower.includes(phrase));
  const bulletLengthChars = text.length;
  const bulletLengthWords = text.split(/\s+/).filter(Boolean).length;
  const lengthGood = bulletLengthChars >= 40 && bulletLengthChars <= 200;

  return [
    {
      id: "action_oriented",
      title: "Action Oriented",
      status: hasActionVerb ? "good" : "issue",
      summary: hasActionVerb
        ? `This bullet already opens with "${text.split(/\s+/)[0]}," which gives it momentum.`
        : "This bullet would read stronger if it opened with a clearer action verb.",
      chips: hasActionVerb
        ? [text.split(/\s+/)[0]]
        : BULLET_ACTION_SUGGESTIONS,
      tip: hasActionVerb
        ? "Keep the opening verb, then tighten the rest around the outcome."
        : "Try replacing the opening with a sharper verb that signals what you actually drove or delivered.",
    },
    {
      id: "specifics",
      title: "Specifics",
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
      status: overusedWords.length > 0 || avoidedMatches.length > 0 ? "issue" : "good",
      summary: overusedWords.length > 0 || avoidedMatches.length > 0
        ? "A few repeated or filler terms are diluting the impact of this bullet."
        : "This bullet avoids the most obvious filler phrasing.",
      chips: [...avoidedMatches, ...overusedWords].slice(0, 5),
      tip: overusedWords.length > 0 || avoidedMatches.length > 0
        ? "Swap repeated terms for more specific language, and remove filler phrases unless they add real meaning."
        : "Keep favoring concrete nouns and verbs over generic phrasing.",
    },
    {
      id: "bullet_length",
      title: "Bullet Length",
      status: lengthGood ? "good" : "issue",
      summary: lengthGood
        ? "This bullet sits in a healthy length range for scanability."
        : bulletLengthChars < 40
          ? "This bullet is too short to communicate real scope."
          : "This bullet is getting long and may be harder to scan quickly.",
      chips: [`${bulletLengthWords} words`, `${bulletLengthChars} chars`],
      tip: lengthGood
        ? "Aim to keep most bullets at roughly one to two lines in the final document."
        : bulletLengthChars < 40
          ? "Add the outcome, scale, or context so the reader understands why the work mattered."
          : "Split the detail or trim supporting clauses so the strongest result lands earlier.",
    },
  ];
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

function ResumeTab({ selectedJob, user }) {
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
  const [rewriteResults, setRewriteResults] = useState({});
  const [rewriteLoading, setRewriteLoading] = useState({});
  const [downloading, setDownloading] = useState(false);
  const [downloadError, setDownloadError] = useState("");
  const [showSetupPanel, setShowSetupPanel] = useState(() => !resumeText.trim());
  const [workspaceView, setWorkspaceView] = useState("feedback");
  const [mobilePanel, setMobilePanel] = useState("edit");
  const [selectedBulletId, setSelectedBulletId] = useState(null);
  const [editingNodeId, setEditingNodeId] = useState(null);
  const [editingValue, setEditingValue] = useState("");
  const [annotationsOn, setAnnotationsOn] = useState(true);
  const [selectedBulletTab, setSelectedBulletTab] = useState("action_oriented");
  const [scoreChange, setScoreChange] = useState(null);
  const [error, setError] = useState("");

  const fileInputRef = useRef(null);
  const scorePanelRef = useRef(null);
  const selectedFeedbackRef = useRef(null);
  const initialScoredRef = useRef(false);
  const previousJobDescriptionRef = useRef("");

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

  const jobDescription = useMemo(() => {
    if (!selectedJob) return "";
    const parts = [`${selectedJob.title} at ${selectedJob.company}`];
    if (selectedJob.skills?.length) parts.push(`Required skills: ${selectedJob.skills.join(", ")}`);
    if (selectedJob.description) parts.push(selectedJob.description);
    return parts.join(". ");
  }, [selectedJob]);

  const scoreFallback = useCallback((text, jd) => {
    const resumeLower = text.toLowerCase();
    let keywords;

    if (jd.trim()) {
      const techTerms = [
        "react", "typescript", "javascript", "python", "java", "sql", "nosql", "aws", "docker",
        "kubernetes", "ci/cd", "agile", "scrum", "rest api", "graphql", "node.js", "git", "linux",
        "terraform", "microservices", "cloud", "machine learning", "data analysis", "tableau",
        "power bi", "excel", "figma", "css", "html", "webpack", "testing", "unit testing",
        "system design", "scalable", "performance optimization", "responsive design", "accessibility",
      ];
      const jdLower = jd.toLowerCase();
      keywords = techTerms.filter((term) => jdLower.includes(term));
      const customTerms = jd.match(/[A-Z][a-zA-Z.+#]+/g) || [];
      customTerms.forEach((term) => {
        if (term.length > 2 && !keywords.includes(term.toLowerCase())) keywords.push(term);
      });
      if (keywords.length < 5) keywords = [...keywords, ...ATS_KEYWORDS_BY_ROLE["Software Engineer"]];
      keywords = [...new Set(keywords)];
    } else {
      keywords = ATS_KEYWORDS_BY_ROLE.default;
    }

    const matched = keywords.filter((keyword) => resumeLower.includes(keyword.toLowerCase()));
    const missing = keywords.filter((keyword) => !resumeLower.includes(keyword.toLowerCase()));
    const score = keywords.length > 0 ? Math.round((matched.length / keywords.length) * 100) : 0;
    const tips = [];

    if (resumeLower.length < 500) tips.push("Resume seems short. Aim for 400-700 words.");
    if (!/\d{4}/.test(resumeLower)) tips.push("Include clear dates for work and education.");
    if (!/\d+%/.test(resumeLower)) tips.push("Add quantifiable achievements where you can.");
    if (!/(bachelor|master|diploma|degree|certification|certified)/.test(resumeLower)) tips.push("Call out education and certifications more clearly.");
    if (!/(singapore|sg|citizen|pr|permanent resident)/.test(resumeLower)) tips.push("Mention residency status if it helps in the Singapore market.");

    return normalizeScoreData({
      fallback: true,
      overall_score: score,
      dimensions: {},
      keyword_match: { matched, missing },
      top_suggestions: tips.map((detail) => ({ action: "Improve Resume", detail, points: 3 })),
      sg_tips: [],
    });
  }, []);

  const runScore = useCallback(async (text, jd = jobDescription, { phase = "opening" } = {}) => {
    if (!text.trim() || text.trim().length < 50) {
      setScoreData(null);
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
    } catch {
      const fallback = scoreFallback(text, jd);
      setScoreData(fallback);
      setScoreError("Detailed scoring is temporarily unavailable. Showing a lighter analysis instead.");
      setNeedsRescore(false);
      setScorePhase(phase === "final" ? "final_complete" : "opening_scored");
      return fallback;
    } finally {
      setScoring(false);
    }
  }, [jobDescription, scoreFallback]);

  useEffect(() => {
    if (!initialScoredRef.current && resumeText.trim().length >= 50) {
      initialScoredRef.current = true;
      runScore(resumeText, jobDescription, { phase: "opening" });
    }
  }, [resumeText, jobDescription, runScore]);

  const resumeKeywords = useMemo(
    () => buildResumeKeywords(selectedJob, scoreData),
    [selectedJob, scoreData],
  );

  const parsedSections = useMemo(
    () => parseResumeToSections(resumeText, resumeKeywords),
    [resumeText, resumeKeywords],
  );

  const bulletSections = useMemo(
    () => parsedSections.filter((section) => section.type === "bullet"),
    [parsedSections],
  );

  const selectedBullet = useMemo(
    () => bulletSections.find((section) => section.id === selectedBulletId) || null,
    [bulletSections, selectedBulletId],
  );

  useEffect(() => {
    if (selectedBulletId && !bulletSections.some((section) => section.id === selectedBulletId)) {
      setSelectedBulletId(null);
    }
  }, [bulletSections, selectedBulletId]);

  useEffect(() => {
    if (selectedBullet && selectedFeedbackRef.current) {
      selectedFeedbackRef.current.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }
  }, [selectedBullet]);

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

  const applyResumeText = useCallback((nextText, { rescore = false, clearRewrites = false } = {}) => {
    setResumeText(nextText);
    setScoreChange(null);
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
      if (typeof window !== "undefined" && window.innerWidth < 1024) {
        setMobilePanel("feedback");
      }
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

    try {
      const response = await apiFetch("/api/resume/format", {
        method: "POST",
        body: JSON.stringify({ resume_text: resumeText, job_description: jobDescription }),
      });
      const data = await response.json();
      if (data.formatted_resume) {
        const previousScore = scoreData?.overall_score;
        setSelectedBulletId(null);
        setEditingNodeId(null);
        applyResumeText(data.formatted_resume, { clearRewrites: true });
        const rescored = await runScore(data.formatted_resume, jobDescription, { phase: "opening" });
        if (Number.isFinite(previousScore) && Number.isFinite(rescored?.overall_score)) {
          setScoreChange({ before: previousScore, after: rescored.overall_score, context: "Updated after AI Improve All" });
        }
      }
    } catch (err) {
      setFormatError(
        err.message?.includes("429")
          ? "You’ve hit today’s AI formatting limit."
          : "Formatting failed. Please try again.",
      );
    } finally {
      setFormatting(false);
    }
  };

  const handleBulletRewrite = async (section) => {
    if (!section?.text) return;

    setRewriteLoading((current) => ({ ...current, [section.id]: true }));
    setCoachError("");
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
          session_id: sessionId,
          used_verbs: usedVerbs,
        }),
      });
      const data = await response.json();
      if (!data || typeof data.original !== "string" || !Array.isArray(data.options)) {
        throw new Error("Rewrite response was malformed.");
      }
      setRewriteResults((current) => ({ ...current, [section.id]: data }));
      if (typeof window !== "undefined" && window.innerWidth < 1024) {
        setMobilePanel("feedback");
      }
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

  const handleDownload = async () => {
    if (!resumeText.trim()) return;

    setDownloading(true);
    setDownloadError("");

    try {
      if (needsRescore) {
        await runScore(resumeText, jobDescription, { phase: "final" });
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
    setMobilePanel("feedback");
    scorePanelRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  const openEditorForSection = (section) => {
    setEditingNodeId(section.id);
    setEditingValue(section.text);
    if (section.type === "bullet") setSelectedBulletId(section.id);
  };

  const commitEdit = (section) => {
    if (!section) return;
    if (editingNodeId !== section.id) return;

    const nextText = updateResumeLine(resumeText, section, editingValue);
    setEditingNodeId(null);
    setEditingValue("");
    applyResumeText(nextText);
  };

  const templateMeta = templates.find((template) => template.id === selectedTemplate) || DEFAULT_RESUME_TEMPLATES.find((template) => template.id === selectedTemplate) || DEFAULT_RESUME_TEMPLATES[1];
  const templateStyles = RESUME_TEMPLATE_STYLES[selectedTemplate] || RESUME_TEMPLATE_STYLES.modern;
  const wordCount = resumeText.split(/\s+/).filter(Boolean).length;
  const overallScore = scoreData?.overall_score || 0;
  const scoreTheme = getScoreTheme(overallScore);
  const matchedKeywords = scoreData?.keyword_match?.matched || [];
  const missingKeywords = scoreData?.keyword_match?.missing || [];
  const selectedRewrite = selectedBullet ? rewriteResults[selectedBullet.id] : null;
  const selectedBulletTabs = useMemo(
    () => getBulletFeedbackTabs(selectedBullet, resumeText),
    [selectedBullet, resumeText],
  );
  const activeBulletTab = selectedBulletTabs.find((tab) => tab.id === selectedBulletTab) || selectedBulletTabs[0] || null;
  const inferredHeaderLines = useMemo(() => extractResumeHeaderLines(resumeText), [resumeText]);
  const shouldInjectProfileHeader = inferredHeaderLines.length === 0 && (profile.name || profile.email || profile.phone || profile.location);
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
      return RESUME_ACTION_VERBS.has(firstWord);
    }).length;

    return [
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
        label: "Action openings",
        current: String(actionOpenings),
        target: "16+",
        status: actionOpenings >= Math.min(Math.max(bulletSections.length - 2, 0), 16) ? "good" : "review",
        note: actionOpenings < Math.min(Math.max(bulletSections.length - 2, 0), 16) ? "More bullets can open stronger." : "Strong action language coverage.",
      },
    ];
  }, [bulletSections, parsedSections, wordCount]);
  const issueBulletCount = bulletSections.filter((section) => section.annotation?.tone && section.annotation.tone !== "emerald").length;
  const improvementCount = issueBulletCount + (scoreData?.top_suggestions?.length || 0) + Math.min(missingKeywords.length, 6);
  const isFeedbackView = workspaceView === "feedback";
  const isEditorView = workspaceView === "editor";
  const lowScoreWarning = scoreData && overallScore < 50;
  const setupVisible = showSetupPanel || !resumeText.trim();
  const scorePhaseLabel = scorePhase === "final_complete"
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
    applyResumeText(nextText);
  }, [applyResumeText, resumeText]);

  const handleDeleteSection = useCallback((section) => {
    if (!section) return;
    const nextText = removeResumeLine(resumeText, section);
    setEditingNodeId(null);
    setEditingValue("");
    if (selectedBulletId === section.id) setSelectedBulletId(null);
    applyResumeText(nextText);
  }, [applyResumeText, resumeText, selectedBulletId]);

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
            <div className="rounded-2xl border border-indigo-200 bg-indigo-50 px-4 py-3 shadow-sm">
              <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-indigo-600">Targeting</div>
              <div className="mt-1 font-semibold text-slate-900">{selectedJob.title} @ {selectedJob.company}</div>
              {selectedJob.skills?.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {selectedJob.skills.slice(0, 8).map((skill) => (
                    <span key={skill} className="rounded-full bg-indigo-100 px-2 py-0.5 text-[11px] font-medium text-indigo-700">
                      {skill}
                    </span>
                  ))}
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
              <span className={`inline-flex h-8 min-w-8 items-center justify-center rounded-xl px-2 text-base font-bold ${scoreTheme.pill}`}>
                {scoreData ? overallScore : "--"}
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
                <div className="text-xs">{issueBulletCount} bullet issues, {missingKeywords.length} missing keywords</div>
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
            onClick={() => setMobilePanel("feedback")}
            className={`rounded-xl px-4 py-2 text-sm font-medium transition ${mobilePanel === "feedback" ? "bg-gray-900 text-white" : "text-gray-600"}`}
          >
            Feedback
          </button>
        </div>
      </div>

      <div className={`grid gap-6 ${isEditorView ? "lg:grid-cols-[minmax(0,65%)_minmax(320px,35%)]" : "lg:grid-cols-[minmax(320px,35%)_minmax(0,65%)]"}`}>
        <aside className={`${mobilePanel === "feedback" ? "block" : "hidden"} space-y-4 ${isEditorView ? "lg:order-2" : "lg:order-1"} lg:block lg:sticky lg:top-16 lg:self-start lg:max-h-[calc(100vh-5rem)] lg:overflow-y-auto`}>
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
                <div className={`mt-2 text-4xl font-bold ${scoreTheme.text}`}>
                  {scoring ? "..." : overallScore}
                  <span className="ml-1 text-base font-medium text-gray-400">/100</span>
                </div>
                <div className="mt-1 text-sm text-gray-600">
                  {scoreData ? "Guidance snapshot based on structure, phrasing, and evidence cues." : "Upload or paste a resume to begin"}
                </div>
              </div>
              {scoring && <Loader2 size={18} className="animate-spin text-indigo-500" />}
            </div>
            <div className="mt-4 h-2.5 overflow-hidden rounded-full bg-white/80">
              <div className={`h-full rounded-full transition-all ${scoreTheme.bar}`} style={{ width: `${scoreData ? overallScore : 0}%` }} />
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

          {isFeedbackView && scoreData && Object.keys(scoreData.dimensions || {}).length > 0 && (
            <div className="space-y-3">
              {Object.entries(scoreData.dimensions).map(([name, dimension]) => {
                const statusMeta = getStatusMeta(dimension.score, dimension.max);
                return (
                  <details key={name} open className="overflow-hidden rounded-3xl border border-gray-200 bg-white shadow-sm">
                    <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-5 py-4">
                      <div>
                        <div className="text-sm font-semibold text-gray-800">{titleCase(name)}</div>
                        <div className="text-xs text-gray-500">{dimension.score}/{dimension.max}</div>
                      </div>
                      <span className={`inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-xs font-semibold ${statusMeta.className}`}>
                        {statusMeta.icon}
                        {statusMeta.label}
                      </span>
                    </summary>
                    <div className="border-t border-gray-100 px-5 py-4">
                      <div className="mb-4 h-2 overflow-hidden rounded-full bg-gray-100">
                        <div
                          className={`h-full rounded-full ${getScoreTheme(Math.round((dimension.score / dimension.max) * 100)).bar}`}
                          style={{ width: `${dimension.max > 0 ? (dimension.score / dimension.max) * 100 : 0}%` }}
                        />
                      </div>
                      <div className="space-y-3">
                        {Object.entries(dimension.items || {}).map(([itemName, item]) => {
                          const itemStatus = getStatusMeta(item.score, item.max);
                          return (
                            <div key={itemName} className="rounded-2xl bg-gray-50 p-3">
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
                            </div>
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
              {selectedBullet?.annotation && (
                <span className={`inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-xs font-semibold ${selectedBullet.annotation.pillClass}`}>
                  {selectedBullet.annotation.icon}
                  {selectedBullet.annotation.label}
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
                          : selected
                            ? "border-rose-200 bg-rose-50 text-rose-800"
                            : "border-gray-200 bg-white text-gray-700";

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
                                    : "bg-gray-100 text-gray-700"
                                }`}
                              >
                                {chip}
                              </span>
                            ))}
                          </div>
                        )}

                        <div className="mt-4 rounded-2xl bg-gray-50 px-3 py-3 text-sm leading-relaxed text-gray-600">
                          {activeBulletTab.tip}
                        </div>

                        {selectedBullet.annotation.keywordMatches?.length > 0 && (
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
                  onClick={() => handleBulletRewrite(selectedBullet)}
                  disabled={rewriteLoading[selectedBullet.id]}
                  className="inline-flex w-full items-center justify-center gap-2 rounded-2xl bg-gray-900 px-4 py-2.5 text-sm font-medium text-white transition hover:bg-black disabled:opacity-50"
                >
                  {rewriteLoading[selectedBullet.id] ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />}
                  {rewriteLoading[selectedBullet.id] ? "Rewriting..." : "AI Rewrite This Bullet"}
                </button>
                <div className="rounded-2xl bg-gray-50 px-3 py-3 text-xs leading-relaxed text-gray-600">
                  Keep only claims, numbers, and scope that you can defend in interview. Treat rewrites as drafting help, not fact generation.
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
                            <div key={`${selectedBullet.id}-rewrite-${optionIndex}`} className="rounded-xl border border-gray-200 bg-gray-50 p-3">
                              <div className="text-[11px] font-semibold uppercase tracking-[0.16em] text-gray-500">Option {optionIndex + 1}</div>
                              <div className="mt-2 text-sm leading-relaxed text-gray-700">{option}</div>
                              <button
                                type="button"
                                onClick={() => acceptRewrite(selectedBullet, optionIndex)}
                                className="mt-3 inline-flex items-center gap-2 rounded-xl bg-indigo-600 px-3 py-2 text-sm font-medium text-white hover:bg-indigo-700"
                              >
                                <CheckCircle size={14} />
                                Use Option {optionIndex + 1}
                              </button>
                            </div>
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

          {isFeedbackView && (
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

          {isFeedbackView && (
          <div className="rounded-3xl border border-gray-200 bg-white p-5 shadow-sm">
            <div className="text-sm font-semibold text-gray-800">Relevant Terms</div>
            {scoreData ? (
              <>
                <div className="mt-2 text-sm text-gray-600">
                  Matched {matchedKeywords.length} term{matchedKeywords.length === 1 ? "" : "s"}{matchedKeywords.length + missingKeywords.length > 0 ? ` of ${matchedKeywords.length + missingKeywords.length}` : ""}.
                </div>
                <div className="mt-2 text-xs leading-relaxed text-gray-500">
                  Use these as alignment cues, not as a keyword-stuffing checklist.
                </div>
                {matchedKeywords.length > 0 && (
                  <div className="mt-3 flex flex-wrap gap-1.5">
                    {matchedKeywords.map((keyword) => (
                      <span key={keyword} className="rounded-full bg-emerald-100 px-2 py-0.5 text-[11px] font-medium text-emerald-700">
                        {keyword}
                      </span>
                    ))}
                  </div>
                )}
                {missingKeywords.length > 0 && (
                  <>
                    <div className="mt-4 text-xs font-semibold uppercase tracking-[0.16em] text-gray-500">Missing</div>
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      {missingKeywords.slice(0, 12).map((keyword) => (
                        <span key={keyword} className="rounded-full bg-rose-100 px-2 py-0.5 text-[11px] font-medium text-rose-700">
                          {keyword}
                        </span>
                      ))}
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
            {aiStatus && (
              <div className="mt-4 inline-flex items-center gap-2 rounded-full bg-gray-100 px-3 py-1 text-xs font-medium text-gray-600">
                <span className={`inline-block h-2 w-2 rounded-full ${aiStatus.status === "ready" ? "bg-emerald-500" : aiStatus.status === "busy" ? "bg-amber-500" : "bg-rose-500"}`} />
                {aiStatus.status === "ready" ? "AI ready" : aiStatus.status === "busy" ? "AI busy" : `Wait about ${Math.round(aiStatus.wait_seconds || 0)}s`}
              </div>
            )}
          </div>

          {isFeedbackView && (
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
                  className={`inline-flex items-center gap-2 rounded-full px-3 py-1.5 text-xs font-semibold ${scoreTheme.pill}`}
                >
                  <Star size={12} />
                  Score {scoreData ? overallScore : "--"}
                </button>
              </div>
            </div>

            <div
              className={`mx-auto mt-5 bg-white shadow-[0_2px_20px_rgba(0,0,0,0.1)] border border-gray-200 ${templateStyles.pageClass}`}
              style={{ ...templateStyles.pageStyle, textAlign: "justify", textJustify: "inter-word" }}
            >
              {resumeText.trim() ? (
                <>
                  {shouldInjectProfileHeader && (
                    <div className="mb-3 pb-2 text-center">
                      {profile.name && <div className={templateStyles.nameClass}>{profile.name}</div>}
                      <div className="mt-0.5 text-[9pt] text-gray-600">
                        {[profile.email, profile.phone, profile.location].filter(Boolean).join(" | ")}
                      </div>
                    </div>
                  )}

                  <div className="space-y-0.5" style={templateStyles.bodyStyle}>
                    {parsedSections.map((section) => {
                      if (section.type === "spacer") return <div key={section.id} className="h-3" />;

                      const isEditing = editingNodeId === section.id;
                      const isSelectedBullet = selectedBulletId === section.id;
                      const annotation = section.annotation;
                      const wrapperClasses = section.type === "bullet" && annotationsOn
                        ? `${annotation?.borderClass || "border-transparent bg-transparent"} border-l-[3px]`
                        : isSelectedBullet
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
                        />
                      ) : (
                        <button
                          type="button"
                          onClick={() => openEditorForSection(section)}
                          className="w-full text-left"
                        >
                          {section.type === "heading" && (
                            <h3 className={templateStyles.headingClass}>
                              {renderHighlightedText(section.text, section.keywordMatches || [])}
                            </h3>
                          )}
                          {section.type === "subheading" && (
                            <div className={`flex flex-col gap-1 sm:flex-row sm:items-baseline sm:justify-between ${templateStyles.subheadingClass}`}>
                              <div className="font-semibold text-gray-900">{renderHighlightedText(section.left, section.keywordMatches || [])}</div>
                              <div className="text-sm text-gray-500">{section.right}</div>
                            </div>
                          )}
                          {section.type === "paragraph" && (
                            <p className="mb-4 text-gray-700" style={templateStyles.bodyStyle}>
                              {renderHighlightedText(section.text, section.keywordMatches || [])}
                            </p>
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
            className={`inline-flex items-center gap-2 rounded-full px-3 py-2 text-sm font-semibold ${scoreTheme.pill}`}
          >
            <Star size={14} />
            Score {scoreData ? overallScore : "--"}
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
          {activeTab === "resume" && <ResumeTab selectedJob={selectedJob} user={user} />}
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
