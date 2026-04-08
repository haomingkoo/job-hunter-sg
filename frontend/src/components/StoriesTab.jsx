import { useState, useEffect, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  BookOpen, Plus, ChevronLeft, Trash2, Pencil,
  User, Trophy, Handshake, Sparkles, Save,
} from "lucide-react";
import { apiFetch } from "../lib/api.js";
import {
  BEHAVIORAL_TAGS, TAG_MAP, SENIORITY_OPTIONS,
  STAR_FIELDS, BIG_THREE_PROMPTS,
} from "../lib/storyConstants.js";

const PROMPT_ICONS = { User, Trophy, Handshake };

function TagPill({ tagId, small }) {
  const tag = TAG_MAP[tagId];
  if (!tag) return null;
  return (
    <span className={`inline-flex items-center rounded-full border px-2 py-0.5 font-medium ${tag.color} ${small ? "text-[10px]" : "text-xs"}`}>
      {tag.label}
    </span>
  );
}

function EmptyState({ onStart }) {
  return (
    <div className="flex flex-col items-center justify-center py-16 px-4">
      <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-violet-100 mb-6">
        <BookOpen size={32} className="text-violet-600" />
      </div>
      <h2 className="text-xl font-bold text-[#384959] text-center">Build Your Interview Story Bank</h2>
      <p className="mt-2 max-w-md text-center text-sm text-[#6A89A7] leading-relaxed">
        Create reusable STAR+R stories that flex across any behavioral interview.
        Start with the Big Three, then expand as you prep for more roles.
      </p>

      <div className="mt-8 grid gap-4 sm:grid-cols-3 max-w-2xl w-full">
        {BIG_THREE_PROMPTS.map((prompt) => {
          const Icon = PROMPT_ICONS[prompt.icon] || Sparkles;
          return (
            <motion.button
              key={prompt.title}
              whileHover={{ y: -2 }}
              onClick={() => onStart(prompt)}
              className="text-left rounded-2xl border-2 border-[#BDDDFC]/30 bg-white p-5 transition-all hover:shadow-md hover:border-violet-300"
            >
              <Icon size={24} className="text-violet-600" />
              <h3 className="mt-3 text-sm font-semibold text-[#384959]">{prompt.title}</h3>
              <p className="mt-1 text-xs text-[#6A89A7] leading-relaxed">{prompt.hint}</p>
              <div className="mt-3 flex flex-wrap gap-1">
                {prompt.defaultTags.map((t) => <TagPill key={t} tagId={t} small />)}
              </div>
            </motion.button>
          );
        })}
      </div>
    </div>
  );
}

function StoryEditor({ story, onSave, onCancel, onDelete, saving }) {
  const [form, setForm] = useState({
    title: story.title || "",
    project_name: story.project_name || "",
    situation: story.situation || "",
    task: story.task || "",
    action: story.action || "",
    result: story.result || "",
    reflection: story.reflection || "",
    tags: story.tags || [],
    seniority: story.seniority || "mid",
  });

  const setField = (key, value) => setForm((prev) => ({ ...prev, [key]: value }));
  const toggleTag = (tagId) => {
    setForm((prev) => ({
      ...prev,
      tags: prev.tags.includes(tagId)
        ? prev.tags.filter((t) => t !== tagId)
        : [...prev.tags, tagId],
    }));
  };

  return (
    <div className="mx-auto max-w-2xl">
      <button
        onClick={onCancel}
        className="mb-4 flex items-center gap-1 text-sm text-[#6A89A7] hover:text-[#384959] transition"
      >
        <ChevronLeft size={16} /> Back to stories
      </button>

      <div className="space-y-5">
        {/* Title + Project */}
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <label className="block text-xs font-semibold uppercase tracking-wide text-[#6A89A7] mb-1">Story Title *</label>
            <input
              value={form.title}
              onChange={(e) => setField("title", e.target.value)}
              placeholder="e.g. Led Fab Yield Turnaround"
              className="w-full rounded-xl border border-[#BDDDFC]/30 bg-white px-4 py-2.5 text-sm text-[#384959] focus:outline-none focus:ring-2 focus:ring-violet-200"
            />
          </div>
          <div>
            <label className="block text-xs font-semibold uppercase tracking-wide text-[#6A89A7] mb-1">Project / Company</label>
            <input
              value={form.project_name}
              onChange={(e) => setField("project_name", e.target.value)}
              placeholder="e.g. Micron Fab 10N"
              className="w-full rounded-xl border border-[#BDDDFC]/30 bg-white px-4 py-2.5 text-sm text-[#384959] focus:outline-none focus:ring-2 focus:ring-violet-200"
            />
          </div>
        </div>

        {/* STAR+R Fields */}
        {STAR_FIELDS.map((field) => (
          <div key={field.key}>
            <label className="block text-xs font-semibold uppercase tracking-wide text-[#6A89A7] mb-1">
              {field.label}
              {field.key === "reflection" && <span className="ml-1 normal-case font-normal">(the +R)</span>}
            </label>
            <textarea
              value={form[field.key]}
              onChange={(e) => setField(field.key, e.target.value)}
              placeholder={field.placeholder}
              rows={3}
              className="w-full resize-none rounded-xl border border-[#BDDDFC]/30 bg-white px-4 py-3 text-sm text-[#384959] leading-relaxed focus:outline-none focus:ring-2 focus:ring-violet-200"
            />
          </div>
        ))}

        {/* Tags */}
        <div>
          <label className="block text-xs font-semibold uppercase tracking-wide text-[#6A89A7] mb-2">Behavioral Tags</label>
          <div className="flex flex-wrap gap-2">
            {BEHAVIORAL_TAGS.map((tag) => {
              const active = form.tags.includes(tag.id);
              return (
                <button
                  key={tag.id}
                  type="button"
                  onClick={() => toggleTag(tag.id)}
                  className={`rounded-full border px-3 py-1.5 text-xs font-medium transition ${
                    active ? tag.color : "border-[#BDDDFC]/30 text-[#6A89A7] bg-white hover:bg-[#f0f4f8]"
                  }`}
                  title={tag.description}
                >
                  {tag.label}
                </button>
              );
            })}
          </div>
        </div>

        {/* Seniority */}
        <div>
          <label className="block text-xs font-semibold uppercase tracking-wide text-[#6A89A7] mb-2">Seniority Level</label>
          <div className="flex gap-2">
            {SENIORITY_OPTIONS.map((opt) => (
              <button
                key={opt.id}
                type="button"
                onClick={() => setField("seniority", opt.id)}
                className={`rounded-full border px-3 py-1.5 text-xs font-medium transition ${
                  form.seniority === opt.id
                    ? "bg-[#384959] text-white border-[#384959]"
                    : "border-[#BDDDFC]/30 text-[#6A89A7] bg-white hover:bg-[#f0f4f8]"
                }`}
              >
                {opt.label}
              </button>
            ))}
          </div>
        </div>

        {/* Actions */}
        <div className="flex items-center gap-3 pt-2">
          <button
            onClick={() => onSave(form)}
            disabled={!form.title.trim() || saving}
            className="flex items-center gap-2 rounded-xl bg-[#384959] px-5 py-2.5 text-sm font-semibold text-white hover:bg-[#2d3a47] disabled:opacity-40 transition"
          >
            <Save size={16} />
            {saving ? "Saving..." : story.id ? "Update Story" : "Save Story"}
          </button>
          <button
            onClick={onCancel}
            className="rounded-xl border border-[#BDDDFC]/30 px-4 py-2.5 text-sm font-medium text-[#6A89A7] hover:bg-[#f0f4f8] transition"
          >
            Cancel
          </button>
          {story.id && (
            <button
              onClick={() => onDelete(story.id)}
              className="ml-auto flex items-center gap-1.5 text-xs text-rose-500 hover:text-rose-700 transition"
            >
              <Trash2 size={14} /> Delete
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

function StoryCard({ story, onClick, onDelete }) {
  const filledFields = STAR_FIELDS.filter((f) => (story[f.key] || "").trim()).length;
  return (
    <motion.div
      whileHover={{ y: -2 }}
      onClick={onClick}
      className="cursor-pointer rounded-2xl border border-[#BDDDFC]/30 bg-white p-5 transition-all hover:shadow-md group"
    >
      <div className="flex items-start justify-between">
        <div className="min-w-0 flex-1">
          <h3 className="text-sm font-semibold text-[#384959] truncate">{story.title}</h3>
          {story.project_name && (
            <p className="mt-0.5 text-xs text-[#6A89A7] truncate">{story.project_name}</p>
          )}
        </div>
        <button
          onClick={(e) => { e.stopPropagation(); onDelete(story.id); }}
          className="ml-2 opacity-0 group-hover:opacity-100 p-1 rounded-lg text-[#6A89A7] hover:text-rose-500 hover:bg-rose-50 transition"
          title="Delete story"
        >
          <Trash2 size={14} />
        </button>
      </div>

      <div className="mt-3 flex flex-wrap gap-1">
        {(story.tags || []).map((t) => <TagPill key={t} tagId={t} small />)}
      </div>

      <div className="mt-3 flex items-center justify-between text-[10px] text-[#6A89A7]">
        <span>{filledFields}/5 STAR+R sections filled</span>
        <span className={`rounded-full border px-1.5 py-0.5 ${
          story.seniority === "senior" || story.seniority === "staff"
            ? "border-amber-200 text-amber-700 bg-amber-50"
            : "border-[#BDDDFC]/30 text-[#6A89A7]"
        }`}>
          {story.seniority}
        </span>
      </div>
    </motion.div>
  );
}

export default function StoriesTab() {
  const [stories, setStories] = useState([]);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(null); // null = list, object = editor
  const [saving, setSaving] = useState(false);
  const [filterTag, setFilterTag] = useState("all");

  const fetchStories = useCallback(async () => {
    try {
      const resp = await apiFetch("/api/stories");
      const data = await resp.json();
      setStories(data);
    } catch {
      // silent
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchStories(); }, [fetchStories]);

  const handleSave = async (form) => {
    setSaving(true);
    try {
      if (editing.id) {
        await apiFetch(`/api/stories/${editing.id}`, {
          method: "PUT",
          body: JSON.stringify(form),
        });
      } else {
        await apiFetch("/api/stories", {
          method: "POST",
          body: JSON.stringify(form),
        });
      }
      await fetchStories();
      setEditing(null);
    } catch {
      // TODO: show error
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (id) => {
    if (!confirm("Delete this story?")) return;
    try {
      await apiFetch(`/api/stories/${id}`, { method: "DELETE" });
      setStories((prev) => prev.filter((s) => s.id !== id));
      if (editing?.id === id) setEditing(null);
    } catch {
      // silent
    }
  };

  const startFromPrompt = (prompt) => {
    setEditing({
      title: prompt.title,
      project_name: "",
      situation: "",
      task: "",
      action: "",
      result: "",
      reflection: "",
      tags: prompt.defaultTags,
      seniority: "mid",
    });
  };

  const filtered = filterTag === "all"
    ? stories
    : stories.filter((s) => (s.tags || []).includes(filterTag));

  if (loading) {
    return (
      <div className="flex items-center justify-center py-24">
        <div className="h-6 w-6 animate-spin rounded-full border-2 border-violet-300 border-t-violet-600" />
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-4xl px-4 py-6">
      <AnimatePresence mode="wait">
        {editing ? (
          <motion.div
            key="editor"
            initial={{ opacity: 0, x: 20 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: -20 }}
            transition={{ duration: 0.2 }}
          >
            <StoryEditor
              story={editing}
              onSave={handleSave}
              onCancel={() => setEditing(null)}
              onDelete={handleDelete}
              saving={saving}
            />
          </motion.div>
        ) : stories.length === 0 ? (
          <motion.div
            key="empty"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
          >
            <EmptyState onStart={startFromPrompt} />
          </motion.div>
        ) : (
          <motion.div
            key="list"
            initial={{ opacity: 0, x: -20 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: 20 }}
            transition={{ duration: 0.2 }}
          >
            {/* Header */}
            <div className="flex items-center justify-between mb-5">
              <div>
                <h2 className="text-lg font-bold text-[#384959]">Interview Story Bank</h2>
                <p className="text-xs text-[#6A89A7]">{stories.length} {stories.length === 1 ? "story" : "stories"} ready for interviews</p>
              </div>
              <button
                onClick={() => setEditing({ tags: [], seniority: "mid" })}
                className="flex items-center gap-1.5 rounded-xl bg-[#384959] px-4 py-2 text-sm font-medium text-white hover:bg-[#2d3a47] transition"
              >
                <Plus size={16} /> New Story
              </button>
            </div>

            {/* Tag filters */}
            <div className="flex flex-wrap gap-1.5 mb-5">
              <button
                onClick={() => setFilterTag("all")}
                className={`rounded-full border px-3 py-1 text-xs font-medium transition ${
                  filterTag === "all" ? "bg-[#384959] text-white border-[#384959]" : "border-[#BDDDFC]/30 text-[#6A89A7] hover:bg-[#f0f4f8]"
                }`}
              >
                All
              </button>
              {BEHAVIORAL_TAGS.map((tag) => (
                <button
                  key={tag.id}
                  onClick={() => setFilterTag(tag.id)}
                  className={`rounded-full border px-3 py-1 text-xs font-medium transition ${
                    filterTag === tag.id ? tag.color : "border-[#BDDDFC]/30 text-[#6A89A7] hover:bg-[#f0f4f8]"
                  }`}
                >
                  {tag.label}
                </button>
              ))}
            </div>

            {/* Story grid */}
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {filtered.map((story) => (
                <StoryCard
                  key={story.id}
                  story={story}
                  onClick={() => setEditing(story)}
                  onDelete={handleDelete}
                />
              ))}
            </div>

            {filtered.length === 0 && (
              <p className="py-12 text-center text-sm text-[#6A89A7]">No stories match this filter.</p>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
