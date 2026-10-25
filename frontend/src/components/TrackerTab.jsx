import { useEffect, useState } from "react";
import { DndContext, PointerSensor, closestCorners, useDraggable, useDroppable, useSensor, useSensors } from "@dnd-kit/core";
import { CSS } from "@dnd-kit/utilities";
import {
  Plus, X, AlertCircle, RefreshCw,
  Download, Loader2, Edit3, Trash2,
  Search, FileText, GripVertical,
} from "lucide-react";
import { apiFetch, downloadBlob } from "../lib/api.js";
import { STATUS_CONFIG, SG_JOB_PORTALS } from "../lib/constants.js";
import { todayStr, daysBetween, formatPostingDate } from "../lib/helpers.js";
import StatusBadge from "./StatusBadge.jsx";

const PANEL = "rounded-[10px] border border-line bg-white";
const FIELD = "min-h-11 w-full rounded-md border border-field bg-white px-3 text-sm text-ink focus:border-accent";
const TEXTAREA = "w-full rounded-md border border-field bg-white px-3 py-2 text-sm text-ink focus:border-accent";
const LABEL = "mb-1 block text-sm font-medium text-ink";
const BTN_PRIMARY = "inline-flex min-h-11 items-center justify-center gap-2 rounded-md bg-accent px-4 text-sm font-semibold text-white transition-colors hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-60";
const BTN_SECONDARY = "inline-flex min-h-11 items-center justify-center gap-2 rounded-md border border-field bg-white px-4 text-sm font-medium text-ink transition-colors hover:bg-tint disabled:cursor-not-allowed disabled:opacity-60";
const BTN_TEXT = "inline-flex min-h-11 items-center gap-1.5 rounded-md px-2 text-sm font-medium text-accent transition-colors hover:bg-tint";
const BTN_ICON = "inline-flex h-10 w-10 items-center justify-center rounded-md text-muted transition-colors hover:bg-tint hover:text-ink";
const BTN_ICON_DANGER = "inline-flex h-10 w-10 items-center justify-center rounded-md text-muted transition-colors hover:bg-[#fef3f2] hover:text-[#b42318]";
const BTN_TEXT_DANGER = "inline-flex min-h-11 items-center gap-1.5 rounded-md px-2 text-sm font-medium text-[#b42318] transition-colors hover:bg-[#fef3f2]";
const SECTION = "border-t border-line pt-5";
const H3 = "text-base font-semibold text-ink";
const H4 = "text-sm font-semibold text-ink";
const LINK = "text-accent underline-offset-2 hover:underline";

function Notice({ children, action }) {
  return (
    <div role="alert" className="flex items-start justify-between gap-3 rounded-md border border-[#b42318]/30 bg-white p-3 text-sm text-[#b42318]">
      <div className="flex items-start gap-2">
        <AlertCircle size={16} className="mt-0.5 shrink-0" aria-hidden="true" />
        <span>{children}</span>
      </div>
      {action}
    </div>
  );
}

const RESEARCH_SOURCE_DISPLAY_LIMIT = 5;
const NEGOTIATION_ROUND_DISPLAY_LIMIT = 3;
const SGD_FORMATTER = new Intl.NumberFormat("en-SG", {
  maximumFractionDigits: 0,
});
const RESEARCH_DATE_FORMATTER = new Intl.DateTimeFormat("en-SG", {
  day: "numeric",
  month: "short",
  year: "numeric",
});

function formatResearchDate(value) {
  if (!value) return "retrieval date unavailable";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : RESEARCH_DATE_FORMATTER.format(date);
}

function formatSgd(value) {
  return typeof value === "number" ? `S$${SGD_FORMATTER.format(value)}` : "?";
}

export function getPipelineStatusMove(active, over) {
  if (!over) return null;
  const jobId = active?.data?.current?.jobId;
  const previousStatus = active?.data?.current?.status;
  const nextStatus = String(over.id || "").replace("status:", "");
  if (!jobId || !STATUS_CONFIG[nextStatus] || nextStatus === previousStatus) return null;
  return { jobId, nextStatus };
}

function PipelineCard({ job, moving, openWorkspace, handleEdit, handleDelete }) {
  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({
    id: `job:${job.id}`,
    data: { jobId: job.id, status: job.status },
  });

  return (
    <div
      ref={setNodeRef}
      style={{ transform: CSS.Transform.toString(transform) }}
      className={`rounded-md border border-line bg-white p-3 text-sm transition-opacity ${isDragging || moving ? "opacity-60" : ""}`}
      data-pipeline-card={job.id}
    >
      <div className="flex items-start gap-1">
        <button
          type="button"
          className="-ml-1 inline-flex h-8 w-6 shrink-0 cursor-grab items-center justify-center rounded text-muted active:cursor-grabbing"
          aria-label={`Move ${job.company} ${job.role}`}
          title="Move"
          {...listeners}
          {...attributes}
        >
          <GripVertical size={14} aria-hidden="true" />
        </button>
        <div className="min-w-0 flex-1 pt-1">
          <div className="font-semibold text-ink [overflow-wrap:anywhere]">{job.company}</div>
          <div className="mt-0.5 text-muted [overflow-wrap:anywhere]">{job.role}</div>
        </div>
      </div>
      <div className="mt-2 flex flex-wrap items-center justify-between gap-x-2 text-xs text-muted">
        <span className="tabular-nums">{job.date_applied ? formatPostingDate(job.date_applied) : "No date"}</span>
        <span>{job.source || "Manual"}</span>
      </div>
      <div className="-mx-1 mt-2 flex gap-1">
        <button type="button" onClick={() => openWorkspace(job.id)} className="min-h-9 rounded px-1.5 text-xs font-medium text-accent hover:bg-tint">Open</button>
        <button type="button" onClick={() => handleEdit(job)} className="min-h-9 rounded px-1.5 text-xs font-medium text-accent hover:bg-tint">Edit</button>
        <button type="button" onClick={() => handleDelete(job.id)} className="min-h-9 rounded px-1.5 text-xs font-medium text-[#b42318] hover:bg-[#fef3f2]">Delete</button>
      </div>
    </div>
  );
}

function PipelineColumn({ status, jobs, movingId, openWorkspace, handleEdit, handleDelete }) {
  const { isOver, setNodeRef } = useDroppable({ id: `status:${status}` });
  const config = STATUS_CONFIG[status];

  return (
    <div ref={setNodeRef} className={`min-h-[220px] rounded-[10px] p-2 transition-colors ${isOver ? "bg-tint ring-2 ring-accent" : ""}`} data-pipeline-column={status}>
      <div className="mb-2 flex items-baseline justify-between gap-2 px-1">
        <h3 className="text-sm font-semibold text-ink">{config?.label || status}</h3>
        <span className="text-xs tabular-nums text-muted">{jobs.length}</span>
      </div>
      <div className="space-y-2">
        {jobs.length === 0 ? (
          <div className="rounded-md border border-dashed border-field px-3 py-6 text-center text-xs text-muted">
            Drop here
          </div>
        ) : (
          jobs.map((job) => (
            <PipelineCard
              key={job.id}
              job={job}
              moving={movingId === job.id}
              openWorkspace={openWorkspace}
              handleEdit={handleEdit}
              handleDelete={handleDelete}
            />
          ))
        )}
      </div>
    </div>
  );
}

function compensationObservationLabel(observation) {
  if (observation.kind === "employer_posting") return observation.value;
  if (observation.kind === "mom_occupational_wages") {
    const basic = observation.basic_wage || {};
    const gross = observation.gross_wage || {};
    return `Monthly basic ${formatSgd(basic.p25)} / ${formatSgd(basic.median)} / ${formatSgd(basic.p75)}; monthly gross ${formatSgd(gross.p25)} / ${formatSgd(gross.median)} / ${formatSgd(gross.p75)} (P25 / median / P75)`;
  }
  return observation.value || observation.label || "Source observation";
}

function negotiationAnchorLabel(anchor) {
  if (anchor.kind === "mom_occupational_wages") return compensationObservationLabel(anchor);
  return anchor.value || "Value unavailable";
}

export default function TrackerTab({
  jobs,
  loadError = "",
  loading = false,
  refreshJobs,
  setActiveTab,
  openJobId = null,
  onOpenJobHandled,
}) {
  const [showForm, setShowForm] = useState(false);
  const [formMode, setFormMode] = useState("manual");
  const [editingId, setEditingId] = useState(null);
  const [filterStatus, setFilterStatus] = useState("all");
  const [viewMode, setViewMode] = useState("table");
  const [saving, setSaving] = useState(false);
  const [movingId, setMovingId] = useState(null);
  const [error, setError] = useState("");
  const [workspace, setWorkspace] = useState(null);
  const [workspaceLoading, setWorkspaceLoading] = useState(false);
  const [workspaceError, setWorkspaceError] = useState("");
  const [workspaceAgentLoading, setWorkspaceAgentLoading] = useState(false);
  const [workspaceAgentError, setWorkspaceAgentError] = useState("");
  const [researchLoading, setResearchLoading] = useState(false);
  const [researchError, setResearchError] = useState("");
  const [negotiationPriorities, setNegotiationPriorities] = useState("");
  const [walkAwayPoint, setWalkAwayPoint] = useState("");
  const [negotiationScenario, setNegotiationScenario] = useState("");
  const [authorizedEvidenceLabel, setAuthorizedEvidenceLabel] = useState("");
  const [authorizedEvidenceValue, setAuthorizedEvidenceValue] = useState("");
  const [authorizedEvidenceDefinition, setAuthorizedEvidenceDefinition] = useState("");
  const [authorizedEvidenceSourceUrl, setAuthorizedEvidenceSourceUrl] = useState("");
  const [authorizedEvidenceDataDate, setAuthorizedEvidenceDataDate] = useState("");
  const [negotiationLoading, setNegotiationLoading] = useState(false);
  const [negotiationError, setNegotiationError] = useState("");
  const [submittedFile, setSubmittedFile] = useState(null);
  const [submittedDate, setSubmittedDate] = useState(todayStr());
  const [submittedNotes, setSubmittedNotes] = useState("");
  const [submittedSaving, setSubmittedSaving] = useState(false);
  const [submittedError, setSubmittedError] = useState("");
  const blankForm = (mode = "manual") => ({
    company: "", role: "", date_applied: todayStr(),
    status: mode === "workspace" ? "saved" : "applied",
    source: mode === "workspace" ? "Other" : "MyCareersFuture",
    source_url: "", job_description: "",
    follow_up_date: "", notes: "",
  });
  const [form, setForm] = useState(blankForm);

  const resetForm = () => {
    setForm(blankForm());
    setFormMode("manual");
    setShowForm(false);
    setEditingId(null);
    setError("");
  };

  const openForm = (mode = "manual") => {
    setForm(blankForm(mode));
    setFormMode(mode);
    setEditingId(null);
    setError("");
    setShowForm(true);
  };

  const handleSave = async () => {
    if (!form.company.trim() || !form.role.trim()) {
      setError("Company and role are required.");
      return;
    }
    if (!editingId && formMode === "workspace" && !form.job_description.trim()) {
      setError("Job description is required to create a workspace.");
      return;
    }
    setSaving(true);
    setError("");
    try {
      if (editingId) {
        await apiFetch(`/api/tracked/${editingId}`, {
          method: "PUT",
          body: JSON.stringify(form),
        });
      } else if (formMode === "workspace") {
        await apiFetch("/api/applications/workspaces", {
          method: "POST",
          body: JSON.stringify({
            company: form.company,
            title: form.role,
            job_description: form.job_description,
            source_url: form.source_url,
            source: form.source,
            status: form.status,
            date_applied: form.date_applied,
            follow_up_date: form.follow_up_date,
            notes: form.notes,
          }),
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
      source_url: job.source_url || "",
      job_description: job.job_description || "",
      follow_up_date: job.follow_up_date || "",
      notes: job.notes || "",
    });
    setFormMode(job.job_description ? "workspace" : "manual");
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

  const openWorkspace = async (id) => {
    setWorkspace(null);
    setWorkspaceError("");
    setWorkspaceAgentError("");
    setResearchError("");
    setNegotiationError("");
    setSubmittedFile(null);
    setSubmittedDate(todayStr());
    setSubmittedNotes("");
    setSubmittedError("");
    setWorkspaceLoading(true);
    try {
      const response = await apiFetch(`/api/applications/workspaces/${id}`);
      const loadedWorkspace = await response.json();
      setWorkspace(loadedWorkspace);
      const savedNegotiation = loadedWorkspace.role_metadata?.negotiation;
      setNegotiationPriorities((savedNegotiation?.priorities || []).join("\n"));
      setWalkAwayPoint(savedNegotiation?.walk_away_point || "");
    } catch (err) {
      setWorkspaceError(err.message || "Failed to load workspace.");
    } finally {
      setWorkspaceLoading(false);
    }
  };

  useEffect(() => {
    if (!openJobId) return;
    openWorkspace(openJobId);
    onOpenJobHandled?.();
  }, [openJobId]);

  const runWorkspaceAgentReview = async () => {
    if (!workspace || workspaceAgentLoading) return;
    setWorkspaceAgentLoading(true);
    setWorkspaceAgentError("");
    try {
      let resumeVersionId = workspace.resume_version_id;
      if (!resumeVersionId) {
        const versionsResponse = await apiFetch("/api/resume/versions");
        const versions = await versionsResponse.json();
        const selectedVersion = versions.find((version) => version.is_master) || versions[0];
        if (!selectedVersion) {
          throw new Error("Save a resume version in Resume before running Deep Agent review.");
        }
        resumeVersionId = selectedVersion.id;
        await apiFetch(`/api/tracked/${workspace.id}`, {
          method: "PUT",
          body: JSON.stringify({ resume_version_id: resumeVersionId }),
        });
      }
      const response = await apiFetch(`/api/applications/workspaces/${workspace.id}/agent-review`, {
        method: "POST",
        body: JSON.stringify({}),
      });
      setWorkspace(await response.json());
    } catch (err) {
      setWorkspaceAgentError(err.message || "Deep Agent review failed.");
    } finally {
      setWorkspaceAgentLoading(false);
    }
  };

  const buildResearchPack = async () => {
    if (!workspace || researchLoading) return;
    setResearchLoading(true);
    setResearchError("");
    try {
      const response = await apiFetch(`/api/applications/workspaces/${workspace.id}/research-pack`, {
        method: "POST",
        body: JSON.stringify({}),
      });
      setWorkspace(await response.json());
    } catch (err) {
      setResearchError(err.message || "Research sources could not be checked.");
    } finally {
      setResearchLoading(false);
    }
  };

  const rehearseNegotiation = async (event) => {
    event.preventDefault();
    if (!workspace || negotiationLoading || !negotiationScenario.trim()) return;
    setNegotiationLoading(true);
    setNegotiationError("");
    try {
      const response = await apiFetch(`/api/applications/workspaces/${workspace.id}/negotiation/rehearse`, {
        method: "POST",
        body: JSON.stringify({
          priorities: negotiationPriorities.split("\n").map((item) => item.trim()).filter(Boolean),
          walk_away_point: walkAwayPoint.trim(),
          scenario: negotiationScenario.trim(),
          authorized_evidence: (
            authorizedEvidenceLabel.trim()
            && authorizedEvidenceValue.trim()
            && authorizedEvidenceDefinition.trim()
          ) ? [{
            label: authorizedEvidenceLabel.trim(),
            value: authorizedEvidenceValue.trim(),
            definition: authorizedEvidenceDefinition.trim(),
            source_url: authorizedEvidenceSourceUrl.trim(),
            data_date: authorizedEvidenceDataDate,
          }] : [],
        }),
      });
      setWorkspace(await response.json());
      setNegotiationScenario("");
      setAuthorizedEvidenceLabel("");
      setAuthorizedEvidenceValue("");
      setAuthorizedEvidenceDefinition("");
      setAuthorizedEvidenceSourceUrl("");
      setAuthorizedEvidenceDataDate("");
    } catch (err) {
      setNegotiationError(err.message || "Negotiation rehearsal could not be saved.");
    } finally {
      setNegotiationLoading(false);
    }
  };

  const saveSubmittedResume = async () => {
    if (!workspace || !submittedFile) return;
    setSubmittedSaving(true);
    setSubmittedError("");
    try {
      const formData = new FormData();
      formData.append("file", submittedFile);
      formData.append("submitted_date", submittedDate || todayStr());
      formData.append("notes", submittedNotes);
      const response = await apiFetch(`/api/applications/workspaces/${workspace.id}/submitted-resume`, {
        method: "POST",
        body: formData,
      });
      setWorkspace(await response.json());
      setSubmittedFile(null);
      setSubmittedNotes("");
    } catch (err) {
      setSubmittedError(err.message || "Failed to save submitted resume.");
    } finally {
      setSubmittedSaving(false);
    }
  };

  const handleExport = async () => {
    try {
      const resp = await apiFetch("/api/tracked/export");
      const blob = await resp.blob();
      downloadBlob(blob, "tracked_jobs.csv");
    } catch (err) {
      setError(err.message || "Export failed. Please try again.");
    }
  };

  const filtered = filterStatus === "all" ? jobs : jobs.filter((j) => j.status === filterStatus);
  const boardStatuses = Object.keys(STATUS_CONFIG);
  const boardJobsByStatus = boardStatuses.reduce((groups, status) => {
    groups[status] = filtered.filter((job) => job.status === status);
    return groups;
  }, {});
  const stats = {
    submitted: jobs.filter((j) => j.status === "applied").length,
    interview: jobs.filter((j) => ["screening", "interview", "assessment", "final_round"].includes(j.status)).length,
    offer: jobs.filter((j) => ["offer", "accepted"].includes(j.status)).length,
    rejected: jobs.filter((j) => j.status === "rejected").length,
    withdrawn: jobs.filter((j) => j.status === "withdrawn").length,
    noResponse: jobs.filter((j) => j.status === "no_response").length,
  };

  const agentReview = workspace?.role_metadata?.agent_review;
  const recruitmentPipeline = workspace?.role_metadata?.recruitment_pipeline;
  const applicationResearch = workspace?.role_metadata?.application_research;
  const roleCompanyBrief = applicationResearch?.role_company_brief;
  const interviewPack = applicationResearch?.interview_pack;
  const compensationBrief = applicationResearch?.compensation_brief;
  const negotiation = workspace?.role_metadata?.negotiation;
  const workspaceContacts = Array.isArray(workspace?.role_metadata?.contacts)
    ? workspace.role_metadata.contacts
    : [];
  const workspaceActivity = [
    ...(Array.isArray(workspace?.role_metadata?.activity) ? workspace.role_metadata.activity : []),
    ...(Array.isArray(recruitmentPipeline?.activity) ? recruitmentPipeline.activity : []),
  ];
  const debateSummary = agentReview?.debate_summary;
  const submittedResume = workspace?.role_metadata?.submitted_resume;
  const dndSensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 8 } }));

  const handleBoardDragEnd = async ({ active, over }) => {
    const move = getPipelineStatusMove(active, over);
    if (!move) return;
    const { jobId, nextStatus } = move;
    setMovingId(jobId);
    setError("");
    try {
      await apiFetch(`/api/tracked/${jobId}`, {
        method: "PUT",
        body: JSON.stringify({ status: nextStatus }),
      });
      await refreshJobs();
    } catch (err) {
      setError(err.message || "Failed to move application.");
    } finally {
      setMovingId(null);
    }
  };

  const pageHeading = (
    <div>
      <h1 className="text-xl font-bold tracking-[-0.01em] text-ink">Applications</h1>
      <p className="mt-1 text-sm text-muted">Jobs you saved or applied for, and where each one stands.</p>
    </div>
  );

  if (loading && jobs.length === 0) {
    return (
      <div className="space-y-6">
        {pageHeading}
        <div className={`${PANEL} p-4`} role="status">
          <span className="sr-only">Loading applications</span>
          {[0, 1, 2].map((row) => (
            <div key={row} className="flex items-center gap-4 border-b border-line py-4 last:border-0">
              <div className="h-4 w-1/4 rounded bg-paper" />
              <div className="h-4 w-1/3 rounded bg-paper" />
              <div className="ml-auto h-4 w-16 rounded bg-paper" />
            </div>
          ))}
        </div>
      </div>
    );
  }

  // Show onboarding empty state when no jobs tracked at all
  if (jobs.length === 0 && !showForm) {
    return (
      <div className="mx-auto max-w-lg px-4 py-16 text-center">
        {loadError && (
          <div className="mb-8 text-left">
            <Notice action={<button type="button" onClick={() => refreshJobs()} className="shrink-0 font-semibold underline-offset-2 hover:underline">Retry</button>}>
              {loadError}
            </Notice>
          </div>
        )}
        <h1 className="text-xl font-bold tracking-[-0.01em] text-ink">No applications yet</h1>
        <p className="mx-auto mt-2 max-w-md text-sm leading-relaxed text-muted">
          Save a job from Search and it appears here, with its status, follow-up date and notes.
          You can also paste a job description or add an application by hand.
        </p>
        <div className="mt-6 flex flex-col items-stretch justify-center gap-2 sm:flex-row sm:items-center">
          {setActiveTab && (
            <button type="button" onClick={() => setActiveTab("jobs")} className={BTN_PRIMARY}>
              <Search size={16} aria-hidden="true" /> Search jobs
            </button>
          )}
          <button type="button" onClick={() => openForm("workspace")} className={BTN_SECONDARY}>
            Paste JD
          </button>
          <button type="button" onClick={() => openForm("manual")} className={`${BTN_TEXT} justify-center`}>
            Add manually
          </button>
        </div>
      </div>
    );
  }

  const outcomes = [
    { key: "submitted", label: "Submitted", value: stats.submitted },
    { key: "interview", label: "Interview", value: stats.interview },
    { key: "offer", label: "Offer", value: stats.offer },
    { key: "rejected", label: "Rejected", value: stats.rejected },
    { key: "withdrawn", label: "Withdrawn", value: stats.withdrawn },
    { key: "no_response", label: "No Response", value: stats.noResponse },
  ];

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        {pageHeading}
        <div className="flex gap-2">
          <button type="button" onClick={() => openForm("workspace")} className={`${BTN_SECONDARY} flex-1 sm:flex-none`}>
            Paste JD
          </button>
          <button type="button" onClick={() => openForm("manual")} className={`${showForm ? BTN_SECONDARY : BTN_PRIMARY} flex-1 sm:flex-none`}>
            <Plus size={16} aria-hidden="true" /> Add
          </button>
        </div>
      </div>

      {(error || loadError) && !showForm && (
        <Notice
          action={error ? (
            <button type="button" onClick={() => setError("")} aria-label="Dismiss" className="-m-2 inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-md hover:bg-[#fef3f2]"><X size={14} aria-hidden="true" /></button>
          ) : (
            <button type="button" onClick={() => refreshJobs()} className="shrink-0 font-semibold underline-offset-2 hover:underline">Retry</button>
          )}
        >
          {error || loadError}
        </Notice>
      )}

      <dl className={`${PANEL} grid grid-cols-3 sm:grid-cols-6`}>
        {outcomes.map((s, index) => (
          <div
            key={s.key}
            className={`px-4 py-3 ${index % 3 ? "border-l border-line" : ""} ${index >= 3 ? "border-t border-line sm:border-t-0" : ""} ${index === 3 ? "sm:border-l" : ""}`}
            data-outcome-count={s.key}
          >
            <div className="text-xl font-semibold tabular-nums text-ink">{s.value}</div>
            <dt className="mt-0.5 text-xs text-muted">{s.label}</dt>
          </div>
        ))}
      </dl>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <label htmlFor="tracker-status-filter" className="sr-only">Filter by status</label>
          <select id="tracker-status-filter" value={filterStatus} onChange={(e) => setFilterStatus(e.target.value)} className="min-h-11 rounded-md border border-field bg-white px-3 text-sm text-ink">
            <option value="all">All statuses</option>
            {Object.entries(STATUS_CONFIG).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
          </select>
          <div className="inline-flex rounded-md border border-field bg-white p-0.5" role="group" aria-label="Application view">
            {[["table", "Table"], ["board", "Board"]].map(([mode, label]) => (
              <button
                key={mode}
                type="button"
                onClick={() => setViewMode(mode)}
                aria-pressed={viewMode === mode}
                className={`min-h-10 rounded px-3 text-sm transition-colors ${viewMode === mode ? "bg-tint font-semibold text-ink" : "text-muted hover:text-ink"}`}
              >
                {label}
              </button>
            ))}
          </div>
        </div>
        <div className="flex items-center gap-1">
          <button type="button" onClick={handleExport} className={BTN_TEXT}>
            <Download size={14} aria-hidden="true" /> Export CSV
          </button>
          <button type="button" onClick={() => refreshJobs()} aria-label="Refresh applications" title="Refresh" className={BTN_ICON}>
            <RefreshCw size={16} aria-hidden="true" />
          </button>
        </div>
      </div>

      {showForm && (
        <section className={`${PANEL} space-y-4 p-5`} aria-labelledby="tracker-form-title">
          <div className="flex items-center justify-between gap-3">
            <h2 id="tracker-form-title" className={H3}>
              {editingId ? "Edit application" : formMode === "workspace" ? "New application from a job description" : "New application"}
            </h2>
            <button type="button" onClick={resetForm} aria-label="Close form" className={BTN_ICON}><X size={18} aria-hidden="true" /></button>
          </div>
          {error && <Notice>{error}</Notice>}
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <label className="block">
              <span className={LABEL}>Company</span>
              <input placeholder="Company *" value={form.company} onChange={(e) => setForm({ ...form, company: e.target.value })} className={FIELD} />
            </label>
            <label className="block">
              <span className={LABEL}>Role</span>
              <input placeholder="Role *" value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })} className={FIELD} />
            </label>
            <label className="block">
              <span className={LABEL}>Applied</span>
              <input type="date" value={form.date_applied} onChange={(e) => setForm({ ...form, date_applied: e.target.value })} className={FIELD} />
            </label>
            <label className="block">
              <span className={LABEL}>Status</span>
              <select value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value })} className={FIELD}>
                {Object.entries(STATUS_CONFIG).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
              </select>
            </label>
            <label className="block">
              <span className={LABEL}>Where you found it</span>
              <select value={form.source} onChange={(e) => setForm({ ...form, source: e.target.value })} className={FIELD}>
                {SG_JOB_PORTALS.map((p) => <option key={p.key} value={p.name}>{p.name}</option>)}
                <option value="Referral">Referral</option>
                <option value="Other">Other</option>
              </select>
            </label>
            <label className="block">
              <span className={LABEL}>Follow up on</span>
              <input type="date" value={form.follow_up_date || ""} onChange={(e) => setForm({ ...form, follow_up_date: e.target.value })} className={FIELD} />
            </label>
          </div>
          {(formMode === "workspace" || form.job_description) && (
            <>
              <label className="block">
                <span className={LABEL}>Job posting link</span>
                <input
                  placeholder="Source URL"
                  value={form.source_url}
                  onChange={(e) => setForm({ ...form, source_url: e.target.value })}
                  className={FIELD}
                />
              </label>
              <label className="block">
                <span className={LABEL}>Job description</span>
                <textarea
                  placeholder="Paste job description *"
                  value={form.job_description}
                  onChange={(e) => setForm({ ...form, job_description: e.target.value })}
                  className={TEXTAREA}
                  rows={6}
                />
              </label>
            </>
          )}
          <label className="block">
            <span className={LABEL}>Notes</span>
            <textarea placeholder="Notes" value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} className={TEXTAREA} rows={2} />
          </label>
          <button type="button" onClick={handleSave} disabled={saving || !form.company || !form.role} className={BTN_PRIMARY}>
            {saving && <Loader2 size={14} className="animate-spin" aria-hidden="true" />}
            {editingId ? "Update" : "Save"}
          </button>
        </section>
      )}

      {(workspaceLoading || workspace || workspaceError) && (
        <section className={`${PANEL} space-y-5 p-5`} aria-labelledby="workspace-title">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div className="min-w-0">
              <h2 id="workspace-title" className={H3}>Application Workspace</h2>
              {workspace && (
                <p className="mt-0.5 text-sm text-muted [overflow-wrap:anywhere]">{workspace.title} at {workspace.company}</p>
              )}
            </div>
            <div className="flex w-full items-center gap-2 sm:w-auto">
              {workspace && (
                <button
                  type="button"
                  onClick={runWorkspaceAgentReview}
                  disabled={workspaceAgentLoading}
                  className={`${BTN_SECONDARY} flex-1 sm:flex-none`}
                >
                  {workspaceAgentLoading && <Loader2 size={14} className="animate-spin" aria-hidden="true" />}
                  {workspaceAgentLoading ? "Reviewing..." : agentReview ? "Run review again" : "Run Deep Agent review"}
                </button>
              )}
              <button type="button" onClick={() => { setWorkspace(null); setWorkspaceError(""); setWorkspaceAgentError(""); }} aria-label="Close workspace" className={BTN_ICON}><X size={18} aria-hidden="true" /></button>
            </div>
          </div>
          {workspaceLoading && (
            <div className="flex items-center gap-2 text-sm text-muted">
              <Loader2 size={14} className="animate-spin" aria-hidden="true" /> Loading workspace...
            </div>
          )}
          {workspaceError && <Notice>{workspaceError}</Notice>}
          {workspaceAgentLoading && (
            <div className="flex items-start gap-3 rounded-md bg-tint p-3 text-sm text-ink" role="status">
              <Loader2 size={16} className="mt-0.5 shrink-0 animate-spin text-accent" aria-hidden="true" />
              <div>
                <div className="font-medium">Deep Agent is reviewing your evidence and role fit.</div>
                <div className="mt-1 text-muted">This usually takes 20–40 seconds. You will review every proposed edit before anything changes.</div>
              </div>
            </div>
          )}
          {workspaceAgentError && (
            <Notice
              action={workspaceAgentError.startsWith("Save a resume version") && (
                <button type="button" onClick={() => setActiveTab("resume")} className="shrink-0 font-semibold underline">Open Resume</button>
              )}
            >
              {workspaceAgentError}
            </Notice>
          )}
          {workspace && (
            <>
              <dl className="grid grid-cols-1 gap-x-6 gap-y-3 text-sm sm:grid-cols-3">
                <div>
                  <dt className="text-xs text-muted">Status</dt>
                  <dd className="mt-0.5"><StatusBadge status={workspace.status} /></dd>
                </div>
                <div>
                  <dt className="text-xs text-muted">Resume context</dt>
                  <dd className="mt-0.5 text-ink">
                    {workspace.resume_version_id ? `Version #${workspace.resume_version_id}` : "No resume linked yet"}
                  </dd>
                </div>
                <div>
                  <dt className="text-xs text-muted">Source</dt>
                  <dd className="mt-0.5 break-all text-ink">{workspace.source_url || workspace.source || "Manual"}</dd>
                </div>
                {(workspace.follow_up_date || workspace.notes) && (
                  <>
                    <div>
                      <dt className="text-xs text-muted">Follow-up</dt>
                      <dd className="mt-0.5 text-ink tabular-nums">{workspace.follow_up_date ? formatPostingDate(workspace.follow_up_date) : "No follow-up date set."}</dd>
                    </div>
                    <div className="sm:col-span-2">
                      <dt className="text-xs text-muted">Notes</dt>
                      <dd className="mt-0.5 whitespace-pre-wrap text-ink">{workspace.notes || "No notes saved."}</dd>
                    </div>
                  </>
                )}
                {recruitmentPipeline && (
                  <>
                    <div className="sm:col-span-2">
                      <dt className="text-xs text-muted">Next action</dt>
                      <dd className="mt-0.5 text-ink">{recruitmentPipeline.next_action?.label || "Review this application"}</dd>
                    </div>
                    <div>
                      <dt className="text-xs text-muted">Fit evidence</dt>
                      <dd className="mt-0.5 text-ink tabular-nums">
                        {recruitmentPipeline.fit_evidence?.matched?.length || 0} matched · {recruitmentPipeline.fit_evidence?.stretch?.length || 0} stretch · {recruitmentPipeline.fit_evidence?.missing?.length || 0} missing
                      </dd>
                    </div>
                  </>
                )}
              </dl>
              <div>
                <h3 className={H4}>Job description</h3>
                <p className="mt-2 max-w-3xl whitespace-pre-wrap border-l-2 border-line pl-3 text-sm leading-relaxed text-ink">
                  {workspace.job_description || "No job description saved."}
                </p>
              </div>
              <section aria-labelledby="application-research-title" className={SECTION}>
                <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                  <div>
                    <h3 id="application-research-title" className={H3}>Research for this role</h3>
                    <p className="mt-1 text-sm text-muted">
                      Current public postings and official MOM wage figures, each with its source.
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={buildResearchPack}
                    disabled={researchLoading}
                    className={BTN_SECONDARY}
                  >
                    {researchLoading && <Loader2 size={14} className="animate-spin" aria-hidden="true" />}
                    {researchLoading ? "Checking sources..." : applicationResearch ? "Refresh research" : "Build research pack"}
                  </button>
                </div>
                {researchError && <div className="mt-3"><Notice>{researchError}</Notice></div>}
                {applicationResearch && (
                  <div className="mt-4 space-y-5 text-sm">
                    <p className="text-xs text-muted">
                      {[
                        `Status: ${applicationResearch.status.replaceAll("_", " ")}`,
                        `Evidence: ${roleCompanyBrief?.freshness || "unknown"}`,
                        ...(applicationResearch.source_statuses || []).map((source) => (
                          `${source.source.replaceAll("_", " ")}: ${source.status.replaceAll("_", " ")}`
                        )),
                      ].join(" · ")}
                    </p>
                    {(applicationResearch.source_statuses || []).some((source) => source.detail) && (
                      <ul className="space-y-1 text-xs text-muted">
                        {applicationResearch.source_statuses.filter((source) => source.detail).map((source) => (
                          <li key={`${source.source}-detail`}>{source.source.replaceAll("_", " ")}: {source.detail}</li>
                        ))}
                      </ul>
                    )}
                    <div className="grid grid-cols-1 gap-x-8 gap-y-5 lg:grid-cols-2">
                      <div>
                        <h4 className={H4}>Role and company</h4>
                        <p className="mt-1 text-ink">
                          {roleCompanyBrief?.company?.current_posting_count || 0} current company posting(s); {(roleCompanyBrief?.role?.comparable_titles || []).length} comparable title(s).
                        </p>
                        {(roleCompanyBrief?.company?.observed_industries || []).length > 0 && (
                          <p className="mt-1 text-xs text-muted">Observed context: {roleCompanyBrief.company.observed_industries.join(" · ")}</p>
                        )}
                        {(roleCompanyBrief?.role?.comparable_titles || []).length > 0 && (
                          <ul className="mt-2 space-y-1 text-ink">
                            {roleCompanyBrief.role.comparable_titles.map((item) => (
                              <li key={`${item.company}-${item.title}`}>Comparable: {item.title} at {item.company}</li>
                            ))}
                          </ul>
                        )}
                        {(roleCompanyBrief?.role?.ats_terms || []).length > 0 && (
                          <p className="mt-2 text-ink">
                            <span className="text-muted">Terms in postings: </span>
                            {roleCompanyBrief.role.ats_terms.map((term) => term.term).join(", ")}
                          </p>
                        )}
                        <div className="mt-2 space-y-1 text-xs">
                          {(roleCompanyBrief?.sources || []).filter((source) => source.url).slice(0, RESEARCH_SOURCE_DISPLAY_LIMIT).map((source, index) => (
                            <a key={`${source.url}-${index}`} href={source.url} target="_blank" rel="noreferrer" className={`block break-all ${LINK}`}>
                              {source.publisher || source.source_type} · {source.confidence} · {source.freshness}
                            </a>
                          ))}
                        </div>
                      </div>
                      <div>
                        <h4 className={H4}>Pay</h4>
                        <p className="mt-1 text-xs text-muted">{compensationBrief?.comparison_rule}</p>
                        <p className="mt-1 text-xs text-muted">
                          Coverage: {(compensationBrief?.comparison_state || "valid_empty").replaceAll("_", " ")}
                        </p>
                        <ul className="mt-2 space-y-3">
                          {(compensationBrief?.observations || []).map((observation, index) => (
                            <li key={`${observation.kind}-${index}`} className="text-ink">
                              <div className="font-medium">{observation.kind.replaceAll("_", " ")}</div>
                              <div className="mt-0.5 tabular-nums">{compensationObservationLabel(observation)}</div>
                              <div className="mt-0.5 text-xs text-muted">
                                {observation.occupation || observation.definition || ""}{observation.data_date ? ` · ${observation.data_date}` : ""}
                              </div>
                              {observation.source_url && (
                                <a href={observation.source_url} target="_blank" rel="noreferrer" className={`mt-1 inline-block text-xs ${LINK}`}>View source</a>
                              )}
                            </li>
                          ))}
                        </ul>
                        {!(compensationBrief?.observations || []).length && <p className="mt-2 text-xs text-muted">No compatible compensation observation was available.</p>}
                        {(compensationBrief?.recruiter_guide_leads || []).length > 0 && (
                          <div className="mt-3 border-t border-line pt-3 text-xs">
                            <div className="font-medium text-ink">Public recruiter-guide leads</div>
                            {(compensationBrief.recruiter_guide_leads || []).map((source) => (
                              <a key={source.source_url} href={source.source_url} target="_blank" rel="noreferrer" className={`mt-2 block ${LINK}`}>
                                {source.publisher} · {source.publication_date} · {source.status.replaceAll("_", " ")}
                                <span className="block text-muted">{source.evidence_note}</span>
                              </a>
                            ))}
                          </div>
                        )}
                      </div>
                    </div>
                    <div>
                      <h4 className={H4}>Interview preparation</h4>
                      <p className="mt-1 text-xs text-muted">
                        {interviewPack?.confidence_note} Source state: {(interviewPack?.source_state || "valid_empty").replaceAll("_", " ")}.
                        Answer formats: {(interviewPack?.answer_formats || []).join(" / ") || "none"}.
                      </p>
                      <ul className="mt-2 divide-y divide-line border-y border-line">
                        {(interviewPack?.questions || []).map((item, index) => (
                          <li key={`${item.cluster}-${index}`}>
                            <details className="group py-3">
                              <summary className="cursor-pointer list-none rounded text-ink">
                                <span className="block text-xs text-muted">{item.cluster.replaceAll("_", " ")} · {item.confidence}</span>
                                <span className="mt-0.5 block">{item.question}</span>
                                <span className="mt-1 block text-xs font-medium text-accent group-open:hidden">Show evidence and answer outline</span>
                              </summary>
                              <p className="mt-2 text-xs text-muted">
                                {item.answer_scaffold?.evidence_quote || (item.answer_scaffold?.status === "missing_evidence" ? "Missing evidence: confirm a real example first." : "Candidate input required.")}
                              </p>
                              {(item.answer_scaffold?.steps || []).length > 0 && (
                                <ol className="mt-2 list-decimal space-y-1 pl-4 text-xs text-muted">
                                  {item.answer_scaffold.steps.map((step) => <li key={step}>{step}</li>)}
                                </ol>
                              )}
                              {(item.sources || []).filter((source) => source.url).map((source) => (
                                <a key={source.url} href={source.url} target="_blank" rel="noreferrer" className={`mt-2 block text-xs ${LINK}`}>
                                  {source.source_type.replaceAll("_", " ")} · retrieved {formatResearchDate(source.retrieved_at)} · {source.evidence_note}
                                </a>
                              ))}
                            </details>
                          </li>
                        ))}
                      </ul>
                    </div>
                  </div>
                )}
                <form onSubmit={rehearseNegotiation} className="mt-5">
                  <h4 className={H4}>Private negotiation rehearsal</h4>
                  <p className="mt-1 max-w-3xl text-xs text-muted">Your scenario and authorised evidence are sent to the AI coach and saved on this application, but are not copied into usage logs. Your walk-away point is not sent to the coach. One priority per line.</p>
                  <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2">
                    <textarea value={negotiationPriorities} onChange={(event) => setNegotiationPriorities(event.target.value)} aria-label="Priorities, one per line" placeholder={"Priorities\nRole scope\nBase salary"} rows={3} className={TEXTAREA} />
                    <input value={walkAwayPoint} onChange={(event) => setWalkAwayPoint(event.target.value)} aria-label="Private walk-away point" placeholder="Private walk-away point (optional)" className={FIELD} />
                  </div>
                  <div className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-3">
                    <input value={authorizedEvidenceLabel} onChange={(event) => setAuthorizedEvidenceLabel(event.target.value)} aria-label="Authorized evidence label" placeholder="Authorized evidence label" className={FIELD} />
                    <input value={authorizedEvidenceValue} onChange={(event) => setAuthorizedEvidenceValue(event.target.value)} aria-label="Observed value" placeholder="Observed value" className={FIELD} />
                    <input value={authorizedEvidenceDefinition} onChange={(event) => setAuthorizedEvidenceDefinition(event.target.value)} aria-label="Definition or package basis" placeholder="Definition / package basis" className={FIELD} />
                    <input type="url" value={authorizedEvidenceSourceUrl} onChange={(event) => setAuthorizedEvidenceSourceUrl(event.target.value)} aria-label="Authorized source URL" placeholder="Authorized source URL (optional)" className={FIELD} />
                    <label className="flex min-h-11 items-center gap-2 rounded-md border border-field bg-white px-3 text-sm text-muted">
                      Evidence date
                      <input type="date" value={authorizedEvidenceDataDate} onInput={(event) => setAuthorizedEvidenceDataDate(event.currentTarget.value)} className="min-w-0 flex-1 bg-transparent text-ink" />
                    </label>
                  </div>
                  <textarea value={negotiationScenario} onChange={(event) => setNegotiationScenario(event.target.value)} aria-label="What the recruiter or hiring manager said" placeholder="What did the recruiter or hiring manager say?" rows={3} className={`mt-2 ${TEXTAREA}`} />
                  {negotiationError && <div className="mt-2"><Notice>{negotiationError}</Notice></div>}
                  <button type="submit" disabled={negotiationLoading || !negotiationScenario.trim() || !negotiationPriorities.trim()} className={`mt-2 ${BTN_SECONDARY}`}>
                    {negotiationLoading && <Loader2 size={14} className="animate-spin" aria-hidden="true" />}
                    Save and rehearse
                  </button>
                  {(negotiation?.rounds || []).length > 0 && (
                    <div className="mt-4 space-y-4">
                      {negotiation.rounds.slice(-NEGOTIATION_ROUND_DISPLAY_LIMIT).map((round, index) => (
                        <div key={`${round.created_at}-${index}`} className="border-l-2 border-line pl-3 text-sm">
                          <div className="font-medium text-ink">Scenario: {round.scenario}</div>
                          <p className="mt-1 text-muted">{round.coach_response.opening}</p>
                          <p className="mt-1 text-muted">{round.coach_response.walk_away_guidance}</p>
                          {(round.coach_response.anchor_options || []).map((anchor, anchorIndex) => (
                            <div key={`${anchor.kind}-${anchorIndex}`} className="mt-2 text-muted">
                              <span className="font-medium text-ink">{anchor.label}: </span>
                              {negotiationAnchorLabel(anchor)} · {anchor.definition || "definition unavailable"}
                              <span className="block text-xs">{anchor.source_type || "source unknown"} · {anchor.data_date || "data date unavailable"}</span>
                              {anchor.source_url && <a href={anchor.source_url} target="_blank" rel="noreferrer" className={`mt-1 block text-xs ${LINK}`}>View anchor source</a>}
                            </div>
                          ))}
                          <ul className="mt-2 list-disc space-y-1 pl-4 text-muted">
                            {(round.coach_response.questions || []).map((question) => <li key={question}>{question}</li>)}
                            {(round.coach_response.trade_offs || []).map((tradeOff) => <li key={tradeOff}>{tradeOff}</li>)}
                            {(round.coach_response.concessions || []).map((concession) => <li key={concession}>{concession}</li>)}
                          </ul>
                        </div>
                      ))}
                    </div>
                  )}
                </form>
              </section>
              <div className={`${SECTION} grid grid-cols-1 gap-x-8 gap-y-5 text-sm sm:grid-cols-2`}>
                <div>
                  <h3 className={H4}>Contacts</h3>
                  {workspaceContacts.length ? workspaceContacts.map((contact, index) => (
                    <div key={`${contact.name || "contact"}-${index}`} className="mt-2 text-ink">
                      {contact.name || contact.label || "Contact"}{contact.details ? ` · ${contact.details}` : ""}
                    </div>
                  )) : <p className="mt-2 text-muted">No contacts saved yet.</p>}
                </div>
                <div>
                  <h3 className={H4}>Application activity</h3>
                  {workspaceActivity.length ? workspaceActivity.map((item, index) => (
                    <div key={`${item.action || item.type || "activity"}-${index}`} className="mt-2 flex justify-between gap-2 text-ink">
                      <span>{String(item.action || item.type || "updated").replaceAll("_", " ")}</span>
                      <span className="text-xs tabular-nums text-muted">{item.recorded_at ? new Date(item.recorded_at).toLocaleDateString("en-SG", { day: "numeric", month: "short", year: "numeric" }) : ""}</span>
                    </div>
                  )) : <p className="mt-2 text-muted">No application activity recorded yet.</p>}
                </div>
                <div className="sm:col-span-2">
                  <h3 className={H4}>Stage history</h3>
                  {(workspace.stage_history || []).length === 0 ? (
                    <p className="mt-2 text-muted">No stage history recorded yet.</p>
                  ) : (
                    <ol className="mt-2 divide-y divide-line border-y border-line">
                      {workspace.stage_history.map((event, index) => (
                        <li key={`${event.stage}-${index}`} className="flex items-center justify-between gap-3 py-2">
                          <span className="font-medium text-ink">{STATUS_CONFIG[event.stage]?.label || event.stage}</span>
                          <span className="tabular-nums text-muted">{formatPostingDate(event.date)}</span>
                        </li>
                      ))}
                    </ol>
                  )}
                </div>
              </div>
              <div className={`${SECTION} grid grid-cols-1 gap-x-8 gap-y-5 text-sm sm:grid-cols-2`}>
                {debateSummary ? (
                  <div className="text-ink">
                    <h3 className={H4}>Debate summary</h3>
                    <p className="mt-2">{debateSummary.final_recommendation}</p>
                    {(Array.isArray(debateSummary.roles) ? debateSummary.roles : []).length > 0 && (
                      <p className="mt-2 text-xs text-muted">Reviewers: {debateSummary.roles.join(", ")}</p>
                    )}
                    {(Array.isArray(debateSummary.key_disagreements) ? debateSummary.key_disagreements : []).length > 0 && (
                      <ul className="mt-2 list-disc space-y-1 pl-4 text-xs text-muted">
                        {debateSummary.key_disagreements.map((item) => (
                          <li key={item}>{item}</li>
                        ))}
                      </ul>
                    )}
                    <div className="mt-2 text-xs text-muted">
                      Confidence: {debateSummary.confidence || "unknown"}
                      {debateSummary.trace_id ? `, trace ID: ${debateSummary.trace_id}` : ""}
                    </div>
                  </div>
                ) : (
                  <div>
                    <h3 className={H4}>Agent review</h3>
                    <p className="mt-2 text-muted">Agent review not run yet.</p>
                  </div>
                )}
                <div className="text-ink">
                  <h3 className={H4}>Submitted resume</h3>
                  {submittedResume ? (
                    <div className="mt-2 space-y-1">
                      <div>{submittedResume.filename}</div>
                      <div className="text-xs tabular-nums text-muted">
                        {submittedResume.submitted_date} - {submittedResume.word_count || 0} words
                      </div>
                      {submittedResume.notes && <div className="text-xs text-muted">{submittedResume.notes}</div>}
                    </div>
                  ) : (
                    <p className="mt-2 text-muted">No submitted resume recorded yet.</p>
                  )}
                  <div className="mt-3 space-y-2">
                    <input
                      type="file"
                      accept=".pdf,.docx"
                      aria-label="Resume file you submitted"
                      onChange={(event) => setSubmittedFile(event.target.files?.[0] || null)}
                      className="w-full text-sm text-muted file:mr-3 file:min-h-10 file:rounded-md file:border file:border-field file:bg-white file:px-3 file:text-sm file:font-medium file:text-ink hover:file:bg-tint"
                    />
                    <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                      <input
                        type="date"
                        aria-label="Date submitted"
                        value={submittedDate}
                        onChange={(event) => setSubmittedDate(event.target.value)}
                        className={FIELD}
                      />
                      <input
                        aria-label="Submitted resume notes"
                        placeholder="Submitted resume notes"
                        value={submittedNotes}
                        onChange={(event) => setSubmittedNotes(event.target.value)}
                        className={FIELD}
                      />
                    </div>
                    {submittedError && <Notice>{submittedError}</Notice>}
                    <button
                      type="button"
                      onClick={saveSubmittedResume}
                      disabled={!submittedFile || submittedSaving}
                      className={BTN_SECONDARY}
                    >
                      {submittedSaving ? <Loader2 size={14} className="animate-spin" aria-hidden="true" /> : <FileText size={14} aria-hidden="true" />}
                      Save submitted resume
                    </button>
                  </div>
                </div>
              </div>
            </>
          )}
        </section>
      )}

      {viewMode === "board" && (
        <DndContext sensors={dndSensors} collisionDetection={closestCorners} onDragEnd={handleBoardDragEnd}>
          <div className="-mx-4 overflow-x-auto px-4 pb-1 sm:mx-0 sm:px-0">
            <div
              className="grid gap-2"
              style={{ gridTemplateColumns: `repeat(${boardStatuses.length}, minmax(180px, 1fr))` }}
            >
              {boardStatuses.map((status) => (
                <PipelineColumn
                  key={status}
                  status={status}
                  jobs={boardJobsByStatus[status] || []}
                  movingId={movingId}
                  openWorkspace={openWorkspace}
                  handleEdit={handleEdit}
                  handleDelete={handleDelete}
                />
              ))}
            </div>
          </div>
        </DndContext>
      )}

      {viewMode === "table" && (
        <>
          <div className={`${PANEL} hidden overflow-hidden sm:block`}>
            <table className="w-full text-sm">
              <thead className="border-b border-line text-left text-xs text-muted">
                <tr>
                  <th scope="col" className="px-4 py-3 font-semibold">Company</th>
                  <th scope="col" className="px-4 py-3 font-semibold">Role</th>
                  <th scope="col" className="px-4 py-3 font-semibold">Applied</th>
                  <th scope="col" className="px-4 py-3 font-semibold">Source</th>
                  <th scope="col" className="px-4 py-3 font-semibold">Status</th>
                  <th scope="col" className="px-4 py-3 text-right font-semibold">Days</th>
                  <th scope="col" className="px-4 py-3 text-right font-semibold"><span className="sr-only">Actions</span></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {filtered.length === 0 && (
                  <tr><td colSpan={7} className="px-4 py-10 text-center text-muted">{jobs.length ? "No applications have this status." : "No applications yet."}</td></tr>
                )}
                {filtered.map((job) => (
                  <tr key={job.id} className="transition-colors hover:bg-paper">
                    <td className="px-4 py-2 font-medium text-ink">{job.company}</td>
                    <td className="px-4 py-2 text-ink">{job.role}</td>
                    <td className="whitespace-nowrap px-4 py-2 tabular-nums text-muted">{formatPostingDate(job.date_applied)}</td>
                    <td className="px-4 py-2 text-muted">{job.source}</td>
                    <td className="px-4 py-2"><StatusBadge status={job.status} /></td>
                    <td className="px-4 py-2 text-right tabular-nums text-muted">{daysBetween(job.date_applied, todayStr())}d</td>
                    <td className="whitespace-nowrap px-2 py-1 text-right">
                      <button type="button" aria-label={`Open workspace for ${job.company} ${job.role}`} title="Open" onClick={() => openWorkspace(job.id)} className={BTN_ICON}><FileText size={16} aria-hidden="true" /></button>
                      <button type="button" aria-label={`Edit ${job.company} ${job.role}`} title="Edit" onClick={() => handleEdit(job)} className={BTN_ICON}><Edit3 size={16} aria-hidden="true" /></button>
                      <button type="button" aria-label={`Delete ${job.company} ${job.role}`} title="Delete" onClick={() => handleDelete(job.id)} className={BTN_ICON_DANGER}><Trash2 size={16} aria-hidden="true" /></button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <ul className="space-y-2 sm:hidden">
            {filtered.length === 0 && (
              <li className={`${PANEL} px-4 py-8 text-center text-sm text-muted`}>{jobs.length ? "No applications have this status." : "No applications yet."}</li>
            )}
            {filtered.map((job) => (
              <li key={job.id} className={`${PANEL} p-4`}>
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="font-semibold text-ink [overflow-wrap:anywhere]">{job.company}</div>
                    <div className="text-sm text-ink [overflow-wrap:anywhere]">{job.role}</div>
                  </div>
                  <span className="shrink-0"><StatusBadge status={job.status} /></span>
                </div>
                <div className="mt-1 flex flex-wrap gap-x-3 text-xs text-muted">
                  <span className="tabular-nums">{formatPostingDate(job.date_applied)}</span>
                  <span>{job.source}</span>
                  <span className="tabular-nums">{daysBetween(job.date_applied, todayStr())}d ago</span>
                </div>
                {job.notes && <p className="mt-2 text-sm text-muted">{job.notes}</p>}
                <div className="-mx-2 mt-1 flex gap-1">
                  <button type="button" onClick={() => openWorkspace(job.id)} className={BTN_TEXT}>Open</button>
                  <button type="button" onClick={() => handleEdit(job)} className={BTN_TEXT}>Edit</button>
                  <button type="button" onClick={() => handleDelete(job.id)} className={BTN_TEXT_DANGER}>Delete</button>
                </div>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
