# Resume Workspace — Build Spec for Codex

## Context

Job Hunter SG is a Singapore job aggregator + AI resume coach. The backend is complete with 30+ endpoints. The frontend needs the Resume tab rebuilt from scratch into a VMock-style resume editing workspace.

**Reference**: VMock (used by NUS) — see screenshots in the chat history. Key features: resume rendered as a document with inline annotations, scoring sidebar, click-to-edit, per-bullet AI suggestions.

## Current State

- **Backend**: All endpoints working. See `backend/main.py` for full list.
- **Frontend**: `frontend/src/App.jsx` — single file React + Vite + Tailwind app.
- **Database**: 17,450 SG jobs cached. SQLite locally, PostgreSQL on Railway.
- **AI**: SEA-LION (AI Singapore) with 4 API keys, 36 req/min capacity.
- **No new npm dependencies allowed**. Use only: react, react-dom, lucide-react, tailwindcss.

## What to Build

Replace the current `ResumeTab` component in `App.jsx` with a VMock-style workspace.

### User Flow

```
1. User clicks "Resume" tab
2. Sees upload zone → drops PDF/DOCX (or pastes text)
3. Resume appears as a formatted document (right panel)
4. Score appears immediately in left panel (72/100)
5. Problem areas highlighted inline on the resume (red/amber/green)
6. Left panel shows detailed feedback (Impact, Presentation, Competencies)
7. User clicks a highlighted bullet → left panel shows specific suggestion + "AI Rewrite" button
8. User can directly edit text on the resume (contentEditable)
9. User clicks "AI Improve All" → AI reformats entire resume
10. Re-score to confirm improvement (72 → 85)
11. Choose template at the top → Download DOCX
```

### Layout (Desktop, 1024px+)

```
┌─────────────────────────────────────────────────────────────┐
│  [Upload zone (compact)] [Name] [Email] [Phone] [Location]  │
│  Template: [Classic] [Modern] [SG Pro] [Compact]             │
├──────────────── 35% ────────┬─────────── 65% ───────────────┤
│  FEEDBACK PANEL              │  RESUME DOCUMENT (editable)    │
│                              │                                │
│  Score: 72/100               │  ┌──────────────────────────┐  │
│  ████████░░                  │  │  Haoming Koo             │  │
│                              │  │  email | phone | linkedin│  │
│  Impact: 31/40 ✓             │  │                          │  │
│  Presentation: 11/30 ⚠       │  │  PROFESSIONAL SUMMARY    │  │
│  Competencies: 29/30 ✓       │  │  Program and mfg...      │  │
│                              │  │                          │  │
│  ─────────────               │  │  EXPERIENCE              │  │
│  ▸ Action Oriented ✓         │  │  Micron Technology       │  │
│    "Good use of action       │  │  Program Manager         │  │
│     verbs in your bullets"   │  │  Aug 2022 – Jan 2025     │  │
│                              │  │  • [highlighted] Led...  │  │
│  ▸ Specifics ⚠               │  │  • [green] Orchestr...  │  │
│    "Add quantification to:   │  │                          │  │
│     - professional exp       │  │  EDUCATION               │  │
│     - key projects"          │  │  NUS — MSc, Smart Ind.   │  │
│                              │  │                          │  │
│  ▸ Overusage ⚠               │  │  SKILLS                  │  │
│    "Overused words:          │  │  Python, SQL, AWS...     │  │
│     Led (3x), Integrated     │  └──────────────────────────┘  │
│     (4x)"                    │                                │
│                              │                                │
│  Keywords Matched: 5/8       │                                │
│  Missing: Docker, K8s        │                                │
│                              │                                │
│  [✨ AI Improve All]         │                                │
│  [🔄 Re-Score]               │                                │
│                              │                                │
├──────────────────────────────┴────────────────────────────────┤
│  STICKY BOTTOM: [Score: 72] [Template ▼]  [⬇ Download DOCX]  │
└───────────────────────────────────────────────────────────────┘
```

### Layout (Mobile, <1024px)

- Upload zone: full width
- Profile fields: 2-column grid
- Template selector: 2x2 grid
- Single panel with Edit/Preview toggle tabs
- Edit mode = contentEditable resume document
- Feedback panel = collapsible drawer triggered by tapping the score pill
- Sticky bottom bar always visible

### Backend Endpoints to Use

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/resume/upload` | POST (multipart) | Upload PDF/DOCX → returns `{text, name, email, phone, word_count}` |
| `/api/resume/score` | POST | Score resume → returns `{overall_score, dimensions, keyword_match, top_suggestions, sg_tips}` |
| `/api/ai/coach` | POST | AI review → returns `{coaching, session_id}` |
| `/api/ai/rewrite` | POST | Rewrite bullet → returns `{original, rewritten}` |
| `/api/ai/status` | GET | AI availability → returns `{status, message, wait_seconds}` |
| `/api/resume/format` | POST | AI reformat entire resume → returns `{formatted_resume}` |
| `/api/resume/download` | POST | Generate DOCX → returns binary blob |
| `/api/resume/templates` | GET | List templates → returns `[{id, name, description}]` |

### Resume Document Rendering (Right Panel)

The resume text is stored as plain text in state (`resumeText`). Parse it into sections and render as formatted HTML using `contentEditable`.

**Parser function** `parseResumeToSections(text)`:

```
Input: plain text string
Output: [{type, text, annotation?}, ...]

Types:
- "heading": ALL CAPS lines or known headers (EXPERIENCE, EDUCATION, SKILLS, etc.)
- "subheading": Lines with company | title | dates pattern
- "bullet": Lines starting with -, *, •
- "paragraph": Regular text
- "spacer": Empty lines
```

**Rendering each type**:

- `heading`: `<h2>` with bold, uppercase, bottom border, larger font
- `subheading`: flex row with company bold on left, date on right
- `bullet`: `<li>` in a `<ul>` with disc markers
- `paragraph`: `<p>` with regular text styling

**Template styles** (applied to the container):

| Template | Font | Heading Style |
|----------|------|---------------|
| Classic | Georgia (serif) | ALL CAPS + bottom border |
| Modern | Inter/Calibri (sans) | Left indigo border |
| SG Pro | Calibri (sans) | Bottom border + bold |
| Compact | Arial (sans) | Bold only, tight spacing |

**Page styling**: The resume should look like an A4 page:
```css
bg-white shadow-lg max-w-[700px] mx-auto p-8 min-h-[800px]
```

### Inline Annotations

During the render pass, annotate each bullet:

- **Green** (good): Contains numbers/metrics (`\d+%`, `$\d+`, `\d+ users/team/projects`). Show green left border + ✓ icon.
- **Amber** (warning): Too short (<40 chars), too long (>200 chars), or starts with weak verb ("Responsible for", "Helped", "Assisted"). Show amber left border + ⚠ icon.
- **Red** (needs work): Doesn't start with a recognized action verb. Show red left border + ✗ icon.
- **Blue highlight**: Keywords from the target job description that appear in the resume text.

Each annotation is clickable. Clicking it scrolls the left feedback panel to the relevant suggestion.

### ContentEditable Implementation

Use a `div` with `contentEditable="true"` for the resume document. This allows direct inline editing while maintaining the formatted appearance.

**Key considerations**:
- `onInput` handler: extract `innerText` from the contentEditable div and update `resumeText` state
- Use `dangerouslySetInnerHTML` only with sanitized content (the resume text is already sanitized by the backend)
- Actually safer approach: render parsed sections as React elements with individual contentEditable spans per text node
- Debounce state updates (300ms) to avoid re-renders on every keystroke
- `onBlur` → trigger re-parse and re-render annotations

**Simpler alternative** (if contentEditable is too fragile):
- Keep a textarea but style it with `font-sans text-sm leading-relaxed` (not monospace)
- The formatted preview shows next to it on desktop, or as a toggle on mobile
- Each bullet in the preview has a "click to edit" that focuses the textarea at the right line

### Feedback Panel (Left Side)

**Structure**:

```
1. Overall Score
   - Large number (72/100) with colored circle
   - Progress bar (green/yellow/red)

2. Dimension Scores (collapsible sections)
   - Impact: 31/40
     ▸ Action Oriented: Good Job ✓
     ▸ Specifics: On Track ⚠ — "Include more quantification..."
     ▸ Overusage: Needs Work ✗ — "Overused: Led (3x)..."
     ▸ Avoided Words: Good Job ✓
     ▸ Extracurricular: On Track ⚠
   - Presentation: 11/30
     ▸ Word Count, Bullet Count, Section Count, etc.
   - Competencies: 29/30
     ▸ Analytical, Communication, Leadership, Teamwork, Initiative

3. Keyword Match (if job is targeted)
   - Matched: [Python] [SQL] [AWS] (green pills)
   - Missing: [Docker] [K8s] [CI/CD] (red pills)

4. SG Tips
   - "Mention residency status"
   - "Add SkillsFuture certs"

5. Action Buttons
   - [✨ AI Improve All] → calls POST /api/resume/format
   - [🔄 Re-Score] → calls POST /api/resume/score
   - [💬 AI Coach] → calls POST /api/ai/coach (shows detailed feedback)
```

**Status indicators per item**:
- Score >= 80% of max: green badge "Good Job"
- Score >= 50% of max: amber badge "On Track"
- Score < 50% of max: red badge "Needs Work"

### Scoring Flow

1. **On upload**: Auto-score immediately after text is extracted. Call `POST /api/resume/score`.
2. **On edit**: Do NOT auto-score on every keystroke. Show a "Re-Score" button instead.
3. **After AI Improve**: Auto-score the new text to show improvement.
4. **Before download**: Show the final score. If < 50, show a warning: "Your resume may be filtered by ATS systems."

### AI Session Flow

1. User clicks "AI Coach" → `POST /api/ai/coach` returns `{coaching, session_id}`
2. Coaching text appears in the feedback panel as a collapsible section
3. User clicks "AI Rewrite" on a specific bullet → `POST /api/ai/rewrite` with `{bullet, session_id}` (free within session)
4. Rewritten text shown inline with before/after. User accepts or rejects.
5. User clicks "AI Improve All" → `POST /api/resume/format` → replaces entire resume text

### Template Selector

Position: between upload/profile section and the main workspace panels.

```
4 cards in a single row (grid-cols-4). Each card:
- Mini thumbnail (abstract lines representing a resume layout)
- Template name
- Selected state: indigo border + ring

On mobile: grid-cols-2 (2x2 grid)
```

No horizontal scrolling. All 4 visible at once.

### Download

Sticky bottom bar (always visible):
- Left: Score pill (clickable → scrolls to score panel)
- Center: Template dropdown (desktop only)
- Right: "Download DOCX" button

Download calls `POST /api/resume/download` with `{resume_text, template, name, email, phone, location}` and triggers a file save via blob URL.

### State Variables

```js
// Resume content
const [resumeText, setResumeText] = useState("");
const [profile, setProfile] = useState({name: "", email: "", phone: "", location: "Singapore"});

// Scoring
const [scoreData, setScoreData] = useState(null);
const [scoring, setScoring] = useState(false);

// AI
const [aiStatus, setAiStatus] = useState(null);
const [sessionId, setSessionId] = useState("");
const [coachResponse, setCoachResponse] = useState(null);
const [coachLoading, setCoachLoading] = useState(false);
const [rewriteResults, setRewriteResults] = useState({});
const [rewriteLoading, setRewriteLoading] = useState({});

// Template
const [selectedTemplate, setSelectedTemplate] = useState("modern");
const [templates, setTemplates] = useState([]);

// UI
const [uploading, setUploading] = useState(false);
const [downloading, setDownloading] = useState(false);
const [mobilePanel, setMobilePanel] = useState("edit"); // "edit" | "feedback"
const [selectedBullet, setSelectedBullet] = useState(null); // index of clicked bullet
const [annotationsOn, setAnnotationsOn] = useState(true);
const [error, setError] = useState("");

// Persist in localStorage
// - resumeText
// - profile
// - selectedTemplate
```

### Files to Modify

1. **`frontend/src/App.jsx`**: Replace the `ResumeTab` component (approximately lines 825-1200). Also remove any remaining `ATSTab` references.

2. **`backend/resume_parser.py`**: Already updated with name detection. No changes needed.

3. **`backend/main.py`**: Already has all required endpoints. No changes needed.

### Anti-Patterns to Avoid

- Do NOT use `dangerouslySetInnerHTML` with unsanitized user input
- Do NOT add any new npm dependencies
- Do NOT use monospace font for the resume display
- Do NOT auto-score on every keystroke (too many API calls)
- Do NOT show internal model names ("SEA-LION", "Qwen") in the UI
- Do NOT hardcode any emails, passwords, or API keys
- Do NOT show "scraper", "VMock", or developer jargon in user-facing text
- The resume editor MUST preserve all factual information (names, dates, companies) exactly as-is

### Quality Bar

- Must look professional enough to show to AIAP batch mates at AI Singapore
- The resume document must look like an actual resume, not a code editor
- All API calls must have loading states and error handling
- Mobile must work (this is Singapore — people job hunt on their phones)
- Inline annotations should feel helpful, not overwhelming
