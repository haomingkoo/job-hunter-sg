// ResumeTab component extracted from App.jsx (Phase 3)

import { useState, useEffect, useMemo, useCallback, useRef, Fragment, memo } from "react";
import {
  Search, FileText, Plus, X, ChevronRight,
  CheckCircle, AlertCircle, Trash2, Edit3,
  RefreshCw, Zap, Download, Star,
  Loader2, Sparkles, UploadCloud, Printer,
  Check, ArrowLeft, ArrowRight, ArrowUp, ArrowDown, List, Type, GripVertical,
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
  getIssueLabel,
  evaluateRewriteOption,
  getRewriteOptionMeta,
  rankRewriteOptions,
  buildFocusedFeedbackContext,
} from "../lib/resumeHelpers.jsx";

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
          className="cursor-grab active:cursor-grabbing opacity-0 group-hover/section:opacity-60 transition-opacity mt-2 -ml-4 px-0.5 text-gray-300 hover:text-gray-500 shrink-0"
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
  const [dragOver, setDragOver] = useState(false);
  const [pastedText, setPastedText] = useState("");
  const [resumeVersions, setResumeVersions] = useState([]);
  const [versionsLoading, setVersionsLoading] = useState(false);
  const [saveVersionLabel, setSaveVersionLabel] = useState("");
  const [savingVersion, setSavingVersion] = useState(false);
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
  const [showSetupPanel, setShowSetupPanel] = useState(() => !resumeText.trim());
  const [workspaceView, setWorkspaceView] = useState("feedback");
  const [mobilePanel, setMobilePanel] = useState("edit");
  const [showVersionDropdown, setShowVersionDropdown] = useState(false);
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
    // Push current text to undo stack (max 30) unless this IS an undo/redo
    if (!_isUndo && resumeText && resumeText !== nextText) {
      undoStackRef.current = [...undoStackRef.current.slice(-29), resumeText];
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
      runScore(nextText, jobDescription, { phase: "opening" });
    } else {
      setNeedsRescore(Boolean(nextText.trim()));
      if (nextText.trim()) setScorePhase("editing");
    }
  }, [jobDescription, runScore, resumeText]);

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

  const handleRegenerateSummary = useCallback(async () => {
    if (!resumeText.trim() || regeneratingSummary) return;
    setRegeneratingSummary(true);
    try {
      const resp = await apiFetch("/api/ai/regenerate-summary", {
        method: "POST",
        body: JSON.stringify({
          resume_text: resumeText,
          job_id: selectedJob?.id || null,
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
                  ? "bg-blue-600 text-white"
                  : isComplete
                    ? "bg-blue-100 text-blue-700 cursor-pointer hover:bg-blue-200"
                    : "bg-gray-100 text-gray-400 cursor-default"
              }`}
            >
              {isComplete ? <Check size={12} /> : <span>{step}</span>}
              {label}
            </button>
          );
        })}
      </div>

      {selectedJob && (
        <div className="mb-4 rounded-3xl border border-indigo-200 bg-indigo-50 p-5 shadow-sm">
          <div className="flex items-center justify-between">
            <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-indigo-600">Target Job Description</div>
            <button
              type="button"
              onClick={() => setActiveTab("scraper")}
              className="text-xs font-semibold text-indigo-700 hover:text-indigo-900"
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
                    <span key={`${label}-${index}`} className="rounded-full bg-indigo-100 px-2 py-0.5 text-[11px] font-medium text-indigo-700" title={term?.jd_context || ""}>
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
            <h2 className="text-xl font-bold text-gray-900">How would you like to start?</h2>
            <p className="mt-1 text-sm text-gray-500">Choose the option that fits your situation.</p>
          </div>

          <div className="grid gap-4 sm:grid-cols-3">
            {/* Upload */}
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              onDrop={handleDrop}
              onDragOver={(event) => { event.preventDefault(); setDragOver(true); }}
              onDragLeave={() => setDragOver(false)}
              className={`group text-left rounded-2xl border-2 bg-white p-6 transition-all hover:shadow-md hover:-translate-y-0.5 ${
                dragOver ? "border-blue-400 bg-blue-50" : "border-gray-200 hover:border-blue-300"
              }`}
            >
              {uploading ? (
                <Loader2 size={28} className="animate-spin text-blue-600" />
              ) : (
                <UploadCloud size={28} className="text-blue-600" />
              )}
              <h3 className="mt-3 text-base font-semibold text-gray-900">Upload Resume</h3>
              <p className="mt-1.5 text-sm text-gray-500">
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
              className="group text-left rounded-2xl border-2 border-gray-200 bg-white p-6 transition-all hover:shadow-md hover:-translate-y-0.5 hover:border-emerald-300"
            >
              <FileText size={28} className="text-emerald-600" />
              <h3 className="mt-3 text-base font-semibold text-gray-900">Paste Text</h3>
              <p className="mt-1.5 text-sm text-gray-500">Copy-paste your resume from any source</p>
            </button>

            {/* Start Fresh */}
            <button
              type="button"
              onClick={() => {
                const starter = `PROFESSIONAL SUMMARY\nAdd a concise summary of your experience and goals.\n\nPROFESSIONAL EXPERIENCE\nCompany Name | Job Title | Start Date - End Date\n- Describe your key achievement or responsibility\n- Include metrics where possible (%, $, team size)\n\nEDUCATION\nDegree Name\nUniversity Name, Graduation Year\n\nSKILLS\nList your technical and professional skills here`;
                applyResumeText(starter, { rescore: false });
                setShowSetupPanel(false);
                setWizardStep(2);
              }}
              className="group text-left rounded-2xl border-2 border-gray-200 bg-white p-6 transition-all hover:shadow-md hover:-translate-y-0.5 hover:border-violet-300"
            >
              <Edit3 size={28} className="text-violet-600" />
              <h3 className="mt-3 text-base font-semibold text-gray-900">Start Fresh</h3>
              <p className="mt-1.5 text-sm text-gray-500">Build from scratch with a guided template</p>
            </button>
          </div>

          {/* ── Paste Area (hidden by default, revealed on click) ──────── */}
          <div id="resume-paste-area" className="hidden rounded-2xl border border-gray-200 bg-white p-4 shadow-sm">
            <div className="text-sm font-semibold text-gray-800">Paste your resume text</div>
            <textarea
              value={pastedText}
              onChange={(event) => setPastedText(event.target.value)}
              placeholder="Paste your resume content here..."
              className="mt-3 min-h-[160px] w-full resize-none rounded-xl border border-gray-200 bg-gray-50 px-4 py-3 text-sm text-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-200"
            />
            <div className="mt-3 flex gap-2">
              <button
                type="button"
                onClick={handlePasteResume}
                disabled={!pastedText.trim()}
                className="rounded-xl bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-500 disabled:opacity-40"
              >
                Use This Text
              </button>
              <button
                type="button"
                onClick={() => document.getElementById("resume-paste-area")?.classList.add("hidden")}
                className="rounded-xl border border-gray-200 px-4 py-2 text-sm font-medium text-gray-600 hover:bg-gray-50"
              >
                Cancel
              </button>
            </div>
          </div>

          {/* ── Saved Versions (if logged in and has versions) ─────────── */}
          {user && resumeVersions.length > 0 && (
            <div className="rounded-2xl border border-gray-200 bg-white p-4 shadow-sm">
              <div className="flex items-center justify-between">
                <div className="text-sm font-semibold text-gray-800">Your Saved Resumes</div>
                <button type="button" onClick={fetchVersions} className="text-xs text-blue-600 hover:text-blue-800">
                  {versionsLoading ? "Loading..." : "Refresh"}
                </button>
              </div>
              <div className="mt-3 grid gap-2 sm:grid-cols-2">
                {resumeVersions.slice(0, 4).map((v) => (
                  <button
                    key={v.id}
                    type="button"
                    onClick={() => loadVersion(v.id)}
                    className="flex items-center justify-between rounded-xl border border-gray-200 bg-gray-50 px-4 py-3 text-left text-sm hover:border-blue-300 hover:bg-blue-50 transition"
                  >
                    <div>
                      <div className="font-medium text-gray-800">{v.label}</div>
                      <div className="text-xs text-gray-500">
                        {v.score ? `Score ${v.score}` : ""}{v.word_count ? ` · ${v.word_count}w` : ""}
                      </div>
                    </div>
                    <ChevronRight size={14} className="text-gray-400" />
                  </button>
                ))}
              </div>
              {resumeVersions.length > 4 && (
                <button type="button" onClick={fetchVersions} className="mt-2 text-xs text-blue-600 hover:text-blue-800">
                  View all {resumeVersions.length} versions
                </button>
              )}
            </div>
          )}

          {/* ── Profile Fields ─────────────────────────────────────────── */}
          <div className="rounded-2xl border border-gray-200 bg-white p-4 shadow-sm">
            <div className="text-sm font-semibold text-gray-800">Your Details</div>
            <p className="mt-1 text-xs text-gray-500">Used for the resume header. Auto-detected from uploaded files.</p>
            <div className="mt-3 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
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

          {/* Step 1 Next button */}
          <div className="flex justify-end">
            <button
              type="button"
              disabled={!hasResume}
              onClick={() => setWizardStep(2)}
              className="inline-flex items-center gap-2 rounded-xl bg-blue-600 px-5 py-2.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              Next: Pick Template
              <ArrowRight size={14} />
            </button>
          </div>
        </div>
      ) : null}

      {/* ── Step 3: Setup Complete bar ──────────────────────────────── */}
      {wizardStep === 3 && !setupVisible && (
        <div className="rounded-3xl border border-gray-200 bg-white p-4 shadow-sm">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
            <div className="min-w-0">
              <div className="text-xs font-semibold uppercase tracking-[0.16em] text-gray-500">Setup Complete</div>
              <div className="mt-1 text-sm text-gray-700 truncate">
                {profile.name || "Resume loaded"}{profile.email ? ` • ${profile.email}` : ""}{profile.phone ? ` • ${profile.phone}` : ""}
              </div>
              <div className="mt-1 text-xs text-gray-500">
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
                      className="inline-flex items-center gap-1.5 rounded-xl border border-gray-200 bg-white px-3 py-2 text-xs font-medium text-gray-700 hover:bg-gray-50"
                    >
                      <Download size={13} />
                      Load Version
                      <ChevronRight size={12} className={`transition-transform ${showVersionDropdown ? "rotate-90" : ""}`} />
                    </button>
                    {showVersionDropdown && (
                      <div className="absolute right-0 top-full z-50 mt-1 w-64 rounded-xl border border-gray-200 bg-white p-2 shadow-lg">
                        {versionsLoading ? (
                          <div className="flex items-center gap-2 px-3 py-2 text-xs text-gray-500"><Loader2 size={12} className="animate-spin" />Loading...</div>
                        ) : resumeVersions.length === 0 ? (
                          <div className="px-3 py-2 text-xs text-gray-400">No saved versions yet.</div>
                        ) : (
                          <div className="max-h-48 overflow-y-auto space-y-0.5">
                            {resumeVersions.map((v) => (
                              <button
                                key={v.id}
                                type="button"
                                onClick={() => { loadVersion(v.id); setShowVersionDropdown(false); }}
                                className="w-full text-left rounded-lg px-3 py-2 text-xs hover:bg-gray-50 transition"
                              >
                                <div className="font-medium text-gray-800 truncate">{v.label}</div>
                                <div className="text-gray-400 mt-0.5">
                                  {v.score ? `Score ${v.score}` : ""}{v.job_title ? ` • ${v.job_title}` : ""}
                                  {v.word_count ? ` • ${v.word_count}w` : ""}
                                </div>
                              </button>
                            ))}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                  <div className="inline-flex items-center gap-1 rounded-xl border border-gray-200 bg-white p-1">
                    <input
                      type="text"
                      value={saveVersionLabel}
                      onChange={(e) => setSaveVersionLabel(e.target.value)}
                      onKeyDown={(e) => { if (e.key === "Enter") saveCurrentVersion(); }}
                      placeholder="Name this version..."
                      className="w-32 rounded-lg bg-transparent px-2 py-1 text-xs focus:outline-none"
                    />
                    <button
                      type="button"
                      onClick={saveCurrentVersion}
                      disabled={savingVersion || !saveVersionLabel.trim() || !resumeText.trim()}
                      className="rounded-lg bg-indigo-600 px-2.5 py-1 text-xs font-medium text-white hover:bg-indigo-700 disabled:opacity-40"
                    >
                      {savingVersion ? "..." : "Save"}
                    </button>
                  </div>
                </>
              )}
              <button
                type="button"
                onClick={() => { setShowSetupPanel(true); setWizardStep(1); }}
                className="inline-flex items-center gap-2 rounded-xl border border-gray-200 bg-white px-3 py-2 text-xs font-medium text-gray-700 hover:bg-gray-50"
              >
                <Edit3 size={13} />
                Edit Setup
              </button>
              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                className="inline-flex items-center gap-2 rounded-xl bg-indigo-600 px-3 py-2 text-xs font-medium text-white hover:bg-indigo-700"
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

      {/* ── Step 2: Template ─────────────────────────────────────────── */}
      {wizardStep === 2 && (<>
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

      {/* Step 2 navigation */}
      <div className="flex items-center justify-between">
        <button
          type="button"
          onClick={() => { setShowSetupPanel(true); setWizardStep(1); }}
          className="inline-flex items-center gap-2 rounded-xl border border-gray-200 bg-white px-4 py-2.5 text-sm font-medium text-gray-700 hover:bg-gray-50"
        >
          <ArrowLeft size={14} />
          Back
        </button>
        <button
          type="button"
          onClick={() => setWizardStep(3)}
          className="inline-flex items-center gap-2 rounded-xl bg-blue-600 px-5 py-2.5 text-sm font-medium text-white hover:bg-blue-700"
        >
          Next: Review & Edit
          <ArrowRight size={14} />
        </button>
      </div>
      </>)}

      {/* ── Step 3: Review & Edit ────────────────────────────────────── */}
      {wizardStep === 3 && (<>
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

            {user && (
              <div className="inline-flex items-center gap-1.5 rounded-2xl border border-gray-200 bg-white px-2 py-1.5">
                <input
                  type="text"
                  value={saveVersionLabel}
                  onChange={(e) => setSaveVersionLabel(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter") saveCurrentVersion(); }}
                  placeholder="Name this version..."
                  className="w-32 rounded-lg border border-gray-200 bg-white px-2 py-1 text-xs focus:outline-none focus:ring-1 focus:ring-indigo-300"
                />
                <button
                  type="button"
                  onClick={saveCurrentVersion}
                  disabled={savingVersion || !saveVersionLabel.trim() || !resumeText.trim()}
                  className="rounded-lg bg-indigo-600 px-3 py-1 text-xs font-medium text-white hover:bg-indigo-700 disabled:opacity-40"
                >
                  {savingVersion ? "..." : "Save Version"}
                </button>
              </div>
            )}

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
                    <div className="mt-4 flex items-center gap-2">
                      <span className="text-xs font-semibold uppercase tracking-[0.16em] text-gray-500">Missing</span>
                      <span className="text-[10px] text-gray-400">Click to insert</span>
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
                        className="mt-2 rounded-2xl border border-gray-200 bg-white p-3 shadow-lg"
                        style={{ zIndex: 50 }}
                      >
                        <div className="flex items-center justify-between">
                          <div className="text-xs font-semibold text-gray-800">
                            Insert <span className="rounded bg-rose-100 px-1.5 py-0.5 text-rose-700">{insertKeywordPopup.keyword}</span> into:
                          </div>
                          <button
                            type="button"
                            onClick={() => setInsertKeywordPopup(null)}
                            className="rounded-full p-0.5 text-gray-400 hover:bg-gray-100 hover:text-gray-600"
                          >
                            <X size={12} />
                          </button>
                        </div>
                        {insertKeywordPopup.suggestions.length > 0 ? (
                          <div className="mt-2 space-y-1.5">
                            {insertKeywordPopup.suggestions.map((bullet) => (
                              <div
                                key={bullet.id}
                                className="group flex items-start gap-2 rounded-xl border border-gray-100 bg-gray-50 px-2.5 py-2 transition hover:border-indigo-200 hover:bg-indigo-50"
                              >
                                <div className="min-w-0 flex-1">
                                  <div className="text-[10px] font-medium uppercase tracking-wider text-gray-400">
                                    {bullet.sectionKey || "section"}
                                  </div>
                                  <div className="mt-0.5 truncate text-xs text-gray-700" title={bullet.text}>
                                    {bullet.text.length > 80 ? `${bullet.text.slice(0, 80)}...` : bullet.text}
                                  </div>
                                </div>
                                <button
                                  type="button"
                                  onClick={() => handleInsertKeywordIntoBullet(bullet, insertKeywordPopup.keyword)}
                                  className="shrink-0 rounded-lg bg-indigo-600 px-2 py-1 text-[10px] font-medium text-white transition hover:bg-indigo-700"
                                >
                                  Insert
                                </button>
                              </div>
                            ))}
                          </div>
                        ) : (
                          <div className="mt-2 text-xs text-gray-500">
                            No bullet points found. Add experience bullets to your resume first.
                          </div>
                        )}
                      </div>
                    )}
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
                <div className="inline-flex items-center rounded-full border border-gray-200 bg-white">
                  <button
                    type="button"
                    onClick={handleUndo}
                    disabled={undoStackRef.current.length === 0}
                    className="rounded-l-full px-2.5 py-1.5 text-xs text-gray-500 transition hover:text-gray-700 disabled:opacity-30"
                    title="Undo (Ctrl+Z)"
                  >
                    <RefreshCw size={12} className="scale-x-[-1]" />
                  </button>
                  <div className="h-4 w-px bg-gray-200" />
                  <button
                    type="button"
                    onClick={handleRedo}
                    disabled={redoStackRef.current.length === 0}
                    className="rounded-r-full px-2.5 py-1.5 text-xs text-gray-500 transition hover:text-gray-700 disabled:opacity-30"
                    title="Redo (Ctrl+Shift+Z)"
                  >
                    <RefreshCw size={12} />
                  </button>
                </div>
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
              ref={resumePrintRef}
              className={`resume-print-target mx-auto mt-5 bg-white shadow-[0_2px_20px_rgba(0,0,0,0.1)] border border-gray-200 ${templateStyles.pageClass}`}
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

                  <div style={templateStyles.bodyStyle}>
                   <DndContext sensors={dndSensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
                    <SortableContext items={bulletIds} strategy={verticalListSortingStrategy}>
                    {bodySections.map((section, sectionIndex) => {
                      if (section.type === "spacer") {
                        // Check if next non-spacer item starts a new section - show "Add Entry" button
                        const prevItem = bodySections.slice(0, sectionIndex).reverse().find((s) => s.type !== "spacer");
                        const nextItem = bodySections.slice(sectionIndex + 1).find((s) => s.type !== "spacer");
                        const isEndOfEntrySection = prevItem && nextItem
                          && nextItem.type === "heading"
                          && ["experience", "education", "certifications", "projects"].includes(prevItem.sectionKey);
                        if (isEndOfEntrySection) {
                          const templates = {
                            experience: "Company Name | Job Title | Start - End\n- Describe your key achievement",
                            education: "Degree Name\nUniversity Name, Year",
                            certifications: "- Certification Name (Year)",
                            projects: "Project Name | Year\n- Describe the project and your role",
                          };
                          const template = templates[prevItem.sectionKey];
                          if (template) {
                            return (
                              <div key={section.id} className="group/addentry flex justify-center py-1">
                                <button
                                  type="button"
                                  onClick={() => {
                                    const lines = resumeText.replace(/\r\n?/g, "\n").split("\n");
                                    const insertAt = (prevItem.lineIndices?.[prevItem.lineIndices.length - 1] ?? prevItem.lineIndex) + 1;
                                    lines.splice(insertAt, 0, "", ...template.split("\n"));
                                    applyResumeText(lines.join("\n"));
                                  }}
                                  className="opacity-0 group-hover/addentry:opacity-100 focus:opacity-100 transition-opacity inline-flex items-center gap-1.5 rounded-full border border-dashed border-blue-300 bg-white px-3 py-1 text-[11px] font-medium text-blue-600 hover:bg-blue-50"
                                >
                                  <Plus size={11} />
                                  Add {prevItem.sectionKey === "experience" ? "Position" : prevItem.sectionKey === "education" ? "Education" : "Entry"}
                                </button>
                              </div>
                            );
                          }
                        }
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
                          {section.type === "education_entry" && (
                            <div className={`mb-2 rounded-lg border border-gray-100 bg-gray-50/40 px-4 py-3 ${templateStyles.subheadingClass}`}>
                              <div className="flex items-baseline justify-between gap-4">
                                <div className="font-semibold leading-snug text-gray-900">
                                  {renderHighlightedText(
                                    section.fields.degree || section.fields.institution || section.text,
                                    section.keywordMatches || [],
                                  )}
                                </div>
                                {section.fields.dateRange && (
                                  <div className="shrink-0 text-[0.9em] text-gray-400 whitespace-nowrap">
                                    {section.fields.dateRange}
                                  </div>
                                )}
                              </div>
                              {section.fields.degree && section.fields.institution && (
                                <div className="mt-0.5 text-[0.93em] leading-snug text-gray-600">
                                  {section.fields.institution}
                                </div>
                              )}
                              {(section.fields.gpa || section.fields.honors.length > 0 || section.fields.details.length > 0) && (
                                <div className="mt-1 text-[0.85em] text-gray-500">
                                  {[section.fields.gpa, ...section.fields.honors, ...section.fields.details].filter(Boolean).join(" · ")}
                                </div>
                              )}
                              {section.fields.bullets.length > 0 && (
                                <div className="mt-1.5 space-y-0.5">
                                  {section.fields.bullets.map((bullet) => (
                                    <div key={bullet.id} className="flex gap-2 text-[0.88em] text-gray-600">
                                      <span className="text-gray-400">•</span>
                                      <span>{renderHighlightedText(bullet.text, section.keywordMatches || [])}</span>
                                    </div>
                                  ))}
                                </div>
                              )}
                            </div>
                          )}
                          {section.type === "subheading" && (
                            section.variant === "education_main" ? (
                              <div className={`mb-1 rounded-lg border border-gray-100 bg-gray-50/40 px-3 py-2.5 ${templateStyles.subheadingClass}`}>
                                {(() => {
                                  const meta = splitEducationMeta(
                                    getDisplaySubheadingText(section.right, section.sectionKey, section.variant),
                                  );
                                  return (
                                    <>
                                      <div className="flex items-baseline justify-between gap-4">
                                        <div className="font-semibold leading-snug text-gray-900">
                                          {renderHighlightedText(
                                            getDisplaySubheadingText(section.left, section.sectionKey, section.variant),
                                            section.keywordMatches || [],
                                          )}
                                        </div>
                                        {meta.secondary && (
                                          <div className="shrink-0 text-[0.9em] text-gray-400 whitespace-nowrap">
                                            {meta.secondary}
                                          </div>
                                        )}
                                      </div>
                                      {meta.primary && (
                                        <div className="mt-0.5 text-[0.93em] leading-snug text-gray-600">
                                          {meta.primary}
                                        </div>
                                      )}
                                    </>
                                  );
                                })()}
                              </div>
                            ) : section.variant === "education_detail" ? (
                              <div className="-mt-0.5 mb-2 ml-3 flex items-baseline justify-between gap-4 text-[0.88em] text-gray-500">
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

                              if (section.sectionKey === "education") {
                                return (
                                  <p className="-mt-0.5 mb-2 ml-3 text-[0.88em] leading-snug text-gray-500" style={templateStyles.bodyStyle}>
                                    {renderHighlightedText(getDisplayParagraphText(section), section.keywordMatches || [])}
                                  </p>
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
                            <div className={`flex gap-3 ${["education", "personal", "languages", "additional"].includes(section.sectionKey) ? "ml-2" : ""}`}>
                              <div className={`pt-1 text-gray-400 ${["education", "personal", "languages", "additional"].includes(section.sectionKey) ? "text-[0.85rem]" : "text-[1rem]"}`}>•</div>
                              <div className="flex-1">
                                <p className={["education", "personal", "languages", "additional"].includes(section.sectionKey) ? "text-[0.88em] text-gray-500" : "text-gray-700"} style={templateStyles.bodyStyle}>
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
                              className="inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[10px] font-medium text-gray-400 hover:text-indigo-600 hover:bg-indigo-50 transition"
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
                              className="inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[10px] font-medium text-gray-400 hover:text-violet-600 hover:bg-violet-50 transition"
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
                              className="inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[10px] font-medium text-gray-400 hover:text-amber-600 hover:bg-amber-50 transition"
                              title="Convert to bullet point"
                            >
                              <List size={9} />
                              Make Bullet
                            </button>
                          )}
                        </div>
                      ) : null;

                      const sectionMoveButtons = section.type === "heading" && !isEditing ? (
                        <div className="flex gap-0.5 opacity-0 group-hover/section:opacity-100 transition-opacity float-right -mt-6 mr-0">
                          <button
                            type="button"
                            onClick={(e) => { e.stopPropagation(); handleMoveSection(section.id, -1); }}
                            className="rounded p-0.5 text-gray-300 hover:text-gray-600 hover:bg-gray-100 transition"
                            title="Move section up"
                          >
                            <ArrowUp size={12} />
                          </button>
                          <button
                            type="button"
                            onClick={(e) => { e.stopPropagation(); handleMoveSection(section.id, 1); }}
                            className="rounded p-0.5 text-gray-300 hover:text-gray-600 hover:bg-gray-100 transition"
                            title="Move section down"
                          >
                            <ArrowDown size={12} />
                          </button>
                        </div>
                      ) : null;

                      const sectionContent = (
                        <>
                          <div id={`resume-section-${section.id}`} className={`group/section rounded-xl px-3 py-0.5 transition ${wrapperClasses}`}>
                            {lineContent}
                            {actionButtons}
                            {sectionMoveButtons}
                            {section.type === "heading" && section.sectionKey === "summary" && selectedJob && !isEditing && (
                              <button
                                type="button"
                                onClick={handleRegenerateSummary}
                                disabled={regeneratingSummary}
                                className="mt-1 inline-flex items-center gap-1 rounded-lg border border-violet-200 bg-violet-50 px-2 py-1 text-[11px] font-medium text-violet-700 transition hover:bg-violet-100 disabled:opacity-40"
                                title="Regenerate summary for the selected job"
                              >
                                {regeneratingSummary ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />}
                                {regeneratingSummary ? "Regenerating..." : "Regenerate for JD"}
                              </button>
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

                      // Wrap bullets in SortableBulletItem for drag-and-drop
                      if (section.type === "bullet") {
                        return (
                          <SortableBulletItem key={section.id} id={section.id}>
                            {sectionContent}
                          </SortableBulletItem>
                        );
                      }

                      return (
                        <Fragment key={section.id}>
                          {sectionContent}
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
            {user && (
              <div className="inline-flex items-center gap-1 rounded-xl border border-gray-200 bg-white px-1.5 py-1">
                <input
                  type="text"
                  value={saveVersionLabel}
                  onChange={(e) => setSaveVersionLabel(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter" && saveVersionLabel.trim()) saveCurrentVersion(); }}
                  placeholder="Version name..."
                  className="w-28 rounded-lg bg-transparent px-2 py-1 text-xs focus:outline-none"
                />
                <button
                  type="button"
                  onClick={saveCurrentVersion}
                  disabled={savingVersion || !saveVersionLabel.trim() || !resumeText.trim()}
                  className="rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-indigo-700 disabled:opacity-40"
                >
                  {savingVersion ? "..." : "Save"}
                </button>
              </div>
            )}
            <button
              type="button"
              onClick={() => setWizardStep(2)}
              className="inline-flex items-center gap-2 rounded-xl border border-gray-200 bg-white px-4 py-2.5 text-sm font-medium text-gray-700 transition hover:bg-gray-50"
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
          <div className="rounded-3xl border border-gray-200 bg-white p-6 shadow-sm text-center">
            <div className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500">Final Score</div>
            <div className={`mt-3 text-5xl font-bold ${scoreData ? scoreTheme.text : "text-gray-500"}`}>
              {scoring ? "..." : scoreDisplayValue}
              <span className="ml-1 text-lg font-medium text-gray-400">{scoreData ? "/100" : ""}</span>
            </div>
            <div className="mt-3 h-2.5 overflow-hidden rounded-full bg-gray-100 mx-auto max-w-xs">
              <div className={`h-full rounded-full transition-all ${scoreTheme.bar}`} style={{ width: `${scoreData && overallScore !== null ? overallScore : 0}%` }} />
            </div>
            {needsRescore && (
              <button
                type="button"
                onClick={handleFinalizeScore}
                disabled={scoring}
                className="mt-4 inline-flex items-center gap-2 rounded-xl border border-gray-200 bg-white px-4 py-2.5 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-40"
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

          <div className="rounded-3xl border border-gray-200 bg-white p-6 shadow-sm space-y-4">
            <div className="text-sm font-semibold text-gray-800">Download Your Resume</div>
            <p className="text-sm text-gray-500">
              Template: <span className="font-medium text-gray-700">{templateMeta?.name || "Modern"}</span>
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
            <div className="rounded-3xl border border-gray-200 bg-white p-6 shadow-sm space-y-4">
              <div className="text-sm font-semibold text-gray-800">Save This Version</div>
              <div className="flex items-center gap-2">
                <input
                  type="text"
                  value={saveVersionLabel}
                  onChange={(e) => setSaveVersionLabel(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter" && saveVersionLabel.trim()) saveCurrentVersion(); }}
                  placeholder="Name this version..."
                  className="flex-1 rounded-xl border border-gray-200 bg-gray-50 px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-200"
                />
                <button
                  type="button"
                  onClick={saveCurrentVersion}
                  disabled={savingVersion || !saveVersionLabel.trim() || !resumeText.trim()}
                  className="rounded-xl bg-indigo-600 px-5 py-2.5 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-40"
                >
                  {savingVersion ? "Saving..." : "Save Version"}
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

          <div className="flex items-center justify-between">
            <button
              type="button"
              onClick={() => setWizardStep(3)}
              className="inline-flex items-center gap-2 rounded-xl border border-gray-200 bg-white px-4 py-2.5 text-sm font-medium text-gray-700 hover:bg-gray-50"
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
              className="inline-flex items-center gap-2 rounded-xl border border-gray-200 bg-white px-4 py-2.5 text-sm font-medium text-gray-700 hover:bg-gray-50"
            >
              <Plus size={14} />
              Start Another
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
