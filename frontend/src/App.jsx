import { useState, useEffect, useMemo, useCallback } from "react";
import {
  Search, Briefcase, Bell, FileText, Plus, X, ChevronRight, Clock,
  CheckCircle, AlertCircle, ExternalLink, Trash2, Edit3, Save, Filter,
  RefreshCw, Zap, Download, Copy, Star, MapPin, DollarSign, Building2,
  Loader2, User, LogOut, Eye, EyeOff, Mail, MessageSquare, Shield,
  RotateCcw, Sparkles,
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
const daysBetween = (a, b) => Math.round((new Date(b) - new Date(a)) / 86400000);

async function apiFetch(path, options = {}) {
  const token = localStorage.getItem("token");
  const headers = { "Content-Type": "application/json", ...options.headers };
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const resp = await fetch(`${API_BASE}${path}`, { ...options, headers });
  if (resp.status === 401) {
    localStorage.removeItem("token");
    window.location.reload();
  }
  if (!resp.ok) throw new Error(`${resp.status}: ${await resp.text()}`);
  return resp;
}

// ─── Shared Components ─────────────────────────────────────────────────────────

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
    { id: "scraper", label: "Job Scraper", icon: Search },
    { id: "tracker", label: "Tracker", icon: Briefcase },
    { id: "reminders", label: "Reminders", icon: Bell },
    { id: "resume", label: "Resume Builder", icon: FileText },
    { id: "ats", label: "ATS Check", icon: Zap },
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

function AuthModal({ onAuth }) {
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
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-2xl shadow-xl max-w-md w-full p-8">
        <div className="text-center mb-6">
          <div className="flex items-center justify-center gap-2 mb-2">
            <Briefcase size={24} className="text-indigo-600" />
            <h1 className="text-xl font-bold text-gray-800">Job Hunter SG</h1>
          </div>
          <p className="text-sm text-gray-500">
            {mode === "login" ? "Welcome back! Sign in to continue." : "Create your account to get started."}
          </p>
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

        <div className="text-center mt-5">
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

function ScraperTab({ user, trackedJobs, onTrack, setActiveTab, setSelectedJob }) {
  const [query, setQuery] = useState("");
  const [selectedPortals, setSelectedPortals] = useState(SG_JOB_PORTALS.map((p) => p.key));
  const [results, setResults] = useState([]);
  const [loading, setLoading] = useState(false);
  const [levelFilter, setLevelFilter] = useState("all");
  const [sortBy, setSortBy] = useState("relevance");
  const [hasSearched, setHasSearched] = useState(false);
  const [error, setError] = useState("");

  const togglePortal = (key) => {
    setSelectedPortals((prev) => prev.includes(key) ? prev.filter((p) => p !== key) : [...prev, key]);
  };

  const scrapeJobs = async () => {
    if (!query.trim()) return;
    setLoading(true);
    setHasSearched(true);
    setError("");
    try {
      const params = new URLSearchParams({ q: query, limit: "20", skills: "true" });
      if (selectedPortals.length > 0 && selectedPortals.length < SG_JOB_PORTALS.length) {
        params.set("sources", selectedPortals.join(","));
      }

      const resp = await apiFetch(`/api/search?${params}`, { method: "GET" });
      const data = await resp.json();

      const mapped = (data.jobs || []).map((j, i) => ({
        id: `api-${i}-${Date.now()}`,
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
    } catch (err) {
      console.error("Scrape failed:", err);
      setError(err.message || "Failed to search jobs. Please try again.");
      setResults([]);
    } finally {
      setLoading(false);
    }
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
  };

  const generateResume = (scrapedJob) => {
    setSelectedJob(scrapedJob);
    setActiveTab("resume");
  };

  const isFree = user?.tier === "free";

  return (
    <div className="space-y-6">
      <div className="bg-gradient-to-r from-purple-50 to-indigo-50 rounded-xl p-5">
        <h2 className="font-semibold text-gray-800 flex items-center gap-2"><Search size={18} /> Multi-Portal Job Scraper</h2>
        <p className="text-sm text-gray-500 mt-1">Search across all major Singapore job portals simultaneously. Find jobs, track them, and generate tailored resumes.</p>
      </div>

      {isFree && (
        <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 flex items-center gap-2 text-sm text-amber-800">
          <AlertCircle size={14} className="flex-shrink-0" />
          Free tier: 5 searches/day. Upgrade to Pro for 50 searches/day.
        </div>
      )}

      {/* Portal Selection */}
      <div>
        <div className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-2">Portals to search</div>
        <div className="flex flex-wrap gap-2">
          {SG_JOB_PORTALS.map((p) => (
            <button key={p.key} onClick={() => togglePortal(p.key)}
              className={`px-3 py-1.5 rounded-full text-xs font-medium transition inline-flex items-center gap-1 ${selectedPortals.includes(p.key) ? "bg-indigo-600 text-white" : "bg-gray-100 text-gray-500 hover:bg-gray-200"}`}>
              {p.name}
              <span className={`text-[9px] px-1 py-px rounded ${selectedPortals.includes(p.key) ? "bg-indigo-500" : "bg-gray-200 text-gray-400"}`}>
                {p.type === "api" ? "API" : "Web"}
              </span>
            </button>
          ))}
        </div>
      </div>

      {/* Search */}
      <div className="flex gap-3">
        <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search by role, skill, or company..." onKeyDown={(e) => e.key === "Enter" && scrapeJobs()}
          className="flex-1 border border-gray-200 rounded-xl px-4 py-3 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-200 focus:border-indigo-400" />
        <button onClick={scrapeJobs} disabled={loading || !query.trim()}
          className="flex items-center gap-2 bg-indigo-600 text-white px-5 py-3 rounded-xl text-sm font-medium hover:bg-indigo-700 disabled:opacity-40 transition">
          {loading ? <Loader2 size={16} className="animate-spin" /> : <Search size={16} />}
          {loading ? "Searching..." : "Search All"}
        </button>
      </div>

      {/* Filters */}
      {results.length > 0 && (
        <div className="flex items-center gap-4">
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
          <p className="text-sm text-gray-500 mt-3">Searching {selectedPortals.length} portals for "{query}"...</p>
        </div>
      )}

      {/* Error */}
      {!loading && error && (
        <div className="text-center py-8">
          <AlertCircle size={32} className="mx-auto mb-2 text-red-400" />
          <p className="text-sm text-red-600">{error}</p>
        </div>
      )}

      {/* No results */}
      {!loading && !error && hasSearched && filtered.length === 0 && (
        <div className="text-center py-12 text-gray-400">
          <Search size={32} className="mx-auto mb-2 opacity-40" />
          <p>No jobs matched your search. Try broader keywords or select more portals.</p>
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
          <div className="flex items-center justify-between border-t border-gray-100 pt-3 mt-1">
            <div className="flex items-center gap-3 text-xs text-gray-400">
              <span>{job.source}</span>
              {job.posted && <span>{job.posted}</span>}
              {job.type && <span>{job.type}</span>}
            </div>
            <div className="flex gap-2">
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

      {/* Info when no search yet */}
      {!hasSearched && (
        <div className="bg-gray-50 border border-gray-200 rounded-xl p-5">
          <h3 className="font-semibold text-gray-700 text-sm mb-3">Singapore Job APIs & Data Sources</h3>
          <div className="space-y-2 text-sm text-gray-600">
            <div className="flex items-start gap-2"><ChevronRight size={14} className="mt-1 text-indigo-400 flex-shrink-0" /><div><a href="https://data.gov.sg" target="_blank" rel="noreferrer" className="text-indigo-600 hover:underline font-medium">data.gov.sg</a> — SG open data with free developer APIs</div></div>
            <div className="flex items-start gap-2"><ChevronRight size={14} className="mt-1 text-indigo-400 flex-shrink-0" /><div><a href="https://www.developer.tech.gov.sg/products/categories/data-and-apis/index" target="_blank" rel="noreferrer" className="text-indigo-600 hover:underline font-medium">GovTech Developer Portal</a> — Full SG government API catalog</div></div>
            <div className="flex items-start gap-2"><ChevronRight size={14} className="mt-1 text-indigo-400 flex-shrink-0" /><div><a href="https://docs.unified.to/ats/overview" target="_blank" rel="noreferrer" className="text-indigo-600 hover:underline font-medium">Unified.to ATS API</a> — One API for Greenhouse, Lever, Workable, etc.</div></div>
            <div className="flex items-start gap-2"><ChevronRight size={14} className="mt-1 text-indigo-400 flex-shrink-0" /><div><a href="https://www.kombo.dev/use-cases/ats-api" target="_blank" rel="noreferrer" className="text-indigo-600 hover:underline font-medium">Kombo.dev</a> — Unified ATS integration API</div></div>
            <div className="flex items-start gap-2"><ChevronRight size={14} className="mt-1 text-indigo-400 flex-shrink-0" /><div><a href="https://github.com/datagovsg" target="_blank" rel="noreferrer" className="text-indigo-600 hover:underline font-medium">GitHub: datagovsg</a> — Open source repos from data.gov.sg</div></div>
          </div>
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
      console.error("Delete failed:", err);
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
      console.error("Export failed:", err);
    }
  };

  const filtered = filterStatus === "all" ? jobs : jobs.filter((j) => j.status === filterStatus);
  const stats = {
    total: jobs.length,
    applied: jobs.filter((j) => j.status === "applied").length,
    interview: jobs.filter((j) => j.status === "interview").length,
    offer: jobs.filter((j) => j.status === "offer").length,
  };

  const isFree = user?.tier === "free";
  const atLimit = isFree && jobs.length >= 20;
  const isPro = user?.tier === "pro" || user?.tier === "admin";

  return (
    <div className="space-y-6">
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
          <div className="font-medium mb-1">Free tier limit reached (20 tracked jobs)</div>
          <p>Upgrade to Pro for unlimited tracked jobs, CSV export, and more.</p>
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
    const newDate = new Date(Date.now() + 7 * 86400000).toISOString().split("T")[0];
    await onUpdateJob(job.id, { follow_up_date: newDate });
  };

  const markDone = async (job) => {
    await onUpdateJob(job.id, { follow_up_date: null });
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
// TAB 4: RESUME BUILDER
// ═══════════════════════════════════════════════════════════════════════════════

function ResumeBuilderTab({ selectedJob, user }) {
  const [profile, setProfile] = useState(() => {
    try {
      const saved = localStorage.getItem("jh_resume_profile");
      if (saved) return JSON.parse(saved);
    } catch { /* ignore */ }
    return { name: "", email: "", phone: "", location: "Singapore", summary: "", experience: "", education: "", skills: "", certifications: "" };
  });
  const [generatedResume, setGeneratedResume] = useState(null);
  const [generating, setGenerating] = useState(false);

  // AI Coach state
  const [coachResponse, setCoachResponse] = useState(null);
  const [coachLoading, setCoachLoading] = useState(false);
  const [coachError, setCoachError] = useState("");
  const [aiStatus, setAiStatus] = useState(null);
  const [sessionId, setSessionId] = useState("");

  // AI Rewrite state (keyed by bullet index)
  const [rewriteResults, setRewriteResults] = useState({});
  const [rewriteLoading, setRewriteLoading] = useState({});

  // Poll AI status when tab is active
  useEffect(() => {
    const fetchStatus = () => fetch(`${API_BASE}/api/ai/status`).then(r => r.json()).then(setAiStatus).catch(() => {});
    fetchStatus();
    const interval = setInterval(fetchStatus, 10000);
    return () => clearInterval(interval);
  }, []);

  // Persist profile to localStorage on every change (item 6)
  useEffect(() => {
    try { localStorage.setItem("jh_resume_profile", JSON.stringify(profile)); } catch { /* quota */ }
  }, [profile]);

  // AI Coach handler — starts a session, all rewrites within it are free
  const handleAICoach = async () => {
    if (!profile.experience.trim()) return;
    setCoachLoading(true);
    setCoachError("");
    setCoachResponse(null);
    setSessionId("");
    setRewriteResults({});
    try {
      const jd = selectedJob ? `${selectedJob.title} at ${selectedJob.company}. Skills: ${selectedJob.skills.join(", ")}. ${selectedJob.description || ""}` : "";
      const resumeText = [profile.summary, profile.experience, profile.education, profile.skills, profile.certifications].filter(Boolean).join("\n\n");
      const resp = await apiFetch("/api/ai/coach", {
        method: "POST",
        body: JSON.stringify({ resume_text: resumeText, job_description: jd }),
      });
      const data = await resp.json();
      setCoachResponse(data);
      if (data.session_id) setSessionId(data.session_id);
    } catch (err) {
      const msg = err.message?.includes("429") ? "You've used all your AI reviews for today. Sign in with @aisg.sg for more!" : "AI is busy, try again in a moment.";
      setCoachError(msg);
    } finally {
      setCoachLoading(false);
    }
  };

  // AI Rewrite handler — uses session_id so rewrites within a session are free
  const handleRewriteBullet = async (bulletText, index) => {
    setRewriteLoading((prev) => ({ ...prev, [index]: true }));
    try {
      const jobTitle = selectedJob ? selectedJob.title : "";
      const resp = await apiFetch("/api/ai/rewrite", {
        method: "POST",
        body: JSON.stringify({ bullet: bulletText, job_title: jobTitle, session_id: sessionId }),
      });
      const data = await resp.json();
      setRewriteResults((prev) => ({ ...prev, [index]: data }));
    } catch (err) {
      const msg = err.message?.includes("429") ? "AI limit reached" : "AI busy";
      setRewriteResults((prev) => ({ ...prev, [index]: { error: true, message: msg } }));
    } finally {
      setRewriteLoading((prev) => ({ ...prev, [index]: false }));
    }
  };

  const acceptRewrite = (index) => {
    const rw = rewriteResults[index];
    if (!rw || !rw.rewritten) return;
    const lines = profile.experience.split("\n");
    // Find the bullet line and replace
    let bulletIdx = -1;
    for (let i = 0; i < lines.length; i++) {
      const trimmed = lines[i].replace(/^[\s\-\u2022*]+/, "").trim();
      if (trimmed === rw.original.replace(/^[\s\-\u2022*]+/, "").trim()) { bulletIdx = i; break; }
    }
    if (bulletIdx >= 0) {
      const prefix = lines[bulletIdx].match(/^[\s\-\u2022*]*/)?.[0] || "- ";
      lines[bulletIdx] = prefix + rw.rewritten;
      setProfile({ ...profile, experience: lines.join("\n") });
    }
    setRewriteResults((prev) => { const n = { ...prev }; delete n[index]; return n; });
  };

  const rejectRewrite = (index) => {
    setRewriteResults((prev) => { const n = { ...prev }; delete n[index]; return n; });
  };

  const generateResume = () => {
    if (!profile.name || !profile.experience) return;
    setGenerating(true);

    setTimeout(() => {
      const jobSkills = selectedJob ? selectedJob.skills : [];
      const jobTitle = selectedJob ? selectedJob.title : "Software Engineer";
      const jobCompany = selectedJob ? selectedJob.company : "Target Company";

      const expText = profile.experience.toLowerCase();
      const hasMetrics = /\d+%|\d+ (users|clients|projects|team|members|systems)/.test(expText);

      const matchedSkills = jobSkills.filter((s) =>
        profile.skills.toLowerCase().includes(s.toLowerCase()) ||
        profile.experience.toLowerCase().includes(s.toLowerCase())
      );
      const missingSkills = jobSkills.filter((s) => !matchedSkills.includes(s));

      let tailoredSummary = profile.summary || `Results-driven professional with demonstrated expertise in ${matchedSkills.slice(0, 4).join(", ")}. `;
      if (matchedSkills.length > 0 && !profile.summary) {
        tailoredSummary += `Proven track record in ${matchedSkills.slice(0, 3).join(", ")}, with hands-on experience delivering impactful solutions. `;
        tailoredSummary += `Seeking to leverage my skills at ${jobCompany} as a ${jobTitle}.`;
      }

      const allSkills = [...new Set([...matchedSkills, ...profile.skills.split(",").map((s) => s.trim()).filter(Boolean)])];

      const resume = {
        name: profile.name,
        email: profile.email,
        phone: profile.phone,
        location: profile.location,
        targetRole: jobTitle,
        targetCompany: jobCompany,
        summary: tailoredSummary,
        experience: profile.experience,
        education: profile.education,
        skills: allSkills,
        certifications: profile.certifications,
        matchedSkills,
        missingSkills,
        score: Math.round((matchedSkills.length / Math.max(jobSkills.length, 1)) * 100),
        suggestions: [],
      };

      if (!hasMetrics) resume.suggestions.push("Add quantifiable achievements (e.g., 'Reduced load time by 40%', 'Managed team of 5').");
      if (missingSkills.length > 0) resume.suggestions.push(`Consider adding experience with: ${missingSkills.slice(0, 5).join(", ")}.`);
      if (!profile.certifications) resume.suggestions.push("Adding certifications (AWS, SkillsFuture, WSQ) boosts ATS scores for SG roles.");
      if (profile.experience.split("\n").length < 5) resume.suggestions.push("Expand each role with 3-5 bullet points describing achievements and responsibilities.");
      if (!/(singapore|sg|citizen|pr|permanent resident)/i.test(profile.experience + profile.summary)) {
        resume.suggestions.push("Mention residency status (SG Citizen/PR) — many local employers filter for this.");
      }

      setGeneratedResume(resume);
      setGenerating(false);
    }, 800);
  };

  const copyResume = () => {
    if (!generatedResume) return;
    const text = `${generatedResume.name}\n${generatedResume.email} | ${generatedResume.phone} | ${generatedResume.location}\n\n` +
      `PROFESSIONAL SUMMARY\n${generatedResume.summary}\n\n` +
      `SKILLS\n${generatedResume.skills.join(" | ")}\n\n` +
      `EXPERIENCE\n${generatedResume.experience}\n\n` +
      `EDUCATION\n${generatedResume.education}\n` +
      (generatedResume.certifications ? `\nCERTIFICATIONS\n${generatedResume.certifications}` : "");
    navigator.clipboard.writeText(text);
  };

  return (
    <div className="space-y-6">
      <div className="bg-gradient-to-r from-emerald-50 to-teal-50 rounded-xl p-5">
        <h2 className="font-semibold text-gray-800 flex items-center gap-2"><FileText size={18} /> Tailored Resume Builder</h2>
        <p className="text-sm text-gray-500 mt-1">
          {selectedJob
            ? `Generating a resume tailored for "${selectedJob.title}" at ${selectedJob.company}. Fill in your details below.`
            : "Fill in your profile, then we'll generate an ATS-optimized resume. Select a job from the Scraper tab for best results."
          }
        </p>
      </div>

      {selectedJob && (
        <div className="bg-indigo-50 border border-indigo-200 rounded-xl p-4">
          <div className="text-xs font-medium text-indigo-600 uppercase tracking-wide mb-1">Target Job</div>
          <div className="font-semibold text-gray-800">{selectedJob.title} — {selectedJob.company}</div>
          <div className="text-sm text-gray-500">{selectedJob.location} | {selectedJob.salary}</div>
          <div className="flex flex-wrap gap-1 mt-2">
            {selectedJob.skills.map((s) => <span key={s} className="bg-indigo-100 text-indigo-700 px-2 py-0.5 rounded-full text-xs">{s}</span>)}
          </div>
        </div>
      )}

      {/* Profile Form */}
      <div className="bg-white border border-gray-200 rounded-xl p-5 space-y-4">
        <h3 className="font-semibold text-gray-800">Your Profile</h3>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <input placeholder="Full Name *" value={profile.name} onChange={(e) => setProfile({ ...profile, name: e.target.value })} className="border border-gray-200 rounded-lg px-3 py-2 text-sm" />
          <input placeholder="Email" value={profile.email} onChange={(e) => setProfile({ ...profile, email: e.target.value })} className="border border-gray-200 rounded-lg px-3 py-2 text-sm" />
          <input placeholder="Phone" value={profile.phone} onChange={(e) => setProfile({ ...profile, phone: e.target.value })} className="border border-gray-200 rounded-lg px-3 py-2 text-sm" />
          <input placeholder="Location" value={profile.location} onChange={(e) => setProfile({ ...profile, location: e.target.value })} className="border border-gray-200 rounded-lg px-3 py-2 text-sm" />
        </div>
        <textarea placeholder="Professional Summary (optional — we'll generate one if blank)" value={profile.summary} onChange={(e) => setProfile({ ...profile, summary: e.target.value })} className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm" rows={2} />
        <textarea placeholder="Work Experience * (include company, role, dates, and bullet points)" value={profile.experience} onChange={(e) => setProfile({ ...profile, experience: e.target.value })} className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm" rows={6} />
        <textarea placeholder="Education (degree, school, year)" value={profile.education} onChange={(e) => setProfile({ ...profile, education: e.target.value })} className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm" rows={2} />
        <input placeholder="Skills (comma-separated: React, TypeScript, AWS...)" value={profile.skills} onChange={(e) => setProfile({ ...profile, skills: e.target.value })} className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm" />
        <input placeholder="Certifications (optional: AWS Solutions Architect, SkillsFuture...)" value={profile.certifications} onChange={(e) => setProfile({ ...profile, certifications: e.target.value })} className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm" />
        <div className="flex items-center gap-3 flex-wrap">
          <button onClick={generateResume} disabled={!profile.name || !profile.experience || generating}
            className="flex items-center gap-2 bg-emerald-600 text-white px-5 py-2 rounded-lg text-sm font-medium hover:bg-emerald-700 disabled:opacity-40 transition">
            {generating ? <Loader2 size={14} className="animate-spin" /> : <Zap size={14} />}
            {generating ? "Generating..." : "Generate Tailored Resume"}
          </button>
          <button onClick={handleAICoach} disabled={coachLoading || !profile.experience.trim()}
            className="flex items-center gap-2 bg-purple-600 text-white px-5 py-2 rounded-lg text-sm font-medium hover:bg-purple-700 disabled:opacity-40 transition">
            {coachLoading ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />}
            {coachLoading ? "Analyzing..." : "AI Resume Review"}
          </button>
          {aiStatus && (
            <span className={`text-xs px-2 py-1 rounded-full ${aiStatus.status === "ready" ? "bg-green-100 text-green-700" : aiStatus.status === "busy" ? "bg-yellow-100 text-yellow-700" : "bg-orange-100 text-orange-700"}`}>
              {aiStatus.status === "ready" ? "AI Ready" : aiStatus.status === "busy" ? "AI Busy" : `~${Math.round(aiStatus.wait_seconds)}s wait`}
            </span>
          )}
        </div>
      </div>

      {/* AI Coach Response */}
      {coachError && (
        <div className="bg-red-50 border border-red-200 text-red-700 text-sm rounded-lg p-3 flex items-center gap-2">
          <AlertCircle size={14} className="flex-shrink-0" />{coachError}
        </div>
      )}
      {coachLoading && (
        <div className="bg-purple-50 border border-purple-200 rounded-xl p-5 text-center">
          <Loader2 size={24} className="animate-spin text-purple-500 mx-auto" />
          <p className="text-sm text-purple-700 mt-2">Analyzing your resume... this usually takes 15-30 seconds</p>
          <p className="text-xs text-purple-400 mt-1">Powered by AI</p>
        </div>
      )}
      {coachResponse && !coachLoading && (
        <div className="bg-purple-50 border border-purple-200 rounded-xl p-5">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2">
              <Sparkles size={16} className="text-purple-600" />
              <h4 className="text-sm font-semibold text-purple-800">AI Resume Review</h4>
            </div>
            <span className="text-[10px] bg-purple-100 text-purple-600 px-2 py-0.5 rounded-full">Powered by AI</span>
          </div>
          <div className="bg-white rounded-lg p-4 text-sm text-gray-700 leading-relaxed whitespace-pre-line shadow-sm">
            {coachResponse.coaching}
          </div>
          {sessionId && <p className="text-xs text-purple-400 mt-2">You can now rewrite individual bullets below for free within this session.</p>}
        </div>
      )}

      {/* Generated Resume */}
      {generatedResume && (
        <div className="space-y-4">
          <div className="bg-white border border-gray-200 rounded-xl p-5 flex items-center justify-between">
            <div>
              <div className="text-sm text-gray-500">ATS Match Score for {generatedResume.targetRole}</div>
              <div className={`text-3xl font-bold ${generatedResume.score >= 70 ? "text-green-600" : generatedResume.score >= 40 ? "text-yellow-600" : "text-red-600"}`}>
                {generatedResume.score}%
              </div>
            </div>
            <div className="flex gap-2">
              <button onClick={copyResume} className="flex items-center gap-1.5 border border-gray-200 px-3 py-2 rounded-lg text-sm hover:bg-gray-50"><Copy size={14} /> Copy</button>
            </div>
          </div>

          {generatedResume.suggestions.length > 0 && (
            <div className="bg-yellow-50 border border-yellow-200 rounded-xl p-4">
              <h4 className="text-sm font-semibold text-yellow-800 mb-2">Improvement Suggestions</h4>
              <ul className="space-y-1.5">
                {generatedResume.suggestions.map((s, i) => (
                  <li key={i} className="flex items-start gap-2 text-sm text-yellow-900">
                    <AlertCircle size={13} className="mt-0.5 flex-shrink-0 text-yellow-600" />{s}
                  </li>
                ))}
              </ul>
            </div>
          )}

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div className="bg-green-50 border border-green-200 rounded-xl p-4">
              <h4 className="text-sm font-semibold text-green-800 mb-2">Matched Keywords ({generatedResume.matchedSkills.length})</h4>
              <div className="flex flex-wrap gap-1.5">
                {generatedResume.matchedSkills.map((kw) => <span key={kw} className="bg-green-100 text-green-700 px-2 py-0.5 rounded-full text-xs">{kw}</span>)}
              </div>
            </div>
            <div className="bg-red-50 border border-red-200 rounded-xl p-4">
              <h4 className="text-sm font-semibold text-red-800 mb-2">Missing Keywords ({generatedResume.missingSkills.length})</h4>
              <div className="flex flex-wrap gap-1.5">
                {generatedResume.missingSkills.map((kw) => <span key={kw} className="bg-red-100 text-red-700 px-2 py-0.5 rounded-full text-xs">{kw}</span>)}
              </div>
            </div>
          </div>

          <div className="bg-white border border-gray-200 rounded-xl p-6 shadow-sm">
            <div className="border-b border-gray-200 pb-4 mb-4">
              <h2 className="text-xl font-bold text-gray-900">{generatedResume.name}</h2>
              <p className="text-sm text-gray-500 mt-1">
                {[generatedResume.email, generatedResume.phone, generatedResume.location].filter(Boolean).join(" | ")}
              </p>
            </div>
            <div className="space-y-4">
              <div>
                <h3 className="text-xs font-bold text-gray-500 uppercase tracking-wider mb-1">Professional Summary</h3>
                <p className="text-sm text-gray-700 leading-relaxed">{generatedResume.summary}</p>
              </div>
              <div>
                <h3 className="text-xs font-bold text-gray-500 uppercase tracking-wider mb-1">Technical Skills</h3>
                <div className="flex flex-wrap gap-1.5">
                  {generatedResume.skills.map((s) => (
                    <span key={s} className={`px-2 py-0.5 rounded-full text-xs ${generatedResume.matchedSkills.includes(s) ? "bg-green-100 text-green-800 font-medium" : "bg-gray-100 text-gray-600"}`}>{s}</span>
                  ))}
                </div>
              </div>
              <div>
                <h3 className="text-xs font-bold text-gray-500 uppercase tracking-wider mb-1">Experience</h3>
                <div className="space-y-1">
                  {generatedResume.experience.split("\n").map((line, idx) => {
                    const trimmed = line.replace(/^[\s\-\u2022*]+/, "").trim();
                    const isBullet = trimmed.length > 10 && /^[\-\u2022*]/.test(line.trim());
                    return (
                      <div key={idx} className="group">
                        <div className="flex items-start gap-1">
                          <p className="text-sm text-gray-700 leading-relaxed flex-1">{line}</p>
                          {isBullet && user && (
                            <button
                              onClick={() => handleRewriteBullet(trimmed, idx)}
                              disabled={rewriteLoading[idx]}
                              className="opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0 text-purple-500 hover:text-purple-700 p-0.5"
                              title="AI Rewrite">
                              {rewriteLoading[idx] ? <Loader2 size={12} className="animate-spin" /> : <RotateCcw size={12} />}
                            </button>
                          )}
                        </div>
                        {rewriteResults[idx] && !rewriteResults[idx].error && (
                          <div className="ml-4 mt-1 bg-purple-50 border border-purple-200 rounded-lg p-3 text-xs space-y-1.5">
                            <div className="text-gray-500 line-through">{rewriteResults[idx].original}</div>
                            <div className="text-purple-800 font-medium">{rewriteResults[idx].rewritten}</div>
                            <div className="flex gap-2 mt-1">
                              <button onClick={() => acceptRewrite(idx)} className="bg-green-600 text-white px-2 py-0.5 rounded text-[10px] font-medium hover:bg-green-700">Accept</button>
                              <button onClick={() => rejectRewrite(idx)} className="bg-gray-200 text-gray-600 px-2 py-0.5 rounded text-[10px] font-medium hover:bg-gray-300">Reject</button>
                            </div>
                          </div>
                        )}
                        {rewriteResults[idx]?.error && (
                          <div className="ml-4 mt-1 text-xs text-red-500">Rewrite failed. Try again.</div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
              {generatedResume.education && (
                <div>
                  <h3 className="text-xs font-bold text-gray-500 uppercase tracking-wider mb-1">Education</h3>
                  <p className="text-sm text-gray-700 whitespace-pre-line">{generatedResume.education}</p>
                </div>
              )}
              {generatedResume.certifications && (
                <div>
                  <h3 className="text-xs font-bold text-gray-500 uppercase tracking-wider mb-1">Certifications</h3>
                  <p className="text-sm text-gray-700">{generatedResume.certifications}</p>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// TAB 5: ATS CHECKER
// ═══════════════════════════════════════════════════════════════════════════════

function ATSTab() {
  const [resume, setResume] = useState("");
  const [jobDesc, setJobDesc] = useState("");
  const [analysis, setAnalysis] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  // Client-side fallback when API fails
  const analyzeFallback = () => {
    const rText = resume.toLowerCase();
    let keywords;
    if (jobDesc.trim()) {
      const techTerms = [
        "react", "typescript", "javascript", "python", "java", "sql", "nosql", "aws", "docker",
        "kubernetes", "ci/cd", "agile", "scrum", "rest api", "graphql", "node.js", "git", "linux",
        "terraform", "microservices", "cloud", "machine learning", "data analysis", "tableau",
        "power bi", "excel", "figma", "css", "html", "webpack", "testing", "unit testing",
        "system design", "scalable", "performance optimization", "responsive design", "accessibility",
      ];
      const jdLower = jobDesc.toLowerCase();
      keywords = techTerms.filter((t) => jdLower.includes(t));
      const customTerms = jobDesc.match(/[A-Z][a-zA-Z.+#]+/g) || [];
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
    return { fallback: true, overall_score: score, dimensions: [], top_suggestions: tips, sg_tips: [], found, missing, totalKeywords: keywords.length };
  };

  const analyze = async () => {
    if (!resume.trim()) return;
    setLoading(true);
    setError("");
    try {
      const resp = await apiFetch("/api/resume/score", {
        method: "POST",
        body: JSON.stringify({ resume_text: resume, job_description: jobDesc }),
      });
      const data = await resp.json();
      setAnalysis(data);
    } catch (err) {
      console.error("ATS API failed, using fallback:", err);
      setAnalysis(analyzeFallback());
      setError("Backend scorer unavailable — showing basic keyword analysis instead.");
    } finally {
      setLoading(false);
    }
  };

  const scoreBadge = (score) => {
    if (score >= 70) return { label: "Good Job", cls: "bg-green-100 text-green-800" };
    if (score >= 40) return { label: "On Track", cls: "bg-yellow-100 text-yellow-800" };
    return { label: "Needs Work", cls: "bg-red-100 text-red-800" };
  };
  const scoreBarColor = (score) => score >= 70 ? "bg-green-500" : score >= 40 ? "bg-yellow-500" : "bg-red-500";
  const scoreTextColor = (score) => score >= 70 ? "text-green-600" : score >= 40 ? "text-yellow-600" : "text-red-600";

  return (
    <div className="space-y-6">
      <div className="bg-gradient-to-r from-amber-50 to-orange-50 rounded-xl p-5">
        <h2 className="font-semibold text-gray-800 flex items-center gap-2"><Zap size={18} /> AI Resume Scorer</h2>
        <p className="text-sm text-gray-500 mt-1">Paste a job description and your resume for a multi-dimensional ATS analysis powered by our backend scorer.</p>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div>
          <label className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-2 block">Job Description (optional but recommended)</label>
          <textarea value={jobDesc} onChange={(e) => setJobDesc(e.target.value)} placeholder="Paste the full job description here..."
            className="w-full border border-gray-200 rounded-xl px-4 py-3 text-sm h-48 focus:outline-none focus:ring-2 focus:ring-amber-200 resize-y" />
        </div>
        <div>
          <label className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-2 block">Your Resume *</label>
          <textarea value={resume} onChange={(e) => setResume(e.target.value)} placeholder="Paste your resume text here..."
            className="w-full border border-gray-200 rounded-xl px-4 py-3 text-sm h-48 focus:outline-none focus:ring-2 focus:ring-amber-200 resize-y" />
        </div>
      </div>

      <button onClick={analyze} disabled={!resume.trim() || loading}
        className="flex items-center gap-2 bg-amber-600 text-white px-5 py-2 rounded-lg text-sm font-medium hover:bg-amber-700 disabled:opacity-40 transition">
        {loading ? <Loader2 size={14} className="animate-spin" /> : <Zap size={14} />}
        {loading ? "Analyzing..." : "Analyze Match"}
      </button>

      {error && (
        <div className="bg-yellow-50 border border-yellow-200 text-yellow-800 text-sm rounded-lg p-3 flex items-center gap-2">
          <AlertCircle size={14} className="flex-shrink-0" />{error}
        </div>
      )}

      {analysis && (
        <div className="space-y-5">
          {/* Overall Score */}
          <div className="bg-white border border-gray-200 rounded-xl p-5 text-center">
            <div className={`text-5xl font-bold ${scoreTextColor(analysis.overall_score)}`}>
              {analysis.overall_score}%
            </div>
            <div className="text-sm text-gray-500 mt-1">
              {analysis.fallback ? "Keyword Match Score" : "Overall Resume Score"}
            </div>
            <div className="mt-3 w-full bg-gray-100 rounded-full h-3">
              <div className={`h-3 rounded-full transition-all ${scoreBarColor(analysis.overall_score)}`} style={{ width: `${analysis.overall_score}%` }} />
            </div>
          </div>

          {/* Multi-dimensional scores (backend only) */}
          {analysis.dimensions && analysis.dimensions.length > 0 && (
            <div className="bg-white border border-gray-200 rounded-xl p-5">
              <h4 className="text-sm font-semibold text-gray-800 mb-4">Score Breakdown</h4>
              <div className="space-y-4">
                {analysis.dimensions.map((dim) => {
                  const badge = scoreBadge(dim.score);
                  return (
                    <div key={dim.name}>
                      <div className="flex items-center justify-between mb-1.5">
                        <div className="flex items-center gap-2">
                          <span className="text-sm font-medium text-gray-700">{dim.name}</span>
                          <span className={`text-[10px] px-2 py-0.5 rounded-full font-medium ${badge.cls}`}>{badge.label}</span>
                        </div>
                        <span className={`text-sm font-bold ${scoreTextColor(dim.score)}`}>{dim.score}%</span>
                      </div>
                      <div className="w-full bg-gray-100 rounded-full h-2">
                        <div className={`h-2 rounded-full transition-all ${scoreBarColor(dim.score)}`} style={{ width: `${dim.score}%` }} />
                      </div>
                      {dim.details && <p className="text-xs text-gray-500 mt-1">{dim.details}</p>}
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Fallback keyword view */}
          {analysis.fallback && (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div className="bg-green-50 border border-green-200 rounded-xl p-4">
                <h4 className="text-sm font-semibold text-green-800 mb-2">Found ({analysis.found.length})</h4>
                <div className="flex flex-wrap gap-1.5">{analysis.found.map((kw) => <span key={kw} className="bg-green-100 text-green-700 px-2 py-0.5 rounded-full text-xs">{kw}</span>)}</div>
              </div>
              <div className="bg-red-50 border border-red-200 rounded-xl p-4">
                <h4 className="text-sm font-semibold text-red-800 mb-2">Missing ({analysis.missing.length})</h4>
                <div className="flex flex-wrap gap-1.5">{analysis.missing.map((kw) => <span key={kw} className="bg-red-100 text-red-700 px-2 py-0.5 rounded-full text-xs">{kw}</span>)}</div>
              </div>
            </div>
          )}

          {/* Top Suggestions */}
          {analysis.top_suggestions && analysis.top_suggestions.length > 0 && (
            <div className="space-y-3">
              <h4 className="text-sm font-semibold text-gray-800">Actionable Suggestions</h4>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                {analysis.top_suggestions.map((s, i) => (
                  <div key={i} className="bg-white border border-gray-200 rounded-xl p-4 flex items-start gap-3 hover:shadow-sm transition">
                    <div className="bg-amber-100 text-amber-700 rounded-full w-6 h-6 flex items-center justify-center flex-shrink-0 text-xs font-bold">{i + 1}</div>
                    <p className="text-sm text-gray-700">{s}</p>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* SG Tips from backend */}
          {analysis.sg_tips && analysis.sg_tips.length > 0 && (
            <div className="bg-indigo-50 border border-indigo-200 rounded-xl p-5">
              <h4 className="text-sm font-semibold text-indigo-800 mb-2">Singapore-Specific Tips</h4>
              <ul className="space-y-2 text-sm text-indigo-900">
                {analysis.sg_tips.map((tip, i) => (
                  <li key={i} className="flex items-start gap-2"><ChevronRight size={14} className="mt-0.5 flex-shrink-0" />{tip}</li>
                ))}
              </ul>
            </div>
          )}

          {/* Static SG tips fallback */}
          {(!analysis.sg_tips || analysis.sg_tips.length === 0) && (
            <div className="bg-indigo-50 border border-indigo-200 rounded-xl p-5">
              <h4 className="text-sm font-semibold text-indigo-800 mb-2">Singapore ATS Tips</h4>
              <ul className="space-y-2 text-sm text-indigo-900">
                <li className="flex items-start gap-2"><ChevronRight size={14} className="mt-0.5 flex-shrink-0" />MyCareersFuture uses skills-based matching — list specific skills, not just titles.</li>
                <li className="flex items-start gap-2"><ChevronRight size={14} className="mt-0.5 flex-shrink-0" />SG employers often use Workday, SuccessFactors, or Greenhouse — keep formatting simple.</li>
                <li className="flex items-start gap-2"><ChevronRight size={14} className="mt-0.5 flex-shrink-0" />Submit .docx or .pdf — avoid .pages or image-based PDFs.</li>
                <li className="flex items-start gap-2"><ChevronRight size={14} className="mt-0.5 flex-shrink-0" />SkillsFuture or WSQ certs resonate with SG employers.</li>
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// TAB 6: ACCOUNT
// ═══════════════════════════════════════════════════════════════════════════════

function AccountTab({ user, onLogout }) {
  const [showApiKey, setShowApiKey] = useState(false);
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
      } catch (err) {
        console.error("Failed to load usage:", err);
      } finally {
        if (!cancelled) setUsageLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const copyApiKey = () => {
    if (user?.api_key) {
      navigator.clipboard.writeText(user.api_key);
    }
  };

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
            <div className="text-gray-500 text-xs uppercase tracking-wide mb-1">API Key</div>
            <div className="flex items-center gap-2">
              <code className="text-xs bg-gray-100 px-2 py-1 rounded font-mono">
                {showApiKey ? (user?.api_key || "—") : "••••••••••••••••"}
              </code>
              <button onClick={() => setShowApiKey(!showApiKey)} className="text-gray-400 hover:text-gray-600">
                {showApiKey ? <EyeOff size={14} /> : <Eye size={14} />}
              </button>
              <button onClick={copyApiKey} className="text-gray-400 hover:text-gray-600" title="Copy API key">
                <Copy size={14} />
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* Usage Stats */}
      <div className="bg-white border border-gray-200 rounded-xl p-5">
        <h3 className="font-semibold text-gray-800 mb-4">Usage</h3>
        {usageLoading ? (
          <div className="flex items-center gap-2 text-sm text-gray-500"><Loader2 size={14} className="animate-spin" /> Loading usage...</div>
        ) : usage ? (
          <div className="grid grid-cols-3 gap-4">
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
                <th className="text-center px-4 py-3 text-xs uppercase text-indigo-600">Pro ($5/mo)</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              <tr>
                <td className="px-4 py-3 text-gray-700">Searches / day</td>
                <td className="px-4 py-3 text-center text-gray-600">5</td>
                <td className="px-4 py-3 text-center text-indigo-700 font-medium">50</td>
              </tr>
              <tr>
                <td className="px-4 py-3 text-gray-700">Tracked jobs</td>
                <td className="px-4 py-3 text-center text-gray-600">20</td>
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
              <h4 className="font-semibold text-gray-800">Upgrade to Pro</h4>
            </div>
            <p className="text-sm text-gray-600 mb-3">
              Get 50 searches/day, unlimited tracked jobs, CSV export, and full ATS analysis for just $5/month.
            </p>
            <p className="text-sm text-gray-500">
              Send us a message below or reach out directly to upgrade.
            </p>
          </div>
        )}
      </div>

      {/* Contact */}
      <div className="bg-white border border-gray-200 rounded-xl p-5">
        <h3 className="font-semibold text-gray-800 mb-4">Get in Touch</h3>

        <div className="flex gap-3 mb-5">
          <a href="https://wa.me/" target="_blank" rel="noreferrer"
            className="flex items-center gap-2 border border-gray-200 rounded-lg px-4 py-2 text-sm text-gray-600 hover:bg-gray-50 transition">
            <MessageSquare size={14} /> WhatsApp
          </a>
          <a href="https://t.me/" target="_blank" rel="noreferrer"
            className="flex items-center gap-2 border border-gray-200 rounded-lg px-4 py-2 text-sm text-gray-600 hover:bg-gray-50 transition">
            <MessageSquare size={14} /> Telegram
          </a>
          <a href="mailto:hello@jobhuntersg.com"
            className="flex items-center gap-2 border border-gray-200 rounded-lg px-4 py-2 text-sm text-gray-600 hover:bg-gray-50 transition">
            <Mail size={14} /> Email
          </a>
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
    } catch (err) {
      console.error("Failed to load tracked jobs:", err);
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
    try {
      await apiFetch("/api/tracked", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      await refreshJobs();
    } catch (err) {
      console.error("Track failed:", err);
    }
  };

  const handleUpdateJob = async (id, updates) => {
    try {
      await apiFetch(`/api/tracked/${id}`, {
        method: "PUT",
        body: JSON.stringify(updates),
      });
      await refreshJobs();
    } catch (err) {
      console.error("Update failed:", err);
    }
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

  // Show auth modal if not logged in
  if (!user) {
    return (
      <div className="min-h-screen bg-gray-50">
        <div className="max-w-5xl mx-auto">
          <div className="bg-gradient-to-r from-indigo-600 to-purple-600 text-white px-6 py-5">
            <h1 className="text-xl font-bold flex items-center gap-2"><Briefcase size={22} /> Job Hunter SG</h1>
            <p className="text-indigo-100 text-sm mt-1">Scrape jobs across SG portals, track applications, get reminders, and generate ATS-optimized resumes.</p>
          </div>
        </div>
        <AuthModal onAuth={handleAuth} />
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
              <p className="text-indigo-100 text-sm mt-1">Scrape jobs across SG portals, track applications, get reminders, and generate ATS-optimized resumes.</p>
            </div>
            <div className="flex items-center gap-3">
              {usageData && (
                <div className="bg-white/15 rounded-lg px-3 py-1.5 text-xs text-indigo-100 hidden sm:block">
                  {usageData.searches_today}/{usageData.searches_limit} searches today
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
            </div>
          </div>
        </div>

        <Nav active={activeTab} setActive={setActiveTab} />

        <div className="p-6">
          {activeTab === "scraper" && (
            <ScraperTab
              user={user}
              trackedJobs={trackedJobs}
              onTrack={handleTrackJob}
              setActiveTab={setActiveTab}
              setSelectedJob={setSelectedJob}
            />
          )}
          {activeTab === "tracker" && (
            <TrackerTab
              user={user}
              jobs={trackedJobs}
              refreshJobs={refreshJobs}
            />
          )}
          {activeTab === "reminders" && (
            <RemindersTab
              jobs={trackedJobs}
              onUpdateJob={handleUpdateJob}
            />
          )}
          {activeTab === "resume" && <ResumeBuilderTab selectedJob={selectedJob} user={user} />}
          {activeTab === "ats" && <ATSTab />}
          {activeTab === "account" && (
            <AccountTab user={user} onLogout={handleLogout} />
          )}
        </div>
      </div>
    </div>
  );
}
