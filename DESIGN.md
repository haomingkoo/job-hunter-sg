# Job Hunter SG design

Expands the kooexperience design core (`~/.agent-memory/design/DESIGN-core.md`). The core wins on conflict.

## Read
People looking for work in Singapore who want current postings and a resume that fits one. They read long job descriptions in daytime sessions, so the theme is light. Mood: a good classifieds page: dense, current, plain. Dial: ENERGY 1 / RHYTHM 1 / MOTION 1.

## Rules
- Results first. The landing page is a search box and the newest real postings. The Jobs screen opens on results, not on a banner.
- Nothing invented. Every count, salary, date and score comes from `/api/jobs` or the user's own data. No sample people, no illustrative scores.
- One primary action per job card ("Tailor resume", shown when the card is open). Everything else is a text button or link.
- Four top-level sections: Jobs, Resume, Applications, Account. Each has at most four sub-pages in a second row.
- Dates for people: "Posted 25 Oct", "Added 25 Oct". Never "scraped", "beta", "API", model names or request quotas.
- Tags are plain text ("Skills: Python, SQL"), not pill rows.

## Tokens
| Token | Value | Use |
|---|---|---|
| paper | `#f0f4f8` | page ground |
| surface | `#ffffff` | cards, header, footer |
| line | `#d3dde7` | card and section borders |
| field | `#6f88a0` | input borders (3:1 on white) |
| ink | `#384959` | text, 9.3:1 on white |
| muted | `#4f6b85` | secondary text, 5.0:1 on paper |
| accent | `#1f5f99` | primary button, links, active tab, focus ring (6.7:1) |
| tint | `#e8f1fa` | selected filter, hover |
Status only: green `#166534` (saved, match), amber `#92400e` on `#fffbeb` (warning), red `#b42318` (error).

- Type: DM Sans throughout. DM Serif Display for the landing H1 only. Sizes 12, 14, 16, 20, 40. `tabular-nums` on salaries, counts and dates.
- Radius 6 for controls, 10 for cards, 16 for dialogs. Shadow only on dialogs and the mobile filter drawer.
- Focus: 2px accent outline, 2px offset, on every interactive element.
- Motion: colour and opacity transitions under 200ms. No entrance animations on lists.
