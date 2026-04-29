import { useState, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { BookOpen, ChevronDown, ChevronUp, Sparkles } from "lucide-react";
import { apiFetch } from "../lib/api.js";
import { TAG_MAP } from "../lib/storyConstants.js";

function TagPill({ tagId, highlighted }) {
  const tag = TAG_MAP[tagId];
  if (!tag) return null;
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-medium ${
        highlighted ? tag.color : "bg-gray-100 text-gray-500 border-gray-200"
      }`}
    >
      {tag.label}
    </span>
  );
}

const STAR_LABELS = [
  { key: "situation", label: "Situation" },
  { key: "task", label: "Task" },
  { key: "action", label: "Action" },
  { key: "result", label: "Result" },
  { key: "reflection", label: "Reflection" },
];

function StoryCard({ story, matchingTags }) {
  const [open, setOpen] = useState(false);
  const hasStarContent = STAR_LABELS.some((f) => story[f.key]);

  return (
    <div className="rounded-xl border border-[#BDDDFC]/20 bg-white">
      <button
        onClick={() => hasStarContent && setOpen((v) => !v)}
        className={`w-full text-left px-4 py-3 flex items-center justify-between gap-3 ${
          hasStarContent ? "cursor-pointer" : "cursor-default"
        }`}
      >
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold text-[#384959] truncate">{story.title}</p>
          {story.project_name && (
            <p className="text-xs text-[#6A89A7] mt-0.5">{story.project_name}</p>
          )}
          <div className="mt-1.5 flex flex-wrap gap-1">
            {(story.tags || []).map((t) => (
              <TagPill key={t} tagId={t} highlighted={matchingTags.has(t)} />
            ))}
          </div>
        </div>
        {hasStarContent && (
          <span className="shrink-0 text-[#6A89A7]">
            {open ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
          </span>
        )}
      </button>

      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden"
          >
            <div className="px-4 pb-3 space-y-2 border-t border-[#BDDDFC]/20 pt-3">
              {STAR_LABELS.filter((f) => story[f.key]).map((f) => (
                <div key={f.key}>
                  <p className="text-[10px] font-bold uppercase tracking-wide text-[#6A89A7]">
                    {f.label}
                  </p>
                  <p className="text-xs text-[#384959] leading-relaxed mt-0.5">
                    {story[f.key]}
                  </p>
                </div>
              ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

export default function InterviewPrep({ jobId, user, onNavigateToStories }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [showOther, setShowOther] = useState(false);

  useEffect(() => {
    if (!user || !jobId) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    setData(null);
    setShowOther(false);

    apiFetch(`/api/stories/suggest/${jobId}`)
      .then((r) => r.json())
      .then((d) => { if (!cancelled) setData(d); })
      .catch((e) => { if (!cancelled) setError(e.message); })
      .finally(() => { if (!cancelled) setLoading(false); });

    return () => { cancelled = true; };
  }, [jobId, user]);

  if (!user) return null;

  return (
    <div className="w-full rounded-xl border border-[#BDDDFC]/25 bg-white px-3 py-2 shadow-sm sm:w-[340px]">
      {/* Header */}
      <div className="flex items-center gap-2">
        <BookOpen size={16} className="text-violet-600" />
        <h3 className="text-sm font-semibold text-[#384959]">Interview prep</h3>
      </div>

      {/* Loading */}
      {loading && (
        <div className="mt-2 flex items-center gap-2 text-xs text-[#6A89A7]">
          <div className="h-4 w-4 animate-spin rounded-full border-2 border-violet-300 border-t-violet-600" />
          Loading suggestions...
        </div>
      )}

      {/* Error */}
      {error && (
        <p className="text-xs text-red-500 py-2">Failed to load suggestions.</p>
      )}

      {/* Empty state: user has no stories */}
      {data && !data.suggestions?.length && !data.other_stories?.length && (
        <div className="mt-2 flex items-center gap-3">
          <Sparkles size={16} className="shrink-0 text-violet-400" />
          <p className="min-w-0 flex-1 text-xs leading-relaxed text-[#6A89A7]">
            Add a few stories to get interview prompts for this role.
          </p>
          <button
            onClick={onNavigateToStories}
            className="shrink-0 rounded-lg bg-violet-600 px-3 py-1.5 text-xs font-semibold text-white transition hover:bg-violet-700 active:scale-[0.98]"
          >
            Add stories
          </button>
        </div>
      )}

      {/* Results */}
      {data && (data.suggestions?.length > 0 || data.other_stories?.length > 0) && (
        <div className="mt-3 space-y-3">
          {/* Detected tags */}
          {data.detected_tags?.length > 0 && (
            <div>
              <p className="text-[10px] font-semibold uppercase tracking-wide text-[#6A89A7] mb-1">
                Behavioral themes detected
              </p>
              <div className="flex flex-wrap gap-1">
                {data.detected_tags.map((t) => (
                  <TagPill key={t} tagId={t} highlighted />
                ))}
              </div>
            </div>
          )}

          {/* Matched stories */}
          {data.suggestions?.length > 0 && (
            <div className="space-y-2">
              <p className="text-[10px] font-semibold uppercase tracking-wide text-[#6A89A7]">
                Top stories to prep
              </p>
              {data.suggestions.map((s) => (
                <StoryCard
                  key={s.story_id}
                  story={s}
                  matchingTags={new Set(s.matching_tags || [])}
                />
              ))}
            </div>
          )}

          {/* Other stories */}
          {data.other_stories?.length > 0 && (
            <div>
              <button
                onClick={() => setShowOther((v) => !v)}
                className="flex items-center gap-1 text-xs text-[#6A89A7] hover:text-[#384959] transition"
              >
                {showOther ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                {data.other_stories.length} other{" "}
                {data.other_stories.length === 1 ? "story" : "stories"}
              </button>
              <AnimatePresence>
                {showOther && (
                  <motion.div
                    initial={{ height: 0, opacity: 0 }}
                    animate={{ height: "auto", opacity: 1 }}
                    exit={{ height: 0, opacity: 0 }}
                    transition={{ duration: 0.2 }}
                    className="overflow-hidden"
                  >
                    <div className="space-y-2 mt-2">
                      {data.other_stories.map((s) => (
                        <StoryCard
                          key={s.story_id}
                          story={s}
                          matchingTags={new Set(s.matching_tags || [])}
                        />
                      ))}
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
