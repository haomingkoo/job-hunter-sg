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

async function apiFetch(path, options = {}) {
  const token = localStorage.getItem("token");
  const headers = { "Content-Type": "application/json", ...options.headers };
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const resp = await fetch(`${API_BASE}${path}`, { ...options, headers });
  if (resp.status === 401) {
    localStorage.removeItem("token");
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
            {mode === "login" ? "Sign in with your @aisg.sg email" : "Create account with @aisg.sg email"}
          </p>
          <p className="text-xs text-gray-400 mt-1">Sign in to save your applications and get unlimited AI reviews</p>
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
  const [sortBy, setSortBy] = useState("relevance");
  const [error, setError] = useState("");
  const [trackError, setTrackError] = useState("");
  const [page, setPage] = useState(1);
  const [totalLabel, setTotalLabel] = useState("");

  // Load cached jobs on mount (browse mode)
  useEffect(() => {
    loadJobs("");
  }, []);

  const loadJobs = async (searchQuery, pageNum = 1) => {
    setLoading(true);
    setError("");
    try {
      const params = new URLSearchParams({ page: String(pageNum), per_page: "20" });
      if (searchQuery.trim()) params.set("q", searchQuery.trim());

      const resp = await apiFetch(`/api/jobs?${params}`, { method: "GET" });
      const data = await resp.json();

      // /api/jobs returns a flat array of JobOut objects
      const jobs = Array.isArray(data) ? data : (data.jobs || data);
      const mapped = jobs.map((j) => ({
        id: j.id,
        title: j.title,
        company: j.company,
        location: j.location || "Singapore",
        salary: j.salary || "",
        source: j.source,
        posted: j.posted_date || "",
        skills: j.skills || [],
        description: j.description || "",
        type: j.employment_type || "Full-time",
        level: j.seniority || "Mid",
        url: j.url || "",
      }));
      setResults(mapped);
      setPage(pageNum);
      setTotalLabel(mapped.length === 20 ? "20+ jobs" : `${mapped.length} jobs`);
    } catch (err) {
      setError(err.message || "Failed to load jobs. Please try again.");
      setResults([]);
    } finally {
      setLoading(false);
    }
  };

  const handleSearch = () => {
    loadJobs(query, 1);
  };

  const filtered = useMemo(() => {
    let r = [...results];
    if (levelFilter !== "all") r = r.filter((j) => j.level === levelFilter);
    if (sortBy === "salary") r.sort((a, b) => {
      const getMax = (s) => parseInt(s.replace(/[^0-9]/g, "").slice(-5)) || 0;
      return getMax(b.salary) - getMax(a.salary);
    });
    return r;
  }, [results, levelFilter, sortBy]);

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

  return (
    <div className="space-y-6">
      <div className="bg-gradient-to-r from-purple-50 to-indigo-50 rounded-xl p-5">
        <h2 className="font-semibold text-gray-800 flex items-center gap-2"><Search size={18} /> Singapore Jobs</h2>
        <p className="text-sm text-gray-500 mt-1">Browse jobs from MyCareersFuture, Careers@Gov, and more. Updated daily.</p>
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

      {totalLabel && <p className="text-sm text-gray-500">{totalLabel}{query ? ` for "${query}"` : ""}</p>}

      {/* Filters */}
      {results.length > 0 && (
        <div className="flex flex-wrap items-center gap-3 sm:gap-4">
          <div className="flex items-center gap-2">
            <Filter size={14} className="text-gray-400" />
            <select value={levelFilter} onChange={(e) => setLevelFilter(e.target.value)} className="text-sm border border-gray-200 rounded-lg px-3 py-1.5 bg-white">
              <option value="all">All levels</option>
              <option value="Junior">Junior</option>
              <option value="Mid">Mid</option>
              <option value="Mid-Senior">Mid-Senior</option>
              <option value="Senior">Senior</option>
            </select>
          </div>
          <select value={sortBy} onChange={(e) => setSortBy(e.target.value)} className="text-sm border border-gray-200 rounded-lg px-3 py-1.5 bg-white">
            <option value="relevance">Sort: Relevance</option>
            <option value="salary">Sort: Salary (High to Low)</option>
          </select>
          <span className="text-sm text-gray-500 ml-auto">{filtered.length} jobs found</span>
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
        <div key={job.id} className="bg-white border border-gray-200 rounded-xl p-5 hover:shadow-md transition">
          <div className="flex justify-between items-start">
            <div className="flex-1">
              <div className="flex items-center gap-2 mb-1">
                <h3 className="font-semibold text-gray-800">{job.title}</h3>
                {job.level && <span className="text-[10px] bg-gray-100 text-gray-500 px-2 py-0.5 rounded-full">{job.level}</span>}
              </div>
              <div className="flex items-center gap-4 text-sm text-gray-500 mb-2 flex-wrap">
                <span className="flex items-center gap-1"><Building2 size={13} />{job.company}</span>
                {job.location && <span className="flex items-center gap-1"><MapPin size={13} />{job.location}</span>}
                {job.salary && <span className="flex items-center gap-1"><DollarSign size={13} />{job.salary}</span>}
              </div>
              {job.description && <p className="text-sm text-gray-600 mb-3 line-clamp-2">{job.description}</p>}
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
          <div className="flex flex-col sm:flex-row sm:items-center justify-between border-t border-gray-100 pt-3 mt-1 gap-2">
            <div className="flex items-center gap-3 text-xs text-gray-400">
              <span>{job.source}</span>
              {job.posted && <span>{job.posted}</span>}
              {job.type && <span>{job.type}</span>}
            </div>
            <div className="flex flex-wrap gap-2">
              <button onClick={() => generateResume(job)} className="flex items-center gap-1.5 bg-emerald-600 text-white px-3 py-1.5 rounded-lg text-xs font-medium hover:bg-emerald-700 transition">
                <FileText size={12} /> Generate Resume
              </button>
              <button onClick={() => trackJob(job)} className="flex items-center gap-1.5 bg-indigo-600 text-white px-3 py-1.5 rounded-lg text-xs font-medium hover:bg-indigo-700 transition">
                <Plus size={12} /> Track
              </button>
              {job.url && (
                <a href={job.url} target="_blank" rel="noreferrer"
                  className="flex items-center gap-1.5 border border-gray-200 text-gray-600 px-3 py-1.5 rounded-lg text-xs font-medium hover:bg-gray-50 transition">
                  <ExternalLink size={12} /> View
                </a>
              )}
            </div>
          </div>
        </div>
      ))}

      {/* Pagination */}
      {results.length === 20 && (
        <div className="flex justify-center gap-3">
          {page > 1 && (
            <button onClick={() => loadJobs(query, page - 1)} className="px-4 py-2 text-sm border border-gray-200 rounded-lg hover:bg-gray-50">Previous</button>
          )}
          <span className="px-4 py-2 text-sm text-gray-500">Page {page}</span>
          <button onClick={() => loadJobs(query, page + 1)} className="px-4 py-2 text-sm border border-gray-200 rounded-lg hover:bg-gray-50">Next</button>
        </div>
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
          <div className="font-medium mb-1">Application tracking requires an @aisg.sg account</div>
          <p>Sign up with your @aisg.sg email for unlimited tracked jobs, CSV export, and follow-up reminders.</p>
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

function ResumeTab({ selectedJob, user }) {
  // Profile fields (persisted in localStorage)
  const [profile, setProfile] = useState(() => {
    try {
      const saved = localStorage.getItem("jh_resume_profile");
      if (saved) return JSON.parse(saved);
    } catch { /* ignore */ }
    return { name: "", email: "", phone: "", location: "Singapore" };
  });

  // Resume text (persisted in localStorage)
  const [resumeText, setResumeText] = useState(() => {
    try { return localStorage.getItem("jh_resume_text") || ""; } catch { return ""; }
  });

  // Upload state
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState("");
  const [dragOver, setDragOver] = useState(false);
  const fileInputRef = useRef(null);

  // Score state
  const [scoreData, setScoreData] = useState(null);
  const [scoring, setScoring] = useState(false);
  const [scoreError, setScoreError] = useState("");

  // AI Coach state
  const [coachResponse, setCoachResponse] = useState(null);
  const [coachLoading, setCoachLoading] = useState(false);
  const [coachError, setCoachError] = useState("");
  const [sessionId, setSessionId] = useState("");

  // AI Format state
  const [formatting, setFormatting] = useState(false);
  const [formatError, setFormatError] = useState("");

  // AI status
  const [aiStatus, setAiStatus] = useState(null);

  // Templates + Download
  const [templates, setTemplates] = useState([]);
  const [selectedTemplate, setSelectedTemplate] = useState("classic");
  const [downloading, setDownloading] = useState(false);
  const [downloadError, setDownloadError] = useState("");

  // General error display
  const [error, setError] = useState("");

  // Debounce timer ref for auto-scoring
  const scoreTimerRef = useRef(null);

  // Persist profile
  useEffect(() => {
    try { localStorage.setItem("jh_resume_profile", JSON.stringify(profile)); } catch { /* quota */ }
  }, [profile]);

  // Persist resume text
  useEffect(() => {
    try { localStorage.setItem("jh_resume_text", resumeText); } catch { /* quota */ }
  }, [resumeText]);

  // Poll AI status
  useEffect(() => {
    const fetchStatus = () => fetch(`${API_BASE}/api/ai/status`).then(r => r.json()).then(setAiStatus).catch(() => {});
    fetchStatus();
    const interval = setInterval(fetchStatus, 10000);
    return () => clearInterval(interval);
  }, []);

  // Fetch templates on mount
  useEffect(() => {
    fetch(`${API_BASE}/api/resume/templates`)
      .then(r => r.json())
      .then(data => {
        if (Array.isArray(data) && data.length > 0) {
          setTemplates(data);
          setSelectedTemplate(data[0].id);
        }
      })
      .catch(() => {});
  }, []);

  // Build job description string from selectedJob
  const jobDescription = useMemo(() => {
    if (!selectedJob) return "";
    const parts = [`${selectedJob.title} at ${selectedJob.company}`];
    if (selectedJob.skills?.length) parts.push(`Required skills: ${selectedJob.skills.join(", ")}`);
    if (selectedJob.description) parts.push(selectedJob.description);
    return parts.join(". ");
  }, [selectedJob]);

  // Auto-score on resume text change (debounced 1s)
  useEffect(() => {
    if (scoreTimerRef.current) clearTimeout(scoreTimerRef.current);
    if (!resumeText.trim() || resumeText.trim().length < 50) {
      setScoreData(null);
      return;
    }
    scoreTimerRef.current = setTimeout(() => {
      runScore(resumeText, jobDescription);
    }, 1000);
    return () => { if (scoreTimerRef.current) clearTimeout(scoreTimerRef.current); };
  }, [resumeText, jobDescription]);

  // ── Handlers ──────────────────────────────────────────────────────────────

  const handleFileUpload = async (file) => {
    if (!file) return;
    const ext = file.name.split(".").pop()?.toLowerCase();
    if (!["pdf", "docx"].includes(ext)) {
      setUploadError("Please upload a PDF or DOCX file.");
      return;
    }
    if (file.size > 10 * 1024 * 1024) {
      setUploadError("File too large. Maximum size is 10 MB.");
      return;
    }
    setUploading(true);
    setUploadError("");
    try {
      const formData = new FormData();
      formData.append("file", file);
      const token = localStorage.getItem("token");
      const headers = {};
      if (token) headers["Authorization"] = `Bearer ${token}`;
      const resp = await fetch(`${API_BASE}/api/resume/upload`, {
        method: "POST",
        headers,
        body: formData,
      });
      if (!resp.ok) throw new Error(`Upload failed (${resp.status})`);
      const data = await resp.json();
      if (data.text) setResumeText(data.text);
      setProfile(prev => ({
        ...prev,
        ...(data.email ? { email: data.email } : {}),
        ...(data.phone ? { phone: data.phone } : {}),
      }));
    } catch (err) {
      setUploadError(err.message || "Failed to upload file. Please try again.");
    } finally {
      setUploading(false);
    }
  };

  const handleDrop = (e) => {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer?.files?.[0];
    if (file) handleFileUpload(file);
  };

  const handleDragOver = (e) => { e.preventDefault(); setDragOver(true); };
  const handleDragLeave = () => setDragOver(false);

  const runScore = async (text, jd) => {
    setScoring(true);
    setScoreError("");
    try {
      const resp = await apiFetch("/api/resume/score", {
        method: "POST",
        body: JSON.stringify({ resume_text: text, job_description: jd }),
      });
      const data = await resp.json();
      setScoreData(data);
    } catch {
      // Client-side fallback
      setScoreData(scoreFallback(text, jd));
      setScoreError("Full scorer unavailable — showing basic analysis.");
    } finally {
      setScoring(false);
    }
  };

  // Client-side fallback scorer
  const scoreFallback = (text, jd) => {
    const rText = text.toLowerCase();
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
      keywords = techTerms.filter((t) => jdLower.includes(t));
      const customTerms = jd.match(/[A-Z][a-zA-Z.+#]+/g) || [];
      customTerms.forEach((t) => { if (t.length > 2 && !keywords.includes(t.toLowerCase())) keywords.push(t); });
      if (keywords.length < 5) keywords = [...keywords, ...ATS_KEYWORDS_BY_ROLE["Software Engineer"]];
      keywords = [...new Set(keywords)];
    } else {
      keywords = ATS_KEYWORDS_BY_ROLE["Software Engineer"];
    }
    const found = keywords.filter((kw) => rText.includes(kw.toLowerCase()));
    const missing = keywords.filter((kw) => !rText.includes(kw.toLowerCase()));
    const score = Math.round((found.length / keywords.length) * 100);
    const tips = [];
    if (rText.length < 500) tips.push("Resume seems short — aim for 400-600+ words.");
    if (!/\d{4}/.test(rText)) tips.push("Include specific dates/years for work experience.");
    if (!/\d+%/.test(rText)) tips.push("Add quantifiable achievements (e.g., 'Improved X by 30%').");
    if (!/(bachelor|master|diploma|degree|certification|certified)/.test(rText)) tips.push("Clearly list education and certifications.");
    if (!/(singapore|sg|citizen|pr|permanent resident)/.test(rText)) tips.push("For SG jobs, mention residency status if applicable.");
    if (missing.length > 3) tips.push(`Missing ${missing.length} key terms — weave them into your experience.`);
    return { fallback: true, overall_score: score, dimensions: [], top_suggestions: tips, sg_tips: [], keyword_match: { found, missing, total: keywords.length } };
  };

  const handleAIReview = async () => {
    if (!resumeText.trim()) return;
    setCoachLoading(true);
    setCoachError("");
    setCoachResponse(null);
    setSessionId("");
    try {
      const resp = await apiFetch("/api/ai/coach", {
        method: "POST",
        body: JSON.stringify({ resume_text: resumeText, job_description: jobDescription }),
      });
      const data = await resp.json();
      setCoachResponse(data);
      if (data.session_id) setSessionId(data.session_id);
    } catch (err) {
      const msg = err.message?.includes("429")
        ? "You've used all your AI reviews for today. Sign in with @aisg.sg for more!"
        : "AI is busy, try again in a moment.";
      setCoachError(msg);
    } finally {
      setCoachLoading(false);
    }
  };

  const handleAIFormat = async () => {
    if (!resumeText.trim()) return;
    setFormatting(true);
    setFormatError("");
    try {
      const resp = await apiFetch("/api/resume/format", {
        method: "POST",
        body: JSON.stringify({ resume_text: resumeText, job_description: jobDescription }),
      });
      const data = await resp.json();
      if (data.formatted_resume) {
        setResumeText(data.formatted_resume);
      }
    } catch (err) {
      setFormatError(err.message?.includes("429")
        ? "AI limit reached for today."
        : "Formatting failed. Please try again.");
    } finally {
      setFormatting(false);
    }
  };

  const handleDownload = async () => {
    if (!resumeText.trim()) return;
    setDownloading(true);
    setDownloadError("");
    try {
      const token = localStorage.getItem("token");
      const headers = { "Content-Type": "application/json" };
      if (token) headers["Authorization"] = `Bearer ${token}`;
      const resp = await fetch(`${API_BASE}/api/resume/download`, {
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
      if (!resp.ok) throw new Error(`Download failed (${resp.status})`);
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "resume.docx";
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setDownloadError(err.message || "Download failed. Please try again.");
    } finally {
      setDownloading(false);
    }
  };

  // ── Score helpers ─────────────────────────────────────────────────────────

  const scoreBarColor = (score) => score >= 70 ? "bg-green-500" : score >= 40 ? "bg-yellow-500" : "bg-red-500";
  const scoreTextColor = (score) => score >= 70 ? "text-green-600" : score >= 40 ? "text-yellow-600" : "text-red-600";
  const scoreBadge = (score) => {
    if (score >= 70) return { label: "Good", cls: "bg-green-100 text-green-800" };
    if (score >= 40) return { label: "Fair", cls: "bg-yellow-100 text-yellow-800" };
    return { label: "Needs Work", cls: "bg-red-100 text-red-800" };
  };

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="bg-gradient-to-r from-emerald-50 to-teal-50 rounded-xl p-5">
        <h2 className="font-semibold text-gray-800 flex items-center gap-2"><FileText size={18} /> Resume Workspace</h2>
        <p className="text-sm text-gray-500 mt-1">Upload your resume, get scored, improve with AI, and download a polished version.</p>
      </div>

      {/* Job Targeting Banner */}
      {selectedJob && (
        <div className="bg-indigo-50 border border-indigo-200 rounded-xl p-4">
          <div className="flex items-center gap-2 mb-1">
            <span className="text-xs font-medium text-indigo-600 uppercase tracking-wide">Targeting</span>
          </div>
          <div className="font-semibold text-gray-800">{selectedJob.title} @ {selectedJob.company}</div>
          {selectedJob.skills?.length > 0 && (
            <div className="flex flex-wrap gap-1 mt-2">
              {selectedJob.skills.map((s) => <span key={s} className="bg-indigo-100 text-indigo-700 px-2 py-0.5 rounded-full text-xs">{s}</span>)}
            </div>
          )}
        </div>
      )}

      {/* Upload Zone */}
      <div
        className={`border-2 border-dashed rounded-xl p-6 text-center transition cursor-pointer ${dragOver ? "border-indigo-400 bg-indigo-50" : "border-gray-300 bg-white hover:border-gray-400"}`}
        onDrop={handleDrop}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onClick={() => fileInputRef.current?.click()}
      >
        <input
          ref={fileInputRef}
          type="file"
          accept=".pdf,.docx"
          className="hidden"
          onChange={(e) => { handleFileUpload(e.target.files?.[0]); e.target.value = ""; }}
        />
        {uploading ? (
          <div className="flex items-center justify-center gap-2 text-indigo-600">
            <Loader2 size={20} className="animate-spin" />
            <span className="text-sm font-medium">Uploading and parsing...</span>
          </div>
        ) : (
          <>
            <UploadCloud size={28} className="mx-auto text-gray-400 mb-2" />
            <p className="text-sm font-medium text-gray-700">Upload PDF or DOCX</p>
            <p className="text-xs text-gray-400 mt-1">Drag and drop or click to browse</p>
          </>
        )}
      </div>
      {uploadError && (
        <div className="bg-red-50 border border-red-200 text-red-700 text-sm rounded-lg p-3 flex items-center gap-2">
          <AlertCircle size={14} className="flex-shrink-0" />{uploadError}
        </div>
      )}

      {/* Profile Fields */}
      <div className="bg-white border border-gray-200 rounded-xl p-5 space-y-3">
        <h3 className="text-sm font-semibold text-gray-700">Profile Details</h3>
        <div className="grid grid-cols-1 sm:grid-cols-4 gap-3">
          <input placeholder="Full Name" value={profile.name} onChange={(e) => setProfile({ ...profile, name: e.target.value })}
            className="border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-200 focus:border-indigo-400" />
          <input placeholder="Email" value={profile.email} onChange={(e) => setProfile({ ...profile, email: e.target.value })}
            className="border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-200 focus:border-indigo-400" />
          <input placeholder="Phone" value={profile.phone} onChange={(e) => setProfile({ ...profile, phone: e.target.value })}
            className="border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-200 focus:border-indigo-400" />
          <input placeholder="Location" value={profile.location} onChange={(e) => setProfile({ ...profile, location: e.target.value })}
            className="border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-200 focus:border-indigo-400" />
        </div>
      </div>

      {/* Two-panel layout: Score (left) + Editor (right) */}
      <div className="grid grid-cols-1 lg:grid-cols-5 gap-6">

        {/* Score Panel (left, 2 cols) */}
        <div className="lg:col-span-2 space-y-4 order-1 lg:order-1">
          {/* Overall Score */}
          {scoring && (
            <div className="bg-white border border-gray-200 rounded-xl p-5 text-center">
              <Loader2 size={24} className="animate-spin text-indigo-400 mx-auto" />
              <p className="text-xs text-gray-400 mt-2">Scoring...</p>
            </div>
          )}
          {scoreData && !scoring && (
            <>
              <div className="bg-white border border-gray-200 rounded-xl p-5">
                <div className="text-center mb-3">
                  <div className={`text-4xl font-bold ${scoreTextColor(scoreData.overall_score)}`}>
                    {scoreData.overall_score}<span className="text-lg text-gray-400">/100</span>
                  </div>
                  <div className="text-xs text-gray-500 mt-1">{scoreData.fallback ? "Keyword Match" : "Overall Score"}</div>
                </div>
                <div className="w-full bg-gray-100 rounded-full h-2.5 mb-4">
                  <div className={`h-2.5 rounded-full transition-all ${scoreBarColor(scoreData.overall_score)}`} style={{ width: `${scoreData.overall_score}%` }} />
                </div>

                {/* Dimension scores */}
                {scoreData.dimensions && typeof scoreData.dimensions === "object" && !Array.isArray(scoreData.dimensions) && Object.keys(scoreData.dimensions).length > 0 && (
                  <div className="space-y-3">
                    {Object.entries(scoreData.dimensions).map(([name, dim]) => {
                      const pct = dim.max > 0 ? Math.round((dim.score / dim.max) * 100) : 0;
                      return (
                        <div key={name}>
                          <div className="flex items-center justify-between mb-1">
                            <span className="text-xs font-medium text-gray-600 capitalize">{name}</span>
                            <span className={`text-xs font-bold ${scoreTextColor(pct)}`}>{dim.score}/{dim.max}</span>
                          </div>
                          <div className="w-full bg-gray-100 rounded-full h-1.5">
                            <div className={`h-1.5 rounded-full transition-all ${scoreBarColor(pct)}`} style={{ width: `${pct}%` }} />
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}

                {/* Keyword match */}
                {scoreData.keyword_match && (
                  <div className="mt-4 pt-3 border-t border-gray-100">
                    <div className="text-xs font-medium text-gray-600 mb-2">Keywords Matched</div>
                    {scoreData.keyword_match.found && (
                      <div className="flex flex-wrap gap-1 mb-2">
                        {(Array.isArray(scoreData.keyword_match.found) ? scoreData.keyword_match.found : []).map((kw) => (
                          <span key={kw} className="bg-green-100 text-green-700 px-1.5 py-0.5 rounded text-[10px]">{kw}</span>
                        ))}
                      </div>
                    )}
                    {scoreData.keyword_match.missing && (
                      <>
                        <div className="text-xs font-medium text-gray-600 mb-1 mt-2">Missing</div>
                        <div className="flex flex-wrap gap-1">
                          {(Array.isArray(scoreData.keyword_match.missing) ? scoreData.keyword_match.missing : []).map((kw) => (
                            <span key={kw} className="bg-red-100 text-red-700 px-1.5 py-0.5 rounded text-[10px]">{kw}</span>
                          ))}
                        </div>
                      </>
                    )}
                  </div>
                )}
              </div>

              {/* Suggestions */}
              {scoreData.top_suggestions && scoreData.top_suggestions.length > 0 && (
                <div className="bg-white border border-gray-200 rounded-xl p-4">
                  <h4 className="text-xs font-semibold text-gray-700 mb-3 uppercase tracking-wide">Suggestions</h4>
                  <div className="space-y-2">
                    {scoreData.top_suggestions.map((s, i) => {
                      const suggText = typeof s === "string" ? s : (s.detail || s.action || "");
                      const suggPts = typeof s === "object" && s.points ? s.points : null;
                      return (
                        <div key={i} className="flex items-start gap-2">
                          <div className="bg-amber-100 text-amber-700 rounded-full w-5 h-5 flex items-center justify-center flex-shrink-0 text-[10px] font-bold mt-0.5">
                            {suggPts ? `+${suggPts}` : i + 1}
                          </div>
                          <p className="text-xs text-gray-700 leading-relaxed">{suggText}</p>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}

              {/* SG Tips */}
              {scoreData.sg_tips && scoreData.sg_tips.length > 0 && (
                <div className="bg-indigo-50 border border-indigo-200 rounded-xl p-4">
                  <h4 className="text-xs font-semibold text-indigo-800 mb-2 uppercase tracking-wide">SG Tips</h4>
                  <ul className="space-y-1.5">
                    {scoreData.sg_tips.map((tip, i) => (
                      <li key={i} className="flex items-start gap-1.5 text-xs text-indigo-900">
                        <ChevronRight size={12} className="mt-0.5 flex-shrink-0" />{tip}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {(!scoreData.sg_tips || scoreData.sg_tips.length === 0) && (
                <div className="bg-indigo-50 border border-indigo-200 rounded-xl p-4">
                  <h4 className="text-xs font-semibold text-indigo-800 mb-2 uppercase tracking-wide">SG Tips</h4>
                  <ul className="space-y-1.5 text-xs text-indigo-900">
                    <li className="flex items-start gap-1.5"><ChevronRight size={12} className="mt-0.5 flex-shrink-0" />MyCareersFuture uses skills-based matching — list specific skills.</li>
                    <li className="flex items-start gap-1.5"><ChevronRight size={12} className="mt-0.5 flex-shrink-0" />Keep formatting simple for ATS systems like Workday and Greenhouse.</li>
                    <li className="flex items-start gap-1.5"><ChevronRight size={12} className="mt-0.5 flex-shrink-0" />SkillsFuture or WSQ certs resonate with SG employers.</li>
                  </ul>
                </div>
              )}
            </>
          )}

          {/* Placeholder when no score yet */}
          {!scoreData && !scoring && (
            <div className="bg-white border border-gray-200 rounded-xl p-5 text-center">
              <Zap size={24} className="mx-auto text-gray-300 mb-2" />
              <p className="text-sm text-gray-400">Paste or upload your resume to see your score</p>
            </div>
          )}

          {scoreError && (
            <div className="bg-yellow-50 border border-yellow-200 text-yellow-800 text-xs rounded-lg p-2.5 flex items-center gap-1.5">
              <AlertCircle size={12} className="flex-shrink-0" />{scoreError}
            </div>
          )}

          {/* AI Action Buttons */}
          <div className="space-y-2">
            <button onClick={handleAIReview} disabled={coachLoading || !resumeText.trim()}
              className="w-full flex items-center justify-center gap-2 bg-purple-600 text-white px-4 py-2.5 rounded-lg text-sm font-medium hover:bg-purple-700 disabled:opacity-40 transition">
              {coachLoading ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />}
              {coachLoading ? "Analyzing..." : "AI Review"}
            </button>
            <button onClick={handleAIFormat} disabled={formatting || !resumeText.trim()}
              className="w-full flex items-center justify-center gap-2 bg-indigo-600 text-white px-4 py-2.5 rounded-lg text-sm font-medium hover:bg-indigo-700 disabled:opacity-40 transition">
              {formatting ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
              {formatting ? "Formatting..." : "AI Format"}
            </button>
            {aiStatus && (
              <div className="text-center">
                <span className={`text-xs px-2 py-1 rounded-full ${aiStatus.status === "ready" ? "bg-green-100 text-green-700" : aiStatus.status === "busy" ? "bg-yellow-100 text-yellow-700" : "bg-orange-100 text-orange-700"}`}>
                  {aiStatus.status === "ready" ? "AI Ready" : aiStatus.status === "busy" ? "AI Busy" : `~${Math.round(aiStatus.wait_seconds || 0)}s wait`}
                </span>
              </div>
            )}
          </div>
        </div>

        {/* Resume Editor (right, 3 cols) */}
        <div className="lg:col-span-3 order-2 lg:order-2">
          <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
            <div className="bg-gray-50 px-4 py-2.5 border-b border-gray-200 flex items-center justify-between">
              <span className="text-xs font-medium text-gray-500 uppercase tracking-wide">Resume Editor</span>
              <span className="text-xs text-gray-400">{resumeText.split(/\s+/).filter(Boolean).length} words</span>
            </div>
            <textarea
              value={resumeText}
              onChange={(e) => setResumeText(e.target.value)}
              placeholder="Paste your resume text here, or upload a file above..."
              className="w-full px-4 py-3 text-sm text-gray-800 leading-relaxed focus:outline-none resize-y font-mono"
              style={{ minHeight: "400px" }}
            />
          </div>
        </div>
      </div>

      {/* AI Coach Error */}
      {coachError && (
        <div className="bg-red-50 border border-red-200 text-red-700 text-sm rounded-lg p-3 flex items-center gap-2">
          <AlertCircle size={14} className="flex-shrink-0" />{coachError}
        </div>
      )}
      {formatError && (
        <div className="bg-red-50 border border-red-200 text-red-700 text-sm rounded-lg p-3 flex items-center gap-2">
          <AlertCircle size={14} className="flex-shrink-0" />{formatError}
        </div>
      )}

      {/* AI Coach Response */}
      {coachLoading && (
        <div className="bg-purple-50 border border-purple-200 rounded-xl p-5 text-center">
          <Loader2 size={24} className="animate-spin text-purple-500 mx-auto" />
          <p className="text-sm text-purple-700 mt-2">Analyzing your resume... this usually takes 15-30 seconds</p>
        </div>
      )}
      {coachResponse && !coachLoading && (
        <div className="bg-purple-50 border border-purple-200 rounded-xl p-5">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2">
              <Sparkles size={16} className="text-purple-600" />
              <h4 className="text-sm font-semibold text-purple-800">AI Coach Response</h4>
            </div>
            <span className="text-[10px] bg-purple-100 text-purple-600 px-2 py-0.5 rounded-full">Powered by AI</span>
          </div>
          <div className="bg-white rounded-lg p-4 text-sm text-gray-700 leading-relaxed whitespace-pre-line shadow-sm">
            {coachResponse.coaching}
          </div>
          {sessionId && <p className="text-xs text-purple-400 mt-2">Session active — subsequent AI actions in this session use the same credit.</p>}
        </div>
      )}

      {/* Template Selector + Download */}
      <div className="bg-white border border-gray-200 rounded-xl p-5 space-y-4">
        <h3 className="text-sm font-semibold text-gray-700">Download Resume</h3>

        {/* Templates */}
        {templates.length > 0 && (
          <div className="flex gap-3 overflow-x-auto pb-1" style={{ scrollbarWidth: "thin" }}>
            {templates.map((t) => (
              <button
                key={t.id}
                onClick={() => setSelectedTemplate(t.id)}
                className={`flex-shrink-0 border rounded-xl px-4 py-3 text-left transition min-w-[140px] ${selectedTemplate === t.id ? "border-indigo-400 bg-indigo-50 ring-2 ring-indigo-200" : "border-gray-200 hover:border-gray-300 bg-white"}`}
              >
                <div className="text-sm font-medium text-gray-800">{t.name}</div>
                <div className="text-xs text-gray-500 mt-0.5">{t.description}</div>
              </button>
            ))}
          </div>
        )}

        <div className="flex items-center gap-3 flex-wrap">
          <button onClick={handleDownload} disabled={downloading || !resumeText.trim()}
            className="flex items-center gap-2 bg-emerald-600 text-white px-5 py-2.5 rounded-lg text-sm font-medium hover:bg-emerald-700 disabled:opacity-40 transition">
            {downloading ? <Loader2 size={14} className="animate-spin" /> : <Download size={14} />}
            {downloading ? "Preparing..." : "Download DOCX"}
          </button>
          {downloadError && (
            <span className="text-xs text-red-600 flex items-center gap-1"><AlertCircle size={12} />{downloadError}</span>
          )}
        </div>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 text-sm rounded-lg p-3 flex items-center gap-2">
          <AlertCircle size={14} className="flex-shrink-0" />{error}
        </div>
      )}
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
                <td className="px-4 py-3 text-center text-gray-600">Sign in required</td>
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
              Sign up with your @aisg.sg email to get 50 AI reviews/day, unlimited tracked jobs, CSV export, and full ATS analysis — completely free.
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
      <div className="max-w-5xl mx-auto">
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
