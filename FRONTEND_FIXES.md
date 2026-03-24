# Frontend Fixes — Priority List

## Critical (Resume Workspace)

### 1. Resume preview must look EXACTLY like the DOCX output
- Use the same font, margins, sizes as the DOCX templates in resume_templates.py
- Classic: Times New Roman 11pt, 1" margins
- Modern: Calibri 10pt, 0.6" margins
- Singapore Professional: Calibri 11pt, 0.8" margins
- Compact: Arial 10pt, 0.5" margins
- The preview IS the document — what you see should be what you get in the download

### 2. A4 page format
- Width: 210mm (794px at 96dpi)
- Height: 297mm (1123px) minimum
- Margins should match the template (e.g., 20mm = ~75px)
- Add a subtle page break line if content exceeds one page
- Should look like a sheet of paper on screen

### 3. Bullets still split mid-sentence
- The PDF line-joiner was fixed but user needs to re-upload
- After re-upload, verify bullets show as complete sentences
- The frontend parseResumeToSections() also needs to join lines that are clearly continuations
- Test: "Chaired SteerCo sessions and compliance reviews (RACB, ISO 9001); oversaw US$9M front end travel budget" should be ONE bullet, not two lines

### 4. Font size too small/large
- Check what font size the DOCX templates use and match it
- Body text should be 11-12pt equivalent (14-16px)
- Name should be larger (16-20pt)
- Section headers should be 12-14pt

### 5. Left feedback panel should be sticky
- Add `sticky top-0 self-start max-h-screen overflow-y-auto` to the left panel
- When user scrolls the resume, the feedback panel stays visible
- On mobile, feedback is a collapsible drawer instead

### 6. "AI Rewrite This Bullet" button doesn't work
- Check the onClick handler — it calls apiFetch to /api/ai/rewrite
- May be a state issue — selectedBullet might not have the right text
- Should show loading state, then display the rewritten text

### 7. Verb suggestion pills should be clickable
- When user clicks "Administered", it should replace the first verb in the bullet
- Currently they're just static labels

### 8. Show 3 rewrite options instead of 1
- Call the AI once, ask for 3 different rewrites
- User picks Option A, B, C, or keeps original
- Much better UX than "rewrite → don't like it → rewrite again"

### 9. "Finalize Score" doesn't re-score
- Should call POST /api/resume/score with current resumeText
- Update the score display with new results
- Show before/after comparison (old score → new score)

## Nice to Have

### 10. Before/After view for "AI Improve All"
- Show the original resume side-by-side with AI version
- Highlight changes
- User accepts or reverts

### 11. Smart Editor tab functionality
- What does "Smart Editor" do vs "Resume Feedback"?
- Should be: Feedback = scoring/analysis, Editor = inline editing with AI
