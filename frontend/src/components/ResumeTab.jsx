// ResumeTab component extracted from App.jsx (Phase 3)

import { useState, useEffect, useMemo, useCallback, useRef, Fragment, memo } from "react";
import {
  Search, FileText, Plus, X, ChevronRight,
  CheckCircle, AlertCircle, Trash2, Edit3,
  RefreshCw, Zap, Download, Star,
  Loader2, Sparkles, UploadCloud, Printer,
  Check, ArrowLeft, ArrowRight, ArrowUp, ArrowDown, List, Type, GripVertical,
  Send,
} from "lucide-react";
import { DndContext, closestCenter, PointerSensor, useSensor, useSensors } from "@dnd-kit/core";
import { SortableContext, verticalListSortingStrategy, useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";

import { API_BASE, apiFetch, clearResumeDraftStorage } from "../lib/api.js";
import { titleCase, extractKeywordLabel, getScoreTheme } from "../lib/helpers.js";
import { buildJobSkillDisplay, cleanAlignmentTerms } from "../lib/jobSkillHelpers.js";
import {
  DEFAULT_RESUME_TEMPLATES,
  NUS_RESUME_BENCHMARKS,
  RESUME_BULLET_RE,
  RESUME_TEMPLATE_SECTION_ORDER,
  RESUME_SECTION_LABELS,
  TAILOR_STAGE_LABELS,
  ADD_SECTION_OPTIONS,
} from "../lib/resumeConstants.js";
import {
  buildResumeTemplateStyles,
  isResumeActionVerb,
  splitEducationMeta,
  getInlineResumeSegments,
  normalizeScoreData,
  getStatusMeta,
  buildResumeKeywords,
  buildSkillAlignment,
  computeKeywordInsertSuggestions,
  isLikelySummaryLeadParagraph,
  isShoutySummaryParagraph,
  toSentenceCaseDisplayText,
  getDisplayParagraphText,
  getDisplayInlineSegmentText,
  getDisplaySubheadingText,
  looksLikeDateOnlyText,
  analyzeBulletFeedback,
  parseResumeToSections,
  extractResumeHeaderMeta,
  renderHighlightedText,
  updateResumeLine,
  insertResumeLineAfter,
  removeResumeSectionBlock,
  groupEducationSections,
  promoteLineToPosition,
  promoteLineToSection,
  demoteLineToBullet,
  moveResumeBullet,
  moveSectionInText,
  getDownloadFilename,
  normalizeReviewSuggestion,
  summarizeTailoringChanges,
  getAtsGapKey,
  getBulletFeedbackTabs,
  getBulletRewriteFocus,
  getRewriteButtonLabel,
  getRewriteCacheKey,
  isRewriteResultCurrent,
  getIssueLabel,
  evaluateRewriteOption,
  getRewriteOptionMeta,
  rankRewriteOptions,
  buildFocusedFeedbackContext,
} from "../lib/resumeHelpers.jsx";

const RESUME_UNDO_LIMIT = 30;

export function buildAgentJobContext(job) {
  if (!job) return undefined;
  return {
    title: job.title || "",
    company: job.company || "",
    description: job.description || "",
    terms: job.jobTermsPreview || job.skills || [],
    location: job.location || "",
    source: job.source || "",
  };
}

export function buildAgentScoreContext(score) {
  if (!score || !Number.isFinite(score.overall_score)) return undefined;
  return {
    overall_score: score.overall_score,
    quality_score: score.quality_score,
    dimensions: Object.fromEntries(
      Object.entries(score.dimensions || {}).map(([name, value]) => [
        name,
        { score: value?.score, max: value?.max },
      ]),
    ),
    keyword_match: {
      matched: score.keyword_match?.matched?.length || 0,
      missing: score.keyword_match?.missing?.length || 0,
      score_percent: score.keyword_match?.score_percent || 0,
    },
  };
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
    <div className="rounded-xl border border-[#BDDDFC]/30 bg-gradient-to-br from-white to-gray-50 p-3">
      <div className={`h-2 w-2/5 rounded-full ${accent}`} />
      <div className="mt-3 space-y-1.5">
        <div className="h-1.5 w-full rounded-full bg-[#BDDDFC]/20" />
        <div className="h-1.5 w-11/12 rounded-full bg-[#BDDDFC]/20" />
        <div className="h-1.5 w-10/12 rounded-full bg-[#BDDDFC]/20" />
      </div>
      <div className="mt-4 space-y-1.5">
        <div className={`h-1.5 w-1/3 rounded-full ${accent} opacity-80`} />
        <div className="h-1.5 w-full rounded-full bg-[#BDDDFC]/20" />
        <div className="h-1.5 w-10/12 rounded-full bg-[#BDDDFC]/20" />
        <div className="h-1.5 w-4/5 rounded-full bg-[#BDDDFC]/20" />
      </div>
    </div>
  );
}

const RESUME_CHAT_STAGE_META = {
  contact: {
    label: "Contact details",
    description: "Share your name and the best email, phone, or location details for the header.",
    remaining: ["Name", "Email / phone", "Location"],
  },
  summary: {
    label: "Target role",
    description: "Tell us what role you want and roughly how many years of experience you have.",
    remaining: ["Target role", "Years of experience"],
  },
  experience_1: {
    label: "Recent experience",
    description: "We still need at least one role with concrete achievements before we can draft the resume.",
    remaining: ["Latest job", "2-3 achievements", "Metrics or scope"],
  },
  experience_2: {
    label: "More experience",
    description: "Add another role if relevant, or tell the coach you are done with work history.",
    remaining: ["Another role or 'done'"],
  },
  education: {
    label: "Education",
    description: "A degree, school, and graduation year are enough to keep moving.",
    remaining: ["Degree", "School", "Year"],
  },
  skills: {
    label: "Skills",
    description: "List your tools, strengths, certifications, or domain skills so the draft feels complete.",
    remaining: ["Skills", "Certifications"],
  },
  done: {
    label: "Ready to draft",
    description: "You have shared enough for a first draft. Generate it now or switch to a blank starter.",
    remaining: [],
  },
};

function getResumeChatStageMeta(stage, readyToGenerate) {
  if (readyToGenerate) return RESUME_CHAT_STAGE_META.done;
  return RESUME_CHAT_STAGE_META[stage] || RESUME_CHAT_STAGE_META.contact;
}

function buildBlankResumeStarter(profile = {}) {
  const name = String(profile.name || "").trim() || "Your Name";
  const contactLine = [profile.email, profile.phone, profile.location]
    .map((value) => String(value || "").trim())
    .filter(Boolean)
    .join(" | ");

  return [
    name,
    contactLine,
    "",
    "PROFESSIONAL SUMMARY",
    "Add a 2-3 sentence summary of your background, strengths, and target role.",
    "",
    "PROFESSIONAL EXPERIENCE",
    "Job Title",
    "Company | Location | Start – End",
    "• Add a measurable achievement.",
    "• Add a project, scope, or business outcome.",
    "",
    "EDUCATION",
    "Degree – School (Year)",
    "",
    "SKILLS",
    "Skill 1, Skill 2, Skill 3",
  ].join("\n");
}

const POINTER_SENSOR_CONFIG = { activationConstraint: { distance: 5 } };

const SortableBulletItem = memo(function SortableBulletItem({ id, children }) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id });
  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
    zIndex: isDragging ? 10 : undefined,
  };
  return (
    <div ref={setNodeRef} style={style} {...attributes}>
      <div className="flex items-start">
        <button
          type="button"
          {...listeners}
          className="cursor-grab active:cursor-grabbing opacity-0 group-hover/section:opacity-60 transition-opacity mt-2 -ml-4 px-0.5 text-[#6A89A7]/60 hover:text-[#6A89A7] shrink-0"
          aria-label="Drag to reorder bullet"
          title="Drag to reorder"
        >
          <GripVertical size={12} />
        </button>
        <div className="flex-1 min-w-0">{children}</div>
      </div>
    </div>
  );
});

export default function ResumeTab({ selectedJob, user, setActiveTab }) {
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
  const undoStackRef = useRef([]);
  const redoStackRef = useRef([]);
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
  const [uploadWarnings, setUploadWarnings] = useState([]);
  const [dragOver, setDragOver] = useState(false);
  const [pastedText, setPastedText] = useState("");
  const [resumeVersions, setResumeVersions] = useState([]);
  const [versionsLoading, setVersionsLoading] = useState(false);
  const [saveVersionLabel, setSaveVersionLabel] = useState("");
  const [savingVersion, setSavingVersion] = useState(false);
  const [renamingVersionId, setRenamingVersionId] = useState(null);
  const [renamingVersionLabel, setRenamingVersionLabel] = useState("");
  const [deletingVersionId, setDeletingVersionId] = useState(null);
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
  const [regeneratingSummary, setRegeneratingSummary] = useState(false);
  const [summaryDirection, setSummaryDirection] = useState("");
  const [showSummaryPrompt, setShowSummaryPrompt] = useState(false);
  const [showSetupPanel, setShowSetupPanel] = useState(() => !resumeText.trim());
  const [workspaceView, setWorkspaceView] = useState("feedback");
  const [mobilePanel, setMobilePanel] = useState("edit");
  const [showVersionDropdown, setShowVersionDropdown] = useState(false);
  const [selectedBulletId, setSelectedBulletId] = useState(null);
  const [mobileBulletSheet, setMobileBulletSheet] = useState(null);
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
  const [insertKeywordPopup, setInsertKeywordPopup] = useState(null);
  const [wizardStep, setWizardStep] = useState(() => {
    try {
      const saved = Number(sessionStorage.getItem("jh_wizard_step"));
      if (saved >= 1 && saved <= 4) return saved;
    } catch {
      // ignore corrupt data
    }
    // Default: if resume text exists in session, start at step 3; otherwise step 1
    try {
      const text = sessionStorage.getItem("jh_resume_text") || "";
      return text.trim() ? 3 : 1;
    } catch {
      return 1;
    }
  });

  const fileInputRef = useRef(null);
  const scorePanelRef = useRef(null);
  const selectedFeedbackRef = useRef(null);
  const initialScoredRef = useRef(false);
  const previousJobDescriptionRef = useRef("");
  const tailoringPollAttemptsRef = useRef(0);
  const resumePrintRef = useRef(null);

  const [downloadingPdf, setDownloadingPdf] = useState(false);

  // ── Resume Chat Builder state ──────────────────────────────────
  const [showResumeChat, setShowResumeChat] = useState(false);
  const [chatMessages, setChatMessages] = useState([]);
  const [chatInput, setChatInput] = useState("");
  const [chatLoading, setChatLoading] = useState(false);
  const [chatReady, setChatReady] = useState(false);
  const [chatStage, setChatStage] = useState("contact");
  const [chatError, setChatError] = useState("");
  const [activeSuggestionHint, setActiveSuggestionHint] = useState(null);
  const [selectedInjectKeyword, setSelectedInjectKeyword] = useState(null);
  const chatEndRef = useRef(null);
  const [editorMode, setEditorMode] = useState("classic");
  const [agentInput, setAgentInput] = useState("");
  const [agentProfileContext, setAgentProfileContext] = useState("");
  const [agentMessages, setAgentMessages] = useState([]);
  const [agentSessionId, setAgentSessionId] = useState(() => {
    try {
      return sessionStorage.getItem("jh_resume_agent_session") || "";
    } catch {
      return "";
    }
  });
  const [agentRunStatus, setAgentRunStatus] = useState(() => (agentSessionId ? "queued" : "idle"));
  const [agentLoading, setAgentLoading] = useState(Boolean(agentSessionId));
  const [agentElapsedSeconds, setAgentElapsedSeconds] = useState(0);
  const [agentProgress, setAgentProgress] = useState("");
  const [agentError, setAgentError] = useState("");
  const [agentTodos, setAgentTodos] = useState([]);
  const [agentFindings, setAgentFindings] = useState([]);
  const [agentAssessment, setAgentAssessment] = useState({});
  const [agentWorkerRuns, setAgentWorkerRuns] = useState([]);
  const [agentToolSpans, setAgentToolSpans] = useState([]);
  const [agentPendingDiffs, setAgentPendingDiffs] = useState([]);
  const [agentDocument, setAgentDocument] = useState(null);
  const [agentApplyingDiffId, setAgentApplyingDiffId] = useState("");
  const lastAgentResponseRef = useRef("");
  const agentEvidenceById = useMemo(
    () => new Map((agentDocument?.blocks || []).map((block) => [block.id, block])),
    [agentDocument],
  );

  useEffect(() => {
    if (!agentLoading) return undefined;
    const startedAt = Date.now();
    setAgentElapsedSeconds(0);
    const interval = window.setInterval(() => {
      setAgentElapsedSeconds(Math.floor((Date.now() - startedAt) / 1000));
    }, 1000);
    return () => window.clearInterval(interval);
  }, [agentLoading]);

  const openMobileFeedbackPanel = useCallback((targetRef = scorePanelRef) => {
    if (typeof window === "undefined" || window.innerWidth >= 1024) return;
    setMobilePanel("feedback");
    window.requestAnimationFrame(() => {
      window.requestAnimationFrame(() => {
        targetRef?.current?.scrollIntoView({ behavior: "smooth", block: "start" });
      });
    });
  }, []);

  const resetResumeChat = useCallback(() => {
    setShowResumeChat(false);
    setChatMessages([]);
    setChatInput("");
    setChatLoading(false);
    setChatReady(false);
    setChatStage("contact");
    setChatError("");
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
    try {
      sessionStorage.setItem("jh_wizard_step", String(wizardStep));
    } catch {
      // ignore quota failures
    }
  }, [wizardStep]);

  // Auto-advance wizard: step 1 -> 2 when resume text appears
  const prevResumeTextRef = useRef(resumeText);
  useEffect(() => {
    const wasFilled = prevResumeTextRef.current.trim().length > 0;
    const isFilled = resumeText.trim().length > 0;
    prevResumeTextRef.current = resumeText;
    if (!wasFilled && isFilled && wizardStep === 1) {
      setWizardStep(2);
    }
  }, [resumeText, wizardStep]);

  useEffect(() => {
    let interval = null;

    const fetchStatus = () => fetch(`${API_BASE}/api/ai/status`)
      .then((response) => response.json())
      .then(setAiStatus)
      .catch(() => {});

    const start = () => {
      if (interval) return;
      fetchStatus();
      interval = setInterval(fetchStatus, 60000);
    };

    const stop = () => {
      if (!interval) return;
      clearInterval(interval);
      interval = null;
    };

    const handleVisibility = () => {
      if (document.hidden) stop();
      else start();
    };

    if (!document.hidden) start();
    document.addEventListener("visibilitychange", handleVisibility);

    return () => {
      stop();
      document.removeEventListener("visibilitychange", handleVisibility);
    };
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
            const resultResponse = await apiFetch(`/api/resume/tailor/${tailoringSessionId}/result`, {
              method: "POST",
            });
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
        body: JSON.stringify({ resume_text: text, job_description: (jd || "").slice(0, 8000), template_id: selectedTemplate }),
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
  }, [jobDescription, scoreData, selectedTemplate]);

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
    setSelectedInjectKeyword(null);
  }, [selectedBulletId, selectedJob?.id]);

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
    setActiveSuggestionHint(null);
  }, [selectedJob?.id]);

  // Close keyword insert popup when resume text changes or job changes
  useEffect(() => {
    setInsertKeywordPopup(null);
  }, [resumeText, selectedJob?.id]);

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

  const applyResumeText = useCallback((nextText, { rescore = false, clearRewrites = false, preserveTailoringContext = false, _isUndo = false } = {}) => {
    // Push current text to undo stack unless this IS an undo/redo.
    if (!_isUndo && resumeText && resumeText !== nextText) {
      undoStackRef.current = [...undoStackRef.current.slice(-(RESUME_UNDO_LIMIT - 1)), resumeText];
      redoStackRef.current = [];
    }
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
      initialScoredRef.current = true;
      runScore(nextText, jobDescription, { phase: "opening" });
    } else {
      setNeedsRescore(Boolean(nextText.trim()));
      if (nextText.trim()) setScorePhase("editing");
    }
  }, [jobDescription, runScore, resumeText]);

  const refreshAgentState = useCallback(async (nextSessionId) => {
    if (!nextSessionId) return;
    const response = await apiFetch(`/api/resume/agent/${nextSessionId}/state`);
    const data = await response.json();
    setAgentTodos(Array.isArray(data.todos) ? data.todos : []);
    setAgentFindings(Array.isArray(data.persona_findings) ? data.persona_findings : []);
    setAgentAssessment(data.multi_agent_assessment || {});
    setAgentWorkerRuns(Array.isArray(data.worker_runs) ? data.worker_runs : []);
    setAgentToolSpans(Array.isArray(data.tool_spans) ? data.tool_spans : []);
    setAgentPendingDiffs(Array.isArray(data.pending_diffs) ? data.pending_diffs : []);
    setAgentDocument(data.document?.schema_version === 1 ? data.document : null);
    setAgentRunStatus(data.status || "idle");
    setAgentProgress(data.progress || "");
    setAgentLoading(["queued", "running"].includes(data.status));
    if (data.error) setAgentError(data.error);
    if (data.response && data.response !== lastAgentResponseRef.current) {
      lastAgentResponseRef.current = data.response;
      setAgentMessages((current) => [...current, { role: "assistant", content: data.response }]);
    }
    return data;
  }, []);

  useEffect(() => {
    if (!agentSessionId || !["queued", "running"].includes(agentRunStatus)) return undefined;
    let cancelled = false;
    let timeoutId = null;
    const poll = async () => {
      try {
        const data = await refreshAgentState(agentSessionId);
        if (!cancelled && ["queued", "running"].includes(data.status)) {
          timeoutId = window.setTimeout(poll, 1000);
        }
      } catch (err) {
        if (!cancelled) {
          setAgentLoading(false);
          setAgentRunStatus("failed");
          setAgentError(err.message || "Could not reconnect to this review.");
        }
      }
    };
    poll();
    return () => {
      cancelled = true;
      if (timeoutId) window.clearTimeout(timeoutId);
    };
  }, [agentRunStatus, agentSessionId, refreshAgentState]);

  const handleAgentSend = useCallback(async () => {
    const message = agentInput.trim();
    if (!message || agentLoading) return;
    setAgentInput("");
    setAgentError("");
    setAgentLoading(true);
    setAgentAssessment({});
    setAgentWorkerRuns([]);
    setAgentToolSpans([]);
    setAgentProgress("Reading resume evidence");
    lastAgentResponseRef.current = "";
    setAgentMessages((current) => [...current, { role: "user", content: message }]);
    try {
      const response = await apiFetch("/api/resume/agent/start", {
        method: "POST",
        body: JSON.stringify({
          session_id: agentSessionId || undefined,
          message,
          resume_text: resumeText,
          profile_context: agentProfileContext.trim() || undefined,
          job_id: selectedJob?.id || undefined,
          job_context: buildAgentJobContext(selectedJob),
          score_context: buildAgentScoreContext(scoreData),
        }),
      });
      const data = await response.json();
      const nextSessionId = data.session_id || "";
      setAgentSessionId(nextSessionId);
      setAgentRunStatus(data.status || "queued");
      setAgentProgress("Waiting for reviewers");
      try {
        sessionStorage.setItem("jh_resume_agent_session", nextSessionId);
      } catch {
        // Review still runs; only automatic reconnection is unavailable.
      }
    } catch (err) {
      setAgentError(err.message || "Agent Review is unavailable right now.");
      setAgentLoading(false);
      setAgentRunStatus("failed");
    }
  }, [agentInput, agentLoading, agentProfileContext, agentSessionId, resumeText, scoreData, selectedJob]);

  const handleAgentDiffDecision = useCallback(async (bulletId, decision) => {
    if (decision !== "accept") {
      if (!agentSessionId) return;
      setAgentApplyingDiffId(bulletId);
      setAgentError("");
      try {
        const response = await apiFetch(`/api/resume/agent/${agentSessionId}/dismiss`, {
          method: "POST",
          body: JSON.stringify({ bullet_id: bulletId }),
        });
        const data = await response.json();
        setAgentPendingDiffs(Array.isArray(data.pending_diffs) ? data.pending_diffs : []);
      } catch (err) {
        setAgentError(err.message || "Could not dismiss this resume edit.");
      } finally {
        setAgentApplyingDiffId("");
      }
      return;
    }
    const target = agentPendingDiffs.find((diff) => diff.bullet_id === bulletId);
    if (!target || !agentSessionId || !target.document_revision) return;
    setAgentApplyingDiffId(bulletId);
    setAgentError("");
    try {
      const response = await apiFetch(`/api/resume/agent/${agentSessionId}/apply`, {
        method: "POST",
        body: JSON.stringify({
          bullet_id: bulletId,
          expected_revision: target.document_revision,
        }),
      });
      const data = await response.json();
      applyResumeText(data.draft, { preserveTailoringContext: true });
      setAgentPendingDiffs(Array.isArray(data.pending_diffs) ? data.pending_diffs : []);
      setAgentDocument(data.document?.schema_version === 1 ? data.document : null);
    } catch (err) {
      setAgentError(err.message || "Could not safely apply this resume edit.");
    } finally {
      setAgentApplyingDiffId("");
    }
  }, [agentPendingDiffs, agentSessionId, applyResumeText]);

  const startBlankResumeFlow = useCallback(() => {
    const starterResume = buildBlankResumeStarter(profile);
    setSelectedBulletId(null);
    setEditingNodeId(null);
    setCoachResponse(null);
    setCoachError("");
    setSessionId("");
    setShowSetupPanel(false);
    setWizardStep(2);
    resetResumeChat();
    applyResumeText(starterResume, { clearRewrites: true });
  }, [applyResumeText, profile, resetResumeChat]);

  const generateWithWhatWeHave = useCallback(async () => {
    setChatLoading(true);
    setChatError("");
    try {
      const resp = await apiFetch("/api/ai/resume-chat", {
        method: "POST",
        body: JSON.stringify({ messages: chatMessages, action: "generate" }),
      });
      const data = await resp.json();
      if (data.resume_text) {
        applyResumeText(data.resume_text, { rescore: true, clearRewrites: true });
        resetResumeChat();
        setShowSetupPanel(false);
        setWizardStep(2);
      } else {
        setChatError("AI could not generate a usable resume from the current answers. Add more detail or start from a blank draft.");
      }
    } catch (err) {
      setChatError(err.message || "Could not generate a resume right now. Your current draft was not changed.");
    } finally {
      setChatLoading(false);
    }
  }, [chatMessages, applyResumeText, resetResumeChat]);

  const handleUndo = useCallback(() => {
    if (undoStackRef.current.length === 0) return;
    const prev = undoStackRef.current.pop();
    redoStackRef.current.push(resumeText);
    applyResumeText(prev, { _isUndo: true });
  }, [resumeText, applyResumeText]);

  const handleRedo = useCallback(() => {
    if (redoStackRef.current.length === 0) return;
    const next = redoStackRef.current.pop();
    undoStackRef.current.push(resumeText);
    applyResumeText(next, { _isUndo: true });
  }, [resumeText, applyResumeText]);

  // Keyboard shortcuts: Ctrl+Z / Ctrl+Shift+Z
  useEffect(() => {
    const handler = (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "z") {
        const target = e.target;
        if (
          target instanceof HTMLElement
          && (target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName))
        ) {
          return;
        }
        e.preventDefault();
        if (e.shiftKey) handleRedo();
        else handleUndo();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [handleUndo, handleRedo]);

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
    setUploadWarnings([]);
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
      setAgentDocument(data.document?.schema_version === 1 ? data.document : null);
      setUploadWarnings([
        ...(data.parse_quality?.warnings || []),
        ...(data.content_warnings || []),
      ]);
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
      if (wizardStep === 1) setWizardStep(2);
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
    setUploadWarnings([]);
    setAgentDocument(null);
    setProfile({ name: "", email: "", phone: "", location: "" });
    setSelectedBulletId(null);
    setEditingNodeId(null);
    setCoachResponse(null);
    setCoachError("");
    setSessionId("");
    setShowSetupPanel(false);
    if (wizardStep === 1) setWizardStep(2);
    applyResumeText(pastedText.trim(), { rescore: true, clearRewrites: true });
  };

  // ── Resume Versions ──────────────────────────────────────────────────
  // Auto-load versions for logged-in users
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { if (user) fetchVersions(); }, [user]);

  const fetchVersions = async () => {
    if (!user) return;
    setVersionsLoading(true);
    try {
      const resp = await apiFetch("/api/resume/versions");
      if (resp.ok) {
        setResumeVersions(await resp.json());
      }
    } catch { /* ignore */ }
    setVersionsLoading(false);
  };

  const loadVersion = async (versionId) => {
    try {
      const resp = await apiFetch(`/api/resume/versions/${versionId}`);
      if (!resp.ok) return;
      const data = await resp.json();
      setAgentDocument(data.resume_structured?.schema_version === 1 ? data.resume_structured : null);
      setSelectedBulletId(null);
      setEditingNodeId(null);
      setCoachResponse(null);
      setCoachError("");
      setSessionId("");
      setShowSetupPanel(false);
      if (wizardStep === 1) setWizardStep(2);
      applyResumeText(data.resume_text, { rescore: true, clearRewrites: true });
    } catch { /* ignore */ }
  };

  const saveCurrentVersion = async () => {
    if (!user || !resumeText.trim() || !saveVersionLabel.trim()) return;
    setSavingVersion(true);
    try {
      const resp = await apiFetch("/api/resume/versions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          label: saveVersionLabel.trim(),
          resume_text: resumeText,
          resume_structured: agentDocument?.raw_text === resumeText ? agentDocument : undefined,
          source: "manual",
          job_id: selectedJob?.id || null,
          score: scoreData?.total_score || null,
        }),
      });
      if (resp.ok) {
        setSaveVersionLabel("");
        fetchVersions();
      }
    } catch { /* ignore */ }
    setSavingVersion(false);
  };

  const renameVersion = async (versionId, newLabel) => {
    if (!newLabel.trim()) {
      setRenamingVersionId(null);
      return;
    }
    try {
      const resp = await apiFetch(`/api/resume/versions/${versionId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ label: newLabel.trim() }),
      });
      if (resp.ok) fetchVersions();
    } catch { /* ignore */ }
    setRenamingVersionId(null);
    setRenamingVersionLabel("");
  };

  const deleteVersion = async (versionId) => {
    try {
      const resp = await apiFetch(`/api/resume/versions/${versionId}`, {
        method: "DELETE",
      });
      if (resp.ok) fetchVersions();
    } catch { /* ignore */ }
    setDeletingVersionId(null);
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
      const message = /sign in/i.test(err.message || "")
        ? err.message
        : err.message?.includes("429")
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

  const handleBulletRewrite = async (section, activeTabId = selectedBulletTab, suggestionHint = null) => {
    if (!section?.text) return;

    const sectionTabs = getBulletFeedbackTabs(section, resumeText);
    const activeFocusTab = sectionTabs.find((tab) => tab.id === activeTabId) || sectionTabs.find((tab) => tab.status === "issue") || sectionTabs[0] || null;
    const rewriteFocus = getBulletRewriteFocus(section, resumeText, activeTabId);
    const focusedFeedback = buildFocusedFeedbackContext(activeFocusTab, sectionTabs);
    const hintContext = suggestionHint
      ? `\nSUGGESTION TO INCORPORATE: ${suggestionHint.title}. ${suggestionHint.detail || ""} Naturally weave in relevant keywords or competencies from this suggestion if they fit the bullet's context.`
      : selectedInjectKeyword
        ? `\nKEYWORD TO WEAVE IN: "${selectedInjectKeyword}". If it fits naturally in this bullet's context, incorporate it once. If it doesn't fit, ignore it entirely — do NOT force it.`
        : "";
    const usedVerbs = bulletSections
      .filter((candidate) => candidate.id !== section.id && candidate.type === "bullet")
      .map((candidate) => candidate.text.split(/\s+/)[0]?.toLowerCase().replace(/[,:;.]$/, ""))
      .filter(Boolean)
      .join(", ");
    const cacheKey = getRewriteCacheKey({
      bullet: section.text,
      jobTitle: selectedJob?.title || "",
      jobDescription,
      usedVerbs,
      rewriteFocus,
      focusedFeedback: focusedFeedback + hintContext,
    });
    if (rewriteResults[section.id]?.cache_key === cacheKey) {
      openMobileFeedbackPanel(selectedFeedbackRef);
      return;
    }

    setRewriteLoading((current) => ({ ...current, [section.id]: true }));
    setCoachError("");

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
          focused_feedback: focusedFeedback + hintContext,
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
          cache_key: cacheKey,
          source_bullet: section.text,
          job_title: selectedJob?.title || "",
          job_description: jobDescription,
        },
      }));
      if (suggestionHint) setActiveSuggestionHint(null);
      setSelectedInjectKeyword(null);
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

  const handleRegenerateSummary = useCallback(async () => {
    if (!resumeText.trim() || regeneratingSummary) return;
    setRegeneratingSummary(true);
    try {
      const resp = await apiFetch("/api/ai/regenerate-summary", {
        method: "POST",
        body: JSON.stringify({
          resume_text: resumeText,
          job_id: selectedJob?.id || null,
          user_direction: summaryDirection.trim() || null,
        }),
      });
      const data = await resp.json();
      if (data.summary) {
        // Find existing summary paragraphs and replace them
        const summaryParagraphs = parsedSections.filter(
          (s) => s.type === "paragraph" && s.sectionKey === "summary",
        );
        let nextText = resumeText;
        if (summaryParagraphs.length > 0) {
          // Replace all summary paragraph lines with the new summary
          const lines = nextText.replace(/\r\n?/g, "\n").split("\n");
          const allLineIndices = summaryParagraphs.flatMap(
            (s) => (Array.isArray(s.lineIndices) && s.lineIndices.length > 0) ? s.lineIndices : [s.lineIndex],
          ).sort((a, b) => b - a); // reverse order to preserve indices
          // Remove all old summary lines
          for (const idx of allLineIndices) {
            lines.splice(idx, 1);
          }
          // Insert new summary at the position of the first removed line
          const insertAt = Math.min(...summaryParagraphs.map((s) => s.lineIndex));
          lines.splice(insertAt, 0, data.summary);
          nextText = lines.join("\n");
        } else if (parsedSections.some((s) => ["heading", "heading_paragraph"].includes(s.type) && s.sectionKey === "summary")) {
          // Summary heading exists but no paragraph content -- insert after heading
          const summaryHeading = parsedSections.find(
            (s) => ["heading", "heading_paragraph"].includes(s.type) && s.sectionKey === "summary",
          );
          if (summaryHeading) {
            const lines = nextText.replace(/\r\n?/g, "\n").split("\n");
            lines.splice(summaryHeading.lineIndex + 1, 0, data.summary);
            nextText = lines.join("\n");
          }
        } else {
          // No summary section at all -- prepend one
          nextText = `PROFESSIONAL SUMMARY\n${data.summary}\n\n${nextText}`;
        }
        applyResumeText(nextText, { rescore: true });
      }
    } catch {
      // Silently handle -- the user can retry
    } finally {
      setRegeneratingSummary(false);
    }
  }, [resumeText, regeneratingSummary, selectedJob?.id, parsedSections, applyResumeText]);

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

  const handlePrintPdf = async () => {
    if (!resumeText.trim() || downloadingPdf) return;
    setDownloadingPdf(true);
    try {
      const token = localStorage.getItem("token");
      const headers = { "Content-Type": "application/json" };
      if (token) headers.Authorization = `Bearer ${token}`;
      const resp = await fetch(`${API_BASE}/api/resume/download-pdf`, {
        method: "POST",
        headers,
        body: JSON.stringify({
          resume_text: resumeText,
          template: selectedTemplate,
          name: profile.name || "",
          email: profile.email || "",
          phone: profile.phone || "",
        }),
      });
      if (!resp.ok) throw new Error("PDF generation failed");
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${(profile.name || "resume").replace(/[^a-zA-Z0-9]/g, "_")}_resume.pdf`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setDownloadError(err.message || "PDF download failed");
    }
    setDownloadingPdf(false);
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
    if (!section) return;
    setSelectedSectionId(section.id);
    setEditingNodeId(section.id);
    // For education entries, show raw multi-line text for editing
    if (section.type === "education_entry" && section.lineIndices?.length > 0) {
      const lines = resumeText.replace(/\r\n?/g, "\n").split("\n");
      const entryLines = section.lineIndices.map((idx) => lines[idx] || "").filter(Boolean);
      setEditingValue(entryLines.join("\n"));
    } else {
      setEditingValue(section.text);
    }
    if (section.type === "bullet") setSelectedBulletId(section.id);
    else setSelectedBulletId(null);
  };

  const commitEdit = (section) => {
    if (!section) return;
    if (editingNodeId !== section.id) return;

    if (section.type === "education_entry" && section.lineIndices?.length > 0) {
      // Replace each original line individually (handles non-contiguous indices)
      const lines = resumeText.replace(/\r\n?/g, "\n").split("\n");
      const newLines = editingValue.replace(/\r/g, "").split("\n");
      const sortedIndices = [...section.lineIndices].sort((a, b) => a - b);
      // Map new lines to original indices; blank out extras
      sortedIndices.forEach((idx, i) => {
        if (idx >= 0 && idx < lines.length) {
          lines[idx] = i < newLines.length ? newLines[i] : "";
        }
      });
      // If user added more lines than original, insert after last index
      if (newLines.length > sortedIndices.length) {
        const lastIdx = sortedIndices[sortedIndices.length - 1];
        const extras = newLines.slice(sortedIndices.length);
        lines.splice(lastIdx + 1, 0, ...extras);
      }
      setEditingNodeId(null);
      setEditingValue("");
      applyResumeText(lines.join("\n"));
    } else {
      const nextText = updateResumeLine(resumeText, section, editingValue);
      setEditingNodeId(null);
      setEditingValue("");
      applyResumeText(nextText);
    }
  };

  const wordCount = resumeText.split(/\s+/).filter(Boolean).length;
  const overallScore = Number.isFinite(scoreData?.overall_score) ? scoreData.overall_score : null;
  const scoreTheme = getScoreTheme(overallScore ?? 0);
  const scorePillClass = scoreData ? scoreTheme.pill : "bg-[#BDDDFC]/10 text-[#6A89A7]";
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

  const getRankedKeywordsForBullet = useCallback((bulletSection) => {
    if (!relevantMissingKeywords.length || !bulletSection?.text) return [];
    const idx = parsedSections.findIndex((s) => s.id === bulletSection.id);
    const headingText = idx > 0
      ? parsedSections.slice(0, idx).reverse()
          .find((s) => s.type === "subheading" || s.type === "heading")?.text || ""
      : "";
    // Skip the first word (action verb) — "Designed" matching "api design" is a false positive
    const bulletWithoutVerb = bulletSection.text.split(/\s+/).slice(1).join(" ");
    const ctx = (bulletWithoutVerb + " " + headingText).toLowerCase();
    return relevantMissingKeywords
      .map((kw) => {
        const label = extractKeywordLabel(kw);
        const tokens = label.toLowerCase().split(/\W+/).filter((t) => t.length >= 3);
        // Skip garbled/multi-word phrases — real ATS keywords are 1-3 words
        if (tokens.length > 3) return { label, score: -1 };
        const score = tokens.filter((t) => ctx.includes(t)).length;
        return { label, score };
      })
      .filter((item) => item.score > 0)
      .sort((a, b) => b.score - a.score)
      .slice(0, 2)
      .map((item) => item.label);
  }, [parsedSections, relevantMissingKeywords]);

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
  const selectedRewriteCandidate = selectedBullet ? rewriteResults[selectedBullet.id] : null;
  const selectedRewrite = isRewriteResultCurrent(selectedRewriteCandidate, {
    bullet: selectedBullet?.text || "",
    jobTitle: selectedJob?.title || "",
    jobDescription,
  }) ? selectedRewriteCandidate : null;
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
  const displayDetailLines = displayHeaderLines.slice(1);
  const bodySections = useMemo(
    () => groupEducationSections(parsedSections.filter((section) => !headerMeta.lineIndices.includes(section.lineIndex))),
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
        target: "1-2 pages",
        status: wordCount >= 350 && wordCount <= 1200 ? "good" : "review",
        note: wordCount < 350 ? "Draft is still light." : wordCount > 1200 ? "May read dense." : "Healthy range for mid-senior resumes.",
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

    // Prefer backend-detected sections when available (from scoreData.detected_sections)
    // to avoid mismatches between what the AI scored and what the frontend displays.
    const backendSections = scoreData?.detected_sections;
    const matchedSections = backendSections
      ? [...new Set(backendSections.filter((s) => core.has(s)))]
      : [...new Set(
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
  }, [bulletSections, parsedSections, scoreData?.detected_sections]);
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
        hint: "Add a %, $, timeline, team size, or scale detail.",
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
        specificsSuggestions.push("Quantify more bullets with numbers, percentages, dollar amounts, or scale details.");
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
  const improvementCount = issueBulletCount + Math.min(scoreData?.top_suggestions?.length || 0, 3) + Math.min(relevantMissingKeywords.length, 6);
  const isFeedbackView = workspaceView === "feedback";
  const showFeedbackPanels = isFeedbackView || mobilePanel === "feedback";
  const lowScoreWarning = scoreData && overallScore !== null && overallScore < 50;
  const setupVisible = showSetupPanel || !resumeText.trim() || wizardStep === 1;
  const chatStageMeta = useMemo(
    () => getResumeChatStageMeta(chatStage, chatReady),
    [chatReady, chatStage],
  );

  // When a new job is selected, always go to step 1 (Upload) so user can choose their resume
  useEffect(() => {
    if (selectedJob) {
      setWizardStep(1);
      setShowSetupPanel(true);
    }
  }, [selectedJob]);
  const hasResume = resumeText.trim().length > 0;
  const canGoToStep = (step) => {
    if (step === 1) return true;
    if (step === 2) return hasResume;
    if (step === 3) return hasResume;
    if (step === 4) return hasResume;
    return false;
  };
  const scorePhaseLabel = !scoreData && scoreError
    ? "Scoring unavailable"
    : scorePhase === "final_complete"
      ? "Final score complete"
      : scorePhase === "editing"
        ? "Draft edited"
        : scorePhase === "opening_scored"
          ? "Opening score ready"
          : "Opening score pending";

  const focusBullet = useCallback((sectionId) => {
    setSelectedBulletId(sectionId);
    setSelectedSectionId(sectionId);
    setSelectedInjectKeyword(null);
    setMobilePanel("feedback");
    if (typeof window !== "undefined") {
      window.requestAnimationFrame(() => {
        document.getElementById(`resume-section-${sectionId}`)?.scrollIntoView({
          behavior: "smooth",
          block: "center",
        });
      });
      // After re-render attaches selectedFeedbackRef, scroll the sidebar to the feedback panel
      setTimeout(() => {
        selectedFeedbackRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
      }, 80);
    }
  }, [selectedFeedbackRef]);

  const handleMissingKeywordClick = useCallback((keyword, event) => {
    const label = extractKeywordLabel(keyword);
    if (!label) return;

    const allMatchedLabels = relevantMatchedKeywords.map(extractKeywordLabel).filter(Boolean);
    const suggestions = computeKeywordInsertSuggestions(label, bulletSections, allMatchedLabels);

    const rect = event.currentTarget.getBoundingClientRect();
    setInsertKeywordPopup({
      keyword: label,
      suggestions,
      top: rect.bottom + 6,
      left: Math.min(rect.left, window.innerWidth - 320),
    });
  }, [bulletSections, relevantMatchedKeywords]);

  const handleInsertKeywordIntoBullet = useCallback((bullet, keyword) => {
    setInsertKeywordPopup(null);
    const currentText = bullet.text;
    const appendedText = currentText.endsWith(".") || currentText.endsWith(",")
      ? `${currentText.slice(0, -1)}, ${keyword}${currentText.slice(-1)}`
      : `${currentText}, ${keyword}`;

    setSelectedSectionId(bullet.id);
    setSelectedBulletId(bullet.id);
    setEditingNodeId(bullet.id);
    setEditingValue(appendedText);

    window.requestAnimationFrame(() => {
      document.getElementById(`resume-section-${bullet.id}`)?.scrollIntoView({
        behavior: "smooth",
        block: "center",
      });
    });
  }, []);

  // ─── Drag-and-Drop ─────────────────────────────────────────────────────────
  const dndSensors = useSensors(useSensor(PointerSensor, POINTER_SENSOR_CONFIG));
  const bulletIds = useMemo(() => bodySections.filter((s) => s.type === "bullet").map((s) => s.id), [bodySections]);

  const handleDragEnd = useCallback((event) => {
    const { active, over } = event;
    if (!over || active.id === over.id) return;

    const activeSection = bodySections.find((s) => s.id === active.id);
    const overSection = bodySections.find((s) => s.id === over.id);
    if (!activeSection || !overSection) return;
    if (activeSection.sectionKey !== overSection.sectionKey) return;

    // Ensure they're in the same entry group (no heading/subheading separator between them)
    const activeIdx = bodySections.indexOf(activeSection);
    const overIdx = bodySections.indexOf(overSection);
    const [minIdx, maxIdx] = [Math.min(activeIdx, overIdx), Math.max(activeIdx, overIdx)];
    const hasSeparator = bodySections.slice(minIdx + 1, maxIdx).some((s) =>
      s.type === "heading" || s.type === "subheading" || s.type === "education_entry",
    );
    if (hasSeparator) return;

    const nextText = moveResumeBullet(resumeText, activeSection.lineIndex, overSection.lineIndex);
    applyResumeText(nextText);
  }, [bodySections, resumeText, applyResumeText]);

  const handleMoveSection = useCallback((headingId, direction) => {
    const nextText = moveSectionInText(resumeText, parsedSections, headingId, direction);
    if (nextText !== resumeText) applyResumeText(nextText);
  }, [resumeText, parsedSections, applyResumeText]);

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

  const handlePromoteToPosition = useCallback((section) => {
    if (!section) return;
    const nextText = promoteLineToPosition(resumeText, section);
    setEditingNodeId(null);
    setEditingValue("");
    applyResumeText(nextText);
  }, [applyResumeText, resumeText]);

  const handlePromoteToSection = useCallback((section) => {
    if (!section) return;
    const nextText = promoteLineToSection(resumeText, section);
    setEditingNodeId(null);
    setEditingValue("");
    applyResumeText(nextText);
  }, [applyResumeText, resumeText]);

  const handleDemoteToBullet = useCallback((section) => {
    if (!section) return;
    const nextText = demoteLineToBullet(resumeText, section);
    setEditingNodeId(null);
    setEditingValue("");
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

      {/* ── Wizard Progress Bar ──────────────────────────────────────── */}
      <div className="flex items-center gap-2 mb-6">
        {["Upload", "Template", "Edit", "Export"].map((label, i) => {
          const step = i + 1;
          const isActive = wizardStep === step;
          const isComplete = wizardStep > step;
          return (
            <button
              key={label}
              type="button"
              onClick={() => {
                if (!canGoToStep(step)) return;
                if (step === 1) setShowSetupPanel(true);
                setWizardStep(step);
              }}
              className={`flex items-center gap-2 px-3 py-1.5 rounded-full text-xs font-medium transition ${
                isActive
                  ? "bg-[#384959] text-white"
                  : isComplete
                    ? "bg-blue-100 text-blue-700 cursor-pointer hover:bg-blue-200"
                    : "bg-[#BDDDFC]/10 text-[#6A89A7] cursor-default"
              }`}
            >
              {isComplete ? <Check size={12} /> : <span>{step}</span>}
              {label}
            </button>
          );
        })}
      </div>

      {selectedJob && (wizardStep === 1 || wizardStep === 3) && (
        <div className="mb-4 rounded-3xl border border-[#BDDDFC]/30 bg-[#BDDDFC]/10 p-5 shadow-sm">
          <div className="flex items-center justify-between">
            <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[#384959]">Target Job Description</div>
            <button
              type="button"
              onClick={() => setActiveTab("jobs")}
              className="text-xs font-semibold text-[#88BDF2] hover:text-[#384959]"
            >
              Back to Jobs
            </button>
          </div>
          <div className="mt-2 flex flex-col gap-4 lg:flex-row lg:items-start">
            <div className="flex-1 min-w-0">
              <div className="text-lg font-semibold text-slate-900">{selectedJob.title}</div>
              <div className="text-sm text-slate-600">{selectedJob.company}{selectedJob.location ? ` · ${selectedJob.location}` : ""}</div>
              {selectedJobCanonicalTerms.length > 0 && (
                <div className="mt-3 flex flex-wrap gap-1.5">
                  {selectedJobCanonicalTerms.map((term, index) => {
                    const label = extractKeywordLabel(term);
                    return (
                    <span key={`${label}-${index}`} className="rounded-full bg-[#BDDDFC]/25 px-2 py-0.5 text-[11px] font-medium text-[#384959]" title={term?.jd_context || ""}>
                      {label}
                    </span>
                  );})}
                </div>
              )}
            </div>
            {selectedJob.description && (
              <div className="flex-1 min-w-0 max-h-48 overflow-y-auto rounded-xl bg-white/70 p-3 text-sm leading-relaxed text-slate-700">
                {selectedJob.description}
              </div>
            )}
          </div>
        </div>
      )}

      {/* ── Step 1: Upload ──────────────────────────────────────────── */}
      {wizardStep === 1 && setupVisible ? (
        <div className="mx-auto max-w-3xl space-y-6">
          {/* ── Entry Point Cards ─────────────────────────────────────── */}
          <div>
            <h2 className="text-xl font-bold text-[#384959]">How would you like to start?</h2>
            <p className="mt-1 text-sm text-[#6A89A7]">Choose the option that fits your situation.</p>
          </div>

          <div className="grid gap-4 grid-cols-2 lg:grid-cols-4">
            {/* Upload */}
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              onDrop={handleDrop}
              onDragOver={(event) => { event.preventDefault(); setDragOver(true); }}
              onDragLeave={() => setDragOver(false)}
              className={`group text-left rounded-2xl border-2 bg-white p-6 transition-all hover:shadow-md hover:-translate-y-0.5 ${
                dragOver ? "border-blue-400 bg-blue-50" : "border-[#BDDDFC]/30 hover:border-blue-300"
              }`}
            >
              {uploading ? (
                <Loader2 size={28} className="animate-spin text-[#88BDF2]" />
              ) : (
                <UploadCloud size={28} className="text-[#88BDF2]" />
              )}
              <h3 className="mt-3 text-base font-semibold text-[#384959]">Upload Resume</h3>
              <p className="mt-1.5 text-sm text-[#6A89A7]">
                {uploading ? "Extracting text..." : "Drop a PDF or DOCX, or click to browse"}
              </p>
            </button>

            {/* Paste */}
            <button
              type="button"
              onClick={() => {
                const el = document.getElementById("resume-paste-area");
                if (el) { el.classList.remove("hidden"); el.querySelector("textarea")?.focus(); }
              }}
              className="group text-left rounded-2xl border-2 border-[#BDDDFC]/30 bg-white p-6 transition-all hover:shadow-md hover:-translate-y-0.5 hover:border-emerald-300"
            >
              <FileText size={28} className="text-emerald-600" />
              <h3 className="mt-3 text-base font-semibold text-[#384959]">Paste Text</h3>
              <p className="mt-1.5 text-sm text-[#6A89A7]">Copy-paste your resume from any source</p>
            </button>

            {/* Start Fresh — opens AI chat builder */}
            <button
              type="button"
              onClick={() => {
                setShowResumeChat(true);
                setChatInput("");
                setChatReady(false);
                setChatStage("contact");
                setChatError("");
                setChatMessages([{
                  role: "assistant",
                  content: "Hi! I'll help you build your resume step by step. Let's start \u2014 what's your full name?",
                }]);
              }}
              className="group text-left rounded-2xl border-2 border-[#BDDDFC]/30 bg-white p-6 transition-all hover:shadow-md hover:-translate-y-0.5 hover:border-violet-300"
            >
              <Sparkles size={28} className="text-violet-600" />
              <h3 className="mt-3 text-base font-semibold text-[#384959]">Start Fresh</h3>
              <p className="mt-1.5 text-sm text-[#6A89A7]">Build from scratch with AI-guided chat, or switch to a blank starter if you want to move faster</p>
            </button>

            {/* Try Demo */}
            <button
              type="button"
              onClick={() => {
                const demoResume = `Sarah Chen
Singapore | sarah.chen@email.com | +65 9123 4567 | linkedin.com/in/sarahchen

PROFESSIONAL SUMMARY
Results-driven software engineer with 5+ years of experience building scalable web applications and cloud infrastructure. Led migration of legacy systems to microservices architecture, reducing deployment time by 70%. Passionate about clean code, developer experience, and mentoring junior engineers.

PROFESSIONAL EXPERIENCE
Senior Software Engineer
DBS Bank | Singapore | Jan 2022 – Present
• Led microservices migration for core banking platform, serving 5M+ users across APAC
• Reduced API response time by 45% through Redis caching and query optimisation
• Responsible for mentoring junior engineers and doing code reviews
• Helped with CI/CD pipeline improvements and deployment automation

Software Engineer
GovTech Singapore | Singapore | Jul 2019 – Dec 2021
• Built citizen-facing web applications using React and Node.js, serving 500K+ monthly users
• Designed and implemented RESTful APIs for national digital identity platform
• Collaborated with UX team to improve accessibility compliance to WCAG 2.1 AA standards
• Reduced infrastructure costs by 30% through AWS resource optimisation

Junior Developer
Shopee | Singapore | Jan 2018 – Jun 2019
• Developed seller dashboard features using Vue.js and Python Flask
• Wrote automated test suites achieving 85% code coverage
• Participated in on-call rotation, resolving production incidents within SLA

EDUCATION
B.Sc. Computer Science – National University of Singapore (2017)
Dean's List 2016, 2017

SKILLS
Python, JavaScript, TypeScript, React, Node.js, AWS, Docker, Kubernetes, PostgreSQL, Redis, CI/CD, Agile

CERTIFICATIONS
• AWS Solutions Architect Associate (2023)
• Certified Kubernetes Administrator (2022)`;
                applyResumeText(demoResume, { rescore: true });
                setShowSetupPanel(false);
                setWizardStep(3);
              }}
              className="group text-left rounded-2xl border-2 border-[#BDDDFC]/30 bg-white p-6 transition-all hover:shadow-md hover:-translate-y-0.5 hover:border-emerald-300"
            >
              <Star size={28} className="text-emerald-500" />
              <h3 className="mt-3 text-base font-semibold text-[#384959]">Try Demo</h3>
              <p className="mt-1.5 text-sm text-[#6A89A7]">Load a sample resume to explore features</p>
            </button>
          </div>

          {/* ── Paste Area (hidden by default, revealed on click) ──────── */}
          <div id="resume-paste-area" className="hidden rounded-2xl border border-[#BDDDFC]/30 bg-white p-4 shadow-sm">
            <div className="text-sm font-semibold text-[#384959]">Paste your resume text</div>
            <textarea
              value={pastedText}
              onChange={(event) => setPastedText(event.target.value)}
              placeholder="Paste your resume content here..."
              className="mt-3 min-h-[160px] w-full resize-none rounded-xl border border-[#BDDDFC]/30 bg-[#f0f4f8] px-4 py-3 text-sm text-[#384959] focus:outline-none focus:ring-2 focus:ring-blue-200"
            />
            <div className="mt-3 flex gap-2">
              <button
                type="button"
                onClick={handlePasteResume}
                disabled={!pastedText.trim()}
                className="rounded-xl bg-[#384959] px-4 py-2 text-sm font-medium text-white hover:bg-[#2d3a47] disabled:opacity-40"
              >
                Use This Text
              </button>
              <button
                type="button"
                onClick={() => document.getElementById("resume-paste-area")?.classList.add("hidden")}
                className="rounded-xl border border-[#BDDDFC]/30 px-4 py-2 text-sm font-medium text-[#6A89A7] hover:bg-[#f0f4f8]"
              >
                Cancel
              </button>
            </div>
          </div>

          {/* ── AI Resume Chat Builder ─────────────────────────────────── */}
          {showResumeChat && (
            <div className="rounded-2xl border border-violet-200 bg-white shadow-sm overflow-hidden flex flex-col" style={{ height: "480px" }}>
              {/* Header */}
              <div className="flex items-center justify-between border-b border-violet-100 bg-gradient-to-r from-violet-50 to-white px-5 py-3">
                <div className="flex items-center gap-2">
                  <Sparkles size={18} className="text-violet-600" />
                  <span className="text-sm font-semibold text-[#384959]">AI Resume Builder</span>
                </div>
                <button
                  type="button"
                  onClick={resetResumeChat}
                  className="rounded-lg p-1 text-[#6A89A7] hover:bg-[#f0f4f8] transition"
                  aria-label="Close chat"
                >
                  <X size={16} />
                </button>
              </div>

              {/* Messages */}
              <div className="flex-1 overflow-y-auto px-5 py-4 space-y-3">
                {chatMessages.map((msg, i) => (
                  <div key={i} className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}>
                    {msg.role === "assistant" && (
                      <div className="mr-2 mt-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-violet-100">
                        <Sparkles size={14} className="text-violet-600" />
                      </div>
                    )}
                    <div
                      className={`max-w-[80%] rounded-2xl px-4 py-2.5 text-sm leading-relaxed ${
                        msg.role === "user"
                          ? "bg-[#384959] text-white"
                          : "bg-[#f0f4f8] text-[#384959]"
                      }`}
                    >
                      {msg.content}
                    </div>
                  </div>
                ))}
                {chatLoading && (
                  <div className="flex justify-start">
                    <div className="mr-2 mt-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-violet-100">
                      <Sparkles size={14} className="text-violet-600" />
                    </div>
                    <div className="rounded-2xl bg-[#f0f4f8] px-4 py-2.5 text-sm text-[#6A89A7]">
                      <Loader2 size={16} className="inline animate-spin mr-1.5" />
                      Thinking...
                    </div>
                  </div>
                )}
                <div ref={chatEndRef} />
              </div>

              {/* Input */}
              <div className="border-t border-[#BDDDFC]/20 px-4 py-3">
                <div className="mb-2 flex items-center gap-2 text-[11px]">
                  <span className="font-semibold uppercase tracking-wide text-violet-600">{chatStageMeta.label}</span>
                  <span className="text-[#BDDDFC]">/</span>
                  {chatStageMeta.remaining.length > 0 ? (
                    <span className="text-[#6A89A7]">Next: {chatStageMeta.remaining.join(", ")}</span>
                  ) : (
                    <span className="font-semibold text-emerald-600">Ready to generate</span>
                  )}
                </div>

                {chatError && (
                  <div className="mb-3 rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
                    {chatError}
                  </div>
                )}

                {chatReady ? (
                  <div className="mb-3 space-y-2">
                    <div className="rounded-2xl border border-violet-200 bg-violet-50 px-4 py-3 text-sm text-violet-800">
                      <span className="font-semibold">Your resume is ready to generate.</span> Click the button below — you can refine it further after.
                    </div>
                    <button
                      type="button"
                      disabled={chatLoading}
                      onClick={async () => {
                        setChatLoading(true);
                        setChatError("");
                        try {
                          const resp = await apiFetch("/api/ai/resume-chat", {
                            method: "POST",
                            body: JSON.stringify({ messages: chatMessages, action: "generate" }),
                          });
                          const data = await resp.json();
                          if (data.resume_text) {
                            applyResumeText(data.resume_text, { rescore: true, clearRewrites: true });
                            resetResumeChat();
                            setShowSetupPanel(false);
                            setWizardStep(2);
                          } else {
                            setChatMessages((prev) => [...prev, {
                              role: "assistant",
                              content: "I couldn't generate the resume from our conversation yet. Could you share a bit more about your work experience and achievements? That will help me create a stronger resume for you.",
                            }]);
                            setChatError("We still need a bit more concrete experience detail before the draft can be generated.");
                          }
                        } catch (err) {
                          setChatMessages((prev) => [...prev, {
                            role: "assistant",
                            content: "Sorry, I couldn't generate the resume right now. Please try again or use the blank starter below.",
                          }]);
                          setChatError(
                            err.message?.includes("429")
                              ? "The AI coach is busy right now. You can wait a moment, try again, or jump to a blank starter."
                              : "We couldn't generate the draft just now. You can try again or continue with a blank starter.",
                          );
                        } finally {
                          setChatLoading(false);
                        }
                      }}
                      className="w-full rounded-xl bg-violet-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-violet-700 disabled:opacity-50 transition flex items-center justify-center gap-2"
                    >
                      <Sparkles size={16} />
                      Generate My Resume
                    </button>
                  </div>
                ) : chatMessages.filter((m) => m.role === "user").length === 0 ? (
                  <button
                    type="button"
                    disabled={chatLoading}
                    onClick={startBlankResumeFlow}
                    className="mb-3 w-full rounded-xl border border-[#BDDDFC]/30 bg-white px-4 py-2.5 text-sm font-medium text-[#384959] hover:bg-[#f0f4f8] disabled:opacity-50 transition"
                  >
                    Skip the interview and start from a blank resume
                  </button>
                ) : (
                  <button
                    type="button"
                    disabled={chatLoading}
                    onClick={generateWithWhatWeHave}
                    className="mb-3 text-xs text-[#6A89A7] hover:text-[#384959] underline underline-offset-2 transition disabled:opacity-50"
                  >
                    or just draft with what I have
                  </button>
                )}
                <form
                  onSubmit={async (e) => {
                    e.preventDefault();
                    const text = chatInput.trim();
                    if (!text || chatLoading) return;

                    const nextMessages = [...chatMessages, { role: "user", content: text }];
                    setChatMessages(nextMessages);
                    setChatInput("");
                    setChatLoading(true);
                    setChatError("");

                    // Scroll to bottom after adding user message
                    setTimeout(() => { if (chatEndRef.current) chatEndRef.current.parentElement.scrollTop = chatEndRef.current.parentElement.scrollHeight; }, 50);

                    try {
                      const resp = await apiFetch("/api/ai/resume-chat", {
                        method: "POST",
                        body: JSON.stringify({ messages: nextMessages, action: chatReady ? "refine" : "chat" }),
                      });
                      const data = await resp.json();
                      setChatMessages((prev) => [...prev, { role: "assistant", content: data.reply }]);
                      if (data.stage) setChatStage(data.stage);
                      if (data.ready_to_generate) setChatReady(true);
                    } catch (err) {
                      setChatError(
                        err.message?.includes("429")
                          ? "The AI coach is busy right now. You can wait a moment, try again, or start from a blank resume."
                          : "The guided builder hit a snag. You can retry your answer or move on with a blank starter.",
                      );
                      setChatMessages((prev) => [...prev, {
                        role: "assistant",
                        content: err.message?.includes("429")
                          ? "I'm a bit busy right now — too many AI requests at once. Please wait a moment and try again."
                          : "Sorry, something went wrong. Please try sending your message again.",
                      }]);
                    } finally {
                      setChatLoading(false);
                      setTimeout(() => { if (chatEndRef.current) chatEndRef.current.parentElement.scrollTop = chatEndRef.current.parentElement.scrollHeight; }, 50);
                    }
                  }}
                  className="flex gap-2"
                >
                  <textarea
                    value={chatInput}
                    onChange={(e) => {
                      if (e.target.value.length <= 2000) setChatInput(e.target.value);
                    }}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && !e.shiftKey) {
                        e.preventDefault();
                        if (chatInput.trim() && !chatLoading) e.target.form.requestSubmit();
                      }
                    }}
                    placeholder="Type your answer..."
                    disabled={chatLoading}
                    rows={1}
                    onFocus={(e) => {
                      setTimeout(() => e.target.closest('[class*="rounded-2xl"]')?.scrollIntoView({ behavior: "smooth", block: "start" }), 300);
                    }}
                    className="flex-1 rounded-xl border border-[#BDDDFC]/30 bg-[#f0f4f8] px-4 py-2.5 text-sm text-[#384959] placeholder-[#6A89A7]/60 focus:outline-none focus:ring-2 focus:ring-violet-200 disabled:opacity-50 resize-none"
                  />
                  <button
                    type="submit"
                    disabled={!chatInput.trim() || chatLoading}
                    className="rounded-xl bg-[#384959] px-4 py-2.5 text-white hover:bg-[#2d3a47] disabled:opacity-40 transition"
                    aria-label="Send message"
                  >
                    <Send size={16} />
                  </button>
                </form>
              </div>
            </div>
          )}

          {/* ── Saved Versions (if logged in and has versions) ─────────── */}
          {user && resumeVersions.length > 0 && (
            <div className="rounded-2xl border border-[#BDDDFC]/30 bg-white p-4 shadow-sm">
              <div className="flex items-center justify-between">
                <div className="text-sm font-semibold text-[#384959]">Your Saved Resumes</div>
                <button type="button" onClick={fetchVersions} className="text-xs text-[#88BDF2] hover:text-blue-800">
                  {versionsLoading ? "Loading..." : "Refresh"}
                </button>
              </div>
              <div className="mt-3 grid gap-2 sm:grid-cols-2">
                {resumeVersions.slice(0, 4).map((v) => (
                  <div key={v.id} className="group/version relative">
                    {/* Delete confirmation overlay */}
                    {deletingVersionId === v.id && (
                      <div className="absolute inset-0 z-10 flex items-center justify-center gap-2 rounded-xl border border-rose-200 bg-white/95 px-3 backdrop-blur-sm">
                        <span className="text-xs font-medium text-[#384959]">Delete this version?</span>
                        <button
                          type="button"
                          onClick={() => deleteVersion(v.id)}
                          className="rounded-lg bg-[#384959] px-3 py-1 text-xs font-medium text-white hover:bg-[#2a3744] transition"
                        >
                          Delete
                        </button>
                        <button
                          type="button"
                          onClick={() => setDeletingVersionId(null)}
                          className="rounded-lg border border-[#BDDDFC]/30 bg-white px-3 py-1 text-xs font-medium text-[#6A89A7] hover:bg-[#f0f4f8] transition"
                        >
                          Cancel
                        </button>
                      </div>
                    )}
                    {/* Inline rename form */}
                    {renamingVersionId === v.id ? (
                      <div className="flex items-center gap-2 rounded-xl border border-[#6A89A7] bg-white px-4 py-3">
                        <input
                          autoFocus
                          value={renamingVersionLabel}
                          onChange={(e) => setRenamingVersionLabel(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === "Enter") renameVersion(v.id, renamingVersionLabel);
                            if (e.key === "Escape") { setRenamingVersionId(null); setRenamingVersionLabel(""); }
                          }}
                          className="flex-1 rounded-lg border border-[#BDDDFC]/30 px-2 py-1 text-sm text-[#384959] focus:outline-none focus:ring-2 focus:ring-[#6A89A7]/30"
                        />
                        <button
                          type="button"
                          onClick={() => renameVersion(v.id, renamingVersionLabel)}
                          className="rounded-lg bg-[#384959] p-1.5 text-white hover:bg-[#2a3744] transition"
                        >
                          <Check size={12} />
                        </button>
                        <button
                          type="button"
                          onClick={() => { setRenamingVersionId(null); setRenamingVersionLabel(""); }}
                          className="rounded-lg border border-[#BDDDFC]/30 p-1.5 text-[#6A89A7] hover:text-[#6A89A7] transition"
                        >
                          <X size={12} />
                        </button>
                      </div>
                    ) : (
                      <button
                        type="button"
                        onClick={() => loadVersion(v.id)}
                        className="flex w-full items-center justify-between rounded-xl border border-[#BDDDFC]/30 bg-[#f0f4f8] px-4 py-3 text-left text-sm hover:border-blue-300 hover:bg-blue-50 transition"
                      >
                        <div className="min-w-0 flex-1">
                          <div className="font-medium text-[#384959] truncate">{v.label}</div>
                          <div className="text-xs text-[#6A89A7]">
                            {v.score ? `Score ${v.score}` : ""}{v.word_count ? ` · ${v.word_count}w` : ""}
                          </div>
                        </div>
                        <div className="flex items-center gap-1 ml-2">
                          <span
                            role="button"
                            tabIndex={0}
                            onClick={(e) => { e.stopPropagation(); setRenamingVersionId(v.id); setRenamingVersionLabel(v.label); }}
                            onKeyDown={(e) => { if (e.key === "Enter") { e.stopPropagation(); setRenamingVersionId(v.id); setRenamingVersionLabel(v.label); } }}
                            className="rounded p-1 text-[#6A89A7] opacity-0 group-hover/version:opacity-100 hover:text-[#384959] hover:bg-[#BDDDFC]/10 transition"
                            title="Rename"
                          >
                            <Edit3 size={13} />
                          </span>
                          <span
                            role="button"
                            tabIndex={0}
                            onClick={(e) => { e.stopPropagation(); setDeletingVersionId(v.id); }}
                            onKeyDown={(e) => { if (e.key === "Enter") { e.stopPropagation(); setDeletingVersionId(v.id); } }}
                            className="rounded p-1 text-[#6A89A7] opacity-0 group-hover/version:opacity-100 hover:text-rose-500 hover:bg-rose-50 transition"
                            title="Delete"
                          >
                            <Trash2 size={13} />
                          </span>
                          <ChevronRight size={14} className="text-[#6A89A7]" />
                        </div>
                      </button>
                    )}
                  </div>
                ))}
              </div>
              {resumeVersions.length > 4 && (
                <button type="button" onClick={fetchVersions} className="mt-2 text-xs text-[#88BDF2] hover:text-blue-800">
                  View all {resumeVersions.length} versions
                </button>
              )}
            </div>
          )}

          {/* ── Profile Fields ─────────────────────────────────────────── */}
          <div className="rounded-2xl border border-[#BDDDFC]/30 bg-white p-4 shadow-sm">
            <div className="text-sm font-semibold text-[#384959]">Your Details</div>
            <p className="mt-1 text-xs text-[#6A89A7]">Used for the resume header. Auto-detected from uploaded files.</p>
            <div className="mt-3 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
              {[
                { key: "name", label: "Name", value: profile.name, placeholder: "Full name" },
                { key: "email", label: "Email", value: profile.email, placeholder: "Email address" },
                { key: "phone", label: "Phone", value: profile.phone, placeholder: "Phone number" },
                { key: "location", label: "Location", value: profile.location, placeholder: "Location" },
              ].map((field) => (
                <label key={field.key} className="rounded-3xl border border-[#BDDDFC]/30 bg-white p-4 shadow-sm">
                  <div className="text-xs font-semibold uppercase tracking-[0.16em] text-[#6A89A7]">{field.label}</div>
                  <input
                    value={field.value}
                    placeholder={field.placeholder}
                    onChange={(event) => handleProfileChange(field.key, event.target.value)}
                    className="mt-3 w-full rounded-xl border border-[#BDDDFC]/30 px-3 py-2.5 text-sm text-[#384959] focus:outline-none focus:ring-2 focus:ring-[#BDDDFC]"
                  />
                </label>
              ))}
            </div>
          </div>

          <div className="rounded-3xl border border-slate-200 bg-slate-50 p-5 shadow-sm">
            <div className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">Resume Guide</div>
            <div className="mt-2 text-lg font-semibold text-slate-900">Recommended targets</div>
            <p className="mt-2 text-sm leading-relaxed text-slate-600">
              Use these ranges as guide rails while you tighten the draft.
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

          {/* Step 1 Next button */}
          <div className="flex justify-end">
            <button
              type="button"
              disabled={!hasResume}
              onClick={() => setWizardStep(2)}
              className="inline-flex items-center gap-2 rounded-xl bg-[#384959] px-5 py-2.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              Next: Pick Template
              <ArrowRight size={14} />
            </button>
          </div>
        </div>
      ) : null}

      {/* ── Step 3: Setup Complete bar ──────────────────────────────── */}
      {wizardStep === 3 && !setupVisible && (
        <div className="rounded-3xl border border-[#BDDDFC]/30 bg-white p-4 shadow-sm">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
            <div className="min-w-0">
              <div className="text-xs font-semibold uppercase tracking-[0.16em] text-[#6A89A7]">Setup Complete</div>
              <div className="mt-1 text-sm text-[#384959] truncate">
                {profile.name || "Resume loaded"}{profile.email ? ` • ${profile.email}` : ""}{profile.phone ? ` • ${profile.phone}` : ""}
              </div>
              <div className="mt-1 text-xs text-[#6A89A7]">
                {wordCount} words • {scorePhaseLabel}
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              {user && (
                <>
                  <div className="relative">
                    <button
                      type="button"
                      onClick={() => { setShowVersionDropdown((c) => !c); if (!resumeVersions.length) fetchVersions(); }}
                      className="inline-flex items-center gap-1.5 rounded-xl border border-[#BDDDFC]/30 bg-white px-3 py-2 text-xs font-medium text-[#384959] hover:bg-[#f0f4f8]"
                    >
                      <Download size={13} />
                      Load Version
                      <ChevronRight size={12} className={`transition-transform ${showVersionDropdown ? "rotate-90" : ""}`} />
                    </button>
                    {showVersionDropdown && (
                      <div className="absolute right-0 top-full z-50 mt-1 w-64 rounded-xl border border-[#BDDDFC]/30 bg-white p-2 shadow-lg">
                        {versionsLoading ? (
                          <div className="flex items-center gap-2 px-3 py-2 text-xs text-[#6A89A7]"><Loader2 size={12} className="animate-spin" />Loading...</div>
                        ) : resumeVersions.length === 0 ? (
                          <div className="px-3 py-2 text-xs text-[#6A89A7]">No saved versions yet.</div>
                        ) : (
                          <div className="max-h-48 overflow-y-auto space-y-0.5">
                            {resumeVersions.map((v) => (
                              <div key={v.id} className="group/vdrop relative rounded-lg hover:bg-[#f0f4f8] transition">
                                {deletingVersionId === v.id ? (
                                  <div className="flex items-center justify-between gap-2 px-3 py-2">
                                    <span className="text-xs font-medium text-[#384959]">Delete?</span>
                                    <div className="flex gap-1">
                                      <button type="button" onClick={() => { deleteVersion(v.id); }} className="rounded-md bg-[#384959] px-2 py-0.5 text-[10px] font-medium text-white hover:bg-[#2a3744]">Yes</button>
                                      <button type="button" onClick={() => setDeletingVersionId(null)} className="rounded-md border border-[#BDDDFC]/30 px-2 py-0.5 text-[10px] font-medium text-[#6A89A7] hover:bg-white">No</button>
                                    </div>
                                  </div>
                                ) : renamingVersionId === v.id ? (
                                  <div className="flex items-center gap-1 px-2 py-1.5">
                                    <input
                                      autoFocus
                                      value={renamingVersionLabel}
                                      onChange={(e) => setRenamingVersionLabel(e.target.value)}
                                      onKeyDown={(e) => {
                                        if (e.key === "Enter") renameVersion(v.id, renamingVersionLabel);
                                        if (e.key === "Escape") { setRenamingVersionId(null); setRenamingVersionLabel(""); }
                                      }}
                                      className="flex-1 min-w-0 rounded-md border border-[#BDDDFC]/30 px-2 py-0.5 text-xs text-[#384959] focus:outline-none focus:ring-1 focus:ring-[#6A89A7]/30"
                                    />
                                    <button type="button" onClick={() => renameVersion(v.id, renamingVersionLabel)} className="rounded-md bg-[#384959] p-1 text-white hover:bg-[#2a3744]"><Check size={10} /></button>
                                    <button type="button" onClick={() => { setRenamingVersionId(null); setRenamingVersionLabel(""); }} className="rounded-md border border-[#BDDDFC]/30 p-1 text-[#6A89A7]"><X size={10} /></button>
                                  </div>
                                ) : (
                                  <div className="flex items-center">
                                    <button
                                      type="button"
                                      onClick={() => { loadVersion(v.id); setShowVersionDropdown(false); }}
                                      className="flex-1 min-w-0 text-left px-3 py-2 text-xs"
                                    >
                                      <div className="font-medium text-[#384959] truncate">{v.label}</div>
                                      <div className="text-[#6A89A7] mt-0.5">
                                        {v.score ? `Score ${v.score}` : ""}{v.job_title ? ` • ${v.job_title}` : ""}
                                        {v.word_count ? ` • ${v.word_count}w` : ""}
                                      </div>
                                    </button>
                                    <div className="flex items-center gap-0.5 pr-2 opacity-0 group-hover/vdrop:opacity-100 transition-opacity">
                                      <button
                                        type="button"
                                        onClick={(e) => { e.stopPropagation(); setRenamingVersionId(v.id); setRenamingVersionLabel(v.label); }}
                                        className="rounded p-1 text-[#6A89A7] hover:text-[#384959] hover:bg-[#BDDDFC]/10"
                                        title="Rename"
                                      >
                                        <Edit3 size={11} />
                                      </button>
                                      <button
                                        type="button"
                                        onClick={(e) => { e.stopPropagation(); setDeletingVersionId(v.id); }}
                                        className="rounded p-1 text-[#6A89A7] hover:text-rose-500 hover:bg-rose-50"
                                        title="Delete"
                                      >
                                        <Trash2 size={11} />
                                      </button>
                                    </div>
                                  </div>
                                )}
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                  <div className="inline-flex items-center gap-1 rounded-xl border border-[#BDDDFC]/30 bg-white p-1">
                    <input
                      type="text"
                      value={saveVersionLabel}
                      onChange={(e) => setSaveVersionLabel(e.target.value)}
                      onKeyDown={(e) => { if (e.key === "Enter") saveCurrentVersion(); }}
                      placeholder="Name this version..."
                      className="w-36 rounded-lg bg-transparent px-2.5 py-1.5 text-sm text-[#384959] placeholder-[#6A89A7]/60 focus:outline-none"
                    />
                    <button
                      type="button"
                      onClick={saveCurrentVersion}
                      disabled={savingVersion || !saveVersionLabel.trim() || !resumeText.trim()}
                      className="rounded-lg bg-[#384959] px-3 py-1.5 text-sm font-medium text-white hover:bg-[#2d3a47] disabled:opacity-40"
                    >
                      {savingVersion ? "..." : "Save"}
                    </button>
                  </div>
                </>
              )}
              <button
                type="button"
                onClick={() => { setShowSetupPanel(true); setWizardStep(1); }}
                className="inline-flex items-center gap-2 rounded-xl border border-[#BDDDFC]/30 bg-white px-3 py-2 text-xs font-medium text-[#384959] hover:bg-[#f0f4f8]"
              >
                <Edit3 size={13} />
                Edit Setup
              </button>
              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                className="inline-flex items-center gap-2 rounded-xl bg-[#384959] px-3 py-2 text-xs font-medium text-white hover:bg-[#2d3a47]"
              >
                <UploadCloud size={13} />
                Replace
              </button>
            </div>
          </div>
        </div>
      )}

      {wizardStep <= 3 && (uploadError || scoreError || coachError || formatError || downloadError || error) && (
        <div className="space-y-2">
          {[uploadError, scoreError, coachError, formatError, downloadError, error].filter(Boolean).map((message, index) => (
            <div key={`${message}-${index}`} className="flex items-center gap-2 rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
              <AlertCircle size={14} className="flex-shrink-0" />
              <span>{message}</span>
            </div>
          ))}
        </div>
      )}

      {wizardStep <= 3 && uploadWarnings.length > 0 && (
        <div className="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
          <div className="flex items-center gap-2 font-semibold">
            <AlertCircle size={14} className="flex-shrink-0" />
            Review parsed resume text
          </div>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-xs leading-relaxed">
            {uploadWarnings.map((warning) => (
              <li key={warning}>{warning}</li>
            ))}
          </ul>
        </div>
      )}

      {/* ── Step 2: Template ─────────────────────────────────────────── */}
      {wizardStep === 2 && (<>
      <div className="rounded-3xl border border-[#BDDDFC]/30 bg-white p-5 shadow-sm">
        <div className="flex items-center justify-between gap-4">
          <div>
            <div className="text-sm font-semibold text-[#384959]">Templates</div>
            <div className="text-xs text-[#6A89A7]">Pick a layout to get started. You can change this anytime from the editor.</div>
          </div>
          <div className="hidden lg:flex items-center gap-2 rounded-full bg-[#BDDDFC]/10 px-3 py-1 text-xs font-medium text-[#6A89A7]">
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
                    : "border-[#BDDDFC]/30 bg-white hover:border-[#BDDDFC]/30 hover:shadow-sm"
                }`}
              >
                <TemplatePreview templateId={template.id} />
                <div className="mt-3 flex items-center gap-2 text-sm font-semibold text-[#384959]">
                  <span>{template.name}</span>
                  {template.id === "singapore" && (
                    <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-600">
                      SG-ready
                    </span>
                  )}
                </div>
                <div className="mt-1 text-xs leading-relaxed text-[#6A89A7]">{template.description}</div>
              </button>
            );
          })}
        </div>
      </div>

      {/* Step 2 navigation */}
      <div className="flex items-center justify-between">
        <button
          type="button"
          onClick={() => { setShowSetupPanel(true); setWizardStep(1); }}
          className="inline-flex items-center gap-2 rounded-xl border border-[#BDDDFC]/30 bg-white px-4 py-2.5 text-sm font-medium text-[#384959] hover:bg-[#f0f4f8]"
        >
          <ArrowLeft size={14} />
          Back
        </button>
        <button
          type="button"
          onClick={() => setWizardStep(3)}
          className="inline-flex items-center gap-2 rounded-xl bg-[#384959] px-5 py-2.5 text-sm font-medium text-white hover:bg-blue-700"
        >
          Next: Review & Edit
          <ArrowRight size={14} />
        </button>
      </div>
      </>)}

      {/* ── Step 3: Review & Edit ────────────────────────────────────── */}
      {wizardStep === 3 && (<>
      <div className="rounded-3xl border border-[#BDDDFC]/30 bg-white p-4 shadow-sm">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div className="min-w-0">
            <div className="text-sm font-semibold text-[#384959]">Resume Workspace</div>
            <div className="mt-0.5 text-xs text-[#6A89A7]">Edit directly or review evidence-safe bullet proposals.</div>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <div className="inline-flex rounded-2xl border border-[#BDDDFC]/30 bg-[#f0f4f8] p-1" role="tablist" aria-label="Resume editor mode">
              {[
                ["classic", "Classic editor", Edit3],
                ["agent", "Agent review", Sparkles],
              ].map(([mode, label, Icon]) => {
                const active = editorMode === mode;
                return (
                  <button
                    key={mode}
                    type="button"
                    onClick={() => setEditorMode(mode)}
                    aria-pressed={active}
                    className={`inline-flex items-center gap-1.5 rounded-xl px-3 py-1.5 text-xs font-semibold transition ${
                      active ? "bg-[#384959] text-white" : "text-[#6A89A7] hover:bg-[#f0f4f8] hover:text-[#384959]"
                    }`}
                  >
                    <Icon size={13} />
                    {label}
                  </button>
                );
              })}
            </div>

            <div className="inline-flex items-center gap-2 rounded-2xl bg-[#f0f4f8] px-3 py-2 text-sm text-[#6A89A7]">
              <span className={`inline-flex h-8 min-w-8 items-center justify-center rounded-xl px-2 text-base font-bold ${scorePillClass}`}>
                {scoreDisplayValue}
              </span>
              <div>
                <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[#6A89A7]">Resume Score</div>
                <div className="text-xs">{scorePhaseLabel}</div>
              </div>
            </div>

            <div className="inline-flex items-center gap-2 rounded-2xl bg-indigo-50 px-3 py-2 text-sm text-indigo-700">
              <span className="inline-flex h-8 min-w-8 items-center justify-center rounded-xl bg-[#384959] px-2 text-sm font-bold text-white">
                {improvementCount}
              </span>
              <div>
                <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-indigo-500">Suggested Fixes</div>
                <div className="text-xs">{issueBulletCount} bullet issues, {relevantMissingKeywords.length} missing keywords</div>
              </div>
            </div>

            {user && (
              <div className="inline-flex items-center gap-1 rounded-xl border border-[#BDDDFC]/30 bg-white px-1.5 py-1">
                <input
                  type="text"
                  value={saveVersionLabel}
                  onChange={(e) => setSaveVersionLabel(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter") saveCurrentVersion(); }}
                  placeholder="Version name..."
                  className="w-32 rounded-lg bg-transparent px-2.5 py-1.5 text-sm text-[#384959] placeholder-[#6A89A7]/60 focus:outline-none"
                />
                <button
                  type="button"
                  onClick={saveCurrentVersion}
                  disabled={savingVersion || !saveVersionLabel.trim() || !resumeText.trim()}
                  className="rounded-lg bg-[#384959] px-3 py-1.5 text-sm font-medium text-white hover:bg-[#2d3a47] disabled:opacity-40"
                >
                  {savingVersion ? "..." : "Save"}
                </button>
              </div>
            )}

          </div>
        </div>
      </div>

      {editorMode === "agent" && (
        <div data-testid="resume-agent-v2-panel" className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_340px]">
          <section className="rounded-3xl border border-[#BDDDFC]/30 bg-white p-5 shadow-sm">
            <div className="flex items-center justify-between gap-3">
              <div>
                <div className="text-sm font-semibold text-[#384959]">Agent Review</div>
                <div className="mt-1 text-xs text-[#6A89A7]">
                  {selectedJob?.title ? `Targeting ${selectedJob.title} at ${selectedJob.company || "target company"}` : "General resume strengthening"}
                </div>
              </div>
              {agentLoading && <Loader2 size={16} className="animate-spin text-[#6A89A7]" />}
            </div>

            <div className="mt-4 min-h-40 rounded-2xl border border-[#BDDDFC]/30 bg-[#f0f4f8] p-3">
              {agentMessages.length > 0 ? (
                <div className="space-y-2">
                  {agentMessages.map((message, index) => (
                    <div
                      key={`${message.role}-${index}`}
                      className={`max-w-[75ch] whitespace-pre-wrap rounded-2xl px-3 py-2 text-sm leading-relaxed ${
                        message.role === "user"
                          ? "ml-auto bg-[#384959] text-white"
                          : "bg-white text-[#384959]"
                      }`}
                    >
                      {message.content}
                    </div>
                  ))}
                </div>
              ) : (
                <div className="flex min-h-32 items-center justify-center text-center">
                  <div className="max-w-sm">
                    <Sparkles size={18} className="mx-auto text-[#88BDF2]" />
                    <div className="mt-2 text-sm font-semibold text-[#384959]">Ask for a review pass</div>
                    <div className="mt-1 text-sm leading-relaxed text-[#6A89A7]">
                      Several reviewers critique your resume, then return evidence-backed edits for you to approve.
                      This usually takes 30 seconds to 2 minutes.
                    </div>
                  </div>
                </div>
              )}
            </div>

            {agentLoading && (
              <div className="mt-3 flex items-center gap-3 rounded-2xl border border-[#BDDDFC]/30 bg-[#f7fafc] px-3 py-2.5" role="status" aria-live="polite">
                <Loader2 size={16} className="shrink-0 animate-spin text-[#6A89A7]" />
                <div className="min-w-0">
                  <div className="text-sm font-medium text-[#384959]">{agentProgress || "Reviewing your resume"}</div>
                  <div className="mt-0.5 text-xs text-[#6A89A7]">
                    {agentElapsedSeconds}s elapsed. You can switch pages and return while this continues.
                  </div>
                </div>
              </div>
            )}

            {agentError && (
              <div className="mt-3 flex items-start gap-2 rounded-2xl border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">
                <AlertCircle size={14} className="mt-0.5 shrink-0" />
                <span>{agentError}</span>
              </div>
            )}

            <div className="mt-4 flex gap-2">
              <textarea
                value={agentInput}
                onChange={(event) => setAgentInput(event.target.value)}
                rows={3}
                disabled={!resumeText.trim()}
                className="min-h-20 flex-1 resize-y rounded-2xl border border-[#BDDDFC]/30 px-3 py-2 text-sm text-[#384959] outline-none transition focus:border-[#88BDF2] focus:ring-2 focus:ring-[#88BDF2]/20 disabled:bg-[#f0f4f8] disabled:text-[#6A89A7]"
                placeholder={resumeText.trim() ? "Ask for ATS gaps, unsupported claims, or safer bullet rewrites..." : "Upload or paste a resume before using Agent Review."}
              />
              <button
                type="button"
                onClick={handleAgentSend}
                disabled={agentLoading || !agentInput.trim() || !resumeText.trim()}
                className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl bg-[#384959] text-white transition hover:bg-[#2d3a47] disabled:opacity-40"
                title="Send to Agent Review"
              >
                {agentLoading ? <Loader2 size={16} className="animate-spin" /> : <Send size={16} />}
              </button>
            </div>

            <details className="mt-3 rounded-2xl border border-[#BDDDFC]/30 bg-white px-3 py-2">
              <summary className="cursor-pointer text-xs font-semibold text-[#384959]">
                Add LinkedIn or profile context
              </summary>
              <textarea
                value={agentProfileContext}
                onChange={(event) => setAgentProfileContext(event.target.value)}
                rows={4}
                className="mt-3 min-h-24 w-full resize-y rounded-xl border border-[#BDDDFC]/30 px-3 py-2 text-sm text-[#384959] outline-none transition focus:border-[#88BDF2] focus:ring-2 focus:ring-[#88BDF2]/20"
                placeholder="Paste LinkedIn About/Experience or profile notes. The agent uses this for consistency checks and questions, not unsupported resume claims."
              />
              <div className="mt-2 text-xs leading-relaxed text-[#6A89A7]">
                Profile-only details stay as gaps to verify unless your resume already supports them.
              </div>
            </details>
          </section>

          <aside className="space-y-4">
            <div className="rounded-3xl border border-[#BDDDFC]/30 bg-white p-5 shadow-sm">
              <div className="text-sm font-semibold text-[#384959]">Worklist</div>
              <div className="mt-3 space-y-2">
                {(agentTodos.length ? agentTodos : ["Read resume evidence", "Check role fit", "Prepare reviewable bullet edits"]).map((todo) => (
                  <div key={todo} className="flex items-start gap-2 text-sm text-[#6A89A7]">
                    <CheckCircle size={14} className="mt-0.5 shrink-0 text-emerald-600" />
                    <span>{todo}</span>
                  </div>
                ))}
              </div>
            </div>

            <details className="rounded-3xl border border-[#BDDDFC]/30 bg-white p-5 shadow-sm">
              <summary className="cursor-pointer text-sm font-semibold text-[#384959]">Tool activity</summary>
              <div className="mt-3 space-y-2">
                {agentToolSpans.length > 0 ? agentToolSpans.map((span, index) => (
                  <div key={`${span.name || "tool"}-${index}`} className="rounded-2xl bg-[#f0f4f8] px-3 py-2 text-xs text-[#6A89A7]">
                    <div className="flex items-center justify-between gap-3">
                      <span className="font-semibold text-[#384959]">
                        {span.worker && span.worker !== "orchestrator" ? `${String(span.worker).replaceAll("_", " ")} · ` : ""}{span.name || "tool"}
                      </span>
                      <span>{span.status || "unknown"}{Number.isFinite(span.duration_ms) ? ` · ${span.duration_ms} ms` : ""}</span>
                    </div>
                    {Array.isArray(span.input_keys) && span.input_keys.length > 0 && (
                      <div className="mt-1">Inputs: {span.input_keys.join(", ")}</div>
                    )}
                    {span.result && Object.keys(span.result).length > 0 && (
                      <div className="mt-1">Result: {Object.entries(span.result).map(([key, value]) => `${key}=${value}`).join(", ")}</div>
                    )}
                  </div>
                )) : (
                  <div className="text-xs leading-relaxed text-[#6A89A7]">
                    Tool calls will appear as each independent reviewer completes its required research or validation pass.
                  </div>
                )}
              </div>
            </details>

            <div className="rounded-3xl border border-[#BDDDFC]/30 bg-white p-5 shadow-sm">
              <div className="flex items-center justify-between gap-3">
                <div className="text-sm font-semibold text-[#384959]">Independent Reviewer Assessments</div>
                {Number.isFinite(agentAssessment.score) && (
                  <span className="rounded-full bg-[#BDDDFC]/20 px-2.5 py-1 text-xs font-semibold text-[#384959]">
                    Median {agentAssessment.score}/100
                  </span>
                )}
              </div>
              <div className="mt-3 space-y-2">
                {agentWorkerRuns.filter((run) => run.status === "error").map((run) => (
                  <div key={`failure-${run.persona}`} className="rounded-2xl border border-amber-200 bg-amber-50 px-3 py-3 text-xs text-amber-900">
                    <div className="font-semibold capitalize">{String(run.persona || "reviewer").replaceAll("_", " ")} incomplete · {run.failure_type || "error"}</div>
                    <div className="mt-1">{run.remaining_gap || run.error?.message || "This specialist assessment is unavailable."}</div>
                    <div className="mt-1 text-amber-800">Attempted {run.attempt_count || 0} time(s){run.source ? ` using ${run.source}` : ""}.</div>
                    {Array.isArray(run.suggested_alternatives) && run.suggested_alternatives.length > 0 && (
                      <div className="mt-1"><span className="font-semibold">Alternative:</span> {run.suggested_alternatives[0]}</div>
                    )}
                  </div>
                ))}
                {agentFindings.length > 0 ? agentFindings.map((finding, index) => (
                  <div key={`${finding.persona || "persona"}-${index}`} className="rounded-2xl bg-[#f0f4f8] px-3 py-2 text-sm text-[#384959]">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-semibold capitalize">{String(finding.persona || "reviewer").replaceAll("_", " ")}</span>
                      {finding.category && <span className="text-xs text-[#6A89A7]">{finding.category}</span>}
                      {Number.isFinite(finding.score) && <span className="ml-auto text-xs font-semibold text-[#384959]">{finding.score}/100</span>}
                    </div>
                    {finding.summary && <div className="mt-2 text-sm font-medium leading-relaxed text-[#384959]">{finding.summary}</div>}
                    {Array.isArray(finding.strengths) && finding.strengths.length > 0 && (
                      <div className="mt-2 text-xs leading-relaxed text-emerald-700"><span className="font-semibold">Strength:</span> {finding.strengths.join(" ")}</div>
                    )}
                    {Array.isArray(finding.weaknesses) && finding.weaknesses.length > 0 && (
                      <div className="mt-1 text-xs leading-relaxed text-rose-700"><span className="font-semibold">Weakness:</span> {finding.weaknesses.join(" ")}</div>
                    )}
                    {(finding.reasoning || finding.rationale) && <div className="mt-1 text-xs leading-relaxed text-[#6A89A7]"><span className="font-semibold">Reasoning:</span> {finding.reasoning || finding.rationale}</div>}
                    {(finding.suggested_actions?.[0] || finding.suggested_action) && <div className="mt-1 text-xs leading-relaxed text-[#384959]"><span className="font-semibold">Next:</span> {(finding.suggested_actions || [finding.suggested_action]).join(" ")}</div>}
                    {Array.isArray(finding.findings) && finding.findings.length > 0 && (
                      <details className="mt-2 border-t border-[#BDDDFC]/30 pt-2 text-xs text-[#6A89A7]">
                        <summary className="cursor-pointer font-semibold">Evidence methods</summary>
                        <div className="mt-2 space-y-2">
                          {finding.findings.map((item, itemIndex) => (
                            <div key={`${item.source || "source"}-${item.source_location || itemIndex}`}>
                              <span className="font-semibold capitalize">{item.kind} · {Math.round(Number(item.relevance_score || 0) * 100)}%</span>
                              <div>{item.method}</div>
                              <div>Source: {item.source} · {item.source_location}</div>
                            </div>
                          ))}
                        </div>
                      </details>
                    )}
                    {Array.isArray(finding.evidence_ids) && finding.evidence_ids.length > 0 && (
                      <div className="mt-2 border-t border-[#BDDDFC]/30 pt-2 text-xs leading-relaxed text-[#6A89A7]">
                        <span className="font-semibold">Resume evidence:</span>{" "}
                        {finding.evidence_ids
                          .map((id) => agentEvidenceById.get(id)?.text)
                          .filter(Boolean)
                          .slice(0, 2)
                          .map((text) => `“${text}”`)
                          .join("; ")}
                      </div>
                    )}
                    {Array.isArray(finding.target_job_fields) && finding.target_job_fields.length > 0 && (
                      <div className="mt-1 text-xs text-[#6A89A7]">
                        <span className="font-semibold">Target-job evidence:</span>{" "}
                        {finding.target_job_fields.join(", ")}
                      </div>
                    )}
                    {Array.isArray(finding.research_job_ids) && finding.research_job_ids.length > 0 && (
                      <div className="mt-1 text-xs text-[#6A89A7]"><span className="font-semibold">Compared jobs:</span> {finding.research_job_ids.join(", ")}</div>
                    )}
                  </div>
                )) : (
                  <div className="text-sm text-[#6A89A7]">Findings will appear after the agent reviews the draft.</div>
                )}
              </div>
            </div>

            <div className="rounded-3xl border border-[#BDDDFC]/30 bg-white p-5 shadow-sm">
              <div className="flex items-center justify-between gap-3">
                <div className="text-sm font-semibold text-[#384959]">Proposed Edits</div>
                <span className="rounded-full bg-[#BDDDFC]/20 px-2 py-0.5 text-xs font-semibold text-[#384959]">{agentPendingDiffs.length}</span>
              </div>
              <div className="mt-3 space-y-3">
                {agentPendingDiffs.length > 0 ? agentPendingDiffs.map((diff, index) => (
                  <div key={diff.bullet_id} className="rounded-2xl border border-[#BDDDFC]/30 bg-[#f0f4f8] p-3">
                    <div className="text-xs font-semibold uppercase tracking-[0.14em] text-[#6A89A7]">Edit {index + 1}</div>
                    <div className="mt-2 rounded-xl bg-white px-3 py-2">
                      <div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-[#6A89A7]">Current</div>
                      <div className="mt-1 text-xs leading-relaxed text-[#6A89A7]">{diff.original}</div>
                    </div>
                    <div className="mt-2 rounded-xl bg-white px-3 py-2">
                      <div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-emerald-700">Proposed</div>
                      <div className="mt-1 text-sm leading-relaxed text-[#384959]">{diff.rewrite}</div>
                    </div>
                    <div className="mt-3 flex gap-2">
                      <button
                        type="button"
                        onClick={() => handleAgentDiffDecision(diff.bullet_id, "accept")}
                        disabled={Boolean(agentApplyingDiffId)}
                        className="inline-flex items-center gap-1.5 rounded-xl bg-emerald-600 px-3 py-1.5 text-xs font-medium text-white transition hover:bg-emerald-700 disabled:opacity-50"
                      >
                        {agentApplyingDiffId === diff.bullet_id ? <Loader2 size={13} className="animate-spin" /> : <CheckCircle size={13} />}
                        {agentApplyingDiffId === diff.bullet_id ? "Applying" : "Accept"}
                      </button>
                      <button
                        type="button"
                        onClick={() => handleAgentDiffDecision(diff.bullet_id, "reject")}
                        disabled={Boolean(agentApplyingDiffId)}
                        className="inline-flex items-center gap-1.5 rounded-xl border border-[#BDDDFC]/30 bg-white px-3 py-1.5 text-xs font-medium text-[#384959] transition hover:bg-[#f0f4f8] disabled:opacity-50"
                      >
                        <X size={13} />
                        Reject
                      </button>
                    </div>
                  </div>
                )) : (
                  <div className="text-sm leading-relaxed text-[#6A89A7]">Per-bullet edits will appear here for review before they change the draft.</div>
                )}
              </div>
            </div>
          </aside>
        </div>
      )}

      <div className={`${editorMode === "agent" ? "hidden" : "lg:hidden"} rounded-xl bg-blue-50 border border-blue-200 px-3 py-2 text-xs text-blue-700`}>
        Tap any colored bullet for AI feedback. For the full editing experience, use a desktop browser.
      </div>

      <div className={`${editorMode === "agent" ? "hidden" : "grid"} gap-6 lg:grid-cols-[minmax(0,65%)_minmax(320px,35%)]`} data-testid="classic-resume-editor">
        <aside className="hidden space-y-4 lg:order-2 lg:block lg:sticky lg:top-16 lg:self-start lg:max-h-[calc(100vh-5rem)] lg:overflow-y-auto">
          {(
            <div className="rounded-3xl border border-[#BDDDFC]/30 bg-white p-5 shadow-sm">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <div className="text-sm font-semibold text-[#384959]">Next Fixes</div>
                  <div className="mt-1 text-xs text-[#6A89A7]">Pick the next fix without leaving the document.</div>
                </div>
                <span className="inline-flex h-9 min-w-9 items-center justify-center rounded-2xl bg-[#384959] px-2 text-sm font-bold text-white">
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
                            <div className="text-sm font-semibold text-[#384959]">{item.title}</div>
                            <div className="mt-1 text-xs leading-relaxed text-[#6A89A7]">{item.detail}</div>
                          </div>
                          <span className="rounded-full bg-white px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.12em] text-[#6A89A7]">
                            {label}
                          </span>
                        </div>
                      </button>
                    );
                  }

                  const isActive = activeSuggestionHint?.id === item.id;
                  return (
                    <button
                      key={item.id}
                      type="button"
                      onClick={() => {
                        setSelectedInjectKeyword(null);
                        setActiveSuggestionHint(isActive ? null : item);
                        setMobilePanel("feedback");
                      }}
                      className={`w-full rounded-2xl border px-3 py-3 text-left transition hover:shadow-sm ${isActive ? "border-indigo-300 bg-indigo-50" : "border-slate-200 bg-slate-50 hover:border-indigo-200 hover:bg-indigo-50/50"}`}
                    >
                      <div className="flex items-center justify-between gap-3">
                        <div className="text-sm font-semibold text-[#384959]">{item.title}</div>
                        {item.points > 0 && (
                          <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.12em] ${isActive ? "bg-indigo-600 text-white" : "bg-indigo-100 text-indigo-700"}`}>
                            +{item.points}
                          </span>
                        )}
                      </div>
                      <div className="mt-1 text-xs leading-relaxed text-[#6A89A7]">{item.detail}</div>
                      {isActive && <div className="mt-2 text-[10px] font-medium text-indigo-600">Active - select a bullet and rewrite to apply</div>}
                    </button>
                  );
                }) : (
                  <div className="rounded-2xl border border-emerald-200 bg-emerald-50 px-3 py-3 text-sm text-emerald-800">
                    No flagged bullets right now. Keep tightening content and finalize when ready.
                  </div>
                )}
              </div>
            </div>
          )}
          <div ref={scorePanelRef} className={`rounded-3xl border p-5 shadow-sm ${scoreData ? scoreTheme.panel : "border-[#BDDDFC]/30 bg-white"}`}>
            <div className="flex items-start justify-between gap-3">
              <div>
                <div className="text-xs font-semibold uppercase tracking-[0.18em] text-[#6A89A7]">Rule-based Resume Score</div>
                <div className={`mt-2 text-4xl font-bold ${scoreData ? scoreTheme.text : "text-[#6A89A7]"}`}>
                  {scoring ? "..." : scoreDisplayValue}
                  <span className="ml-1 text-base font-medium text-[#6A89A7]">{scoreData ? "/100" : ""}</span>
                </div>
                <div className="mt-1 text-sm text-[#6A89A7]">
                  {scoreData
                    ? "Impact 40 + presentation 30 + competencies 30. Target-job term match is shown separately."
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
                <div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-[#6A89A7]">Solid</div>
                <div className="mt-1 text-lg font-semibold text-emerald-700">{annotationCounts.emerald || 0}</div>
              </div>
              <div className="rounded-2xl bg-white/85 px-3 py-2">
                <div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-[#6A89A7]">Review</div>
                <div className="mt-1 text-lg font-semibold text-amber-700">{annotationCounts.amber || 0}</div>
              </div>
              <div className="rounded-2xl bg-white/85 px-3 py-2">
                <div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-[#6A89A7]">Verb Check</div>
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
                  <details key={name} open className="overflow-hidden rounded-3xl border border-[#BDDDFC]/30 bg-white shadow-sm">
                    <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-5 py-4">
                      <div>
                        <div className="text-sm font-semibold text-[#384959]">{titleCase(name)}</div>
                        <div className="text-xs text-[#6A89A7]">{displayDimensionScore}/{dimension.max}</div>
                      </div>
                      <span className={`inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-xs font-semibold ${statusMeta.className}`}>
                        {statusMeta.icon}
                        {statusMeta.label}
                      </span>
                    </summary>
                    <div className="border-t border-[#BDDDFC]/20 px-5 py-4">
                      <div className="mb-4 h-2 overflow-hidden rounded-full bg-[#BDDDFC]/10">
                        <div
                          className={`h-full rounded-full ${getScoreTheme(Math.round((displayDimensionScore / dimension.max) * 100)).bar}`}
                          style={{ width: `${dimension.max > 0 ? (displayDimensionScore / dimension.max) * 100 : 0}%` }}
                        />
                      </div>
                      <div className="space-y-3">
                        {Object.entries(displayItems).map(([itemName, item]) => {
                          const itemStatus = getStatusMeta(item.score, item.max);
                          return (
                            <details key={itemName} className="rounded-2xl bg-[#f0f4f8]">
                              <summary className="cursor-pointer list-none p-3">
                                <div className="flex items-start justify-between gap-2">
                                  <div>
                                    <div className="text-sm font-medium text-[#384959]">{titleCase(itemName)}</div>
                                    <div className="mt-1 text-xs text-[#6A89A7]">{item.detail}</div>
                                  </div>
                                  <span className={`inline-flex items-center gap-1 rounded-full px-2 py-1 text-[11px] font-semibold ${itemStatus.className}`}>
                                    {itemStatus.icon}
                                    {item.score}/{item.max}
                                  </span>
                                </div>
                                {item.suggestions?.length > 0 && (
                                  <div className="mt-2 text-xs leading-relaxed text-[#6A89A7]">
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
                              <div className="border-t border-[#BDDDFC]/30 px-3 pb-3 pt-2">
                                {item.matched_keywords?.length > 0 && (
                                  <div className="mb-2">
                                    <div className="text-[10px] font-semibold uppercase tracking-wider text-[#6A89A7] mb-1">Matched</div>
                                    <div className="flex flex-wrap gap-1">
                                      {item.matched_keywords.map((kw) => (
                                        <span key={kw} className="rounded-full bg-emerald-50 px-2 py-0.5 text-[11px] text-emerald-700">{kw}</span>
                                      ))}
                                    </div>
                                  </div>
                                )}
                                {item.missing_keywords?.length > 0 && (
                                  <div>
                                    <div className="text-[10px] font-semibold uppercase tracking-wider text-[#6A89A7] mb-1">Try adding</div>
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

          {scoreData?.evaluation_blocks?.length > 0 && (
            <div className="space-y-3">
              {scoreData.evaluation_blocks.map((block) => {
                const blockIcon = block.icon === "target" ? "🎯"
                  : block.icon === "puzzle" ? "🧩"
                  : block.icon === "lightbulb" ? "💡"
                  : "📋";
                return (
                  <details key={block.type} className="overflow-hidden rounded-2xl border border-[#BDDDFC]/30 bg-white shadow-sm">
                    <summary className="flex cursor-pointer list-none items-center gap-3 px-5 py-4">
                      <span className="text-base">{blockIcon}</span>
                      <div className="text-sm font-semibold text-[#384959]">{block.title}</div>
                      <span className="ml-auto rounded-full bg-[#BDDDFC]/15 px-2.5 py-0.5 text-[11px] font-medium text-[#6A89A7]">
                        {block.items.length} {block.items.length === 1 ? "item" : "items"}
                      </span>
                    </summary>
                    <div className="border-t border-[#BDDDFC]/20 px-5 py-4">
                      <div className="space-y-2.5">
                        {block.items.map((item, idx) => {
                          const accentClass = item.action_type === "reframe"
                            ? "border-l-blue-400 bg-blue-50/60"
                            : item.action_type === "add_skill"
                              ? "border-l-emerald-400 bg-emerald-50/60"
                              : item.action_type === "weave_in"
                                ? "border-l-violet-400 bg-violet-50/60"
                                : "border-l-[#BDDDFC]/50 bg-[#f0f4f8]";
                          const labelColor = item.action_type === "reframe"
                            ? "text-blue-700"
                            : item.action_type === "add_skill"
                              ? "text-emerald-700"
                              : item.action_type === "weave_in"
                                ? "text-violet-700"
                                : "text-[#384959]";
                          return (
                            <div
                              key={`${block.type}-${idx}`}
                              className={`rounded-xl border-l-[3px] px-3.5 py-2.5 ${accentClass}`}
                            >
                              <div className={`text-sm font-medium ${labelColor}`}>{item.label}</div>
                              <div className="mt-1 text-xs leading-relaxed text-[#6A89A7]">{item.detail}</div>
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
            className={`rounded-3xl border p-5 shadow-sm ${selectedBullet ? "border-indigo-200 bg-indigo-50" : "border-[#BDDDFC]/30 bg-white"}`}
          >
            <div className="flex items-center justify-between gap-3">
              <div>
                <div className="text-xs font-semibold uppercase tracking-[0.18em] text-[#6A89A7]">Selected Bullet</div>
                <div className="mt-1 text-sm font-semibold text-[#384959]">
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
                <div className="rounded-2xl border border-white/80 bg-white p-4 text-sm leading-relaxed text-[#384959] shadow-sm">
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
                            : "border-[#BDDDFC]/30 bg-white text-[#384959]"
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
                            <div className="text-sm font-semibold text-[#384959]">{activeBulletTab.title}</div>
                            <div className="mt-1 text-sm leading-relaxed text-[#6A89A7]">{activeBulletTab.summary}</div>
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
                            <div className="text-xs font-semibold uppercase tracking-[0.16em] text-[#6A89A7]">Matched Keywords</div>
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
                {activeSuggestionHint && (
                  <div className="flex items-start justify-between gap-2 rounded-2xl border border-indigo-200 bg-indigo-50 px-3 py-3">
                    <div>
                      <div className="text-xs font-semibold text-indigo-700">Hint active: {activeSuggestionHint.title}</div>
                      <div className="mt-0.5 text-xs leading-relaxed text-indigo-600">{activeSuggestionHint.detail}</div>
                    </div>
                    <button type="button" onClick={() => setActiveSuggestionHint(null)} className="shrink-0 text-indigo-400 hover:text-indigo-600">✕</button>
                  </div>
                )}
                {(() => {
                  const ranked = getRankedKeywordsForBullet(selectedBullet);
                  if (!ranked.length || activeSuggestionHint) return null;
                  return (
                    <div>
                      <div className="mb-2 text-[10px] font-semibold uppercase tracking-[0.12em] text-[#6A89A7]">Inject keyword</div>
                      <div className="flex flex-wrap gap-1.5">
                        {ranked.map((label) => {
                          const active = selectedInjectKeyword === label;
                          const display = label.length > 26 ? label.slice(0, 26) + "…" : label;
                          return (
                            <button
                              key={label}
                              type="button"
                              title={label}
                              onClick={() => {
                                setActiveSuggestionHint(null);
                                setSelectedInjectKeyword(active ? null : label);
                              }}
                              className={`rounded-full border px-2.5 py-1 text-[11px] font-medium transition ${
                                active
                                  ? "border-indigo-400 bg-indigo-600 text-white"
                                  : "border-indigo-200 bg-indigo-50 text-indigo-700 hover:bg-indigo-100"
                              }`}
                            >
                              {active ? "✓ " : "+ "}{display}
                            </button>
                          );
                        })}
                      </div>
                    </div>
                  );
                })()}
                <button
                  type="button"
                  onClick={() => handleBulletRewrite(selectedBullet, activeBulletTab?.id, activeSuggestionHint)}
                  disabled={rewriteLoading[selectedBullet.id]}
                  className="inline-flex w-full items-center justify-center gap-2 rounded-2xl bg-gray-900 px-4 py-2.5 text-sm font-medium text-white transition hover:bg-black disabled:opacity-50"
                >
                  {rewriteLoading[selectedBullet.id] ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />}
                  {rewriteLoading[selectedBullet.id]
                    ? "Rewriting..."
                    : selectedRewrite
                      ? "Rewrites ready below"
                      : getRewriteButtonLabel(activeBulletTab, selectedBullet)}
                </button>
                <div className="rounded-2xl bg-[#f0f4f8] px-3 py-3 text-xs leading-relaxed text-[#6A89A7]">
                  {activeBulletTab?.id === "bullet_length" && activeBulletTab.status === "issue"
                    ? "This will ask AI for a tighter bullet that keeps the existing facts, numbers, and scope but lands the result earlier."
                    : "Keep only claims, numbers, and scope that you can defend in interview. Treat rewrites as drafting help, not fact generation."}
                </div>

                <div className="grid grid-cols-2 gap-2">
                  <button
                    type="button"
                    onClick={() => handleInsertBulletBelow(selectedBullet)}
                    className="inline-flex items-center justify-center gap-2 rounded-2xl border border-[#BDDDFC]/30 bg-white px-4 py-2.5 text-sm font-medium text-[#384959] transition hover:bg-[#f0f4f8]"
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
                    <div className="text-xs font-semibold uppercase tracking-[0.16em] text-[#6A89A7]">Suggested Rewrite</div>
                    {selectedRewrite.no_change ? (
                      <>
                        <div className="rounded-xl bg-amber-50 p-3 text-sm leading-relaxed text-amber-900">
                          {selectedRewrite.message || "No stronger rewrite was suggested for this bullet."}
                        </div>
                        <button
                          type="button"
                          onClick={() => rejectRewrite(selectedBullet.id)}
                          className="inline-flex w-full items-center justify-center gap-2 rounded-xl border border-[#BDDDFC]/30 bg-white px-3 py-2 text-sm font-medium text-[#384959] hover:bg-[#f0f4f8]"
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
                                <div key={`${selectedBullet.id}-rewrite-${optionIndex}`} className="rounded-xl border border-[#BDDDFC]/30 bg-[#f0f4f8] p-3">
                                  <div className="text-[11px] font-semibold uppercase tracking-[0.16em] text-[#6A89A7]">
                                    {optionMeta.label}
                                  </div>
                                  <div className="mt-1 text-[11px] leading-relaxed text-[#6A89A7]">
                                    {optionMeta.detail}
                                  </div>
                                  <div className="mt-2 text-sm leading-relaxed text-[#384959]">{option}</div>
                                  {optionEvaluation.unresolvedFocused.length > 0 && (
                                    <div className="mt-2 text-xs leading-relaxed text-amber-700">
                                      Still flags: {optionEvaluation.unresolvedFocused.map(getIssueLabel).join(", ")}.
                                    </div>
                                  )}
                                  <button
                                    type="button"
                                    onClick={() => acceptRewrite(selectedBullet, optionIndex)}
                                    className="mt-3 inline-flex items-center gap-2 rounded-xl bg-[#384959] px-3 py-2 text-sm font-medium text-white hover:bg-[#2d3a47]"
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
                          className="inline-flex w-full items-center justify-center gap-2 rounded-xl border border-[#BDDDFC]/30 bg-white px-3 py-2 text-sm font-medium text-[#384959] hover:bg-[#f0f4f8]"
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
              <div className="mt-4 text-sm leading-relaxed text-[#6A89A7]">
                Click a bullet in the document to review its annotation here, then rewrite it or edit the line directly on the page.
              </div>
            )}
          </div>

          {showFeedbackPanels && (
          <div className="rounded-3xl border border-[#BDDDFC]/30 bg-white p-5 shadow-sm">
            <div className="text-sm font-semibold text-[#384959]">Resume Targets</div>
            <div className="mt-1 text-xs text-[#6A89A7]">Recommended ranges for this template and experience level.</div>
            <div className="mt-4 space-y-2">
              {benchmarkRows.map((row) => (
                <div key={row.label} className="rounded-2xl border border-[#BDDDFC]/20 bg-[#f0f4f8] px-3 py-3">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="text-sm font-semibold text-[#384959]">{row.label}</div>
                      <div className="mt-1 text-xs text-[#6A89A7]">{row.note}</div>
                    </div>
                    <div className="text-right">
                      <div className="text-sm font-semibold text-[#384959]">{row.current}</div>
                      <div className="text-[11px] text-[#6A89A7]">Target {row.target}</div>
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
          <div className="rounded-3xl border border-[#BDDDFC]/30 bg-white p-5 shadow-sm">
            <div className="text-sm font-semibold text-[#384959]">Job Terms</div>
            {scoreData ? (
              <>
                {relevantTermsMode === "no_job" && (
                  <div className="mt-2 rounded-2xl border border-[#BDDDFC]/30 bg-[#f0f4f8] px-3 py-3 text-sm leading-relaxed text-[#6A89A7]">
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
                    <div className="mt-2 text-sm text-[#6A89A7]">
                      Matched {relevantMatchedKeywords.length} term{relevantMatchedKeywords.length === 1 ? "" : "s"}{relevantTermTotal > 0 ? ` of ${relevantTermTotal}` : ""}.
                    </div>
                    <div className="mt-2 text-xs leading-relaxed text-[#6A89A7]">
                      {relevantTermsMode === "job_match"
                        ? "Matched against the selected job description."
                        : relevantTermsMode === "skills_fallback"
                            ? "Using visible job terms until deeper matching is available."
                            : relevantTermsMode === "match_error"
                              ? "Job-specific matching is unavailable right now, so this panel is falling back to the same visible job terms above."
                              : "Use these naturally. Do not force keywords into the resume."}
                    </div>
                  </>
                )}
                {(relevantTermsMode === "empty" || relevantTermsMode === "match_error") && (
                  <div className="mt-3 rounded-2xl border border-[#BDDDFC]/30 bg-[#f0f4f8] px-3 py-3 text-sm leading-relaxed text-[#6A89A7]">
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
                    <div className="mt-4 flex items-center gap-2">
                      <span className="text-xs font-semibold uppercase tracking-[0.16em] text-[#6A89A7]">Missing Terms</span>
                      <span className="text-[10px] text-[#6A89A7]">Use naturally</span>
                    </div>
                    <div className="relative mt-2 flex flex-wrap gap-1.5">
                      {relevantMissingKeywords.slice(0, 12).map((keyword, idx) => {
                        const label = keyword?.skill || "";
                        const isActive = insertKeywordPopup?.keyword === label;
                        return (
                          <span
                            key={label || idx}
                            className={`rounded-full px-2 py-0.5 text-[11px] font-medium cursor-pointer transition-colors ${
                              isActive
                                ? "bg-rose-600 text-white ring-2 ring-rose-300"
                                : "bg-rose-100 text-rose-700 hover:bg-rose-200"
                            }`}
                            title={keyword?.jd_context || "Click to find best bullet for this keyword"}
                            onClick={(event) => handleMissingKeywordClick(keyword, event)}
                          >
                            {label}
                          </span>
                        );
                      })}
                    </div>
                    {insertKeywordPopup && (
                      <div
                        className="mt-2 rounded-2xl border border-[#BDDDFC]/30 bg-white p-3 shadow-lg"
                        style={{ zIndex: 50 }}
                      >
                        <div className="flex items-center justify-between">
                          <div className="text-xs font-semibold text-[#384959]">
                            Insert <span className="rounded bg-rose-100 px-1.5 py-0.5 text-rose-700">{insertKeywordPopup.keyword}</span> into:
                          </div>
                          <button
                            type="button"
                            onClick={() => setInsertKeywordPopup(null)}
                            className="rounded-full p-0.5 text-[#6A89A7] hover:bg-[#BDDDFC]/10 hover:text-[#6A89A7]"
                          >
                            <X size={12} />
                          </button>
                        </div>
                        {insertKeywordPopup.suggestions.length > 0 ? (
                          <div className="mt-2 space-y-1.5">
                            {insertKeywordPopup.suggestions.map((bullet) => (
                              <div
                                key={bullet.id}
                                className="group flex items-start gap-2 rounded-xl border border-[#BDDDFC]/20 bg-[#f0f4f8] px-2.5 py-2 transition hover:border-indigo-200 hover:bg-indigo-50"
                              >
                                <div className="min-w-0 flex-1">
                                  <div className="text-[10px] font-medium uppercase tracking-wider text-[#6A89A7]">
                                    {bullet.sectionKey || "section"}
                                  </div>
                                  <div className="mt-0.5 truncate text-xs text-[#384959]" title={bullet.text}>
                                    {bullet.text.length > 80 ? `${bullet.text.slice(0, 80)}...` : bullet.text}
                                  </div>
                                </div>
                                <button
                                  type="button"
                                  onClick={() => handleInsertKeywordIntoBullet(bullet, insertKeywordPopup.keyword)}
                                  className="shrink-0 rounded-lg bg-[#384959] px-2 py-1 text-[10px] font-medium text-white transition hover:bg-[#2d3a47]"
                                >
                                  Insert
                                </button>
                              </div>
                            ))}
                          </div>
                        ) : (
                          <div className="mt-2 text-xs text-[#6A89A7]">
                            No bullet points found. Add experience bullets to your resume first.
                          </div>
                        )}
                      </div>
                    )}
                  </>
                )}
              </>
            ) : (
              <div className="mt-2 text-sm text-[#6A89A7]">Score the resume to see matched and missing keywords.</div>
            )}
          </div>
          )}

          <div className="rounded-3xl border border-[#BDDDFC]/30 bg-white p-5 shadow-sm">
            <div className="text-sm font-semibold text-[#384959]">Action Buttons</div>
            <div className="mt-4 space-y-2.5">
              <button
                type="button"
                onClick={handleFinalizeScore}
                disabled={scoring || !resumeText.trim()}
                className="inline-flex w-full items-center justify-center gap-2 rounded-2xl border border-[#BDDDFC]/30 bg-white px-4 py-2.5 text-sm font-medium text-[#384959] transition hover:bg-[#f0f4f8] disabled:opacity-40"
              >
                {scoring ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
                {scoring ? "Scoring..." : "Finalize Score"}
              </button>
              {!jobDescription.trim() && (
                <button
                  type="button"
                  onClick={handleAIFormat}
                  disabled={formatting || !resumeText.trim()}
                  className="inline-flex w-full items-center justify-center gap-2 rounded-2xl bg-[#384959] px-4 py-2.5 text-sm font-medium text-white transition hover:bg-[#2d3a47] disabled:opacity-40"
                >
                  {formatting ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />}
                  {formatting ? "Polishing..." : "Quick Polish"}
                </button>
              )}
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
                  {hasSummarySection ? "Optimise Summary" : "Generate Summary"}
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
              <div className="mt-3 rounded-2xl border border-[#BDDDFC]/30 bg-[#f0f4f8] px-3 py-2 text-xs text-[#6A89A7]">
                Select a job first if you want the full tailor run to rewrite bullets, sections, and the summary against a specific JD. Summary generation can still run without one.
              </div>
            )}
            {aiStatus && (
              <div className="mt-4 inline-flex items-center gap-2 rounded-full bg-[#BDDDFC]/10 px-3 py-1 text-xs font-medium text-[#6A89A7]">
                <span className={`inline-block h-2 w-2 rounded-full ${aiStatus.status === "ready" ? "bg-emerald-500" : aiStatus.status === "busy" ? "bg-amber-500" : "bg-rose-500"}`} />
                {aiStatus.status === "ready" ? "Assistant ready" : aiStatus.status === "busy" ? "Assistant busy" : aiStatus.wait_seconds >= 0 ? `Wait about ${Math.round(aiStatus.wait_seconds)}s` : "Assistant unavailable"}
              </div>
            )}
          </div>

          {(tailoringLoading || tailoringStatus || tailoringResult || tailoringError) && (
            <div className="rounded-3xl border border-violet-200 bg-violet-50 p-5 shadow-sm">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <div className="text-sm font-semibold text-[#384959]">Tailor Resume</div>
                  <div className="mt-1 text-xs leading-relaxed text-[#6A89A7]">
                    Reviews bullets, sections, and summary against the selected job.
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
                  {/* Step track */}
                  <div className="flex items-center">
                    {TAILOR_STAGE_LABELS.map((stage, stageIndex) => {
                      const currentStageNumber = Number.isFinite(tailoringStatus?.stage_number) ? tailoringStatus.stage_number : 0;
                      const isComplete = tailoringResult ? true : currentStageNumber > stageIndex;
                      const isActive = !tailoringResult && tailoringStatus?.stage === stage.id;
                      return (
                        <div key={stage.id} className="flex flex-1 items-center">
                          <div
                            title={stage.label}
                            className={`relative flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-[11px] font-bold transition-all ${
                              isComplete
                                ? "bg-emerald-100 text-emerald-700 ring-1 ring-emerald-300"
                                : isActive
                                  ? "bg-violet-600 text-white shadow-sm shadow-violet-200 ring-2 ring-violet-300 ring-offset-1"
                                  : "bg-[#f0f4f8] text-[#6A89A7] ring-1 ring-[#BDDDFC]/40"
                            }`}
                          >
                            {isComplete ? "✓" : stageIndex + 1}
                          </div>
                          {stageIndex < TAILOR_STAGE_LABELS.length - 1 && (
                            <div className={`h-px flex-1 transition-all ${isComplete ? "bg-emerald-300" : "bg-[#BDDDFC]/40"}`} />
                          )}
                        </div>
                      );
                    })}
                  </div>
                  {/* Active stage label + progress */}
                  <div className="mt-3 flex items-baseline justify-between gap-2">
                    <div className="text-sm font-semibold text-[#384959]">
                      {TAILOR_STAGE_LABELS.find((s) => s.id === tailoringStatus.stage)?.label
                        || titleCase(String(tailoringStatus.stage || "Queued").replace(/_/g, " "))}
                      {tailoringStatus.progress?.total ? (
                        <span className="ml-2 text-xs font-normal text-[#6A89A7]">
                          {tailoringStatus.progress.completed}/{tailoringStatus.progress.total} bullets
                        </span>
                      ) : null}
                    </div>
                    <div className="shrink-0 text-xs text-[#6A89A7]">
                      {(() => {
                        const total = tailoringStatus.total_stages || TAILOR_STAGE_LABELS.length;
                        const current = tailoringResult
                          ? total
                          : Math.min(Math.max((tailoringStatus.stage_number || 0) + 1, 1), total);
                        return `${current} / ${total}`;
                      })()}
                    </div>
                  </div>
                  <div className="mt-1 text-sm leading-relaxed text-[#6A89A7]">{tailoringStatus.message}</div>
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
                      <div className="text-xs font-semibold uppercase tracking-[0.16em] text-[#6A89A7]">Score Lift</div>
                      <div className="mt-2 text-sm leading-relaxed text-[#384959]">
                        {Number.isFinite(tailoringResult?.score?.before) ? tailoringResult.score.before : "--"} → {Number.isFinite(tailoringResult?.score?.after) ? tailoringResult.score.after : "--"}
                      </div>
                    </div>
                    <div className="rounded-2xl border border-violet-200 bg-white p-4">
                      <div className="text-xs font-semibold uppercase tracking-[0.16em] text-[#6A89A7]">Tailor Changes</div>
                      <div className="mt-2 text-sm leading-relaxed text-[#384959]">
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
                      <div className="text-xs font-semibold uppercase tracking-[0.16em] text-[#6A89A7]">Pipeline Notes</div>
                      {tailoringResult.pipeline_notes.map((note, index) => (
                        <div key={`${note.type || "note"}-${index}`} className="rounded-xl bg-amber-50 px-3 py-2 text-sm leading-relaxed text-amber-900">
                          {note.message}
                        </div>
                      ))}
                    </div>
                  )}

                  {tailoringResult.skill_match && (
                    <div className="rounded-2xl border border-violet-200 bg-white p-4">
                      <div className="text-xs font-semibold uppercase tracking-[0.16em] text-[#6A89A7]">Job Match</div>
                      <div className="mt-2 text-sm leading-relaxed text-[#384959]">
                        Matched {tailoringResult.skill_match.before} job term{tailoringResult.skill_match.before === 1 ? "" : "s"} before rewrite.
                        {tailoringResult.skill_match.injectable?.length > 0
                          ? ` ${tailoringResult.skill_match.injectable.length} missing term${tailoringResult.skill_match.injectable.length === 1 ? "" : "s"} looked safe to weave into existing experience.`
                          : ""}
                      </div>
                    </div>
                  )}

                  {tailoringChanges.length > 0 && (
                    <div className="space-y-3 rounded-2xl border border-violet-200 bg-white p-4">
                      <div className="flex flex-wrap items-center justify-between gap-3">
                        <div>
                          <div className="text-xs font-semibold uppercase tracking-[0.16em] text-[#6A89A7]">Review Tailor Changes</div>
                          <div className="mt-1 text-sm text-[#384959]">Accept, reject, or edit each proposed change before applying them to the draft.</div>
                        </div>
                        <div className="flex flex-wrap gap-2 text-xs">
                          <span className="rounded-full bg-emerald-100 px-2.5 py-1 font-semibold text-emerald-800">Accepted {tailoringAcceptedCount}</span>
                          <span className="rounded-full bg-rose-100 px-2.5 py-1 font-semibold text-rose-800">Rejected {tailoringRejectedCount}</span>
                          <span className="rounded-full bg-[#BDDDFC]/10 px-2.5 py-1 font-semibold text-[#384959]">Pending {tailoringPendingCount}</span>
                        </div>
                      </div>
                      <div className="max-h-[34rem] space-y-3 overflow-y-auto pr-1">
                        {tailoringChanges.map((change, index) => {
                          const bulletId = change.type === "summary_rewrite" ? "summary" : change.bullet_id;
                          const changeKey = bulletId || `${change.type}-${index}`;
                          const userStatus = change.user_status || "pending";
                          return (
                            <div key={`${changeKey}-${index}`} className="rounded-2xl border border-[#BDDDFC]/30 bg-[#f0f4f8] p-4">
                              <div className="flex flex-wrap items-center justify-between gap-2">
                                <div className="text-xs font-semibold uppercase tracking-[0.16em] text-[#6A89A7]">
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
                                <div className="rounded-xl border border-[#BDDDFC]/30 bg-white p-3">
                                  <div className="text-[10px] font-semibold uppercase tracking-[0.16em] text-[#6A89A7]">Original</div>
                                  <div className="mt-2 text-sm leading-relaxed text-[#384959]">{change.original}</div>
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
                                className="mt-3 w-full rounded-xl border border-[#BDDDFC]/30 bg-white px-3 py-2 text-sm leading-relaxed text-[#384959]"
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
                        <div className="text-xs font-semibold uppercase tracking-[0.16em] text-[#6A89A7]">ATS Gap Report</div>
                        <div className="mt-1 text-sm text-[#384959]">These skills are still missing or underrepresented after the tailor run.</div>
                      </div>
                      <div className="space-y-3">
                        {tailoringResult.ats_gaps.map((gap, index) => {
                          const gapKey = getAtsGapKey(gap);
                          const gapDecision = atsGapDecisions[gapKey] || "";
                          return (
                            <div key={`${gapKey}-${index}`} className="rounded-2xl border border-[#BDDDFC]/30 bg-[#f0f4f8] p-4">
                              <div className="flex flex-wrap items-center gap-2">
                                <div className="text-sm font-semibold text-[#384959]">{gap.skill}</div>
                                <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${gap.required ? "bg-rose-100 text-rose-800" : "bg-amber-100 text-amber-800"}`}>
                                  {gap.required ? "Required" : "Preferred"}
                                </span>
                              </div>
                              <div className="mt-2 text-sm leading-relaxed text-[#6A89A7]">
                                Suggested placement: <span className="font-medium text-[#384959]">{RESUME_SECTION_LABELS[gap.suggested_section] || titleCase(gap.suggested_section || "experience")}</span>
                              </div>
                              {gap.action && (
                                <div className="mt-1 text-sm leading-relaxed text-[#6A89A7]">
                                  Suggested action: {gap.action}
                                </div>
                              )}
                              {gap.needs_user_input && (
                                <textarea
                                  rows={2}
                                  value={atsGapInputs[gapKey] || ""}
                                  onChange={(event) => setAtsGapInputs((current) => ({ ...current, [gapKey]: event.target.value }))}
                                  placeholder={`Add a real example or fact for ${gap.skill}`}
                                  className="mt-3 w-full rounded-xl border border-[#BDDDFC]/30 bg-white px-3 py-2 text-sm leading-relaxed text-[#384959]"
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
                                  className="inline-flex items-center gap-2 rounded-xl border border-[#BDDDFC]/30 bg-white px-3 py-2 text-sm font-medium text-[#384959] hover:bg-[#f0f4f8]"
                                >
                                  <X size={13} />
                                  Skip
                                </button>
                                {gapDecision && (
                                  <span className="inline-flex items-center rounded-full bg-[#BDDDFC]/10 px-2.5 py-1 text-[11px] font-semibold text-[#384959]">
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
                      className="inline-flex items-center gap-2 rounded-2xl border border-[#BDDDFC]/30 bg-white px-4 py-2.5 text-sm font-medium text-[#384959] transition hover:bg-[#f0f4f8]"
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
                  <div className="text-sm font-semibold text-[#384959]">AI Improve All Review</div>
                  <div className="mt-1 text-xs leading-relaxed text-[#6A89A7]">
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
                  className="rounded-full bg-white px-2.5 py-1 text-xs font-medium text-[#6A89A7] hover:bg-[#f0f4f8]"
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
                        <div className="mt-3 text-xs font-semibold uppercase tracking-[0.16em] text-[#6A89A7]">Current bullet</div>
                        <div className="mt-1 text-sm leading-relaxed text-[#384959]">{suggestion.original}</div>
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
                      <div className="mt-3 text-xs font-semibold uppercase tracking-[0.16em] text-[#6A89A7]">Current bullet</div>
                      <div className="mt-1 text-sm leading-relaxed text-[#384959]">{suggestion.original}</div>
                      {suggestion.issue && (
                        <>
                          <div className="mt-3 text-xs font-semibold uppercase tracking-[0.16em] text-[#6A89A7]">Issue</div>
                          <div className="mt-1 text-sm leading-relaxed text-amber-800">{suggestion.issue}</div>
                        </>
                      )}
                      {suggestion.suggested && (
                        <>
                          <div className="mt-3 text-xs font-semibold uppercase tracking-[0.16em] text-[#6A89A7]">Suggested rewrite</div>
                          <div className="mt-1 text-sm leading-relaxed text-[#384959]">{suggestion.suggested}</div>
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
                              : "border border-[#BDDDFC]/30 bg-white text-[#384959] hover:bg-[#f0f4f8]"
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
                <div className="text-xs leading-relaxed text-[#6A89A7]">
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
                  className="inline-flex items-center justify-center gap-2 rounded-2xl bg-[#384959] px-4 py-2.5 text-sm font-medium text-white transition hover:bg-[#2d3a47] disabled:opacity-40"
                >
                  <CheckCircle size={14} />
                  Apply All Accepted Changes
                </button>
              </div>
            </div>
          )}

          {showFeedbackPanels && (
          <div className="rounded-3xl border border-[#BDDDFC]/30 bg-white p-5 shadow-sm">
            <div className="text-sm font-semibold text-[#384959]">Singapore Tips</div>
            <ul className="mt-3 space-y-2">
              {(scoreData?.sg_tips?.length ? scoreData.sg_tips : [
                "Mention residency status if it meaningfully improves your fit.",
                "List concrete tools and platforms. Skills-based matching matters.",
                "Keep the final layout ATS-friendly and easy to scan on mobile.",
              ]).map((tip, index) => (
                <li key={`${tip}-${index}`} className="flex items-start gap-2 text-sm leading-relaxed text-[#6A89A7]">
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
                    <div className="whitespace-pre-line rounded-2xl bg-white p-4 text-sm leading-relaxed text-[#384959]">
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

        <section className="lg:order-1 lg:block">
          <div className="rounded-[2rem] border border-slate-200 bg-[#f3f5f8] p-4 shadow-sm sm:p-5">
            <div className="flex flex-col gap-3 border-b border-[#BDDDFC]/30/70 px-1 pb-4 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <div className="text-xs font-semibold uppercase tracking-[0.18em] text-[#6A89A7]">Document Preview</div>
                <div className="mt-1 text-sm text-[#6A89A7]">
                  {wordCount} words
                  {resumeText.trim() ? " • click any line to edit inline" : " • upload or paste a resume to begin"}
                </div>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <div className="inline-flex items-center gap-1 rounded-full border border-[#BDDDFC]/30 bg-white px-1">
                  <button
                    type="button"
                    onClick={handleUndo}
                    disabled={undoStackRef.current.length === 0}
                    className="inline-flex items-center gap-1 px-2 py-1.5 text-xs text-[#6A89A7] transition hover:text-[#384959] disabled:opacity-30"
                    title="Undo (Ctrl+Z)"
                  >
                    <RefreshCw size={12} className="scale-x-[-1]" /> Undo
                  </button>
                  <div className="h-4 w-px bg-[#BDDDFC]/20" />
                  <button
                    type="button"
                    onClick={handleRedo}
                    disabled={redoStackRef.current.length === 0}
                    className="inline-flex items-center gap-1 px-2 py-1.5 text-xs text-[#6A89A7] transition hover:text-[#384959] disabled:opacity-30"
                    title="Redo (Ctrl+Shift+Z)"
                  >
                    Redo <RefreshCw size={12} />
                  </button>
                </div>
                <button
                  type="button"
                  onClick={() => setAnnotationsOn((current) => !current)}
                  className={`inline-flex items-center gap-2 rounded-full px-3 py-1.5 text-xs font-medium transition ${annotationsOn ? "bg-[#384959] text-white" : "bg-white text-[#6A89A7] ring-1 ring-[#BDDDFC]/30"}`}
                >
                  <Zap size={12} />
                  {annotationsOn ? "Inline Tips On" : "Inline Tips Off"}
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
              ref={resumePrintRef}
              className={`resume-print-target mx-auto mt-5 bg-white shadow-[0_2px_20px_rgba(0,0,0,0.1)] border border-[#BDDDFC]/30 ${templateStyles.pageClass}`}
              style={templateStyles.pageStyle}
            >
              {resumeText.trim() ? (
                <>
                  {displayHeaderLines.length > 0 && (
                    <div className="mb-4 border-b border-[#BDDDFC]/30 pb-2 text-center">
                      <div className={templateStyles.nameClass} style={templateStyles.nameStyle}>{displayHeaderLines[0]}</div>
                      {displayDetailLines.map((line, index) => (
                        <div key={`${line}-${index}`} className="mx-auto mt-0.5 max-w-[34rem] text-[#6A89A7]" style={templateStyles.contactStyle}>{line}</div>
                      ))}
                    </div>
                  )}

                  <div style={templateStyles.bodyStyle}>
                   <DndContext sensors={dndSensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
                    <SortableContext items={bulletIds} strategy={verticalListSortingStrategy}>
                    {bodySections.map((section, sectionIndex) => {
                      if (section.type === "spacer") {
                        return <div key={section.id} className="h-1.5" />;
                      }

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
                          rows={section.type === "education_entry" ? 5 : section.type === "paragraph" ? 3 : 2}
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
                          className="w-full resize-none rounded-xl border border-indigo-200 bg-white px-3 py-2 text-inherit leading-relaxed text-[#384959] focus:outline-none focus:ring-2 focus:ring-[#BDDDFC]"
                          style={{
                            fontSize: "16px",
                            lineHeight: templateStyles.bodyStyle.lineHeight,
                            fontFamily: templateStyles.bodyStyle.fontFamily,
                          }}
                        />
                      ) : (
                        <button
                          type="button"
                          onClick={() => {
                            if (window.innerWidth < 1024 && section.type === "bullet" && section.annotation?.tone && section.annotation.tone !== "emerald") {
                              setMobileBulletSheet(section);
                              setSelectedBulletId(section.id);
                            } else {
                              openEditorForSection(section);
                            }
                          }}
                          className="w-full text-left"
                        >
                          {section.type === "heading" && (
                            <h3 className={templateStyles.headingClass} style={templateStyles.headingStyle}>
                              {renderHighlightedText(section.text, section.keywordMatches || [])}
                            </h3>
                          )}
                          {section.type === "heading_paragraph" && (
                            <div style={{ breakInside: "avoid", columnSpan: "all" }}>
                              <h3 className={templateStyles.headingClass} style={templateStyles.headingStyle}>
                                {section.headingText}
                              </h3>
                              <p className="mb-4 text-[#384959]" style={{ ...templateStyles.bodyStyle, breakInside: "avoid" }}>
                                {renderHighlightedText(
                                  isShoutySummaryParagraph(section.bodyText, section.sectionKey)
                                    ? toSentenceCaseDisplayText(section.bodyText)
                                    : section.bodyText,
                                  section.keywordMatches || [],
                                )}
                              </p>
                            </div>
                          )}
                          {section.type === "education_entry" && (
                            <div className={`mb-2 rounded-lg border border-[#BDDDFC]/20 bg-[#f0f4f8]/40 px-4 py-3 ${templateStyles.subheadingClass}`}>
                              <div className="font-semibold leading-snug text-[#384959]">
                                {renderHighlightedText(
                                  section.fields.degree || section.fields.institution || section.text,
                                  section.keywordMatches || [],
                                )}
                              </div>
                              {section.fields.dateRange && (
                                <div className="mt-0.5 text-[0.9em] text-[#6A89A7]">
                                  {section.fields.dateRange}
                                </div>
                              )}
                              {section.fields.degree && section.fields.institution && (
                                <div className="mt-0.5 text-[0.93em] leading-snug text-[#6A89A7]">
                                  {section.fields.institution}
                                </div>
                              )}
                              {(section.fields.gpa || section.fields.honors.length > 0 || section.fields.details.length > 0) && (
                                <div className="mt-1 text-[0.85em] text-[#6A89A7]">
                                  {[section.fields.gpa, ...section.fields.honors, ...section.fields.details].filter(Boolean).join(" · ")}
                                </div>
                              )}
                              {section.fields.bullets.length > 0 && (
                                <div className="mt-1.5 space-y-0.5">
                                  {section.fields.bullets.map((bullet) => (
                                    <div key={bullet.id} className="flex gap-2 text-[0.88em] text-[#6A89A7]">
                                      <span className="text-[#6A89A7]">•</span>
                                      <span>{renderHighlightedText(bullet.text, section.keywordMatches || [])}</span>
                                    </div>
                                  ))}
                                </div>
                              )}
                            </div>
                          )}
                          {section.type === "subheading" && (
                            section.variant === "education_main" ? (
                              <div className={`mb-1 rounded-lg border border-[#BDDDFC]/20 bg-[#f0f4f8]/40 px-3 py-2.5 ${templateStyles.subheadingClass}`}>
                                {(() => {
                                  const meta = splitEducationMeta(
                                    getDisplaySubheadingText(section.right, section.sectionKey, section.variant),
                                  );
                                  return (
                                    <>
                                      <div className="flex items-baseline justify-between gap-4">
                                        <div className="font-semibold leading-snug text-[#384959]">
                                          {renderHighlightedText(
                                            getDisplaySubheadingText(section.left, section.sectionKey, section.variant),
                                            section.keywordMatches || [],
                                          )}
                                        </div>
                                        {meta.secondary && (
                                          <div className="shrink-0 text-[0.9em] text-[#6A89A7] whitespace-nowrap">
                                            {meta.secondary}
                                          </div>
                                        )}
                                      </div>
                                      {meta.primary && (
                                        <div className="mt-0.5 text-[0.93em] leading-snug text-[#6A89A7]">
                                          {meta.primary}
                                        </div>
                                      )}
                                    </>
                                  );
                                })()}
                              </div>
                            ) : section.variant === "education_detail" ? (
                              <div className="-mt-0.5 mb-2 ml-3 flex items-baseline justify-between gap-4 text-[0.88em] text-[#6A89A7]">
                                <div className="leading-snug">
                                  {renderHighlightedText(
                                    getDisplaySubheadingText(section.left, section.sectionKey, section.variant),
                                    section.keywordMatches || [],
                                  )}
                                </div>
                                <div className="text-right leading-snug shrink-0">
                                  {getDisplaySubheadingText(section.right, section.sectionKey, section.variant)}
                                </div>
                              </div>
                            ) : (
                              <div className={`${templateStyles.subheadingClass}`}>
                                <div className={section.variant === "dated" ? "font-semibold text-[#384959]" : "font-normal text-[#384959]"}>
                                  {renderHighlightedText(
                                    getDisplaySubheadingText(section.left, section.sectionKey, section.variant),
                                    section.keywordMatches || [],
                                  )}
                                </div>
                                {section.right && (
                                  <div className="text-sm text-[#6A89A7] mt-0.5">
                                    {getDisplaySubheadingText(section.right, section.sectionKey, section.variant)}
                                  </div>
                                )}
                              </div>
                            )
                          )}
                          {section.type === "paragraph" && (
                            (() => {
                              // Summary/experience paragraphs always render full-width, never as inline segments
                              const inlineSegments = !["summary", "experience"].includes(section.sectionKey) ? getInlineResumeSegments(section) : null;
                              if (inlineSegments) {
                                return (
                                  <div className="mb-4 flex flex-wrap items-baseline gap-x-2 gap-y-1 text-[#384959]" style={templateStyles.bodyStyle}>
                                    {inlineSegments.map((segment, index) => (
                                      <Fragment key={`${section.id}-segment-${index}`}>
                                        {index > 0 && <span className="text-[#6A89A7]/60">|</span>}
                                        <span className="font-medium text-[#384959]">
                                          {renderHighlightedText(getDisplayInlineSegmentText(segment), section.keywordMatches || [])}
                                        </span>
                                      </Fragment>
                                    ))}
                                  </div>
                                );
                              }

                              if (section.sectionKey === "education") {
                                return (
                                  <p className="-mt-0.5 mb-2 ml-3 text-[0.88em] leading-snug text-[#6A89A7]" style={templateStyles.bodyStyle}>
                                    {renderHighlightedText(getDisplayParagraphText(section), section.keywordMatches || [])}
                                  </p>
                                );
                              }

                              return (
                                <p
                                  className={`${section.sectionKey === "certifications" ? "mb-1.5" : "mb-4"} text-[#384959] ${section.sectionKey === "summary" && isLikelySummaryLeadParagraph(section.text) && !isShoutySummaryParagraph(section.text, section.sectionKey) ? "font-semibold tracking-[0.03em] text-[#384959]" : ""}`}
                                  style={{ ...templateStyles.bodyStyle, breakInside: "avoid" }}
                                >
                                  {renderHighlightedText(getDisplayParagraphText(section), section.keywordMatches || [])}
                                </p>
                              );
                            })()
                          )}
                          {section.type === "bullet" && (
                            <div className={`flex gap-3 ${["education", "personal", "languages", "additional"].includes(section.sectionKey) ? "ml-2" : ""}`}>
                              <div className={`pt-1 text-[#6A89A7] ${["education", "personal", "languages", "additional"].includes(section.sectionKey) ? "text-[0.85rem]" : "text-[1rem]"}`}>•</div>
                              <div className="flex-1">
                                <p className={["education", "personal", "languages", "additional"].includes(section.sectionKey) ? "text-[0.88em] text-[#6A89A7]" : "text-[#384959]"} style={templateStyles.bodyStyle}>
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

                      const actionButtons = !isEditing && (section.type === "bullet" || section.type === "subheading" || section.type === "paragraph" || section.type === "education_entry") ? (
                        <div className="flex gap-1 opacity-0 group-hover/section:opacity-100 transition-opacity -mt-0.5 mb-0.5 ml-1">
                          {section.type === "bullet" && ["experience", "projects", "education", "certifications", "activities"].includes(section.sectionKey) && (
                            <button
                              type="button"
                              onClick={(e) => { e.stopPropagation(); handlePromoteToPosition(section); }}
                              className="inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[10px] font-medium text-[#6A89A7] hover:text-[#384959] hover:bg-indigo-50 transition"
                              title="Convert to position/entry heading"
                            >
                              <ArrowUp size={9} />
                              Make Position
                            </button>
                          )}
                          {(section.type === "bullet" || section.type === "paragraph") && (
                            <button
                              type="button"
                              onClick={(e) => { e.stopPropagation(); handlePromoteToSection(section); }}
                              className="inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[10px] font-medium text-[#6A89A7] hover:text-violet-600 hover:bg-violet-50 transition"
                              title="Convert to section heading"
                            >
                              <Type size={9} />
                              Make Section
                            </button>
                          )}
                          {(section.type === "subheading" || section.type === "paragraph") && (
                            <button
                              type="button"
                              onClick={(e) => { e.stopPropagation(); handleDemoteToBullet(section); }}
                              className="inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[10px] font-medium text-[#6A89A7] hover:text-amber-600 hover:bg-amber-50 transition"
                              title="Convert to bullet point"
                            >
                              <List size={9} />
                              Make Bullet
                            </button>
                          )}
                          {(section.type === "subheading" || section.type === "education_entry") && (
                            <button
                              type="button"
                              onClick={(e) => { e.stopPropagation(); handleDeleteSection(section); }}
                              className="inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[10px] font-medium text-[#6A89A7] hover:text-rose-600 hover:bg-rose-50 transition"
                              title={section.type === "education_entry" ? "Delete education entry" : "Delete entry and its bullets"}
                            >
                              <Trash2 size={9} />
                              Delete
                            </button>
                          )}
                        </div>
                      ) : null;

                      const sectionMoveButtons = section.type === "heading" && !isEditing ? (
                        <div className="flex gap-0.5 opacity-0 group-hover/section:opacity-100 transition-opacity float-right -mt-6 mr-0">
                          <button
                            type="button"
                            onClick={(e) => { e.stopPropagation(); handleMoveSection(section.id, -1); }}
                            className="rounded p-0.5 text-[#6A89A7]/60 hover:text-[#6A89A7] hover:bg-[#BDDDFC]/10 transition"
                            title="Move section up"
                          >
                            <ArrowUp size={12} />
                          </button>
                          <button
                            type="button"
                            onClick={(e) => { e.stopPropagation(); handleMoveSection(section.id, 1); }}
                            className="rounded p-0.5 text-[#6A89A7]/60 hover:text-[#6A89A7] hover:bg-[#BDDDFC]/10 transition"
                            title="Move section down"
                          >
                            <ArrowDown size={12} />
                          </button>
                          <button
                            type="button"
                            onClick={(e) => { e.stopPropagation(); handleDeleteSection(section); }}
                            className="rounded p-0.5 text-[#6A89A7]/60 hover:text-rose-500 hover:bg-rose-50 transition"
                            title="Delete entire section"
                          >
                            <Trash2 size={12} />
                          </button>
                        </div>
                      ) : null;

                      const sectionContent = (
                        <>
                          <div id={`resume-section-${section.id}`} className={`group/section rounded-xl px-3 py-0.5 transition ${wrapperClasses}`}>
                            {lineContent}
                            {actionButtons}
                            {sectionMoveButtons}
                            {section.type === "heading" && section.sectionKey === "summary" && !isEditing && (
                              <div className="mt-1 space-y-1.5">
                                <div className="flex items-center gap-1.5">
                                  <button
                                    type="button"
                                    onClick={() => setShowSummaryPrompt((v) => !v)}
                                    className="inline-flex items-center gap-1 rounded-lg border border-violet-200 bg-violet-50 px-2 py-1 text-[11px] font-medium text-violet-700 transition hover:bg-violet-100"
                                  >
                                    <Sparkles size={12} />
                                    {showSummaryPrompt ? "Hide" : "Rewrite Summary"}
                                  </button>
                                </div>
                                {showSummaryPrompt && (
                                  <div className="flex gap-1.5">
                                    <input
                                      type="text"
                                      value={summaryDirection}
                                      onChange={(e) => setSummaryDirection(e.target.value)}
                                      onKeyDown={(e) => { if (e.key === "Enter") handleRegenerateSummary(); }}
                                      placeholder="e.g., emphasize AI leadership, keep it concise..."
                                      className="flex-1 rounded-lg border border-violet-200 bg-white px-2.5 py-1.5 text-[11px] text-[#384959] placeholder:text-[#6A89A7]/50 focus:outline-none focus:ring-2 focus:ring-violet-300"
                                    />
                                    <button
                                      type="button"
                                      onClick={handleRegenerateSummary}
                                      disabled={regeneratingSummary}
                                      className="inline-flex items-center gap-1 rounded-lg bg-violet-600 px-3 py-1.5 text-[11px] font-medium text-white transition hover:bg-violet-700 disabled:opacity-40"
                                    >
                                      {regeneratingSummary ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />}
                                      {regeneratingSummary ? "..." : "Generate"}
                                    </button>
                                  </div>
                                )}
                              </div>
                            )}
                          </div>
                          {section.type === "bullet" && (
                            <div className="group/insert flex justify-center -my-1 relative z-10">
                              <button
                                type="button"
                                onClick={() => handleInsertBulletBelow(section)}
                                className="opacity-0 group-hover/insert:opacity-100 focus:opacity-100 transition-opacity inline-flex items-center gap-1 rounded-full border border-dashed border-indigo-300 bg-white px-2 py-0.5 text-[10px] font-medium text-indigo-500 hover:bg-indigo-50 hover:border-indigo-400"
                                title="Insert bullet here"
                              >
                                <Plus size={10} />
                              </button>
                            </div>
                          )}
                        </>
                      );

                      // ── End-of-block buttons: Add Bullet / Add Entry ────────
                      const nextNonSpacer = bodySections.slice(sectionIndex + 1).find((s) => s.type !== "spacer");
                      const isAtEntryBoundary = !nextNonSpacer
                        || nextNonSpacer.type === "heading"
                        || nextNonSpacer.type === "subheading"
                        || nextNonSpacer.type === "education_entry";

                      // "Add Bullet" at end of each position/entry block
                      const addBulletButton = section.type === "bullet"
                        && isAtEntryBoundary
                        && ["experience", "projects", "activities", "certifications"].includes(section.sectionKey) ? (
                          <div className="group/addbullet flex justify-center py-1">
                            <button
                              type="button"
                              onClick={() => handleInsertBulletBelow(section)}
                              className="opacity-0 group-hover/addbullet:opacity-100 focus:opacity-100 transition-opacity inline-flex items-center gap-1.5 rounded-full border border-dashed border-indigo-300 bg-white px-3 py-1 text-[11px] font-medium text-indigo-500 hover:bg-indigo-50 hover:border-indigo-400"
                            >
                              <Plus size={11} />
                              Add Bullet
                            </button>
                          </div>
                        ) : null;

                      // "Add Entry" at end of an entry section (before next heading or end of doc)
                      const isAtSectionEnd = !nextNonSpacer || nextNonSpacer.type === "heading";
                      const entryTemplates = {
                        experience: { text: "Company Name | Job Title | Start – End\n• Describe your key achievement", label: "Add Position" },
                        education: { text: "Degree Name\nUniversity Name, Year", label: "Add Education" },
                        certifications: { text: "• Certification Name (Year)", label: "Add Entry" },
                        projects: { text: "Project Name | Year\n• Describe the project and your role", label: "Add Project" },
                      };
                      const addEntryButton = isAtSectionEnd
                        && section.type !== "heading"
                        && section.type !== "spacer"
                        && entryTemplates[section.sectionKey] ? (() => {
                          const tmpl = entryTemplates[section.sectionKey];
                          return (
                            <div className="group/addentry flex justify-center py-1.5">
                              <button
                                type="button"
                                onClick={() => {
                                  const lines = resumeText.replace(/\r\n?/g, "\n").split("\n");
                                  const insertAt = (section.lineIndices?.[section.lineIndices.length - 1] ?? section.lineIndex) + 1;
                                  lines.splice(insertAt, 0, "", ...tmpl.text.split("\n"));
                                  applyResumeText(lines.join("\n"));
                                }}
                                className="opacity-0 group-hover/addentry:opacity-100 focus:opacity-100 transition-opacity inline-flex items-center gap-1.5 rounded-full border border-dashed border-blue-300 bg-white px-3 py-1 text-[11px] font-medium text-[#88BDF2] hover:bg-blue-50"
                              >
                                <Plus size={11} />
                                {tmpl.label}
                              </button>
                            </div>
                          );
                        })() : null;

                      // Wrap bullets in SortableBulletItem for drag-and-drop
                      if (section.type === "bullet") {
                        return (
                          <SortableBulletItem key={section.id} id={section.id}>
                            {sectionContent}
                            {addBulletButton}
                            {addEntryButton}
                          </SortableBulletItem>
                        );
                      }

                      return (
                        <Fragment key={section.id}>
                          {sectionContent}
                          {addBulletButton}
                          {addEntryButton}
                        </Fragment>
                      );
                    })}
                    </SortableContext>
                   </DndContext>
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
                              className="inline-flex items-center gap-2 rounded-full bg-white px-3 py-2 text-sm font-medium text-slate-700 ring-1 ring-gray-200 hover:bg-[#f0f4f8]"
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
                <div className="flex min-h-[700px] flex-col items-center justify-center rounded-[1.5rem] border border-dashed border-[#BDDDFC]/30 bg-[#f0f4f8] px-8 text-center">
                  <FileText size={36} className="text-[#6A89A7]/60" />
                  <div className="mt-4 text-lg font-semibold text-[#384959]">Your resume document will appear here</div>
                  <p className="mt-2 max-w-md text-sm leading-relaxed text-[#6A89A7]">
                    Upload a PDF or DOCX, or paste your resume text above. Once it lands here, you’ll be able to edit line by line and review feedback beside it.
                  </p>
                </div>
              )}
            </div>
          </div>
        </section>
      </div>

      <div className="fixed inset-x-0 bottom-4 z-20 px-4">
        <div className="mx-auto flex w-full items-center justify-between gap-3 rounded-2xl border border-[#BDDDFC]/30 bg-white/95 px-4 py-3 shadow-[0_16px_40px_rgba(15,23,42,0.18)] backdrop-blur">
          <button
            type="button"
            onClick={jumpToScorePanel}
            className={`inline-flex items-center gap-2 rounded-full px-3 py-2 text-sm font-semibold ${scorePillClass}`}
          >
            <Star size={14} />
            Score {scoreDisplayValue}
          </button>

          <div className="hidden lg:flex items-center gap-2">
            <span className="text-xs font-semibold uppercase tracking-[0.14em] text-[#6A89A7]">Template</span>
            <select
              value={selectedTemplate}
              onChange={(event) => setSelectedTemplate(event.target.value)}
              className="rounded-xl border border-[#BDDDFC]/30 bg-white px-3 py-2 text-sm text-[#384959] focus:outline-none focus:ring-2 focus:ring-[#BDDDFC]"
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
                className="hidden sm:inline-flex items-center gap-2 rounded-xl border border-[#BDDDFC]/30 bg-white px-4 py-2.5 text-sm font-medium text-[#384959] transition hover:bg-[#f0f4f8] disabled:opacity-40"
              >
                {scoring ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
                {scoring ? "Scoring..." : "Finalize Score"}
              </button>
            )}
            {user && (
              <div className="inline-flex items-center gap-1 rounded-xl border border-[#BDDDFC]/30 bg-white px-1.5 py-1">
                <input
                  type="text"
                  value={saveVersionLabel}
                  onChange={(e) => setSaveVersionLabel(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter" && saveVersionLabel.trim()) saveCurrentVersion(); }}
                  placeholder="Version name..."
                  className="w-32 rounded-lg bg-transparent px-2.5 py-1.5 text-sm text-[#384959] placeholder-[#6A89A7]/60 focus:outline-none"
                />
                <button
                  type="button"
                  onClick={saveCurrentVersion}
                  disabled={savingVersion || !saveVersionLabel.trim() || !resumeText.trim()}
                  className="rounded-lg bg-[#384959] px-3 py-1.5 text-xs font-medium text-white hover:bg-[#2d3a47] disabled:opacity-40"
                >
                  {savingVersion ? "..." : "Save"}
                </button>
              </div>
            )}
            <button
              type="button"
              onClick={() => setWizardStep(2)}
              className="inline-flex items-center gap-2 rounded-xl border border-[#BDDDFC]/30 bg-white px-4 py-2.5 text-sm font-medium text-[#384959] transition hover:bg-[#f0f4f8]"
            >
              <ArrowLeft size={14} />
              Templates
            </button>
            <button
              type="button"
              onClick={() => setWizardStep(4)}
              className="inline-flex items-center gap-2 rounded-xl bg-emerald-600 px-4 py-2.5 text-sm font-medium text-white transition hover:bg-emerald-700"
            >
              <Download size={14} />
              Export
            </button>
          </div>
        </div>
      </div>
      </>)}

      {/* ── Step 4: Export ────────────────────────────────────────────── */}
      {wizardStep === 4 && (
        <div className="mx-auto max-w-2xl space-y-6">
          <div className="rounded-3xl border border-[#BDDDFC]/30 bg-white p-6 shadow-sm text-center">
            <div className="text-xs font-semibold uppercase tracking-[0.18em] text-[#6A89A7]">Final Score</div>
            <div className={`mt-3 text-5xl font-bold ${scoreData ? scoreTheme.text : "text-[#6A89A7]"}`}>
              {scoring ? "..." : scoreDisplayValue}
              <span className="ml-1 text-lg font-medium text-[#6A89A7]">{scoreData ? "/100" : ""}</span>
            </div>
            <div className="mt-3 h-2.5 overflow-hidden rounded-full bg-[#BDDDFC]/10 mx-auto max-w-xs">
              <div className={`h-full rounded-full transition-all ${scoreTheme.bar}`} style={{ width: `${scoreData && overallScore !== null ? overallScore : 0}%` }} />
            </div>
            {needsRescore && (
              <button
                type="button"
                onClick={handleFinalizeScore}
                disabled={scoring}
                className="mt-4 inline-flex items-center gap-2 rounded-xl border border-[#BDDDFC]/30 bg-white px-4 py-2.5 text-sm font-medium text-[#384959] hover:bg-[#f0f4f8] disabled:opacity-40"
              >
                {scoring ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
                {scoring ? "Scoring..." : "Finalize Score"}
              </button>
            )}
            {lowScoreWarning && (
              <p className="mt-3 text-xs text-rose-600">
                This draft may still struggle in ATS or recruiter screens. Consider going back to edit.
              </p>
            )}
          </div>

          <div className="rounded-3xl border border-[#BDDDFC]/30 bg-white p-6 shadow-sm space-y-4">
            <div className="text-sm font-semibold text-[#384959]">Download Your Resume</div>
            <p className="text-sm text-[#6A89A7]">
              Template: <span className="font-medium text-[#384959]">{templateMeta?.name || "Modern"}</span>
            </p>
            <div className="flex flex-wrap gap-3">
              <button
                type="button"
                onClick={handleDownload}
                disabled={downloading || !resumeText.trim()}
                className="inline-flex items-center gap-2 rounded-xl bg-emerald-600 px-5 py-3 text-sm font-medium text-white transition hover:bg-emerald-700 disabled:opacity-40"
              >
                {downloading ? <Loader2 size={14} className="animate-spin" /> : <Download size={14} />}
                {downloading ? "Preparing..." : "Download DOCX"}
              </button>
              <button
                type="button"
                onClick={handlePrintPdf}
                disabled={downloadingPdf || !resumeText.trim()}
                className="inline-flex items-center gap-2 rounded-xl bg-sky-600 px-5 py-3 text-sm font-medium text-white transition hover:bg-sky-700 disabled:opacity-40"
              >
                {downloadingPdf ? <Loader2 size={14} className="animate-spin" /> : <Printer size={14} />}
                {downloadingPdf ? "Generating..." : "Download PDF"}
              </button>
            </div>
            {downloadError && (
              <div className="flex items-center gap-2 rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
                <AlertCircle size={14} className="flex-shrink-0" />
                <span>{downloadError}</span>
              </div>
            )}
          </div>

          {user && (
            <div className="rounded-3xl border border-[#BDDDFC]/30 bg-white p-4 shadow-sm space-y-3">
              <div className="text-sm font-semibold text-[#384959]">Save This Version</div>
              <div className="flex items-center gap-2">
                <input
                  type="text"
                  value={saveVersionLabel}
                  onChange={(e) => setSaveVersionLabel(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter" && saveVersionLabel.trim()) saveCurrentVersion(); }}
                  placeholder="Name this version..."
                  className="flex-1 rounded-xl border border-[#BDDDFC]/30 bg-[#f0f4f8] px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-[#BDDDFC]"
                />
                <button
                  type="button"
                  onClick={saveCurrentVersion}
                  disabled={savingVersion || !saveVersionLabel.trim() || !resumeText.trim()}
                  className="rounded-xl bg-[#384959] px-4 py-1.5 text-sm font-medium text-white hover:bg-[#2d3a47] disabled:opacity-40"
                >
                  {savingVersion ? "..." : "Save Version"}
                </button>
              </div>
            </div>
          )}

          {downloadReady && (
            <div className="rounded-3xl border border-emerald-200 bg-emerald-50 p-6 shadow-sm">
              <div className="text-sm font-semibold uppercase tracking-[0.16em] text-emerald-700">Next Steps</div>
              <div className="mt-2 text-lg font-semibold text-slate-900">Your resume export is ready.</div>
              <p className="mt-2 text-sm leading-relaxed text-slate-600">
                Keep momentum by searching for matching roles or moving straight into application tracking.
              </p>
              <div className="mt-4 flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={() => setActiveTab("jobs")}
                  className="inline-flex items-center gap-2 rounded-xl bg-[#384959] px-4 py-2.5 text-sm font-medium text-white hover:bg-[#2d3a47]"
                >
                  <Search size={14} />
                  Search Matching Jobs
                </button>
                <button
                  type="button"
                  onClick={() => setActiveTab("tracker")}
                  className="inline-flex items-center gap-2 rounded-xl border border-[#BDDDFC]/30 bg-white px-4 py-2.5 text-sm font-medium text-[#384959] hover:bg-[#f0f4f8]"
                >
                  <Plus size={14} />
                  Track This Application
                </button>
              </div>
            </div>
          )}

          <div className="flex items-center justify-between">
            <button
              type="button"
              onClick={() => setWizardStep(3)}
              className="inline-flex items-center gap-2 rounded-xl border border-[#BDDDFC]/30 bg-white px-4 py-2.5 text-sm font-medium text-[#384959] hover:bg-[#f0f4f8]"
            >
              <ArrowLeft size={14} />
              Back to Editor
            </button>
            <button
              type="button"
              onClick={() => {
                setResumeText("");
                setScoreData(null);
                setShowSetupPanel(true);
                setDownloadReady(false);
                setWizardStep(1);
              }}
              className="inline-flex items-center gap-2 rounded-xl border border-[#BDDDFC]/30 bg-white px-4 py-2.5 text-sm font-medium text-[#384959] hover:bg-[#f0f4f8]"
            >
              <Plus size={14} />
              Start Another
            </button>
          </div>
        </div>
      )}

      {/* Mobile Bullet Feedback Sheet */}
      {mobileBulletSheet && (
        <div className="fixed inset-0 z-50 lg:hidden">
          {/* Backdrop */}
          <div
            className="absolute inset-0 bg-black/40"
            onClick={() => setMobileBulletSheet(null)}
          />
          {/* Sheet */}
          <div className="absolute bottom-0 left-0 right-0 rounded-t-3xl bg-white shadow-2xl max-h-[80vh] overflow-y-auto animate-slide-up" onClick={(e) => e.stopPropagation()}>
            {/* Handle */}
            <div className="flex justify-center pt-3 pb-2">
              <div className="h-1 w-10 rounded-full bg-gray-300" />
            </div>

            {/* Content */}
            <div className="px-5 pb-8 space-y-4">
              {/* Annotation badge */}
              <div className="flex items-center gap-2">
                <span className={`inline-flex items-center gap-1 rounded-full px-3 py-1 text-xs font-semibold ${mobileBulletSheet.annotation?.pillClass || "bg-gray-100"}`}>
                  {mobileBulletSheet.annotation?.icon}
                  {mobileBulletSheet.annotation?.label}
                </span>
              </div>

              {/* Issue description */}
              <p className="text-sm text-[#6A89A7] leading-relaxed">
                {mobileBulletSheet.annotation?.message || "Review this bullet for improvements."}
              </p>

              {/* Current bullet text */}
              <div className="rounded-xl bg-[#f0f4f8] p-4">
                <div className="text-xs font-semibold uppercase tracking-wider text-[#6A89A7] mb-2">Current Bullet</div>
                <p className="text-sm text-[#384959] leading-relaxed">{mobileBulletSheet.text}</p>
              </div>

              {/* Action buttons */}
              <div className="flex gap-3">
                <button
                  type="button"
                  onClick={() => {
                    handleBulletRewrite(mobileBulletSheet, undefined, activeSuggestionHint);
                  }}
                  disabled={rewriteLoading[mobileBulletSheet?.id]}
                  className="flex-1 rounded-xl bg-[#384959] min-h-[44px] py-3 text-sm font-medium text-white hover:bg-[#2d3a47] transition disabled:opacity-50"
                >
                  {rewriteLoading[mobileBulletSheet?.id]
                    ? "Rewriting..."
                    : isRewriteResultCurrent(rewriteResults[mobileBulletSheet?.id], {
                        bullet: mobileBulletSheet?.text || "",
                        jobTitle: selectedJob?.title || "",
                        jobDescription,
                      })
                      ? "Rewrites ready"
                      : "AI Rewrite"}
                </button>
                <button
                  type="button"
                  onClick={() => {
                    openEditorForSection(mobileBulletSheet);
                    setMobileBulletSheet(null);
                  }}
                  className="flex-1 rounded-xl border border-[#BDDDFC]/30 bg-white min-h-[44px] py-3 text-sm font-medium text-[#384959] hover:bg-[#f0f4f8] transition"
                >
                  Edit Manually
                </button>
              </div>

              {/* Rewrite results */}
              {mobileBulletSheet && isRewriteResultCurrent(rewriteResults[mobileBulletSheet.id], {
                bullet: mobileBulletSheet.text || "",
                jobTitle: selectedJob?.title || "",
                jobDescription,
              }) && (
                <div className="space-y-2">
                  <div className="text-xs font-semibold uppercase tracking-wider text-[#6A89A7]">Pick a rewrite</div>
                  {rewriteResults[mobileBulletSheet.id].options.map((option, idx) => (
                    <button
                      key={idx}
                      type="button"
                      onClick={() => {
                        acceptRewrite(mobileBulletSheet, idx);
                        setMobileBulletSheet(null);
                      }}
                      className="w-full text-left rounded-xl border border-[#BDDDFC]/30 bg-[#f0f4f8] p-3 text-sm text-[#384959] hover:bg-blue-50 hover:border-blue-300 transition"
                    >
                      {typeof option === "string" ? option : option.text || option}
                    </button>
                  ))}
                </div>
              )}

              {/* Dismiss */}
              <button
                type="button"
                onClick={() => setMobileBulletSheet(null)}
                className="w-full rounded-xl border border-[#BDDDFC]/30 min-h-[44px] py-2.5 text-sm text-[#6A89A7] hover:bg-[#f0f4f8] transition"
              >
                Dismiss
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
