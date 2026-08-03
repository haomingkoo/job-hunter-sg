import { useEffect, useState } from "react";
import { DndContext, PointerSensor, closestCorners, useDraggable, useDroppable, useSensor, useSensors } from "@dnd-kit/core";
import { CSS } from "@dnd-kit/utilities";
import {
  Plus, X, AlertCircle, Filter, RefreshCw,
  Download, Loader2, Edit3, Save, Trash2,
  Briefcase, Search, FileText, GripVertical,
} from "lucide-react";
import { apiFetch, downloadBlob } from "../lib/api.js";
import { STATUS_CONFIG, SG_JOB_PORTALS } from "../lib/constants.js";
import { todayStr, daysBetween } from "../lib/helpers.js";
import StatusBadge from "./StatusBadge.jsx";

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
      className={`rounded-lg border border-[#BDDDFC]/30 bg-white p-3 text-sm shadow-sm transition ${isDragging || moving ? "opacity-60" : ""}`}
      data-pipeline-card={job.id}
    >
      <div className="flex items-start gap-2">
        <button
          type="button"
          className="mt-0.5 cursor-grab text-[#6A89A7]/70 active:cursor-grabbing"
          aria-label={`Move ${job.company} ${job.role}`}
          title="Move"
          {...listeners}
          {...attributes}
        >
          <GripVertical size={14} />
        </button>
        <div className="min-w-0 flex-1">
          <div className="truncate font-semibold text-[#384959]">{job.company}</div>
          <div className="mt-1 truncate text-[#6A89A7]">{job.role}</div>
        </div>
      </div>
      <div className="mt-2 flex items-center justify-between text-xs text-[#6A89A7]">
        <span>{job.date_applied || "No date"}</span>
        <span>{job.source || "Manual"}</span>
      </div>
      <div className="mt-3 flex gap-2">
        <button type="button" onClick={() => openWorkspace(job.id)} className="text-xs text-[#384959] hover:underline">Open</button>
        <button type="button" onClick={() => handleEdit(job)} className="text-xs text-[#384959] hover:underline">Edit</button>
        <button type="button" onClick={() => handleDelete(job.id)} className="text-xs text-red-500 hover:underline">Delete</button>
      </div>
    </div>
  );
}

function PipelineColumn({ status, jobs, movingId, openWorkspace, handleEdit, handleDelete }) {
  const { isOver, setNodeRef } = useDroppable({ id: `status:${status}` });
  const config = STATUS_CONFIG[status];

  return (
    <div ref={setNodeRef} className={`min-h-[220px] rounded-lg bg-[#f0f4f8] p-3 ${isOver ? "ring-2 ring-[#88BDF2]" : ""}`} data-pipeline-column={status}>
      <div className="mb-3 flex items-center justify-between gap-2">
        <div className="text-sm font-semibold text-[#384959]">{config?.label || status}</div>
        <span className="rounded-full bg-white px-2 py-0.5 text-xs text-[#6A89A7]">{jobs.length}</span>
      </div>
      <div className="space-y-2">
        {jobs.length === 0 ? (
          <div className="rounded-lg border border-dashed border-[#BDDDFC]/50 px-3 py-6 text-center text-xs text-[#6A89A7]">
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

  // Show onboarding empty state when no jobs tracked at all
  if (jobs.length === 0 && !showForm) {
    return (
      <div className="flex flex-col items-center justify-center py-20 px-4">
        {loadError && (
          <div className="mb-6 flex max-w-md items-center justify-between gap-3 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
            <span>{loadError}</span>
            <button onClick={() => refreshJobs()} className="font-medium text-red-800 hover:text-red-900">Retry</button>
          </div>
        )}
        <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-[#f0f4f8] mb-6">
          <Briefcase size={32} className="text-[#6A89A7]" />
        </div>
        <h2 className="text-xl font-bold text-[#384959] text-center">Start Tracking Your Applications</h2>
        <p className="mt-2 max-w-md text-center text-sm text-[#6A89A7] leading-relaxed">
          When you find a job you like in the Jobs tab, click Track to add it here.
          You can monitor your pipeline, set follow-up dates, and track your progress.
        </p>
        <div className="mt-6 flex gap-3">
          {setActiveTab && (
            <button
              onClick={() => setActiveTab("jobs")}
              className="flex items-center gap-2 rounded-xl bg-[#384959] px-5 py-2.5 text-sm font-semibold text-white hover:bg-[#2d3a47] transition"
            >
              <Search size={16} /> Browse Jobs
            </button>
          )}
          <button
            onClick={() => openForm("workspace")}
            className="flex items-center gap-2 rounded-xl bg-[#384959] px-5 py-2.5 text-sm font-semibold text-white hover:bg-[#2d3a47] transition"
          >
            <Plus size={16} /> Paste JD
          </button>
          <button
            onClick={() => openForm("manual")}
            className="flex items-center gap-2 rounded-xl border border-[#BDDDFC]/30 px-5 py-2.5 text-sm font-medium text-[#384959] hover:bg-[#f0f4f8] transition"
          >
            <Plus size={16} /> Add Manually
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {(error || loadError) && !showForm && (
        <div className="bg-red-50 border border-red-200 text-red-700 text-sm rounded-lg p-3 flex items-center justify-between">
          <div className="flex items-center gap-2"><AlertCircle size={14} className="flex-shrink-0" />{error || loadError}</div>
          {error ? (
            <button onClick={() => setError("")} className="text-red-400 hover:text-red-600"><X size={14} /></button>
          ) : (
            <button onClick={() => refreshJobs()} className="font-medium text-red-800 hover:text-red-900">Retry</button>
          )}
        </div>
      )}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 xl:grid-cols-6">
        {[
          { key: "submitted", label: "Submitted", value: stats.submitted, bg: "bg-[#f0f4f8]" },
          { key: "interview", label: "Interview", value: stats.interview, bg: "bg-[#BDDDFC]/15" },
          { key: "offer", label: "Offer", value: stats.offer, bg: "bg-green-50" },
          { key: "rejected", label: "Rejected", value: stats.rejected, bg: "bg-red-50" },
          { key: "withdrawn", label: "Withdrawn", value: stats.withdrawn, bg: "bg-[#f0f4f8]" },
          { key: "no_response", label: "No Response", value: stats.noResponse, bg: "bg-[#f0f4f8]" },
        ].map((s) => (
          <div key={s.key} className={`${s.bg} rounded-xl p-4 text-center`} data-outcome-count={s.key}>
            <div className="text-2xl font-bold text-[#384959]">{s.value}</div>
            <div className="text-xs text-[#6A89A7] mt-1">{s.label}</div>
          </div>
        ))}
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex items-center gap-2">
            <Filter size={14} className="text-[#6A89A7]" />
            <select value={filterStatus} onChange={(e) => setFilterStatus(e.target.value)} className="text-sm border border-[#BDDDFC]/30 rounded-lg px-3 py-1.5 bg-white">
              <option value="all">All statuses</option>
              {Object.entries(STATUS_CONFIG).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
            </select>
          </div>
          <div className="inline-flex rounded-lg border border-[#BDDDFC]/30 bg-white p-0.5 text-sm">
            <button
              type="button"
              onClick={() => setViewMode("table")}
              className={`rounded-md px-3 py-1.5 ${viewMode === "table" ? "bg-[#384959] text-white" : "text-[#6A89A7] hover:text-[#384959]"}`}
            >
              Table
            </button>
            <button
              type="button"
              onClick={() => setViewMode("board")}
              className={`rounded-md px-3 py-1.5 ${viewMode === "board" ? "bg-[#384959] text-white" : "text-[#6A89A7] hover:text-[#384959]"}`}
            >
              Board
            </button>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={handleExport} className="flex items-center gap-2 border border-[#BDDDFC]/30 text-[#6A89A7] px-4 py-2 rounded-lg text-sm font-medium hover:bg-[#f0f4f8] transition">
            <Download size={14} /> Export CSV
          </button>
          <button onClick={() => refreshJobs()} className="flex items-center gap-2 border border-[#BDDDFC]/30 text-[#6A89A7] px-3 py-2 rounded-lg text-sm hover:bg-[#f0f4f8] transition">
            <RefreshCw size={14} />
          </button>
          <button onClick={() => openForm("workspace")}
            className="flex items-center gap-2 border border-[#BDDDFC]/30 text-[#384959] px-4 py-2 rounded-lg text-sm font-medium hover:bg-[#f0f4f8] transition">
            <Plus size={16} /> Paste JD
          </button>
          <button onClick={() => openForm("manual")}
            className="flex items-center gap-2 bg-[#384959] text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-[#2d3a47] transition">
            <Plus size={16} /> Add
          </button>
        </div>
      </div>

      {showForm && (
        <div className="bg-white border border-[#BDDDFC]/30 rounded-xl p-5 space-y-4 shadow-sm">
          <div className="flex justify-between items-center">
            <h3 className="font-semibold text-[#384959]">
              {editingId ? "Edit" : formMode === "workspace" ? "New Workspace" : "New"} Application
            </h3>
            <button onClick={resetForm} className="text-[#6A89A7] hover:text-[#384959]"><X size={18} /></button>
          </div>
          {error && <div className="bg-red-50 border border-red-200 text-red-700 text-sm rounded-lg p-3">{error}</div>}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <input placeholder="Company *" value={form.company} onChange={(e) => setForm({ ...form, company: e.target.value })} className="border border-[#BDDDFC]/30 rounded-lg px-3 py-2 text-sm" />
            <input placeholder="Role *" value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })} className="border border-[#BDDDFC]/30 rounded-lg px-3 py-2 text-sm" />
            <div>
              <label className="text-xs text-[#6A89A7] mb-1 block">Applied</label>
              <input type="date" value={form.date_applied} onChange={(e) => setForm({ ...form, date_applied: e.target.value })} className="border border-[#BDDDFC]/30 rounded-lg px-3 py-2 text-sm w-full" />
            </div>
            <select value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value })} className="border border-[#BDDDFC]/30 rounded-lg px-3 py-2 text-sm">
              {Object.entries(STATUS_CONFIG).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
            </select>
            <select value={form.source} onChange={(e) => setForm({ ...form, source: e.target.value })} className="border border-[#BDDDFC]/30 rounded-lg px-3 py-2 text-sm">
              {SG_JOB_PORTALS.map((p) => <option key={p.key} value={p.name}>{p.name}</option>)}
              <option value="Referral">Referral</option>
              <option value="Other">Other</option>
            </select>
            <div>
              <label className="text-xs text-[#6A89A7] mb-1 block">Follow-up</label>
              <input type="date" value={form.follow_up_date || ""} onChange={(e) => setForm({ ...form, follow_up_date: e.target.value })} className="border border-[#BDDDFC]/30 rounded-lg px-3 py-2 text-sm w-full" />
            </div>
          </div>
          {(formMode === "workspace" || form.job_description) && (
            <>
              <input
                placeholder="Source URL"
                value={form.source_url}
                onChange={(e) => setForm({ ...form, source_url: e.target.value })}
                className="border border-[#BDDDFC]/30 rounded-lg px-3 py-2 text-sm w-full"
              />
              <textarea
                placeholder="Paste job description *"
                value={form.job_description}
                onChange={(e) => setForm({ ...form, job_description: e.target.value })}
                className="border border-[#BDDDFC]/30 rounded-lg px-3 py-2 text-sm w-full"
                rows={6}
              />
            </>
          )}
          <textarea placeholder="Notes" value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} className="border border-[#BDDDFC]/30 rounded-lg px-3 py-2 text-sm w-full" rows={2} />
          <button onClick={handleSave} disabled={saving || !form.company || !form.role}
            className="flex items-center gap-2 bg-[#384959] text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-[#2d3a47] disabled:opacity-40 transition">
            {saving ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
            {editingId ? "Update" : "Save"}
          </button>
        </div>
      )}

      {(workspaceLoading || workspace || workspaceError) && (
        <div className="bg-white border border-[#BDDDFC]/30 rounded-xl p-5 space-y-4 shadow-sm">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <h3 className="font-semibold text-[#384959]">Application Workspace</h3>
              {workspace && (
                <p className="text-sm text-[#6A89A7]">{workspace.title} at {workspace.company}</p>
              )}
            </div>
            <div className="flex w-full items-center gap-2 sm:w-auto">
              {workspace && (
                <button
                  type="button"
                  onClick={runWorkspaceAgentReview}
                  disabled={workspaceAgentLoading}
                  className="flex flex-1 items-center justify-center gap-2 rounded-lg bg-[#384959] px-3 py-2 text-xs font-medium text-white transition hover:bg-[#2d3a47] disabled:opacity-50 sm:flex-none"
                >
                  {workspaceAgentLoading ? <Loader2 size={13} className="animate-spin" /> : <Search size={13} />}
                  {workspaceAgentLoading ? "Reviewing..." : agentReview ? "Run review again" : "Run Deep Agent review"}
                </button>
              )}
              <button onClick={() => { setWorkspace(null); setWorkspaceError(""); setWorkspaceAgentError(""); }} className="text-[#6A89A7] hover:text-[#384959]"><X size={18} /></button>
            </div>
          </div>
          {workspaceLoading && (
            <div className="flex items-center gap-2 text-sm text-[#6A89A7]">
              <Loader2 size={14} className="animate-spin" /> Loading workspace...
            </div>
          )}
          {workspaceError && (
            <div className="bg-red-50 border border-red-200 text-red-700 text-sm rounded-lg p-3">{workspaceError}</div>
          )}
          {workspaceAgentLoading && (
            <div className="flex items-start gap-3 rounded-lg border border-[#BDDDFC]/30 bg-[#f0f4f8] p-3 text-sm text-[#384959]" role="status">
              <Loader2 size={16} className="mt-0.5 shrink-0 animate-spin text-[#6A89A7]" />
              <div>
                <div className="font-medium">Deep Agent is reviewing your evidence and role fit.</div>
                <div className="mt-1 text-xs text-[#6A89A7]">This usually takes 20–40 seconds. You will review every proposed edit before anything changes.</div>
              </div>
            </div>
          )}
          {workspaceAgentError && (
            <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
              {workspaceAgentError}
              {workspaceAgentError.startsWith("Save a resume version") && (
                <button type="button" onClick={() => setActiveTab("resume")} className="ml-2 font-medium underline">Open Resume</button>
              )}
            </div>
          )}
          {workspace && (
            <>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 text-sm">
                <div>
                  <div className="text-xs text-[#6A89A7]">Status</div>
                  <StatusBadge status={workspace.status} />
                </div>
                <div>
                  <div className="text-xs text-[#6A89A7]">Resume context</div>
                  <div className="text-[#384959]">
                    {workspace.resume_version_id ? `Version #${workspace.resume_version_id}` : "No resume linked yet"}
                  </div>
                </div>
                <div>
                  <div className="text-xs text-[#6A89A7]">Source</div>
                  <div className="text-[#384959] break-all">{workspace.source_url || workspace.source || "Manual"}</div>
                </div>
              </div>
              {(workspace.follow_up_date || workspace.notes) && (
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 text-sm">
                  <div className="rounded-lg border border-[#BDDDFC]/30 p-3">
                    <div className="text-xs font-semibold uppercase tracking-[0.14em] text-[#6A89A7]">Follow-up</div>
                    <p className="mt-2 text-[#384959]">{workspace.follow_up_date || "No follow-up date set."}</p>
                  </div>
                  <div className="rounded-lg border border-[#BDDDFC]/30 p-3">
                    <div className="text-xs font-semibold uppercase tracking-[0.14em] text-[#6A89A7]">Notes</div>
                    <p className="mt-2 whitespace-pre-wrap text-[#384959]">{workspace.notes || "No notes saved."}</p>
                  </div>
                </div>
              )}
              <div>
                <div className="text-xs text-[#6A89A7] mb-1">Job description</div>
                <p className="whitespace-pre-wrap rounded-lg bg-[#f0f4f8] p-3 text-sm text-[#384959]">
                  {workspace.job_description || "No job description saved."}
                </p>
              </div>
              {recruitmentPipeline && (
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-3 text-sm">
                  <div className="rounded-lg border border-[#BDDDFC]/30 p-3 sm:col-span-2">
                    <div className="text-xs font-semibold uppercase tracking-[0.14em] text-[#6A89A7]">Next action</div>
                    <p className="mt-2 text-[#384959]">{recruitmentPipeline.next_action?.label || "Review this application"}</p>
                  </div>
                  <div className="rounded-lg border border-[#BDDDFC]/30 p-3">
                    <div className="text-xs font-semibold uppercase tracking-[0.14em] text-[#6A89A7]">Fit evidence</div>
                    <p className="mt-2 text-[#384959]">
                      {recruitmentPipeline.fit_evidence?.matched?.length || 0} matched · {recruitmentPipeline.fit_evidence?.stretch?.length || 0} stretch · {recruitmentPipeline.fit_evidence?.missing?.length || 0} missing
                    </p>
                  </div>
                </div>
              )}
              <section aria-labelledby="application-research-title" className="rounded-xl border border-[#88BDF2]/60 bg-[#f7fafc] p-4">
                <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                  <div>
                    <h4 id="application-research-title" className="font-semibold text-[#384959]">Role research, interview prep, and compensation</h4>
                    <p className="mt-1 text-xs text-[#6A89A7]">
                      Current public postings and official MOM wage definitions stay attributable and separate.
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={buildResearchPack}
                    disabled={researchLoading}
                    className="flex items-center justify-center gap-2 rounded-lg bg-[#384959] px-3 py-2 text-xs font-medium text-white disabled:opacity-40"
                  >
                    {researchLoading ? <Loader2 size={12} className="animate-spin" /> : <Search size={12} />}
                    {researchLoading ? "Checking sources..." : applicationResearch ? "Refresh research" : "Build research pack"}
                  </button>
                </div>
                {researchError && <div className="mt-3 rounded-lg border border-red-200 bg-red-50 p-3 text-xs text-red-700">{researchError}</div>}
                {applicationResearch && (
                  <div className="mt-4 space-y-4 text-sm">
                    <div className="flex flex-wrap items-center gap-2 text-xs">
                      <span className="rounded-full bg-white px-2 py-1 font-medium text-[#384959]">Status: {applicationResearch.status.replaceAll("_", " ")}</span>
                      <span className="rounded-full border border-[#BDDDFC]/60 px-2 py-1 text-[#6A89A7]">
                        Evidence: {roleCompanyBrief?.freshness || "unknown"}
                      </span>
                      {(applicationResearch.source_statuses || []).map((source) => (
                        <span key={source.source} className="rounded-full border border-[#BDDDFC]/60 px-2 py-1 text-[#6A89A7]">
                          {source.source.replaceAll("_", " ")}: {source.status.replaceAll("_", " ")}
                        </span>
                      ))}
                    </div>
                    {(applicationResearch.source_statuses || []).some((source) => source.detail) && (
                      <ul className="space-y-1 text-xs text-[#6A89A7]">
                        {applicationResearch.source_statuses.filter((source) => source.detail).map((source) => (
                          <li key={`${source.source}-detail`}>{source.source.replaceAll("_", " ")}: {source.detail}</li>
                        ))}
                      </ul>
                    )}
                    <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
                      <div className="rounded-lg border border-[#BDDDFC]/30 bg-white p-3">
                        <div className="text-xs font-semibold uppercase tracking-[0.14em] text-[#6A89A7]">Role and company brief</div>
                        <p className="mt-2 text-[#384959]">
                          {roleCompanyBrief?.company?.current_posting_count || 0} current company posting(s); {(roleCompanyBrief?.role?.comparable_titles || []).length} comparable title(s).
                        </p>
                        {(roleCompanyBrief?.company?.observed_industries || []).length > 0 && (
                          <p className="mt-1 text-xs text-[#6A89A7]">Observed context: {roleCompanyBrief.company.observed_industries.join(" · ")}</p>
                        )}
                        {(roleCompanyBrief?.role?.comparable_titles || []).length > 0 && (
                          <ul className="mt-3 space-y-1 text-xs text-[#384959]">
                            {roleCompanyBrief.role.comparable_titles.map((item) => (
                              <li key={`${item.company}-${item.title}`}>Comparable: {item.title} at {item.company}</li>
                            ))}
                          </ul>
                        )}
                        <div className="mt-3 flex flex-wrap gap-1.5">
                          {(roleCompanyBrief?.role?.ats_terms || []).map((term) => (
                            <span key={term.term} className="rounded-full bg-[#f0f4f8] px-2 py-1 text-xs text-[#384959]" title={`${term.confidence} confidence, ${term.observed_in_postings} posting(s)`}>
                              {term.term}
                            </span>
                          ))}
                        </div>
                        <div className="mt-3 space-y-1 text-xs">
                          {(roleCompanyBrief?.sources || []).filter((source) => source.url).slice(0, RESEARCH_SOURCE_DISPLAY_LIMIT).map((source, index) => (
                            <a key={`${source.url}-${index}`} href={source.url} target="_blank" rel="noreferrer" className="block break-all text-[#2f6f9f] hover:underline">
                              {source.publisher || source.source_type} · {source.confidence} · {source.freshness}
                            </a>
                          ))}
                        </div>
                      </div>
                      <div className="rounded-lg border border-[#BDDDFC]/30 bg-white p-3">
                        <div className="text-xs font-semibold uppercase tracking-[0.14em] text-[#6A89A7]">Compensation observations</div>
                        <p className="mt-2 text-xs text-[#6A89A7]">{compensationBrief?.comparison_rule}</p>
                        <p className="mt-1 text-xs font-medium text-[#6A89A7]">
                          Coverage: {(compensationBrief?.comparison_state || "valid_empty").replaceAll("_", " ")}
                        </p>
                        <div className="mt-3 space-y-3">
                          {(compensationBrief?.observations || []).map((observation, index) => (
                            <div key={`${observation.kind}-${index}`} className="text-[#384959]">
                              <div className="font-medium">{observation.kind.replaceAll("_", " ")}</div>
                              <div className="mt-1 text-xs">{compensationObservationLabel(observation)}</div>
                              <div className="mt-1 text-xs text-[#6A89A7]">
                                {observation.occupation || observation.definition || ""}{observation.data_date ? ` · ${observation.data_date}` : ""}
                              </div>
                              {observation.source_url && (
                                <a href={observation.source_url} target="_blank" rel="noreferrer" className="mt-1 inline-block text-xs text-[#2f6f9f] hover:underline">View source</a>
                              )}
                            </div>
                          ))}
                          {!(compensationBrief?.observations || []).length && <p className="text-xs text-[#6A89A7]">No compatible compensation observation was available.</p>}
                        </div>
                        {(compensationBrief?.recruiter_guide_leads || []).length > 0 && (
                          <div className="mt-4 border-t border-[#BDDDFC]/30 pt-3 text-xs">
                            <div className="font-medium text-[#384959]">Public recruiter-guide leads</div>
                            {(compensationBrief.recruiter_guide_leads || []).map((source) => (
                              <a key={source.source_url} href={source.source_url} target="_blank" rel="noreferrer" className="mt-2 block text-[#2f6f9f] hover:underline">
                                {source.publisher} · {source.publication_date} · {source.status.replaceAll("_", " ")}
                                <span className="block text-[#6A89A7] no-underline">{source.evidence_note}</span>
                              </a>
                            ))}
                          </div>
                        )}
                      </div>
                    </div>
                    <div className="rounded-lg border border-[#BDDDFC]/30 bg-white p-3">
                      <div className="text-xs font-semibold uppercase tracking-[0.14em] text-[#6A89A7]">Interview preparation</div>
                      <p className="mt-2 text-xs text-[#6A89A7]">
                        {interviewPack?.confidence_note} Source state: {(interviewPack?.source_state || "valid_empty").replaceAll("_", " ")}.
                        Answer formats: {(interviewPack?.answer_formats || []).join(" / ") || "none"}.
                      </p>
                      <div className="mt-3 grid grid-cols-1 gap-3 lg:grid-cols-2">
                        {(interviewPack?.questions || []).map((item, index) => (
                          <details key={`${item.cluster}-${index}`} className="group rounded-lg bg-[#f7fafc] p-3">
                            <summary className="cursor-pointer list-none text-[#384959]">
                              <span className="block text-xs font-medium uppercase text-[#6A89A7]">{item.cluster.replaceAll("_", " ")} · {item.confidence}</span>
                              <span className="mt-1 block pr-5">{item.question}</span>
                              <span className="mt-1 block text-xs text-[#2f6f9f] group-open:hidden">Show evidence and answer scaffold</span>
                            </summary>
                            <p className="mt-3 text-xs text-[#6A89A7]">
                              {item.answer_scaffold?.evidence_quote || (item.answer_scaffold?.status === "missing_evidence" ? "Missing evidence: confirm a real example first." : "Candidate input required.")}
                            </p>
                            {(item.answer_scaffold?.steps || []).length > 0 && (
                              <ol className="mt-2 list-decimal space-y-1 pl-4 text-xs text-[#6A89A7]">
                                {item.answer_scaffold.steps.map((step) => <li key={step}>{step}</li>)}
                              </ol>
                            )}
                            {(item.sources || []).filter((source) => source.url).map((source) => (
                              <a key={source.url} href={source.url} target="_blank" rel="noreferrer" className="mt-2 block text-xs text-[#2f6f9f] hover:underline">
                                {source.source_type.replaceAll("_", " ")} · retrieved {formatResearchDate(source.retrieved_at)} · {source.evidence_note}
                              </a>
                            ))}
                          </details>
                        ))}
                      </div>
                    </div>
                  </div>
                )}
                <form onSubmit={rehearseNegotiation} className="mt-4 rounded-lg border border-[#BDDDFC]/30 bg-white p-3">
                  <div className="text-xs font-semibold uppercase tracking-[0.14em] text-[#6A89A7]">Private negotiation rehearsal</div>
                  <p className="mt-2 text-xs text-[#6A89A7]">Your scenario and authorised evidence are sent to the configured AI coach and saved on this application, but are not copied into metadata telemetry. Your walk-away point is not sent to the coach. One priority per line.</p>
                  <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2">
                    <textarea value={negotiationPriorities} onChange={(event) => setNegotiationPriorities(event.target.value)} placeholder="Priorities\nRole scope\nBase salary" rows={3} className="rounded-lg border border-[#BDDDFC]/30 px-3 py-2 text-xs text-[#384959]" />
                    <input value={walkAwayPoint} onChange={(event) => setWalkAwayPoint(event.target.value)} placeholder="Private walk-away point (optional)" className="rounded-lg border border-[#BDDDFC]/30 px-3 py-2 text-xs text-[#384959]" />
                  </div>
                  <div className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-3">
                    <input value={authorizedEvidenceLabel} onChange={(event) => setAuthorizedEvidenceLabel(event.target.value)} placeholder="Authorized evidence label" className="rounded-lg border border-[#BDDDFC]/30 px-3 py-2 text-xs text-[#384959]" />
                    <input value={authorizedEvidenceValue} onChange={(event) => setAuthorizedEvidenceValue(event.target.value)} placeholder="Observed value" className="rounded-lg border border-[#BDDDFC]/30 px-3 py-2 text-xs text-[#384959]" />
                    <input value={authorizedEvidenceDefinition} onChange={(event) => setAuthorizedEvidenceDefinition(event.target.value)} placeholder="Definition / package basis" className="rounded-lg border border-[#BDDDFC]/30 px-3 py-2 text-xs text-[#384959]" />
                    <input type="url" value={authorizedEvidenceSourceUrl} onChange={(event) => setAuthorizedEvidenceSourceUrl(event.target.value)} placeholder="Authorized source URL (optional)" className="rounded-lg border border-[#BDDDFC]/30 px-3 py-2 text-xs text-[#384959]" />
                    <label className="flex items-center gap-2 rounded-lg border border-[#BDDDFC]/30 px-3 py-2 text-xs text-[#6A89A7]">
                      Evidence date
                      <input type="date" value={authorizedEvidenceDataDate} onInput={(event) => setAuthorizedEvidenceDataDate(event.currentTarget.value)} className="min-w-0 flex-1 text-[#384959]" />
                    </label>
                  </div>
                  <textarea value={negotiationScenario} onChange={(event) => setNegotiationScenario(event.target.value)} placeholder="What did the recruiter or hiring manager say?" rows={3} className="mt-2 w-full rounded-lg border border-[#BDDDFC]/30 px-3 py-2 text-xs text-[#384959]" />
                  {negotiationError && <div className="mt-2 text-xs text-red-600">{negotiationError}</div>}
                  <button type="submit" disabled={negotiationLoading || !negotiationScenario.trim() || !negotiationPriorities.trim()} className="mt-2 flex items-center gap-2 rounded-lg border border-[#BDDDFC] px-3 py-2 text-xs font-medium text-[#384959] disabled:opacity-40">
                    {negotiationLoading && <Loader2 size={12} className="animate-spin" />}
                    Save and rehearse
                  </button>
                  {(negotiation?.rounds || []).length > 0 && (
                    <div className="mt-4 space-y-3">
                      {negotiation.rounds.slice(-NEGOTIATION_ROUND_DISPLAY_LIMIT).map((round, index) => (
                        <div key={`${round.created_at}-${index}`} className="rounded-lg bg-[#f7fafc] p-3 text-xs">
                          <div className="font-medium text-[#384959]">Scenario: {round.scenario}</div>
                          <p className="mt-2 text-[#6A89A7]">{round.coach_response.opening}</p>
                          <p className="mt-2 text-[#6A89A7]">{round.coach_response.walk_away_guidance}</p>
                          {(round.coach_response.anchor_options || []).map((anchor, anchorIndex) => (
                            <div key={`${anchor.kind}-${anchorIndex}`} className="mt-2 rounded border border-[#BDDDFC]/30 p-2 text-[#6A89A7]">
                              <span className="font-medium text-[#384959]">{anchor.label}: </span>
                              {negotiationAnchorLabel(anchor)} · {anchor.definition || "definition unavailable"}
                              <span className="block">{anchor.source_type || "source unknown"} · {anchor.data_date || "data date unavailable"}</span>
                              {anchor.source_url && <a href={anchor.source_url} target="_blank" rel="noreferrer" className="mt-1 block text-[#2f6f9f] hover:underline">View anchor source</a>}
                            </div>
                          ))}
                          <ul className="mt-2 list-disc space-y-1 pl-4 text-[#6A89A7]">
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
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 text-sm">
                <div className="rounded-lg border border-[#BDDDFC]/30 p-3">
                  <div className="text-xs font-semibold uppercase tracking-[0.14em] text-[#6A89A7]">Contacts</div>
                  {workspaceContacts.length ? workspaceContacts.map((contact, index) => (
                    <div key={`${contact.name || "contact"}-${index}`} className="mt-2 text-[#384959]">
                      {contact.name || contact.label || "Contact"}{contact.details ? ` · ${contact.details}` : ""}
                    </div>
                  )) : <p className="mt-2 text-[#6A89A7]">No contacts saved yet.</p>}
                </div>
                <div className="rounded-lg border border-[#BDDDFC]/30 p-3">
                  <div className="text-xs font-semibold uppercase tracking-[0.14em] text-[#6A89A7]">Application activity</div>
                  {workspaceActivity.length ? workspaceActivity.map((item, index) => (
                    <div key={`${item.action || item.type || "activity"}-${index}`} className="mt-2 flex justify-between gap-2 text-[#384959]">
                      <span>{String(item.action || item.type || "updated").replaceAll("_", " ")}</span>
                      <span className="text-xs text-[#6A89A7]">{item.recorded_at ? new Date(item.recorded_at).toLocaleDateString() : ""}</span>
                    </div>
                  )) : <p className="mt-2 text-[#6A89A7]">No application activity recorded yet.</p>}
                </div>
              </div>
              <div>
                <div className="text-xs text-[#6A89A7] mb-2">Stage history</div>
                <div className="space-y-2">
                  {(workspace.stage_history || []).length === 0 && (
                    <div className="rounded-lg border border-[#BDDDFC]/30 px-3 py-2 text-sm text-[#6A89A7]">
                      No stage history recorded yet.
                    </div>
                  )}
                  {(workspace.stage_history || []).map((event, index) => (
                    <div key={`${event.stage}-${index}`} className="flex items-center justify-between rounded-lg border border-[#BDDDFC]/30 px-3 py-2 text-sm">
                      <span className="font-medium text-[#384959]">{STATUS_CONFIG[event.stage]?.label || event.stage}</span>
                      <span className="text-[#6A89A7]">{event.date}</span>
                    </div>
                  ))}
                </div>
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-sm">
                {debateSummary ? (
                  <div className="rounded-lg border border-[#BDDDFC]/30 p-3 text-[#384959]">
                    <div className="text-xs font-semibold uppercase tracking-[0.14em] text-[#6A89A7]">Debate summary</div>
                    <p className="mt-2 text-sm">{debateSummary.final_recommendation}</p>
                    <div className="mt-3 flex flex-wrap gap-1.5">
                      {(Array.isArray(debateSummary.roles) ? debateSummary.roles : []).map((role) => (
                        <span key={role} className="rounded-full bg-[#f0f4f8] px-2 py-1 text-xs text-[#384959]">
                          {role}
                        </span>
                      ))}
                    </div>
                    {(Array.isArray(debateSummary.key_disagreements) ? debateSummary.key_disagreements : []).length > 0 && (
                      <ul className="mt-3 list-disc space-y-1 pl-4 text-xs text-[#6A89A7]">
                        {debateSummary.key_disagreements.map((item) => (
                          <li key={item}>{item}</li>
                        ))}
                      </ul>
                    )}
                    <div className="mt-3 text-xs text-[#6A89A7]">
                      Confidence: {debateSummary.confidence || "unknown"}
                      {debateSummary.trace_id ? `, trace ID: ${debateSummary.trace_id}` : ""}
                    </div>
                  </div>
                ) : (
                  <div className="rounded-lg border border-[#BDDDFC]/30 p-3 text-[#6A89A7]">Agent review not run yet.</div>
                )}
                <div className="rounded-lg border border-[#BDDDFC]/30 p-3 text-[#384959]">
                  <div className="text-xs font-semibold uppercase tracking-[0.14em] text-[#6A89A7]">Submitted resume</div>
                  {submittedResume ? (
                    <div className="mt-2 space-y-1 text-sm">
                      <div>{submittedResume.filename}</div>
                      <div className="text-xs text-[#6A89A7]">
                        {submittedResume.submitted_date} - {submittedResume.word_count || 0} words
                      </div>
                      {submittedResume.notes && <div className="text-xs text-[#6A89A7]">{submittedResume.notes}</div>}
                    </div>
                  ) : (
                    <div className="mt-2 text-sm text-[#6A89A7]">No submitted resume recorded yet.</div>
                  )}
                  <div className="mt-3 space-y-2">
                    <input
                      type="file"
                      accept=".pdf,.docx"
                      onChange={(event) => setSubmittedFile(event.target.files?.[0] || null)}
                      className="w-full text-xs text-[#6A89A7]"
                    />
                    <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                      <input
                        type="date"
                        value={submittedDate}
                        onChange={(event) => setSubmittedDate(event.target.value)}
                        className="rounded-lg border border-[#BDDDFC]/30 px-3 py-2 text-xs text-[#384959]"
                      />
                      <input
                        placeholder="Submitted resume notes"
                        value={submittedNotes}
                        onChange={(event) => setSubmittedNotes(event.target.value)}
                        className="rounded-lg border border-[#BDDDFC]/30 px-3 py-2 text-xs text-[#384959]"
                      />
                    </div>
                    {submittedError && <div className="text-xs text-red-600">{submittedError}</div>}
                    <button
                      type="button"
                      onClick={saveSubmittedResume}
                      disabled={!submittedFile || submittedSaving}
                      className="flex items-center gap-2 rounded-lg bg-[#384959] px-3 py-2 text-xs font-medium text-white transition hover:bg-[#2d3a47] disabled:opacity-40"
                    >
                      {submittedSaving ? <Loader2 size={12} className="animate-spin" /> : <FileText size={12} />}
                      Save submitted resume
                    </button>
                  </div>
                </div>
              </div>
            </>
          )}
        </div>
      )}

      {viewMode === "board" && (
        <DndContext sensors={dndSensors} collisionDetection={closestCorners} onDragEnd={handleBoardDragEnd}>
          <div className="overflow-x-auto pb-1">
            <div
              className="grid gap-3"
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
          {/* Desktop table */}
          <div className="bg-white border border-[#BDDDFC]/30 rounded-xl overflow-hidden hidden sm:block">
            <table className="w-full text-sm">
              <thead className="bg-[#f0f4f8] text-[#6A89A7] text-xs uppercase">
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
              <tbody className="divide-y divide-[#BDDDFC]/15">
                {filtered.length === 0 && (
                  <tr><td colSpan={7} className="text-center py-8 text-[#6A89A7]">No applications tracked yet. Browse jobs and click Track to get started!</td></tr>
                )}
                {filtered.map((job) => (
                  <tr key={job.id} className="hover:bg-[#f0f4f8] transition">
                    <td className="px-4 py-3 font-medium text-[#384959]">{job.company}</td>
                    <td className="px-4 py-3 text-[#6A89A7]">{job.role}</td>
                    <td className="px-4 py-3 text-[#6A89A7]">{job.date_applied}</td>
                    <td className="px-4 py-3 text-[#6A89A7]">{job.source}</td>
                    <td className="px-4 py-3"><StatusBadge status={job.status} /></td>
                    <td className="px-4 py-3 text-[#6A89A7]">{daysBetween(job.date_applied, todayStr())}d</td>
                    <td className="px-4 py-3 text-right">
                      <button aria-label={`Open workspace for ${job.company} ${job.role}`} onClick={() => openWorkspace(job.id)} className="text-[#6A89A7] hover:text-[#384959] mr-2"><FileText size={14} /></button>
                      <button onClick={() => handleEdit(job)} className="text-[#6A89A7] hover:text-[#384959] mr-2"><Edit3 size={14} /></button>
                      <button onClick={() => handleDelete(job.id)} className="text-[#6A89A7] hover:text-red-500"><Trash2 size={14} /></button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Mobile card layout */}
          <div className="sm:hidden space-y-3">
            {filtered.length === 0 && (
              <div className="text-center py-8 text-[#6A89A7] text-sm">No applications tracked yet. Browse jobs and click Track to get started!</div>
            )}
            {filtered.map((job) => (
              <div key={job.id} className="bg-white border border-[#BDDDFC]/30 rounded-xl p-4 space-y-2">
                <div className="flex items-start justify-between">
                  <div>
                    <div className="font-semibold text-[#384959] text-sm">{job.company}</div>
                    <div className="text-sm text-[#6A89A7]">{job.role}</div>
                  </div>
                  <StatusBadge status={job.status} />
                </div>
                <div className="flex items-center gap-3 text-xs text-[#6A89A7]">
                  <span>{job.date_applied}</span>
                  <span>{job.source}</span>
                  <span>{daysBetween(job.date_applied, todayStr())}d ago</span>
                </div>
                {job.notes && <p className="text-xs text-[#6A89A7]">{job.notes}</p>}
                <div className="flex gap-2 pt-1">
                  <button onClick={() => openWorkspace(job.id)} className="text-xs text-[#384959] hover:underline flex items-center gap-1"><FileText size={12} /> Open</button>
                  <button onClick={() => handleEdit(job)} className="text-xs text-[#384959] hover:underline flex items-center gap-1"><Edit3 size={12} /> Edit</button>
                  <button onClick={() => handleDelete(job.id)} className="text-xs text-red-500 hover:underline flex items-center gap-1"><Trash2 size={12} /> Delete</button>
                </div>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
