import { useState, useEffect, useMemo, useCallback, useRef } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Search, Plus, ChevronRight, Clock, AlertCircle,
  ExternalLink, Filter, Loader2, FileText,
  MapPin, DollarSign, Building2, X, SlidersHorizontal,
  PanelLeftClose, PanelLeftOpen, CheckCircle2, Bot, Copy,
  Sparkles, RefreshCw,
} from "lucide-react";
import { apiFetch, downloadBlob } from "../lib/api.js";
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

const ARCHIVE_REASON_COPY = {
  source_retired: "No longer present in a completed source crawl.",
  age_retired: "Retired after it was not refreshed for 30 days.",
  closing_date: "Closing date has passed.",
};

const EMPLOYMENT_TYPE_GROUPS = [
  { value: "full_time", label: "Full Time", aliases: ["Full Time", "Full-time"] },
  { value: "part_time", label: "Part Time", aliases: ["Part Time", "Part-time"] },
  { value: "internship", label: "Internship", aliases: ["Internship", "Internship/Attachment"] },
  { value: "permanent", label: "Permanent", aliases: ["Permanent", "Permanent/Contract"] },
  { value: "contract", label: "Contract", aliases: ["Contract", "Fixed Terms", "Permanent/Contract"] },
  { value: "freelance", label: "Freelance", aliases: ["Freelance"] },
];

const normalizeEmploymentType = (value) => String(value || "").toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();

const singaporeToday = () => new Intl.DateTimeFormat("en-CA", {
  timeZone: "Asia/Singapore",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
}).format(new Date());

const formatScrapedDate = (value) => {
  if (!value) return "";
  const timestamp = /(?:Z|[+-]\d{2}:\d{2})$/.test(value) ? value : `${value}Z`;
  const parsed = new Date(timestamp);
  if (Number.isNaN(parsed.getTime())) return "";
  return new Intl.DateTimeFormat("en-SG", {
    timeZone: "Asia/Singapore",
    day: "numeric",
    month: "short",
    year: "numeric",
  }).format(parsed);
};

const dateRangeLabel = (from, to) => {
  if (from && to) return from === to ? from : `${from} to ${to}`;
  if (from) return `from ${from}`;
  return to ? `through ${to}` : "";
};

const buildEmploymentTypeOptions = (rawTypes) => {
  const rawValues = [...new Set((rawTypes || []).map((type) => String(type || "").trim()).filter(Boolean))];
  const used = new Set();
  const grouped = EMPLOYMENT_TYPE_GROUPS.map((group) => {
    const aliasKeys = new Set(group.aliases.map(normalizeEmploymentType));
    const queryValues = rawValues.filter((type) => aliasKeys.has(normalizeEmploymentType(type)));
    queryValues.forEach((type) => used.add(type));
    return queryValues.length > 0 ? { ...group, queryValues } : null;
  }).filter(Boolean);

  const unknown = rawValues
    .filter((type) => !used.has(type))
    .sort((a, b) => a.localeCompare(b))
    .map((type) => ({ value: `raw:${type}`, label: type, queryValues: [type] }));

  return [...grouped, ...unknown];
};

const employmentQueryValuesFor = (selectedTypes, options) => {
  const selected = selectedTypes instanceof Set ? selectedTypes : new Set([selectedTypes].filter(Boolean));
  const byValue = new Map((options || []).map((option) => [option.value, option]));
  const queryValues = new Set();

  for (const value of selected) {
    const option = byValue.get(value);
    const values = option?.queryValues?.length ? option.queryValues : [value];
    values.forEach((queryValue) => queryValues.add(queryValue));
  }

  return [...queryValues];
};

const APPLICATION_VERDICT_LABELS = {
  shortlist: "Shortlist",
  maybe: "Maybe",
  weak_fit: "Weak fit",
};

const formatApplicationPack = (pack) => {
  if (!pack) return "";
  const lines = [];
  const verdict = pack.verdict || {};
  lines.push(`Verdict: ${APPLICATION_VERDICT_LABELS[verdict.decision] || verdict.decision || "Maybe"} (${verdict.fit_score || 0}/100)`);
  if (verdict.rationale) lines.push(verdict.rationale);
  const appendList = (label, items) => {
    if (!Array.isArray(items) || items.length === 0) return;
    lines.push("", label);
    items.forEach((item) => lines.push(`- ${typeof item === "string" ? item : JSON.stringify(item)}`));
  };
  appendList("Strengths", verdict.strengths);
  appendList("Risks", verdict.risks);
  appendList("Missing Terms", pack.ats?.missing_terms);
  appendList("Evidence Questions", (pack.evidence_questions || []).map((q) => q.prompt));
  appendList("Before You Use This", pack.guardrails);
  if (pack.resume?.summary) lines.push("", "Tailored Summary", pack.resume.summary);
  appendList("Bullet Upgrades", (pack.resume?.bullet_upgrades || []).map((b) => `${b.original} -> ${b.rewrite}`));
  if (pack.application_assets?.cover_letter) lines.push("", "Cover Letter", pack.application_assets.cover_letter);
  if (pack.application_assets?.recruiter_dm) lines.push("", "Recruiter DM", pack.application_assets.recruiter_dm);
  if (pack.application_assets?.follow_up_email) lines.push("", "Follow-up Email", pack.application_assets.follow_up_email);
  appendList("Likely Interview Questions", pack.interview?.likely_questions);
  appendList("Questions To Ask", pack.interview?.interviewer_questions);
  return lines.join("\n");
};

const filterOptionClass = (active) => `flex items-center gap-2.5 px-2.5 py-1.5 rounded-lg cursor-pointer transition text-sm ${active ? "bg-[#BDDDFC]/20 text-[#384959] font-medium" : "text-[#384959] hover:bg-[#BDDDFC]/10"}`;

const FilterOption = ({ name, active, onChange, children }) => (
  <label className={filterOptionClass(active)}>
    <input type="radio" name={name} checked={active} onChange={onChange} className="w-3.5 h-3.5 accent-[#384959]" />
    {children}
  </label>
);

const CheckboxFilter = ({ active, onChange, children }) => (
  <label className={filterOptionClass(active)}>
    <input type="checkbox" checked={active} onChange={onChange} className="w-3.5 h-3.5 accent-[#384959] rounded" />
    {children}
  </label>
);

export const trackedWorkspaceFor = (trackedJobs, job) => (trackedJobs || []).find((tracked) => (
  tracked.scraped_job_id != null && String(tracked.scraped_job_id) === String(job.id)
));

export default function ScraperTab({ user, trackedJobs, onTrack, setActiveTab, setSelectedJob, onSignIn }) {
  const [query, setQuery] = useState("");
  const [submittedQuery, setSubmittedQuery] = useState("");
  const [results, setResults] = useState([]);
  const [loading, setLoading] = useState(false);
  const [levelFilter, setLevelFilter] = useState("all");
  const [employmentFilter, setEmploymentFilter] = useState(new Set());
  const [expYearsFilter, setExpYearsFilter] = useState(new Set());
  const [minSalaryFilter, setMinSalaryFilter] = useState("");
  const [filterMeta, setFilterMeta] = useState({ employment_types: [], locations: [], sources: [] });
  const [sortBy, setSortBy] = useState("balanced");
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
  const [sourceFilter, setSourceFilter] = useState("");
  const [directEmployersOnly, setDirectEmployersOnly] = useState(false);
  const [postedFromFilter, setPostedFromFilter] = useState("");
  const [postedToFilter, setPostedToFilter] = useState("");
  const [scrapedFromFilter, setScrapedFromFilter] = useState("");
  const [scrapedToFilter, setScrapedToFilter] = useState("");
  const [powerMatch, setPowerMatch] = useState(null);
  const [minMatchScore, setMinMatchScore] = useState("");
  const [powerGenerating, setPowerGenerating] = useState(false);
  const [powerError, setPowerError] = useState("");
  const [jobsView, setJobsView] = useState("active");
  const jobsRequestRef = useRef({ id: 0, controller: null });
  const activeSearchQuery = submittedQuery;

  const trackedJobIds = useMemo(() => {
    const ids = new Set();
    for (const tj of (trackedJobs || [])) {
      if (tj.scraped_job_id) ids.add(tj.scraped_job_id);
      // Also match by title+company for jobs tracked without ID
      if (tj.company && tj.role) ids.add(`${tj.role}|${tj.company}`.toLowerCase());
    }
    return ids;
  }, [trackedJobs]);

  const [coverLetterModal, setCoverLetterModal] = useState(null); // { job } or null
  const [coverLetterDirection, setCoverLetterDirection] = useState("");
  const [coverLetterText, setCoverLetterText] = useState("");
  const [coverLetterLoading, setCoverLetterLoading] = useState(false);
  const [coverLetterError, setCoverLetterError] = useState("");
  const [coverLetterCopied, setCoverLetterCopied] = useState(false);
  const [coverLetterWorkspaceId, setCoverLetterWorkspaceId] = useState(null);
  const [coverLetterSaveState, setCoverLetterSaveState] = useState("");
  const [coverLetterSaving, setCoverLetterSaving] = useState(false);
  const coverLetterWorkspace = coverLetterModal
    ? trackedWorkspaceFor(trackedJobs, coverLetterModal.job)
    : null;

  const [applicationPackModal, setApplicationPackModal] = useState(null); // { job } or null
  const [applicationPackDirection, setApplicationPackDirection] = useState("");
  const [applicationPack, setApplicationPack] = useState(null);
  const [applicationPackLoading, setApplicationPackLoading] = useState(false);
  const [applicationPackError, setApplicationPackError] = useState("");
  const [applicationPackCopied, setApplicationPackCopied] = useState(false);

  useEffect(() => {
    loadJobs("");
    return () => jobsRequestRef.current.controller?.abort();
  }, []);

  const loadJobs = async (searchQuery, pageNum = 1, nextFilters = {}) => {
    jobsRequestRef.current.controller?.abort();
    const controller = new AbortController();
    const requestId = jobsRequestRef.current.id + 1;
    jobsRequestRef.current = { id: requestId, controller };
    setLoading(true);
    setError("");
    try {
      const normalizedQuery = searchQuery.trim();
      const params = new URLSearchParams({ page: String(pageNum), per_page: "20" });
      const activeLevel = nextFilters.levelFilter ?? levelFilter;
      const activeEmployment = nextFilters.employmentFilter ?? employmentFilter;
      const activeExperience = nextFilters.expYearsFilter ?? expYearsFilter;
      const activeLocations = nextFilters.locationFilter ?? locationFilter;
      const activeMinSalary = nextFilters.minSalaryFilter ?? minSalaryFilter;
      const activeSource = nextFilters.sourceFilter ?? sourceFilter;
      const activeSort = nextFilters.sortBy ?? sortBy;
      const activeDirectEmployersOnly = nextFilters.directEmployersOnly ?? directEmployersOnly;
      const activePostedFrom = nextFilters.postedFromFilter ?? postedFromFilter;
      const activePostedTo = nextFilters.postedToFilter ?? postedToFilter;
      const activeScrapedFrom = nextFilters.scrapedFromFilter ?? scrapedFromFilter;
      const activeScrapedTo = nextFilters.scrapedToFilter ?? scrapedToFilter;
      const activeMinMatchScore = nextFilters.minMatchScore ?? minMatchScore;
      const activeView = nextFilters.jobsView ?? jobsView;

      if (normalizedQuery) params.set("q", normalizedQuery);
      if (activeLevel !== "all") params.set("seniority", activeLevel);
      if (activeSource) params.set("source", activeSource);
      if (activeDirectEmployersOnly) params.set("direct_employers_only", "true");
      if (activeEmployment instanceof Set && activeEmployment.size > 0) {
        params.set("employment_type", employmentQueryValuesFor(activeEmployment, employmentTypeOptions).join(","));
      } else if (typeof activeEmployment === "string" && activeEmployment !== "all") {
        params.set("employment_type", activeEmployment);
      }
      if (activeExperience instanceof Set) {
        activeExperience.forEach((value) => params.append("experience", value));
      }
      if (activeLocations instanceof Set) {
        activeLocations.forEach((value) => params.append("location", value));
      }
      if (String(activeMinSalary).trim()) params.set("min_salary", String(activeMinSalary).trim());
      if (activePostedFrom) params.set("posted_from", activePostedFrom);
      if (activePostedTo) params.set("posted_to", activePostedTo);
      if (activeScrapedFrom) params.set("scraped_from", activeScrapedFrom);
      if (activeScrapedTo) params.set("scraped_to", activeScrapedTo);
      if (String(activeMinMatchScore).trim() && powerMatch?.status === "ready") {
        params.set("min_match_score", String(activeMinMatchScore).trim());
      }
      if (activeView === "expired") params.set("view", "expired");
      params.set("sort", activeSort);
      const activeSector = nextFilters.sectorFilter ?? sectorFilter;
      if (activeSector) params.set("sector", activeSector);

      const resp = await apiFetch(`/api/jobs?${params}`, { method: "GET", signal: controller.signal });
      const data = await resp.json();
      if (jobsRequestRef.current.id !== requestId) return;
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
        scrapedAt: j.scraped_at || "",
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
        powerMatchScore: j.power_match_score,
        powerMatchLabel: j.power_match_label || "",
        archiveReason: j.archive_reason || "",
        retiredAt: j.retired_at || "",
        lastSeen: j.last_seen || j.scraped_at || "",
        closingDate: j.closing_date || "",
      }));
      if (user) setPowerMatch(data.power_match || null);
      setResults(mapped);
      if (pageNum === 1 && data.filter_meta && typeof data.filter_meta === "object") {
        setFilterMeta({
          employment_types: Array.isArray(data.filter_meta.employment_types) ? data.filter_meta.employment_types : [],
          locations: Array.isArray(data.filter_meta.locations) ? data.filter_meta.locations : [],
          sources: Array.isArray(data.filter_meta.sources) ? data.filter_meta.sources : [],
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
      const total = activeView === "expired"
        ? `${Math.max(totalCount, 0).toLocaleString()} known expired postings`
        : `${Math.max(totalCount, 0).toLocaleString()} unique active postings`;
      setTotalLabel(total);
    } catch (err) {
      if (controller.signal.aborted || jobsRequestRef.current.id !== requestId) return;
      if (err.detail?.code === "power_match_not_ready") {
        setPowerMatch(err.detail);
        setMinMatchScore("");
        await loadJobs(searchQuery, pageNum, { ...nextFilters, minMatchScore: "" });
        return;
      }
      setError(err.message || "Failed to load jobs. Please try again.");
      setResults([]);
      setTotalPages(1);
      setTotalLabel("");
      setSubmittedQuery(searchQuery.trim());
    } finally {
      if (jobsRequestRef.current.id === requestId) setLoading(false);
    }
  };

  const handleSearch = () => {
    loadJobs(query, 1);
  };

  const generateBrowseScores = async () => {
    if (!user || powerGenerating) return;
    setPowerGenerating(true);
    setPowerError("");
    try {
      const params = new URLSearchParams({
        limit: "200",
        direct_employers_only: String(directEmployersOnly),
      });
      await apiFetch(`/api/jobs/power-match?${params}`, {
        method: "POST",
        timeoutMs: 45000,
      });
      setMinMatchScore("");
      await loadJobs(activeSearchQuery, 1, { minMatchScore: "" });
    } catch (err) {
      setPowerError(err.message || "Power Match scores could not be generated.");
    } finally {
      setPowerGenerating(false);
    }
  };

  const employmentTypeOptions = useMemo(
    () => buildEmploymentTypeOptions(
      filterMeta.employment_types.length > 0
        ? filterMeta.employment_types.map((type) => type.value)
        : results.map((job) => job.type),
    ),
    [results, filterMeta.employment_types],
  );

  const locationOptions = (filterMeta.locations || []).slice(0, 12);

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
    setCoverLetterWorkspaceId(null);
    setCoverLetterSaveState("");
  };

  const closeCoverLetterModal = () => {
    setCoverLetterModal(null);
    setCoverLetterText("");
    setCoverLetterDirection("");
    setCoverLetterError("");
    setCoverLetterLoading(false);
    setCoverLetterCopied(false);
    setCoverLetterWorkspaceId(null);
    setCoverLetterSaveState("");
    setCoverLetterSaving(false);
  };

  const generateCoverLetter = async () => {
    const resumeText = sessionStorage.getItem("jh_resume_text") || "";
    const job = coverLetterModal?.job;
    if (!job) return;
    if (resumeText.length < 50 && !coverLetterWorkspace?.resume_version_id) {
      setCoverLetterError("Please upload or paste your resume in the Resume tab first (at least 50 characters).");
      return;
    }

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
          workspace_id: coverLetterWorkspace?.id || null,
          job_title: job.title || "",
          job_company: job.company || "",
          job_description: job.description || "",
          user_direction: coverLetterDirection.trim() || null,
        }),
      });
      const data = await resp.json();
      setCoverLetterText(data.cover_letter || "");
      setCoverLetterWorkspaceId(data.workspace_id || null);
      setCoverLetterSaveState(data.saved ? "saved" : "unsaved");
    } catch (err) {
      setCoverLetterError(err.message || "Failed to generate cover letter. Please try again.");
    } finally {
      setCoverLetterLoading(false);
    }
  };

  const saveCoverLetterChanges = async () => {
    if (!coverLetterWorkspaceId || !coverLetterText.trim()) return;
    setCoverLetterSaving(true);
    setCoverLetterError("");
    try {
      await apiFetch(`/api/applications/workspaces/${coverLetterWorkspaceId}/cover-letter`, {
        method: "PUT",
        body: JSON.stringify({ content: coverLetterText }),
      });
      setCoverLetterSaveState("saved");
    } catch (err) {
      setCoverLetterError(err.message || "Failed to save cover letter changes.");
    } finally {
      setCoverLetterSaving(false);
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
    downloadBlob(blob, filename);
  };

  const openApplicationPackModal = (job) => {
    setApplicationPackModal({ job });
    setApplicationPackDirection("");
    setApplicationPack(null);
    setApplicationPackError("");
    setApplicationPackLoading(false);
    setApplicationPackCopied(false);
  };

  const closeApplicationPackModal = () => {
    setApplicationPackModal(null);
    setApplicationPack(null);
    setApplicationPackDirection("");
    setApplicationPackError("");
    setApplicationPackLoading(false);
    setApplicationPackCopied(false);
  };

  const generateApplicationPack = async () => {
    const resumeText = sessionStorage.getItem("jh_resume_text") || "";
    if (!resumeText || resumeText.length < 50) {
      setApplicationPackError("Please upload or paste your resume in the Resume tab first (at least 50 characters).");
      return;
    }
    const job = applicationPackModal?.job;
    if (!job) return;

    setApplicationPackLoading(true);
    setApplicationPackError("");
    setApplicationPack(null);
    setApplicationPackCopied(false);

    try {
      const resp = await apiFetch("/api/ai/application-pack", {
        method: "POST",
        body: JSON.stringify({
          resume_text: resumeText,
          job_id: job.id || null,
          job_title: job.title || "",
          job_company: job.company || "",
          job_description: job.description || "",
          user_direction: applicationPackDirection.trim() || null,
        }),
      });
      const data = await resp.json();
      setApplicationPack(data);
    } catch (err) {
      setApplicationPackError(err.message || "Failed to build the application pack. Please try again.");
    } finally {
      setApplicationPackLoading(false);
    }
  };

  const copyApplicationPack = async () => {
    try {
      await navigator.clipboard.writeText(formatApplicationPack(applicationPack));
      setApplicationPackCopied(true);
      setTimeout(() => setApplicationPackCopied(false), 2000);
    } catch {
      setApplicationPackError("Failed to copy. Please select the text and copy manually.");
    }
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
    sourceFilter !== "",
    directEmployersOnly,
    postedFromFilter !== "" || postedToFilter !== "",
    scrapedFromFilter !== "" || scrapedToFilter !== "",
    String(minMatchScore).trim() !== "",
  ].filter(Boolean).length;

  const clearFilters = () => {
    setLevelFilter("all");
    setEmploymentFilter(new Set());
    setExpYearsFilter(new Set());
    setLocationFilter(new Set());
    setMinSalaryFilter("");
    setSectorFilter("");
    setSourceFilter("");
    setDirectEmployersOnly(false);
    setPostedFromFilter("");
    setPostedToFilter("");
    setScrapedFromFilter("");
    setScrapedToFilter("");
    setMinMatchScore("");
    setExpandedJobId(null);
    loadJobs(activeSearchQuery, 1, {
      levelFilter: "all",
      employmentFilter: new Set(),
      expYearsFilter: new Set(),
      locationFilter: new Set(),
      minSalaryFilter: "",
      sectorFilter: "",
      sourceFilter: "",
      directEmployersOnly: false,
      postedFromFilter: "",
      postedToFilter: "",
      scrapedFromFilter: "",
      scrapedToFilter: "",
      minMatchScore: "",
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

  const sidebarContent = (
    <div className="space-y-5">
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

      {(filterMeta.sources || []).length > 0 && (
        <div>
          <label className="block text-xs font-semibold text-[#6A89A7] uppercase tracking-wide mb-2">Data Source</label>
          <div className="space-y-0.5">
            <FilterOption
              name="source"
              active={!sourceFilter}
              onChange={() => {
                setSourceFilter("");
                loadJobs(activeSearchQuery, 1, { sourceFilter: "" });
              }}
            >
              <span className="flex-1">All sources</span>
            </FilterOption>
            {filterMeta.sources.map((source) => (
              <FilterOption
                key={source.value}
                name="source"
                active={sourceFilter === source.value}
                onChange={() => {
                  setSourceFilter(source.value);
                  loadJobs(activeSearchQuery, 1, { sourceFilter: source.value });
                }}
              >
                <span className="flex-1">{source.label || source.value}</span>
                <span className="text-[11px] tabular-nums text-[#6A89A7]">{Number(source.count || 0).toLocaleString()}</span>
              </FilterOption>
            ))}
          </div>
        </div>
      )}

      <div>
        <label className="block text-xs font-semibold text-[#6A89A7] uppercase tracking-wide mb-2">Employer Type</label>
        <button
          type="button"
          onClick={() => {
            const next = !directEmployersOnly;
            setDirectEmployersOnly(next);
            setMinMatchScore("");
            setPowerMatch(null);
            loadJobs(activeSearchQuery, 1, { directEmployersOnly: next, minMatchScore: "" });
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

      {user && (
        <div>
          <label className="block text-xs font-semibold text-[#6A89A7] uppercase tracking-wide mb-1.5">Minimum Power Match</label>
          <select
            aria-label="Minimum Power Match score"
            value={minMatchScore}
            disabled={powerMatch?.status !== "ready"}
            onChange={(event) => {
              const next = event.target.value;
              setMinMatchScore(next);
              loadJobs(activeSearchQuery, 1, { minMatchScore: next });
            }}
            className="w-full rounded-lg border border-[#BDDDFC]/30 bg-white px-3 py-2 text-sm disabled:cursor-not-allowed disabled:opacity-50"
          >
            <option value="">Any score</option>
            <option value="35">35+ · Stretch</option>
            <option value="55">55+ · Good</option>
            <option value="75">75+ · Strong</option>
          </select>
          {powerMatch?.status !== "ready" && (
            <p className="mt-1.5 text-[11px] leading-tight text-[#6A89A7]">Generate scores for this resume, corpus, and employer mode first.</p>
          )}
        </div>
      )}

      <div>
        <label className="block text-xs font-semibold text-[#6A89A7] uppercase tracking-wide mb-2">Seniority</label>
        <div className="space-y-0.5">
          {levelOptions.map(({ value, label }) => {
            const active = levelFilter === value;
            return (
              <FilterOption
                key={value}
                name="level"
                active={active}
                onChange={() => {
                  const next = active ? "all" : value;
                  setLevelFilter(next);
                  loadJobs(activeSearchQuery, 1, { levelFilter: next });
                }}
              >
                {label}
              </FilterOption>
            );
          })}
        </div>
      </div>

      {employmentTypeOptions.length > 0 && (
        <div>
          <label className="block text-xs font-semibold text-[#6A89A7] uppercase tracking-wide mb-2">Job Type</label>
          <div className="space-y-0.5">
            {employmentTypeOptions.map((option) => {
              const active = employmentFilter.has(option.value);
              return (
                <CheckboxFilter
                  key={option.value}
                  active={active}
                  onChange={() => {
                    const next = new Set(employmentFilter);
                    if (active) next.delete(option.value); else next.add(option.value);
                    setEmploymentFilter(next);
                    loadJobs(activeSearchQuery, 1, { employmentFilter: next });
                  }}
                >
                  {option.label}
                </CheckboxFilter>
              );
            })}
          </div>
        </div>
      )}

      {(filterMeta.sectors || []).length > 0 && (
        <div>
          <label className="block text-xs font-semibold text-[#6A89A7] uppercase tracking-wide mb-2">Industry</label>
          <div className="space-y-0.5">
            <FilterOption
              name="sector"
              active={!sectorFilter}
              onChange={() => { setSectorFilter(""); loadJobs(activeSearchQuery, 1, { sectorFilter: "" }); }}
            >
              All Industries
            </FilterOption>
            {filterMeta.sectors.slice(0, 12).map((s) => (
              <FilterOption
                key={s.value}
                name="sector"
                active={sectorFilter === s.value}
                onChange={() => { setSectorFilter(s.value); loadJobs(activeSearchQuery, 1, { sectorFilter: s.value }); }}
              >
                {s.value}
              </FilterOption>
            ))}
          </div>
        </div>
      )}

      {locationOptions.length > 0 && (
        <div>
          <label className="block text-xs font-semibold text-[#6A89A7] uppercase tracking-wide mb-2">Location</label>
          <div className="space-y-0.5">
            {locationOptions.map((location) => {
              const active = locationFilter.has(location.value);
              return (
                <CheckboxFilter
                  key={location.value}
                  active={active}
                  onChange={() => {
                    const next = new Set(locationFilter);
                    if (active) next.delete(location.value); else next.add(location.value);
                    setLocationFilter(next);
                    loadJobs(activeSearchQuery, 1, { locationFilter: next });
                  }}
                >
                  <span className="flex-1">{location.label || location.value}</span>
                  <span className="text-[11px] tabular-nums text-[#6A89A7]">{Number(location.count || 0).toLocaleString()}</span>
                </CheckboxFilter>
              );
            })}
          </div>
        </div>
      )}

      <div>
        <label className="block text-xs font-semibold text-[#6A89A7] uppercase tracking-wide mb-2">Experience</label>
        <div className="space-y-0.5">
          {["0-2 yrs", "3-5 yrs", "6-10 yrs", "10+ yrs"].map((label) => {
            const active = expYearsFilter.has(label);
            return (
              <CheckboxFilter
                key={label}
                active={active}
                onChange={() => {
                  const next = new Set(expYearsFilter);
                  if (active) next.delete(label); else next.add(label);
                  setExpYearsFilter(next);
                  loadJobs(activeSearchQuery, 1, { expYearsFilter: next });
                }}
              >
                {label}
              </CheckboxFilter>
            );
          })}
        </div>
        {expYearsFilter.size > 0 && (
          <p className="mt-1.5 text-[11px] text-[#6A89A7] leading-tight">
            Jobs without a stated requirement stay visible.
          </p>
        )}
      </div>

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

      <div>
        <label className="block text-xs font-semibold text-[#6A89A7] uppercase tracking-wide mb-2">Posted date</label>
        <div className="grid grid-cols-2 gap-2">
          <label className="min-w-0 text-[11px] text-[#6A89A7]">
            From
            <input
              type="date"
              aria-label="Posted from"
              value={postedFromFilter}
              max={postedToFilter || undefined}
              onChange={(event) => {
                const next = event.target.value;
                setPostedFromFilter(next);
                loadJobs(activeSearchQuery, 1, { postedFromFilter: next });
              }}
              className="mt-1 w-full min-w-0 rounded-lg border border-[#BDDDFC]/30 bg-white px-2 py-2 text-xs text-[#384959]"
            />
          </label>
          <label className="min-w-0 text-[11px] text-[#6A89A7]">
            To
            <input
              type="date"
              aria-label="Posted to"
              value={postedToFilter}
              min={postedFromFilter || undefined}
              onChange={(event) => {
                const next = event.target.value;
                setPostedToFilter(next);
                loadJobs(activeSearchQuery, 1, { postedToFilter: next });
              }}
              className="mt-1 w-full min-w-0 rounded-lg border border-[#BDDDFC]/30 bg-white px-2 py-2 text-xs text-[#384959]"
            />
          </label>
        </div>
      </div>

      <div>
        <div className="mb-2 flex items-center justify-between gap-2">
          <label className="text-xs font-semibold uppercase tracking-wide text-[#6A89A7]">Scraped date</label>
          <button
            type="button"
            onClick={() => {
              const today = singaporeToday();
              setScrapedFromFilter(today);
              setScrapedToFilter(today);
              loadJobs(activeSearchQuery, 1, { scrapedFromFilter: today, scrapedToFilter: today });
            }}
            className="rounded-lg border border-[#BDDDFC]/30 bg-white px-2 py-1 text-[11px] font-medium text-[#384959] hover:bg-[#f0f4f8]"
          >
            Scraped today
          </button>
        </div>
        <div className="grid grid-cols-2 gap-2">
          <label className="min-w-0 text-[11px] text-[#6A89A7]">
            From
            <input
              type="date"
              aria-label="Scraped from"
              value={scrapedFromFilter}
              max={scrapedToFilter || undefined}
              onChange={(event) => {
                const next = event.target.value;
                setScrapedFromFilter(next);
                loadJobs(activeSearchQuery, 1, { scrapedFromFilter: next });
              }}
              className="mt-1 w-full min-w-0 rounded-lg border border-[#BDDDFC]/30 bg-white px-2 py-2 text-xs text-[#384959]"
            />
          </label>
          <label className="min-w-0 text-[11px] text-[#6A89A7]">
            To
            <input
              type="date"
              aria-label="Scraped to"
              value={scrapedToFilter}
              min={scrapedFromFilter || undefined}
              onChange={(event) => {
                const next = event.target.value;
                setScrapedToFilter(next);
                loadJobs(activeSearchQuery, 1, { scrapedToFilter: next });
              }}
              className="mt-1 w-full min-w-0 rounded-lg border border-[#BDDDFC]/30 bg-white px-2 py-2 text-xs text-[#384959]"
            />
          </label>
        </div>
      </div>

      <div>
        <label className="block text-xs font-semibold text-[#6A89A7] uppercase tracking-wide mb-1.5">Sort By</label>
        <select
          value={sortBy}
          onChange={(e) => {
            setSortBy(e.target.value);
            loadJobs(activeSearchQuery, 1, { sortBy: e.target.value });
          }}
          className="w-full text-sm border border-[#BDDDFC]/30 rounded-lg px-3 py-2 bg-white focus:outline-none focus:ring-2 focus:ring-[#BDDDFC] focus:border-[#88BDF2]"
        >
          <option value="balanced">Best mix</option>
          <option value="newest">Newest first</option>
          <option value="salary">Salary (high to low)</option>
        </select>
      </div>

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
      <div className="rounded-2xl bg-white border border-[#BDDDFC]/25 p-6 shadow-sm">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-[#384959]">
              <Search size={18} className="text-white" />
            </div>
            <div>
              <h2 className="font-bold text-[#384959] text-lg">Singapore Jobs</h2>
              <p className="text-sm text-[#6A89A7]">
                {jobsView === "expired"
                  ? "Inspect listings with a known expiry reason. Application actions are disabled."
                  : "Browse jobs from MyCareersFuture and Careers@Gov."}
              </p>
            </div>
          </div>
          <div className="inline-flex w-full rounded-lg bg-[#f0f4f8] p-1 sm:w-auto" aria-label="Job listing view">
            {[{ value: "active", label: "Active jobs" }, { value: "expired", label: "Expired archive" }].map((option) => (
              <button
                key={option.value}
                type="button"
                aria-pressed={jobsView === option.value}
                onClick={() => {
                  setJobsView(option.value);
                  loadJobs(activeSearchQuery, 1, { jobsView: option.value });
                }}
                className={`flex-1 whitespace-nowrap rounded-md px-3 py-2 text-xs font-semibold transition sm:flex-none ${jobsView === option.value ? "bg-white text-[#384959] shadow-sm" : "text-[#6A89A7] hover:text-[#384959]"}`}
              >
                {option.label}
              </button>
            ))}
          </div>
        </div>
        <div className="mt-4 rounded-lg border border-[#88BDF2]/20 bg-[#BDDDFC]/10 px-3 py-2 text-xs text-[#384959]">
          <strong>Beta</strong> -- Free to use with 500 AI requests/day to help fund hosting and API costs. Data refreshes nightly.
        </div>
        {user && (
          <div className="mt-4 flex flex-col gap-3 rounded-xl border border-[#BDDDFC]/30 bg-[#f7fafc] p-3 sm:flex-row sm:items-center sm:justify-between" data-testid="browse-power-match-state">
            <div>
              <div className="flex items-center gap-2 text-sm font-semibold text-[#384959]"><Sparkles size={15} /> Power Match scores</div>
              <p className="mt-1 text-xs text-[#6A89A7]">
                {powerMatch?.message || "Checking for scores saved for this exact resume and job view."}
              </p>
              {powerError && <p className="mt-1 text-xs text-red-600">{powerError}</p>}
            </div>
            <button
              type="button"
              onClick={generateBrowseScores}
              disabled={powerGenerating}
              className="inline-flex min-h-10 items-center justify-center gap-2 rounded-lg bg-[#384959] px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
            >
              {powerGenerating ? <Loader2 size={14} className="animate-spin" /> : powerMatch?.status === "ready" ? <RefreshCw size={14} /> : <Sparkles size={14} />}
              {powerGenerating ? "Generating..." : (powerMatch?.generate_action || "Generate Power Match scores")}
            </button>
          </div>
        )}
      </div>

      <div className="lg:hidden">
        <button
          onClick={() => setSidebarOpen(true)}
          className="flex items-center gap-2 border border-[#BDDDFC]/30 bg-white rounded-lg px-4 py-2.5 text-sm font-medium text-[#384959] hover:bg-[#f0f4f8] transition w-full justify-center"
        >
          <SlidersHorizontal size={16} />
          Filters{activeFilterCount > 0 ? ` (${activeFilterCount})` : ""}
        </button>
      </div>

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

      <div className="flex gap-6 items-start">
        <aside className={`hidden lg:block flex-shrink-0 sticky top-20 max-h-[calc(100vh-5rem)] overscroll-contain transition-all duration-200 ${sidebarCollapsed ? "w-12 overflow-visible" : "w-[280px] overflow-y-auto pr-1"}`}>
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

        <div className="flex-1 min-w-0 space-y-4">
          {totalLabel && (
            <div className="space-y-1">
              <p className="text-sm text-[#6A89A7]">
                <span className="font-medium text-[#384959]">{totalLabel}</span>
                {activeSearchQuery ? ` matching "${activeSearchQuery}"` : " across Singapore"}
                {results.length > 0 && ` -- page ${page}`}
              </p>
              {(postedFromFilter || postedToFilter || scrapedFromFilter || scrapedToFilter) && (
                <p className="text-xs text-[#6A89A7]" aria-live="polite">
                  {dateRangeLabel(postedFromFilter, postedToFilter) && `Posted ${dateRangeLabel(postedFromFilter, postedToFilter)}`}
                  {dateRangeLabel(postedFromFilter, postedToFilter) && dateRangeLabel(scrapedFromFilter, scrapedToFilter) && " · "}
                  {dateRangeLabel(scrapedFromFilter, scrapedToFilter) && `Scraped ${dateRangeLabel(scrapedFromFilter, scrapedToFilter)}`}
                </p>
              )}
            </div>
          )}

          {loading && <JobCardSkeleton count={5} />}

          {!loading && error && (
            <div className="text-center py-8">
              <AlertCircle size={32} className="mx-auto mb-2 text-red-400" />
              <p className="text-sm text-red-600">{error}</p>
            </div>
          )}

          {trackError && (
            <div className="bg-red-50 border border-red-200 text-red-700 text-sm rounded-lg p-3 flex items-center gap-2">
              <AlertCircle size={14} className="flex-shrink-0" />{trackError}
            </div>
          )}

          {!loading && !error && results.length === 0 && (
            <div className="text-center py-12 text-[#6A89A7]">
              <Search size={32} className="mx-auto mb-2 opacity-40" />
              <p>{jobsView === "expired"
                ? "No known expired jobs match these filters."
                : query ? "No jobs matched your search. Try broader keywords." : "No jobs available yet. Please check back later."}</p>
            </div>
          )}

          {!loading && (
          <motion.div
            initial="hidden"
            animate="visible"
            variants={{ visible: { transition: { staggerChildren: 0.04 } } }}
            className="space-y-4"
          >
          {results.map((job, index) => {
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
            const scrapedDate = formatScrapedDate(job.scrapedAt);

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
                  <div className="flex min-w-0 flex-wrap items-center gap-2 mb-1" data-testid={`job-badge-row-${job.id}`}>
                    <h3 className="min-w-0 break-words font-semibold text-[#384959]">{job.title}</h3>
                    {job.level && <span className="shrink-0 text-[10px] bg-[#f0f4f8] text-[#6A89A7] px-2 py-0.5 rounded-full">{job.level}</span>}
                    {jobsView === "expired" && <span className="rounded-full bg-amber-50 px-2 py-0.5 text-[10px] font-semibold text-amber-700 ring-1 ring-amber-200">Expired</span>}
                    {job.sector && job.sector !== "Other" && (
                      <span
                        title={job.companySsicSource === "acra" ? `${job.companySsicCode} ${job.companySsicDescription}` : "Inferred sector"}
                        className={`shrink-0 text-[10px] border px-2 py-0.5 rounded-full ${job.companySsicSource === "acra" ? "bg-emerald-50 text-emerald-700 border-emerald-200" : "bg-violet-50 text-violet-700 border-violet-200"}`}
                      >
                        {job.sector}
                      </span>
                    )}
                    {job.archetype && job.archetype !== "Generalist" && <span className={`shrink-0 text-[10px] border px-2 py-0.5 rounded-full ${ARCHETYPE_COLORS[job.archetype] || "bg-gray-50 text-gray-600 border-gray-200"}`}>{job.archetype}</span>}
                    {Number.isFinite(job.powerMatchScore) && (
                      <span className="shrink-0 text-[10px] border border-indigo-200 bg-indigo-50 px-2 py-0.5 rounded-full font-semibold text-indigo-700" data-testid={`power-match-score-${job.id}`}>
                        {job.powerMatchScore} · {job.powerMatchLabel}
                      </span>
                    )}
                    {(trackedJobIds.has(job.id) || trackedJobIds.has(`${job.title}|${job.company}`.toLowerCase())) && <span className="flex shrink-0 items-center gap-0.5 rounded-full border border-emerald-200 bg-emerald-50 px-1.5 py-0.5 text-[10px] text-emerald-700"><CheckCircle2 size={10} />Tracked</span>}
                    <ChevronRight size={14} className={`ml-auto shrink-0 text-[#6A89A7] transition-transform ${isExpanded ? "rotate-90" : ""}`} />
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
                  {jobsView === "expired" && (
                    <div className="mb-3 rounded-lg border border-amber-200 bg-amber-50/60 px-3 py-2 text-xs text-amber-900">
                      <p className="font-medium">{ARCHIVE_REASON_COPY[job.archiveReason] || "This listing has expired."}</p>
                      <p className="mt-1 text-amber-800">
                        {job.lastSeen && `Last seen ${formatScrapedDate(job.lastSeen)}`}
                        {job.retiredAt && ` · Retired ${formatScrapedDate(job.retiredAt)}`}
                        {!job.retiredAt && job.closingDate && ` · Closed ${job.closingDate}`}
                      </p>
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
                <div className="flex flex-wrap items-center gap-3 text-xs text-[#6A89A7]">
                  {job.source && <span>{job.source}</span>}
                  {job.posted && <span>Posted {job.posted}</span>}
                  {scrapedDate && <span>Scraped {scrapedDate}</span>}
                  {job.type && <span>{job.type}</span>}
                </div>
                {jobsView === "active" && user && isExpanded && (
                  <div className="mb-3" onClick={(e) => e.stopPropagation()}>
                    <InterviewPrep jobId={job.id} user={user} onNavigateToStories={() => setActiveTab("stories")} />
                  </div>
                )}

                {jobsView === "expired" ? (
                  <p className="text-xs font-medium text-amber-700">Archived listing — application actions are unavailable.</p>
                ) : (
                <div className="flex flex-wrap gap-2">
                  <button onClick={(event) => { event.stopPropagation(); openApplicationPackModal(job); }} className="flex items-center gap-1.5 bg-[#384959] text-white px-3 py-1.5 rounded-lg text-xs font-medium hover:bg-[#2d3a47] transition">
                    <Bot size={12} /> Application Pack
                  </button>
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
                )}
              </div>
            </motion.div>
          );
          })}
          </motion.div>
          )}

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
                    {!sessionStorage.getItem("jh_resume_text") && !coverLetterWorkspace?.resume_version_id && (
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
                  <>
                    <textarea
                      value={coverLetterText}
                      onChange={(e) => {
                        setCoverLetterText(e.target.value);
                        if (coverLetterWorkspaceId) setCoverLetterSaveState("dirty");
                      }}
                      className="w-full h-80 px-4 py-3 border border-gray-200 rounded-lg text-sm leading-relaxed resize-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none font-[system-ui]"
                    />
                    <p className={`text-xs ${coverLetterSaveState === "dirty" ? "text-amber-700" : "text-[#6A89A7]"}`}>
                      {coverLetterSaveState === "saved" && "Saved to Documents."}
                      {coverLetterSaveState === "dirty" && "You have unsaved changes."}
                      {coverLetterSaveState === "unsaved" && "Not saved. Track this job to save future letters in Documents."}
                    </p>
                  </>
                )}
              </div>

              <div className="flex items-center justify-between px-6 py-4 border-t border-gray-200 bg-gray-50">
                {coverLetterText ? (
                  <>
                    <span className="text-xs text-[#6A89A7]">
                      {coverLetterText.split(/\s+/).length} words
                    </span>
                    <div className="flex gap-2">
                      {coverLetterWorkspaceId && coverLetterSaveState === "dirty" && (
                        <button
                          onClick={saveCoverLetterChanges}
                          disabled={coverLetterSaving}
                          className="px-4 py-2 text-sm border border-blue-300 rounded-lg text-blue-700 hover:bg-blue-50 transition disabled:opacity-50"
                        >
                          {coverLetterSaving ? "Saving..." : "Save changes"}
                        </button>
                      )}
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

      <AnimatePresence>
        {applicationPackModal && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4"
            onClick={closeApplicationPackModal}
          >
            <motion.div
              initial={{ scale: 0.96, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.96, opacity: 0 }}
              className="bg-white rounded-xl shadow-2xl w-full max-w-4xl max-h-[92vh] flex flex-col overflow-hidden"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <Bot size={18} className="text-[#384959]" />
                    <h3 className="text-lg font-semibold text-[#384959]">Application Pack</h3>
                  </div>
                  <p className="mt-0.5 truncate text-sm text-[#6A89A7]">
                    {applicationPackModal.job?.title} at {applicationPackModal.job?.company}
                  </p>
                </div>
                <button onClick={closeApplicationPackModal} className="p-1 hover:bg-gray-100 rounded-lg transition">
                  <X size={20} className="text-[#6A89A7]" />
                </button>
              </div>

              <div className="flex-1 overflow-y-auto px-6 py-4">
                {!applicationPack && !applicationPackLoading && (
                  <div className="space-y-4">
                    <div>
                      <label className="block text-sm font-medium text-[#384959] mb-1.5">
                        Optional direction
                      </label>
                      <input
                        type="text"
                        value={applicationPackDirection}
                        onChange={(e) => setApplicationPackDirection(e.target.value)}
                        placeholder="e.g. focus on public sector fit, leadership, analytics, or concise outreach"
                        className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-[#88BDF2] focus:border-[#88BDF2] outline-none"
                        maxLength={1000}
                      />
                    </div>
                    {!sessionStorage.getItem("jh_resume_text") && (
                      <p className="text-sm text-amber-700 bg-amber-50 px-3 py-2 rounded-lg">
                        No resume found in this session. Upload or paste your resume in the Resume tab first.
                      </p>
                    )}
                  </div>
                )}

                {applicationPackError && (
                  <div className="mb-4 flex items-start gap-2 text-sm text-red-600 bg-red-50 px-3 py-2 rounded-lg">
                    <AlertCircle size={16} className="mt-0.5 flex-shrink-0" />
                    {applicationPackError}
                  </div>
                )}

                {applicationPackLoading && (
                  <div className="flex flex-col items-center justify-center py-14 gap-3">
                    <Loader2 size={30} className="animate-spin text-[#384959]" />
                    <p className="text-sm text-[#6A89A7]">Analysing the role, resume evidence, gaps, and interview angles...</p>
                  </div>
                )}

                {applicationPack && (
                  <div className="space-y-5">
                    {applicationPack.degraded && (
                      <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
                        The model was unavailable, so this pack uses local ATS signals. Rerun before using final copy.
                      </div>
                    )}

                    {(applicationPack.guardrails || []).length > 0 && (
                      <section className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2">
                        <h4 className="text-sm font-semibold text-amber-900">Before You Use This</h4>
                        <ul className="mt-1 space-y-1 text-sm text-amber-800">
                          {applicationPack.guardrails.map((item, index) => <li key={index}>• {item}</li>)}
                        </ul>
                      </section>
                    )}

                    <div className="grid gap-3 md:grid-cols-3">
                      <div className="rounded-xl border border-[#BDDDFC]/30 bg-[#f8fbff] p-4">
                        <div className="text-xs font-semibold uppercase tracking-[0.14em] text-[#6A89A7]">Verdict</div>
                        <div className="mt-1 text-xl font-bold text-[#384959]">
                          {APPLICATION_VERDICT_LABELS[applicationPack.verdict?.decision] || "Maybe"}
                        </div>
                        <div className="mt-1 text-sm text-[#6A89A7]">{applicationPack.verdict?.fit_score || 0}/100 fit</div>
                      </div>
                      <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-4">
                        <div className="text-xs font-semibold uppercase tracking-[0.14em] text-emerald-700">Matched</div>
                        <div className="mt-1 text-xl font-bold text-emerald-800">
                          {(applicationPack.ats?.matched_terms || []).length}
                        </div>
                        <div className="mt-1 text-sm text-emerald-700">terms already covered</div>
                      </div>
                      <div className="rounded-xl border border-rose-200 bg-rose-50 p-4">
                        <div className="text-xs font-semibold uppercase tracking-[0.14em] text-rose-700">Gaps</div>
                        <div className="mt-1 text-xl font-bold text-rose-800">
                          {(applicationPack.ats?.missing_terms || []).length}
                        </div>
                        <div className="mt-1 text-sm text-rose-700">terms to address carefully</div>
                      </div>
                    </div>

                    {applicationPack.verdict?.rationale && (
                      <section className="border-t border-[#BDDDFC]/30 pt-4">
                        <h4 className="text-sm font-semibold text-[#384959]">Recruiter Read</h4>
                        <p className="mt-2 text-sm leading-relaxed text-[#384959]">{applicationPack.verdict.rationale}</p>
                      </section>
                    )}

                    <div className="grid gap-4 md:grid-cols-2">
                      {(applicationPack.verdict?.strengths || []).length > 0 && (
                        <section className="border-t border-[#BDDDFC]/30 pt-4">
                          <h4 className="text-sm font-semibold text-[#384959]">Strengths</h4>
                          <ul className="mt-2 space-y-1.5 text-sm text-[#384959]">
                            {applicationPack.verdict.strengths.map((item, index) => <li key={index}>• {item}</li>)}
                          </ul>
                        </section>
                      )}
                      {(applicationPack.verdict?.risks || []).length > 0 && (
                        <section className="border-t border-[#BDDDFC]/30 pt-4">
                          <h4 className="text-sm font-semibold text-[#384959]">Risks</h4>
                          <ul className="mt-2 space-y-1.5 text-sm text-[#384959]">
                            {applicationPack.verdict.risks.map((item, index) => <li key={index}>• {item}</li>)}
                          </ul>
                        </section>
                      )}
                    </div>

                    {(applicationPack.evidence_questions || []).length > 0 && (
                      <section className="border-t border-[#BDDDFC]/30 pt-4">
                        <h4 className="text-sm font-semibold text-[#384959]">Evidence Questions</h4>
                        <div className="mt-2 space-y-2">
                          {applicationPack.evidence_questions.map((item, index) => (
                            <div key={item.id || index} className="rounded-lg border border-[#BDDDFC]/25 bg-[#f0f4f8] px-3 py-2">
                              <div className="text-sm font-medium text-[#384959]">{item.prompt}</div>
                              {item.why_it_matters && <div className="mt-1 text-xs text-[#6A89A7]">{item.why_it_matters}</div>}
                            </div>
                          ))}
                        </div>
                      </section>
                    )}

                    {(applicationPack.ats?.missing_terms || []).length > 0 && (
                      <section className="border-t border-[#BDDDFC]/30 pt-4">
                        <h4 className="text-sm font-semibold text-[#384959]">ATS Gaps</h4>
                        <div className="mt-2 flex flex-wrap gap-1.5">
                          {applicationPack.ats.missing_terms.map((term) => (
                            <span key={term} className="rounded-full bg-rose-50 px-2 py-0.5 text-xs font-medium text-rose-700 ring-1 ring-rose-200">
                              {term}
                            </span>
                          ))}
                        </div>
                      </section>
                    )}

                    {applicationPack.resume?.summary && (
                      <section className="border-t border-[#BDDDFC]/30 pt-4">
                        <h4 className="text-sm font-semibold text-[#384959]">Tailored Summary</h4>
                        <p className="mt-2 text-sm leading-relaxed text-[#384959]">{applicationPack.resume.summary}</p>
                      </section>
                    )}

                    {(applicationPack.resume?.bullet_upgrades || []).length > 0 && (
                      <section className="border-t border-[#BDDDFC]/30 pt-4">
                        <h4 className="text-sm font-semibold text-[#384959]">Bullet Upgrades</h4>
                        <div className="mt-2 space-y-3">
                          {applicationPack.resume.bullet_upgrades.map((item, index) => (
                            <div key={index} className="rounded-lg border border-[#BDDDFC]/25 p-3">
                              <div className="text-xs font-semibold uppercase tracking-[0.14em] text-[#6A89A7]">Original</div>
                              <p className="mt-1 text-sm text-[#6A89A7]">{item.original}</p>
                              <div className="mt-3 text-xs font-semibold uppercase tracking-[0.14em] text-[#6A89A7]">Rewrite</div>
                              <p className="mt-1 text-sm font-medium leading-relaxed text-[#384959]">{item.rewrite}</p>
                              {item.needs_user_fact && (
                                <div className="mt-2 rounded-md bg-amber-50 px-2 py-1 text-xs text-amber-800">
                                  Verify facts before using this rewrite.
                                </div>
                              )}
                            </div>
                          ))}
                        </div>
                      </section>
                    )}

                    <div className="grid gap-4 md:grid-cols-2">
                      {applicationPack.application_assets?.cover_letter && (
                        <section className="border-t border-[#BDDDFC]/30 pt-4 md:col-span-2">
                          <h4 className="text-sm font-semibold text-[#384959]">Cover Letter</h4>
                          <textarea
                            value={applicationPack.application_assets.cover_letter}
                            readOnly
                            className="mt-2 h-52 w-full resize-none rounded-lg border border-[#BDDDFC]/30 bg-[#f8fbff] px-3 py-2 text-sm leading-relaxed text-[#384959] outline-none"
                          />
                        </section>
                      )}
                      {applicationPack.application_assets?.recruiter_dm && (
                        <section className="border-t border-[#BDDDFC]/30 pt-4">
                          <h4 className="text-sm font-semibold text-[#384959]">Recruiter DM</h4>
                          <p className="mt-2 whitespace-pre-line text-sm leading-relaxed text-[#384959]">{applicationPack.application_assets.recruiter_dm}</p>
                        </section>
                      )}
                      {applicationPack.application_assets?.follow_up_email && (
                        <section className="border-t border-[#BDDDFC]/30 pt-4">
                          <h4 className="text-sm font-semibold text-[#384959]">Follow-up Email</h4>
                          <p className="mt-2 whitespace-pre-line text-sm leading-relaxed text-[#384959]">{applicationPack.application_assets.follow_up_email}</p>
                        </section>
                      )}
                    </div>

                    {((applicationPack.interview?.likely_questions || []).length > 0 || (applicationPack.interview?.interviewer_questions || []).length > 0) && (
                      <section className="border-t border-[#BDDDFC]/30 pt-4">
                        <h4 className="text-sm font-semibold text-[#384959]">Interview Prep</h4>
                        <div className="mt-2 grid gap-4 md:grid-cols-2">
                          {(applicationPack.interview?.likely_questions || []).length > 0 && (
                            <div>
                              <div className="text-xs font-semibold uppercase tracking-[0.14em] text-[#6A89A7]">Likely Questions</div>
                              <ul className="mt-2 space-y-1.5 text-sm text-[#384959]">
                                {applicationPack.interview.likely_questions.map((item, index) => <li key={index}>• {item}</li>)}
                              </ul>
                            </div>
                          )}
                          {(applicationPack.interview?.interviewer_questions || []).length > 0 && (
                            <div>
                              <div className="text-xs font-semibold uppercase tracking-[0.14em] text-[#6A89A7]">Ask Them</div>
                              <ul className="mt-2 space-y-1.5 text-sm text-[#384959]">
                                {applicationPack.interview.interviewer_questions.map((item, index) => <li key={index}>• {item}</li>)}
                              </ul>
                            </div>
                          )}
                        </div>
                      </section>
                    )}
                  </div>
                )}
              </div>

              <div className="flex items-center justify-between gap-3 px-6 py-4 border-t border-gray-200 bg-gray-50">
                <span className="text-xs text-[#6A89A7]">
                  {applicationPack?.agent?.workflow || "application_pack_v1"}
                </span>
                {applicationPack ? (
                  <button
                    onClick={copyApplicationPack}
                    className="flex items-center gap-1.5 px-4 py-2 text-sm bg-[#384959] text-white rounded-lg hover:bg-[#2d3a47] transition font-medium"
                  >
                    <Copy size={14} />
                    {applicationPackCopied ? "Copied" : "Copy Pack"}
                  </button>
                ) : (
                  <button
                    onClick={generateApplicationPack}
                    disabled={applicationPackLoading}
                    className="flex items-center gap-1.5 px-5 py-2 text-sm bg-[#384959] text-white rounded-lg hover:bg-[#2d3a47] transition font-medium disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {applicationPackLoading ? <Loader2 size={14} className="animate-spin" /> : <Bot size={14} />}
                    {applicationPackLoading ? "Building..." : "Build Pack"}
                  </button>
                )}
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
