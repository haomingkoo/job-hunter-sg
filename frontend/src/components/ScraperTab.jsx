import { useState, useEffect, useMemo, useCallback, useRef } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Search, Plus, ChevronRight, AlertCircle,
  ExternalLink, Loader2, FileText,
  DollarSign, X, SlidersHorizontal,
  PanelLeftClose, PanelLeftOpen, CheckCircle2, Copy,
  RefreshCw,
} from "lucide-react";
import { apiFetch, downloadBlob } from "../lib/api.js";
import { displayJobTitle, formatPostingDate, todayStr } from "../lib/helpers.js";
import { buildJobSkillDisplay, normalizeJobTermLabels } from "../lib/jobSkillHelpers.js";
import JobCardSkeleton from "./JobCardSkeleton.jsx";
import InterviewPrep from "./InterviewPrep.jsx";

const ARCHIVE_REASON_COPY = {
  source_retired: "The job site no longer lists it.",
  age_retired: "Removed after 30 days without an update.",
  closing_date: "The closing date has passed.",
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

const filterOptionClass = (active) => `flex min-h-9 items-center gap-2.5 rounded-md px-2.5 py-1.5 cursor-pointer transition-colors text-sm text-ink ${active ? "bg-tint font-medium" : "hover:bg-tint/60"}`;

const FilterOption = ({ name, active, onChange, children }) => (
  <label className={filterOptionClass(active)}>
    <input type="radio" name={name} checked={active} onChange={onChange} className="h-4 w-4 accent-[#1f5f99]" />
    {children}
  </label>
);

const CheckboxFilter = ({ active, onChange, children }) => (
  <label className={filterOptionClass(active)}>
    <input type="checkbox" checked={active} onChange={onChange} className="h-4 w-4 rounded accent-[#1f5f99]" />
    {children}
  </label>
);

export const trackedWorkspaceFor = (trackedJobs, job) => (trackedJobs || []).find((tracked) => (
  tracked.scraped_job_id != null && String(tracked.scraped_job_id) === String(job.id)
));

export default function ScraperTab({ user, initialQuery = "", trackedJobs, onTrack, setActiveTab, setSelectedJob, onSignIn }) {
  const [query, setQuery] = useState(initialQuery);
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
    loadJobs(initialQuery);
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
      if (activeView === "active" && String(activeMinMatchScore).trim() && powerMatch?.status === "ready") {
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
      const countText = Math.max(totalCount, 0).toLocaleString("en-SG");
      const plural = totalCount === 1 ? "" : "s";
      const total = activeView === "expired" ? `${countText} expired job${plural}` : `${countText} job${plural}`;
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
    jobsView === "active" && String(minMatchScore).trim() !== "",
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
      {(filterMeta.sources || []).length > 0 && (
        <div>
          <h3 className="mb-2 text-sm font-semibold text-ink">Source</h3>
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
                <span className="text-xs tabular-nums text-muted">{Number(source.count || 0).toLocaleString()}</span>
              </FilterOption>
            ))}
          </div>
        </div>
      )}

      <div>
        <h3 className="mb-2 text-sm font-semibold text-ink">Employer type</h3>
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
          className={`flex min-h-10 w-full items-center justify-between gap-3 rounded-md border px-3 text-left text-sm font-medium text-ink transition-colors ${
            directEmployersOnly ? "border-accent bg-tint" : "border-field bg-white hover:bg-tint"
          }`}
        >
          <span>Hide known recruiters</span>
          <span aria-hidden="true" className={`h-5 w-9 rounded-full p-0.5 transition-colors ${directEmployersOnly ? "bg-accent" : "bg-field"}`}>
            <span className={`block h-4 w-4 rounded-full bg-white transition-transform ${directEmployersOnly ? "translate-x-4" : "translate-x-0"}`} />
          </span>
        </button>
        <p className="mt-1.5 text-xs leading-snug text-muted">
          Verified direct and unverified employers remain eligible.
        </p>
      </div>

      {user && jobsView === "active" && (
        <div>
          <label className="block text-sm font-semibold text-ink mb-1.5">Minimum Power Match score</label>
          <select
            aria-label="Minimum Power Match score"
            value={minMatchScore}
            disabled={powerMatch?.status !== "ready"}
            onChange={(event) => {
              const next = event.target.value;
              setMinMatchScore(next);
              loadJobs(activeSearchQuery, 1, { minMatchScore: next });
            }}
            className="min-h-10 w-full rounded-md border border-field bg-white px-3 text-sm disabled:cursor-not-allowed disabled:opacity-60"
          >
            <option value="">Any score</option>
            <option value="35">35+ · Stretch</option>
            <option value="55">55+ · Good</option>
            <option value="75">75+ · Strong</option>
          </select>
          {powerMatch?.status !== "ready" && (
            <p className="mt-1.5 text-xs leading-snug text-muted">Generate scores for this resume, corpus, and employer mode first.</p>
          )}
        </div>
      )}

      <div>
        <h3 className="mb-2 text-sm font-semibold text-ink">Seniority</h3>
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
          <h3 className="mb-2 text-sm font-semibold text-ink">Job type</h3>
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
          <h3 className="mb-2 text-sm font-semibold text-ink">Industry</h3>
          <div className="space-y-0.5">
            <FilterOption
              name="sector"
              active={!sectorFilter}
              onChange={() => { setSectorFilter(""); loadJobs(activeSearchQuery, 1, { sectorFilter: "" }); }}
            >
              All industries
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
          <h3 className="mb-2 text-sm font-semibold text-ink">Location</h3>
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
                  <span className="text-xs tabular-nums text-muted">{Number(location.count || 0).toLocaleString()}</span>
                </CheckboxFilter>
              );
            })}
          </div>
        </div>
      )}

      <div>
        <h3 className="mb-2 text-sm font-semibold text-ink">Experience</h3>
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
          <p className="mt-1.5 text-xs leading-snug text-muted">
            Jobs without a stated requirement stay visible.
          </p>
        )}
      </div>

      <div>
        <label htmlFor="jobs-min-salary" className="block text-sm font-semibold text-ink mb-1.5">Minimum monthly salary</label>
        <div className="flex items-center gap-2">
          <DollarSign size={14} className="text-muted flex-shrink-0" />
          <input
            id="jobs-min-salary"
            type="number"
            min="0"
            value={minSalaryFilter}
            onChange={(e) => setMinSalaryFilter(e.target.value)}
            onBlur={() => loadJobs(activeSearchQuery, 1, { minSalaryFilter })}
            onKeyDown={(e) => {
              if (e.key === "Enter") loadJobs(activeSearchQuery, 1, { minSalaryFilter });
            }}
            placeholder="e.g. 4000"
            className="min-h-10 flex-1 rounded-md border border-field bg-white px-3 text-sm focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/30"
          />
        </div>
        {minSalaryFilter && (
          <p className="mt-1.5 text-xs leading-snug text-muted">
            Jobs with no salary posted stay visible.
          </p>
        )}
      </div>

      <div>
        <h3 className="mb-2 text-sm font-semibold text-ink">Posted date</h3>
        <div className="grid grid-cols-2 gap-2">
          <label className="min-w-0 text-xs text-muted">
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
              className="mt-1 w-full min-w-0 rounded-md border border-field bg-white px-2 py-2 text-xs text-ink"
            />
          </label>
          <label className="min-w-0 text-xs text-muted">
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
              className="mt-1 w-full min-w-0 rounded-md border border-field bg-white px-2 py-2 text-xs text-ink"
            />
          </label>
        </div>
      </div>

      <div>
        <div className="mb-2 flex items-center justify-between gap-2">
          <h3 className="text-sm font-semibold text-ink">Date added</h3>
          <button
            type="button"
            onClick={() => {
              const today = singaporeToday();
              setScrapedFromFilter(today);
              setScrapedToFilter(today);
              loadJobs(activeSearchQuery, 1, { scrapedFromFilter: today, scrapedToFilter: today });
            }}
            className="min-h-9 rounded-md border border-field bg-white px-2.5 text-xs font-medium text-ink hover:bg-tint"
          >
            Added today
          </button>
        </div>
        <div className="grid grid-cols-2 gap-2">
          <label className="min-w-0 text-xs text-muted">
            From
            <input
              type="date"
              aria-label="Added from"
              value={scrapedFromFilter}
              max={scrapedToFilter || undefined}
              onChange={(event) => {
                const next = event.target.value;
                setScrapedFromFilter(next);
                loadJobs(activeSearchQuery, 1, { scrapedFromFilter: next });
              }}
              className="mt-1 w-full min-w-0 rounded-md border border-field bg-white px-2 py-2 text-xs text-ink"
            />
          </label>
          <label className="min-w-0 text-xs text-muted">
            To
            <input
              type="date"
              aria-label="Added to"
              value={scrapedToFilter}
              min={scrapedFromFilter || undefined}
              onChange={(event) => {
                const next = event.target.value;
                setScrapedToFilter(next);
                loadJobs(activeSearchQuery, 1, { scrapedToFilter: next });
              }}
              className="mt-1 w-full min-w-0 rounded-md border border-field bg-white px-2 py-2 text-xs text-ink"
            />
          </label>
        </div>
      </div>

      <div>
        <label htmlFor="jobs-sort" className="block text-sm font-semibold text-ink mb-1.5">Sort by</label>
        <select
          id="jobs-sort"
          value={sortBy}
          onChange={(e) => {
            setSortBy(e.target.value);
            loadJobs(activeSearchQuery, 1, { sortBy: e.target.value });
          }}
          className="min-h-10 w-full rounded-md border border-field bg-white px-3 text-sm focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/30"
        >
          <option value="balanced">Best mix</option>
          <option value="newest">Newest first</option>
          <option value="salary">Salary (high to low)</option>
        </select>
      </div>

      {activeFilterCount > 0 && (
        <button
          onClick={clearFilters}
          className="min-h-10 w-full rounded-md border border-field bg-white px-3 text-sm font-medium text-ink transition-colors hover:bg-tint"
        >
          Clear all filters ({activeFilterCount})
        </button>
      )}
    </div>
  );

  const isTracked = (job) => trackedJobIds.has(job.id) || trackedJobIds.has(`${job.title}|${job.company}`.toLowerCase());

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-1">
        <h1 className="text-xl font-bold tracking-[-0.01em] text-ink">
          {jobsView === "expired" ? "Expired jobs" : "Singapore jobs"}
        </h1>
        <p className="text-sm text-muted">
          {jobsView === "expired"
            ? "Postings that have closed or left their source. You can read them but not apply."
            : "Current postings from MyCareersFuture and Careers@Gov. New jobs are added every night."}
        </p>
      </div>

      <form
        role="search"
        className="flex gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          handleSearch();
        }}
      >
        <label htmlFor="jobs-search" className="sr-only">Search jobs</label>
        <input
          id="jobs-search"
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Role, skill or company"
          enterKeyHint="search"
          className="min-h-11 min-w-0 flex-1 rounded-md border border-field bg-white px-3 text-base text-ink focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/30"
        />
        <button
          type="submit"
          disabled={loading}
          className="inline-flex min-h-11 shrink-0 items-center justify-center gap-2 rounded-md bg-accent px-4 text-sm font-semibold text-white transition-colors hover:bg-accent-hover disabled:opacity-60"
        >
          {loading ? <Loader2 size={16} className="animate-spin" aria-hidden="true" /> : <Search size={16} aria-hidden="true" />}
          <span className="hidden sm:inline">Search</span>
          <span className="sr-only sm:hidden">Search</span>
        </button>
      </form>

      {user && jobsView === "active" && (
        <div className="flex flex-col gap-3 rounded-[10px] border border-line bg-white p-4 sm:flex-row sm:items-center sm:justify-between" data-testid="browse-power-match-state">
          <div>
            <h2 className="text-sm font-semibold text-ink">Power Match scores</h2>
            <p className="mt-1 text-sm text-muted">
              {powerMatch?.message || "Checking for scores saved for this exact resume and job view."}
            </p>
            {powerError && <p className="mt-1 text-sm text-[#b42318]" role="alert">{powerError}</p>}
          </div>
          <button
            type="button"
            onClick={generateBrowseScores}
            disabled={powerGenerating}
            className="inline-flex min-h-10 shrink-0 items-center justify-center gap-2 rounded-md border border-field bg-white px-4 text-sm font-medium text-ink transition-colors hover:bg-tint disabled:opacity-60"
          >
            {powerGenerating ? <Loader2 size={14} className="animate-spin" aria-hidden="true" /> : powerMatch?.status === "ready" ? <RefreshCw size={14} aria-hidden="true" /> : null}
            {powerGenerating ? "Generating..." : (powerMatch?.generate_action || "Generate Power Match scores")}
          </button>
        </div>
      )}

      <div className="lg:hidden">
        <button
          type="button"
          onClick={() => setSidebarOpen(true)}
          className="flex min-h-11 w-full items-center justify-center gap-2 rounded-md border border-field bg-white px-4 text-sm font-medium text-ink transition-colors hover:bg-tint"
        >
          <SlidersHorizontal size={16} aria-hidden="true" />
          Filters{activeFilterCount > 0 ? ` (${activeFilterCount})` : ""}
        </button>
      </div>

      {sidebarOpen && (
        <div className="fixed inset-0 !mt-0 z-50 lg:hidden" role="dialog" aria-modal="true" aria-label="Filters" onKeyDown={(event) => event.key === "Escape" && setSidebarOpen(false)}>
          <div className="absolute inset-0 bg-black/40" onClick={() => setSidebarOpen(false)} />
          <div className="absolute inset-y-0 left-0 w-full max-w-sm overflow-y-auto bg-white shadow-xl">
            <div className="sticky top-0 z-10 flex items-center justify-between border-b border-line bg-white px-5 py-2">
              <h2 className="text-base font-semibold text-ink">Filters</h2>
              <button
                type="button"
                onClick={() => setSidebarOpen(false)}
                className="inline-flex h-11 w-11 items-center justify-center rounded-md text-muted transition-colors hover:bg-tint hover:text-ink"
                aria-label="Close filters"
                autoFocus
              >
                <X size={18} aria-hidden="true" />
              </button>
            </div>
            <div className="p-5">
              {sidebarContent}
            </div>
          </div>
        </div>
      )}

      <div className="flex items-start gap-6">
        <aside className={`sticky top-20 hidden max-h-[calc(100vh-6rem)] flex-shrink-0 overscroll-contain lg:block ${sidebarCollapsed ? "w-12 overflow-visible" : "w-[272px] overflow-y-auto pr-1"}`}>
          {sidebarCollapsed ? (
            <div className="flex flex-col items-center gap-2 rounded-[10px] border border-line bg-white p-1">
              <button
                type="button"
                onClick={() => setSidebarCollapsed(false)}
                className="inline-flex h-10 w-10 items-center justify-center rounded-md text-muted transition-colors hover:bg-tint hover:text-ink"
                aria-label="Show filters"
              >
                <PanelLeftOpen size={16} aria-hidden="true" />
              </button>
              {activeFilterCount > 0 && (
                <span className="pb-1 text-xs font-semibold tabular-nums text-ink" aria-label={`${activeFilterCount} filters on`}>{activeFilterCount}</span>
              )}
            </div>
          ) : (
            <div className="rounded-[10px] border border-line bg-white p-4">
              <div className="mb-4 flex items-center gap-2 border-b border-line pb-2">
                <h2 className="text-base font-semibold text-ink">Filters</h2>
                {activeFilterCount > 0 && (
                  <span className="text-sm tabular-nums text-muted">({activeFilterCount} on)</span>
                )}
                <button
                  type="button"
                  onClick={() => setSidebarCollapsed(true)}
                  className="ml-auto inline-flex h-10 w-10 items-center justify-center rounded-md text-muted transition-colors hover:bg-tint hover:text-ink"
                  aria-label="Hide filters"
                >
                  <PanelLeftClose size={16} aria-hidden="true" />
                </button>
              </div>
              {sidebarContent}
            </div>
          )}
        </aside>

        <div className="min-w-0 flex-1 space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
            <p className="text-sm text-muted" aria-live="polite">
              {totalLabel && (
                <>
                  <span className="font-semibold tabular-nums text-ink">{totalLabel}</span>
                  {activeSearchQuery ? ` matching "${activeSearchQuery}"` : ""}
                  {results.length > 0 && totalPages > 1 && <span className="tabular-nums">{` · page ${page} of ${totalPages.toLocaleString("en-SG")}`}</span>}
                </>
              )}
            </p>
            <div className="inline-flex rounded-md border border-field bg-white p-0.5" role="group" aria-label="Job listing view">
              {[{ value: "active", label: "Current jobs" }, { value: "expired", label: "Expired archive" }].map((option) => (
                <button
                  key={option.value}
                  type="button"
                  aria-pressed={jobsView === option.value}
                  onClick={() => {
                    setJobsView(option.value);
                    loadJobs(activeSearchQuery, 1, { jobsView: option.value });
                  }}
                  className={`min-h-9 whitespace-nowrap rounded px-3 text-xs font-semibold transition-colors ${jobsView === option.value ? "bg-ink text-white" : "text-muted hover:text-ink"}`}
                >
                  {option.label}
                </button>
              ))}
            </div>
          </div>
          {(postedFromFilter || postedToFilter || scrapedFromFilter || scrapedToFilter) && (
            <p className="text-xs text-muted">
              {dateRangeLabel(postedFromFilter, postedToFilter) && `Posted ${dateRangeLabel(postedFromFilter, postedToFilter)}`}
              {dateRangeLabel(postedFromFilter, postedToFilter) && dateRangeLabel(scrapedFromFilter, scrapedToFilter) && " · "}
              {dateRangeLabel(scrapedFromFilter, scrapedToFilter) && `Added ${dateRangeLabel(scrapedFromFilter, scrapedToFilter)}`}
            </p>
          )}

          {loading && <JobCardSkeleton count={5} />}

          {!loading && error && (
            <div className="rounded-[10px] border border-line bg-white px-6 py-10 text-center" role="alert">
              <AlertCircle size={24} aria-hidden="true" className="mx-auto mb-3 text-[#b42318]" />
              <p className="font-semibold text-ink">Jobs could not load</p>
              <p className="mx-auto mt-1 max-w-md text-sm text-muted">
                {/internal server error|bad gateway|service unavailable|gateway timeout/i.test(error)
                  ? "The job search is not responding right now."
                  : error}
              </p>
              <p className="mx-auto mt-1 max-w-md text-sm text-muted">Your search and filters are kept.</p>
              <button
                type="button"
                onClick={() => loadJobs(activeSearchQuery, page)}
                className="mt-5 inline-flex min-h-11 items-center gap-2 rounded-md bg-accent px-5 text-sm font-semibold text-white transition-colors hover:bg-accent-hover"
              >
                <RefreshCw size={14} aria-hidden="true" /> Try again
              </button>
            </div>
          )}

          {trackError && (
            <div className="flex items-center gap-2 rounded-md border border-[#b42318]/30 bg-white p-3 text-sm text-[#b42318]" role="alert">
              <AlertCircle size={14} className="flex-shrink-0" aria-hidden="true" />{trackError}
            </div>
          )}

          {!loading && !error && results.length === 0 && (
            <div className="rounded-[10px] border border-line bg-white px-6 py-12 text-center">
              <p className="font-semibold text-ink">
                {jobsView === "expired" ? "No expired jobs match these filters." : query ? "No jobs match that search." : "No jobs to show yet."}
              </p>
              <p className="mx-auto mt-1 max-w-md text-sm text-muted">
                {jobsView === "expired"
                  ? "Try removing a filter."
                  : query ? (activeFilterCount > 0 ? "Try fewer or broader words, or clear the filters." : "Try fewer or broader words.") : "New jobs are added every night. Check back tomorrow."}
              </p>
              {activeFilterCount > 0 && (
                <button type="button" onClick={clearFilters} className="mt-4 min-h-11 text-sm font-semibold text-accent underline-offset-2 hover:underline">
                  Clear all filters
                </button>
              )}
            </div>
          )}

          {!loading && results.length > 0 && (
          <ul className="space-y-3">
          {results.map((job) => {
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
            const previewSkills = effectiveSkillDisplay.visibleSkills.slice(0, 5);
            const summaryText = (parsedMeta?.jdSummary || job.jdSummary || "").trim();
            const longCueLoad = Boolean(parsedMeta?.loading && parsedMeta?.stalled);
            const cuesWereAlreadyChecked = Boolean(job.jobTermsPreviewReady || parsedMeta?.previewReady);
            const addedDate = formatScrapedDate(job.scrapedAt);
            const postedDate = formatPostingDate(job.posted);
            const tracked = isTracked(job);
            const facts = [
              job.company,
              job.location,
              job.level,
              job.experienceYears && `${job.experienceYears} yrs experience`,
            ].filter(Boolean);
            const meta = [
              job.source,
              postedDate && `Posted ${postedDate}`,
              addedDate && `Added ${addedDate}`,
              job.type,
            ].filter(Boolean);

            return (
            <li key={job.id} className="rounded-[10px] border border-line bg-white">
              <div className="p-4 sm:p-5">
                <div className="grid grid-cols-[minmax(0,1fr)_auto] items-start gap-x-4 gap-y-1">
                  <h3 className="min-w-0 text-base font-semibold leading-6 text-ink">
                    <button
                      type="button"
                      aria-expanded={isExpanded}
                      aria-controls={`job-details-${job.id}`}
                      onClick={() => toggleExpandedJob(job.id)}
                      className="line-clamp-2 rounded-sm text-left [overflow-wrap:anywhere] underline-offset-2 hover:underline"
                    >
                      {displayJobTitle(job.title)}
                    </button>
                  </h3>
                  {job.salary ? (
                    <p className="whitespace-nowrap text-right text-sm font-semibold tabular-nums text-ink">{job.salary}</p>
                  ) : <span />}
                  <p className="col-span-2 text-sm text-muted [overflow-wrap:anywhere]">{facts.join(" · ")}</p>
                </div>

                {(summaryText || job.description) && !isExpanded && (
                  <p className="mt-2 line-clamp-2 max-w-[75ch] text-sm leading-relaxed text-muted">{summaryText || job.description}</p>
                )}
                {!isExpanded && previewSkills.length > 0 && (
                  <p className="mt-2 text-sm text-muted">
                    <span className="font-medium text-ink">Skills: </span>
                    {previewSkills.join(", ")}
                    {effectiveSkillDisplay.visibleSkills.length > previewSkills.length && `, +${effectiveSkillDisplay.visibleSkills.length - previewSkills.length} more`}
                  </p>
                )}

                {jobsView === "expired" && (
                  <div className="mt-3 rounded-md border border-[#92400e]/25 bg-[#fffbeb] px-3 py-2 text-sm text-[#92400e]">
                    <p className="font-medium">{ARCHIVE_REASON_COPY[job.archiveReason] || "This listing has expired."}</p>
                    <p className="mt-1">
                      {job.lastSeen && `Last seen ${formatScrapedDate(job.lastSeen)}`}
                      {job.retiredAt && ` · Removed ${formatScrapedDate(job.retiredAt)}`}
                      {!job.retiredAt && job.closingDate && ` · Closed ${job.closingDate}`}
                    </p>
                  </div>
                )}

                <div className="mt-3 flex flex-wrap items-center justify-between gap-x-4 gap-y-1">
                  <p className="text-xs tabular-nums text-muted">
                    {meta.join(" · ")}
                    {Number.isFinite(job.powerMatchScore) && (
                      <span data-testid={`power-match-score-${job.id}`}>{` · Power Match ${job.powerMatchScore} (${job.powerMatchLabel})`}</span>
                    )}
                  </p>
                  <div className="flex items-center gap-1">
                    {jobsView === "active" && (tracked ? (
                      <span className="inline-flex min-h-9 items-center gap-1 px-2 text-sm font-medium text-[#166534]">
                        <CheckCircle2 size={14} aria-hidden="true" /> Saved
                      </span>
                    ) : (
                      <button
                        type="button"
                        onClick={() => trackJob(job)}
                        className="inline-flex min-h-9 items-center gap-1 rounded-md px-2 text-sm font-medium text-accent transition-colors hover:bg-tint"
                      >
                        <Plus size={14} aria-hidden="true" /> Save
                      </button>
                    ))}
                    <button
                      type="button"
                      aria-expanded={isExpanded}
                      aria-controls={`job-details-${job.id}`}
                      onClick={() => toggleExpandedJob(job.id)}
                      className="inline-flex min-h-9 items-center gap-1 rounded-md px-2 text-sm font-medium text-ink transition-colors hover:bg-tint"
                    >
                      {isExpanded ? "Hide details" : "Details"}
                      <ChevronRight size={14} aria-hidden="true" className={`transition-transform ${isExpanded ? "-rotate-90" : "rotate-90"}`} />
                    </button>
                  </div>
                </div>
              </div>

              {isExpanded && (
                <div id={`job-details-${job.id}`} className="border-t border-line bg-paper/60 px-4 py-4 sm:px-5">
                  {jobsView === "expired" ? (
                    <p className="text-sm font-medium text-[#92400e]">This job has closed, so you can no longer apply.</p>
                  ) : (
                    <div className="flex flex-wrap items-center gap-x-2 gap-y-2">
                      <button
                        type="button"
                        onClick={() => generateResume(job)}
                        className="inline-flex min-h-10 items-center gap-2 rounded-md bg-accent px-4 text-sm font-semibold text-white transition-colors hover:bg-accent-hover"
                      >
                        <FileText size={14} aria-hidden="true" /> Tailor resume
                      </button>
                      <button type="button" onClick={() => openCoverLetterModal(job)} className="inline-flex min-h-10 items-center rounded-md px-3 text-sm font-medium text-accent transition-colors hover:bg-tint">
                        Cover letter
                      </button>
                      <button type="button" onClick={() => openApplicationPackModal(job)} className="inline-flex min-h-10 items-center rounded-md px-3 text-sm font-medium text-accent transition-colors hover:bg-tint">
                        Application pack
                      </button>
                      {job.url && (
                        <a href={job.url} target="_blank" rel="noreferrer" className="inline-flex min-h-10 items-center gap-1 rounded-md px-3 text-sm font-medium text-accent transition-colors hover:bg-tint">
                          Open on {job.source || "source site"} <ExternalLink size={13} aria-hidden="true" />
                          <span className="sr-only">(opens in a new tab)</span>
                        </a>
                      )}
                    </div>
                  )}

                  {job.sector && job.sector !== "Other" && (
                    <p className="mt-4 text-sm text-muted">
                      <span className="font-medium text-ink">Industry: </span>
                      {job.sector}
                      {job.companySsicSource === "acra" ? " (from the company's ACRA registration)" : " (estimated from the posting)"}
                    </p>
                  )}

                  {summaryText && (
                    <>
                      <h4 className="mt-4 text-sm font-semibold text-ink">Summary</h4>
                      <p className="mt-1 max-w-[75ch] text-sm leading-relaxed text-ink">{summaryText}</p>
                    </>
                  )}
                  <h4 className="mt-4 text-sm font-semibold text-ink">{summaryText ? "Full description" : "Description"}</h4>
                  {job.description ? (
                    <p className="mt-1 max-w-[75ch] whitespace-pre-line text-sm leading-relaxed text-ink [overflow-wrap:anywhere]">{job.description}</p>
                  ) : (
                    <p className="mt-1 text-sm text-muted">
                      This posting has no description here.
                      {job.url && " Open it on the source site to read the full posting."}
                    </p>
                  )}

                  <h4 className="mt-4 text-sm font-semibold text-ink">Skills in this posting</h4>
                  {effectiveSkillDisplay.visibleSkills.length > 0 ? (
                    <>
                      <p className="mt-1 max-w-[75ch] text-sm leading-relaxed text-ink">{effectiveSkillDisplay.visibleSkills.join(", ")}</p>
                      {effectiveSkillDisplay.hiddenStudyAreas.length > 0 && (
                        <p className="mt-2 text-xs text-muted">
                          Left out {effectiveSkillDisplay.hiddenStudyAreas.length} broad label{effectiveSkillDisplay.hiddenStudyAreas.length === 1 ? "" : "s"} such as {effectiveSkillDisplay.hiddenStudyAreas.slice(0, 2).join(", ")}.
                        </p>
                      )}
                    </>
                  ) : parsedMeta?.loading && !longCueLoad && !cuesWereAlreadyChecked ? (
                    <p className="mt-1 flex items-center gap-2 text-sm text-muted">
                      <Loader2 size={14} className="animate-spin" aria-hidden="true" />
                      Reading the job description...
                    </p>
                  ) : parsedMeta?.loading && longCueLoad && !cuesWereAlreadyChecked ? (
                    <p className="mt-1 text-sm text-muted">
                      This is taking longer than usual. Close and reopen the details to try again, or open the posting.
                    </p>
                  ) : parsedMeta?.error ? (
                    <p className="mt-1 text-sm text-muted">{parsedMeta.error}</p>
                  ) : cuesWereAlreadyChecked ? (
                    <p className="mt-1 text-sm text-muted">We read this posting but found no clear skills to list.</p>
                  ) : job.skills.length > 0 ? (
                    <p className="mt-1 text-sm text-muted">This posting only lists broad categories, so no specific skills are shown.</p>
                  ) : (
                    <p className="mt-1 text-sm text-muted">No clear skills were found in this posting.</p>
                  )}

                  {jobsView === "active" && user && (
                    <div className="mt-4">
                      <InterviewPrep jobId={job.id} user={user} onNavigateToStories={() => setActiveTab("stories")} />
                    </div>
                  )}
                </div>
              )}
            </li>
          );
          })}
          </ul>
          )}

          {totalPages > 1 && (
            <nav aria-label="Pages" className="flex items-center justify-center gap-3 pt-2">
              {page > 1 && (
                <button type="button" onClick={() => loadJobs(activeSearchQuery, page - 1)} className="min-h-11 rounded-md border border-field bg-white px-4 text-sm font-medium text-ink transition-colors hover:bg-tint">Previous</button>
              )}
              <span className="px-2 text-sm tabular-nums text-muted">Page {page} of {totalPages.toLocaleString("en-SG")}</span>
              {page < totalPages && (
                <button type="button" onClick={() => loadJobs(activeSearchQuery, page + 1)} className="min-h-11 rounded-md border border-field bg-white px-4 text-sm font-medium text-ink transition-colors hover:bg-tint">Next</button>
              )}
            </nav>
          )}
        </div>
      </div>

      <AnimatePresence>
        {coverLetterModal && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 !mt-0 bg-black/50 z-50 flex items-center justify-center p-4"
            onClick={closeCoverLetterModal}
            onKeyDown={(event) => event.key === "Escape" && closeCoverLetterModal()}
            role="dialog"
            aria-modal="true"
            aria-label="Cover letter"
          >
            <motion.div
              initial={{ scale: 0.95, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.95, opacity: 0 }}
              className="bg-white rounded-2xl shadow-2xl w-full max-w-2xl max-h-[90vh] flex flex-col overflow-hidden"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200">
                <div>
                  <h3 className="text-lg font-semibold text-ink">Cover letter</h3>
                  <p className="text-sm text-muted mt-0.5">
                    {coverLetterModal.job?.title} at {coverLetterModal.job?.company}
                  </p>
                </div>
                <button type="button" onClick={closeCoverLetterModal} aria-label="Close" className="inline-flex h-11 w-11 items-center justify-center rounded-md text-muted transition-colors hover:bg-tint hover:text-ink">
                  <X size={20} aria-hidden="true" />
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
                        className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-accent/30 focus:border-accent outline-none"
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
                    <Loader2 size={28} className="animate-spin text-accent" />
                    <p className="text-sm text-muted">Generating your cover letter...</p>
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
                      className="w-full h-80 px-4 py-3 border border-gray-200 rounded-lg text-sm leading-relaxed resize-none focus:ring-2 focus:ring-accent/30 focus:border-accent outline-none font-[system-ui]"
                    />
                    <p className={`text-xs ${coverLetterSaveState === "dirty" ? "text-amber-700" : "text-muted"}`}>
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
                    <span className="text-xs text-muted">
                      {coverLetterText.split(/\s+/).length} words
                    </span>
                    <div className="flex gap-2">
                      {coverLetterWorkspaceId && coverLetterSaveState === "dirty" && (
                        <button
                          onClick={saveCoverLetterChanges}
                          disabled={coverLetterSaving}
                          className="px-4 py-2 text-sm border border-field rounded-md text-ink hover:bg-tint transition disabled:opacity-50"
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
                        className="px-4 py-2 text-sm bg-accent text-white rounded-md hover:bg-accent-hover transition font-medium"
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
                      className="px-5 py-2 text-sm bg-accent text-white rounded-md hover:bg-accent-hover transition font-medium disabled:opacity-50 disabled:cursor-not-allowed"
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
            className="fixed inset-0 !mt-0 bg-black/50 z-50 flex items-center justify-center p-4"
            onClick={closeApplicationPackModal}
            onKeyDown={(event) => event.key === "Escape" && closeApplicationPackModal()}
            role="dialog"
            aria-modal="true"
            aria-label="Application pack"
          >
            <motion.div
              initial={{ scale: 0.96, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.96, opacity: 0 }}
              className="bg-white rounded-2xl shadow-2xl w-full max-w-4xl max-h-[92vh] flex flex-col overflow-hidden"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <h3 className="text-lg font-semibold text-ink">Application pack</h3>
                  </div>
                  <p className="mt-0.5 truncate text-sm text-muted">
                    {applicationPackModal.job?.title} at {applicationPackModal.job?.company}
                  </p>
                </div>
                <button type="button" onClick={closeApplicationPackModal} aria-label="Close" className="inline-flex h-11 w-11 items-center justify-center rounded-md text-muted transition-colors hover:bg-tint hover:text-ink">
                  <X size={20} aria-hidden="true" />
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
                    <p className="text-sm text-muted">Reading the posting and your resume...</p>
                  </div>
                )}

                {applicationPack && (
                  <div className="space-y-5">
                    {applicationPack.degraded && (
                      <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
                        The writing service was busy, so this pack is based on keyword matching only. Try again before you use the wording.
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
                        <div className="text-xs font-semibold uppercase tracking-[0.14em] text-muted">Verdict</div>
                        <div className="mt-1 text-xl font-bold text-[#384959]">
                          {APPLICATION_VERDICT_LABELS[applicationPack.verdict?.decision] || "Maybe"}
                        </div>
                        <div className="mt-1 text-sm text-muted">{applicationPack.verdict?.fit_score || 0}/100 fit</div>
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
                              {item.why_it_matters && <div className="mt-1 text-xs text-muted">{item.why_it_matters}</div>}
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
                              <div className="text-xs font-semibold uppercase tracking-[0.14em] text-muted">Original</div>
                              <p className="mt-1 text-sm text-muted">{item.original}</p>
                              <div className="mt-3 text-xs font-semibold uppercase tracking-[0.14em] text-muted">Rewrite</div>
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
                              <div className="text-xs font-semibold uppercase tracking-[0.14em] text-muted">Likely Questions</div>
                              <ul className="mt-2 space-y-1.5 text-sm text-[#384959]">
                                {applicationPack.interview.likely_questions.map((item, index) => <li key={index}>• {item}</li>)}
                              </ul>
                            </div>
                          )}
                          {(applicationPack.interview?.interviewer_questions || []).length > 0 && (
                            <div>
                              <div className="text-xs font-semibold uppercase tracking-[0.14em] text-muted">Ask Them</div>
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
                <span />
                {applicationPack ? (
                  <button
                    onClick={copyApplicationPack}
                    className="flex min-h-10 items-center gap-1.5 rounded-md bg-accent px-4 text-sm font-semibold text-white transition-colors hover:bg-accent-hover"
                  >
                    <Copy size={14} aria-hidden="true" />
                    {applicationPackCopied ? "Copied" : "Copy pack"}
                  </button>
                ) : (
                  <button
                    onClick={generateApplicationPack}
                    disabled={applicationPackLoading}
                    className="flex min-h-10 items-center gap-1.5 rounded-md bg-accent px-5 text-sm font-semibold text-white transition-colors hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    {applicationPackLoading && <Loader2 size={14} className="animate-spin" aria-hidden="true" />}
                    {applicationPackLoading ? "Building..." : "Build pack"}
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
