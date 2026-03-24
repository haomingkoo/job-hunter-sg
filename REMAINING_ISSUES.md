# Remaining Issues — Prioritized

## BLOCKING (must fix for launch)

1. **Resume preview formatting** — looks like plain text, not a document. Needs proper font sizes, bold headers, visible bullets, justified text, A4 proportions
2. **Keyword crash fixed but "0 terms matched"** — because no JD is passed. When user clicks "Generate Resume" from a job, the JD must flow into the Resume tab and be used for scoring
3. **"AI Improve All" makes score worse** — needs targeted approach: only rewrite weak bullets, preserve good ones
4. **Finalize Score doesn't re-score** — button exists but doesn't call the API
5. **AI Rewrite shows empty box** — backend returns {options:[]} but frontend reads .rewritten

## HIGH (should fix before sharing with batch mates)

6. **JD should be visible on Resume tab** — show the target job description as a reference panel
7. **Certs still flagged as "Review Opening"** — fix committed but needs refresh/rebuild
8. **Score still shows 0/0 bullets** — backend detects bullets correctly but frontend score is cached/stale
9. **Job description in listings is a wall of text** — needs paragraph breaks, bullet parsing
10. **Left feedback panel should follow scroll** — sticky positioning

## MEDIUM (polish)

11. **3 rewrite options** — backend returns 3 but frontend only shows 1 (or empty)
12. **Verb suggestions not clickable** — the pills should replace the verb on click
13. **Used verbs not sent to AI** — causes verb repetition (multiple "Spearheaded")
14. **Resume preview doesn't change per template** — Modern/Classic/SG Pro look the same

## URGENT ADDITIONS (from user testing)

15. **Templates must reorder sections**:
    - Classic: Summary → Education → Experience → Skills → Certs
    - Modern: Summary → Experience → Skills → Education → Certs
    - SG Pro: Summary → Experience → Education → Skills → Certs
    - Compact: Summary → Experience → Skills → Education
    Currently all templates show same order.

16. **Name styling**: must be 18-20pt, BOLD, centered. Currently too small, left-aligned.

17. **"Professional Summary" not styled as section header** — renders as regular text

18. **Skills breaking across lines**: "AI &" on one line, rest on next. Must wrap at | boundaries

19. **Contact line**: email | phone | linkedin on ONE centered line, 9pt

20. **Too much vertical spacing** — every element has too much gap. Reduce to match real PDF resume

21. **After download: show "Search matching jobs" and "Track application" buttons**

22. **JD should be visible when targeting a job** — show collapsible JD panel on Resume tab

23. **"AI Improve All" should only fix weak bullets**, not rewrite the whole resume
