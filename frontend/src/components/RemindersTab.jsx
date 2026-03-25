import { useState } from "react";
import { Bell, AlertCircle, X } from "lucide-react";
import { todayStr, daysBetween } from "../lib/helpers.js";
import StatusBadge from "./StatusBadge.jsx";

export default function RemindersTab({ jobs, onUpdateJob }) {
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
