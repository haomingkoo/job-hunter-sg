// Interview Story Bank constants

export const BEHAVIORAL_TAGS = [
  { id: "motivation", label: "Motivation", description: "What drives you, passion for impact", color: "bg-violet-100 text-violet-800 border-violet-200" },
  { id: "proactiveness", label: "Proactiveness", description: "Taking initiative without being told", color: "bg-blue-100 text-blue-800 border-blue-200" },
  { id: "ambiguity", label: "Ambiguity", description: "Owning unstructured problems", color: "bg-amber-100 text-amber-800 border-amber-200" },
  { id: "perseverance", label: "Perseverance", description: "Pushing through blockers and setbacks", color: "bg-rose-100 text-rose-800 border-rose-200" },
  { id: "conflict_resolution", label: "Conflict Resolution", description: "Handling difficult people or situations", color: "bg-orange-100 text-orange-800 border-orange-200" },
  { id: "empathy", label: "Empathy", description: "Understanding others' perspectives", color: "bg-emerald-100 text-emerald-800 border-emerald-200" },
  { id: "growth", label: "Growth", description: "Learning from mistakes, self-awareness", color: "bg-teal-100 text-teal-800 border-teal-200" },
  { id: "communication", label: "Communication", description: "Clarity, cross-functional collaboration", color: "bg-indigo-100 text-indigo-800 border-indigo-200" },
];

export const TAG_MAP = Object.fromEntries(BEHAVIORAL_TAGS.map((t) => [t.id, t]));

export const SENIORITY_OPTIONS = [
  { id: "junior", label: "Junior" },
  { id: "mid", label: "Mid" },
  { id: "senior", label: "Senior" },
  { id: "staff", label: "Staff" },
];

export const STAR_FIELDS = [
  { key: "situation", label: "Situation", placeholder: "Set the scene. What was the context, team, and challenge?" },
  { key: "task", label: "Task", placeholder: "What was your specific responsibility or goal?" },
  { key: "action", label: "Action", placeholder: "What did you do? Be specific about YOUR actions, not the team's." },
  { key: "result", label: "Result", placeholder: "What was the outcome? Use numbers: %, $, time saved, people impacted." },
  { key: "reflection", label: "Reflection", placeholder: "What did you learn? What would you do differently?" },
];

export const BIG_THREE_PROMPTS = [
  {
    title: "Tell Me About Yourself",
    hint: "Your elevator pitch - who you are, what you've done, where you're headed",
    defaultTags: ["motivation", "communication"],
    icon: "User",
  },
  {
    title: "Biggest Impact Project",
    hint: "A time you drove meaningful results with measurable outcomes",
    defaultTags: ["proactiveness", "perseverance"],
    icon: "Trophy",
  },
  {
    title: "Conflict Resolution",
    hint: "How you navigated a tough disagreement or difficult stakeholder",
    defaultTags: ["conflict_resolution", "empathy"],
    icon: "Handshake",
  },
];
