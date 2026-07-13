import { useState } from "react";
import {
  Plus, X, AlertCircle, Filter, RefreshCw,
  Download, Loader2, Edit3, Save, Trash2,
  Briefcase, Search,
} from "lucide-react";
import { API_BASE, apiFetch } from "../lib/api.js";
import { STATUS_CONFIG, SG_JOB_PORTALS } from "../lib/constants.js";
import { todayStr, daysBetween } from "../lib/helpers.js";
import StatusBadge from "./StatusBadge.jsx";

export default function TrackerTab({ jobs, loadError = "", refreshJobs, setActiveTab }) {
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
    active: jobs.filter((j) => ["applied", "screening", "interview", "assessment", "final_round"].includes(j.status)).length,
    offers: jobs.filter((j) => ["offer", "accepted"].includes(j.status)).length,
    closed: jobs.filter((j) => ["rejected", "withdrawn", "no_response"].includes(j.status)).length,
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
            onClick={() => setShowForm(true)}
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
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        {[
          { label: "Total", value: stats.total, bg: "bg-[#f0f4f8]" },
          { label: "Active", value: stats.active, bg: "bg-[#BDDDFC]/15" },
          { label: "Offers", value: stats.offers, bg: "bg-green-50" },
          { label: "Closed", value: stats.closed, bg: "bg-[#f0f4f8]" },
        ].map((s) => (
          <div key={s.label} className={`${s.bg} rounded-xl p-4 text-center`}>
            <div className="text-2xl font-bold text-[#384959]">{s.value}</div>
            <div className="text-xs text-[#6A89A7] mt-1">{s.label}</div>
          </div>
        ))}
      </div>

      <div className="flex justify-between items-center">
        <div className="flex items-center gap-2">
          <Filter size={14} className="text-[#6A89A7]" />
          <select value={filterStatus} onChange={(e) => setFilterStatus(e.target.value)} className="text-sm border border-[#BDDDFC]/30 rounded-lg px-3 py-1.5 bg-white">
            <option value="all">All statuses</option>
            {Object.entries(STATUS_CONFIG).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
          </select>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={handleExport} className="flex items-center gap-2 border border-[#BDDDFC]/30 text-[#6A89A7] px-4 py-2 rounded-lg text-sm font-medium hover:bg-[#f0f4f8] transition">
            <Download size={14} /> Export CSV
          </button>
          <button onClick={() => refreshJobs()} className="flex items-center gap-2 border border-[#BDDDFC]/30 text-[#6A89A7] px-3 py-2 rounded-lg text-sm hover:bg-[#f0f4f8] transition">
            <RefreshCw size={14} />
          </button>
          <button onClick={() => { resetForm(); setShowForm(true); }}
            className="flex items-center gap-2 bg-[#384959] text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-[#2d3a47] transition">
            <Plus size={16} /> Add
          </button>
        </div>
      </div>

      {showForm && (
        <div className="bg-white border border-[#BDDDFC]/30 rounded-xl p-5 space-y-4 shadow-sm">
          <div className="flex justify-between items-center">
            <h3 className="font-semibold text-[#384959]">{editingId ? "Edit" : "New"} Application</h3>
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
          <textarea placeholder="Notes" value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} className="border border-[#BDDDFC]/30 rounded-lg px-3 py-2 text-sm w-full" rows={2} />
          <button onClick={handleSave} disabled={saving || !form.company || !form.role}
            className="flex items-center gap-2 bg-[#384959] text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-[#2d3a47] disabled:opacity-40 transition">
            {saving ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
            {editingId ? "Update" : "Save"}
          </button>
        </div>
      )}

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
              <button onClick={() => handleEdit(job)} className="text-xs text-[#384959] hover:underline flex items-center gap-1"><Edit3 size={12} /> Edit</button>
              <button onClick={() => handleDelete(job.id)} className="text-xs text-red-500 hover:underline flex items-center gap-1"><Trash2 size={12} /> Delete</button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
