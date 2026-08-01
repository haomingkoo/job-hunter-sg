"""HTML legal pages for the hosted app.

These pages are practical product notices, not a substitute for legal advice.
"""

from __future__ import annotations

import html


LEGAL_UPDATED = "27 April 2026"


def _page(title: str, body: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{html.escape(title)} - Job Hunter SG</title>
  <style>
    :root {{ color-scheme: light; }}
    body {{
      margin: 0;
      background: #f6f9fc;
      color: #243447;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      line-height: 1.65;
    }}
    main {{
      max-width: 820px;
      margin: 32px auto;
      padding: 28px;
      background: #fff;
      border: 1px solid #dbe7f3;
      border-radius: 12px;
    }}
    h1 {{ margin: 0 0 4px; font-size: 28px; color: #243447; }}
    h2 {{ margin: 28px 0 8px; font-size: 18px; color: #243447; }}
    p, li {{ font-size: 15px; }}
    ul {{ padding-left: 22px; }}
    a {{ color: #2563eb; }}
    .updated {{ margin: 0 0 24px; color: #6a89a7; font-size: 13px; }}
    .notice {{
      margin-top: 22px;
      padding: 14px 16px;
      border: 1px solid #fde68a;
      background: #fffbeb;
      border-radius: 10px;
      color: #854d0e;
      font-size: 14px;
    }}
    @media (max-width: 700px) {{
      main {{ margin: 0; min-height: 100vh; border: 0; border-radius: 0; padding: 22px; }}
    }}
  </style>
</head>
<body><main>{body}</main></body>
</html>"""


def render_terms_html(contact_line: str) -> str:
    contact = html.escape(contact_line)
    body = f"""
<h1>Terms of Service</h1>
<p class="updated">Last updated: {LEGAL_UPDATED}</p>

<p>These Terms apply when you use Job Hunter SG. By creating an account, using the service,
or enabling job alerts, you agree to these Terms and our Privacy Notice.</p>

<h2>1. What This Service Is</h2>
<p>Job Hunter SG helps users search job listings, review resumes,
track applications, view market signals, and receive optional job match alerts. It is not an
employment agency, recruiter, career adviser, financial adviser, legal adviser, or job placement service.</p>

<h2>2. No Guarantees</h2>
<p>Job listings, salary information, matching scores, resume feedback, AI outputs, market insights,
course suggestions, and employer classifications are provided for general information only. They may be
incomplete, delayed, inaccurate, unavailable, or changed by third-party sources without notice.</p>
<p>We do not guarantee interviews, offers, employment outcomes, salary outcomes, employer responses,
job availability, eligibility, or suitability of any role.</p>

<h2>3. User Responsibility</h2>
<p>You are responsible for checking job postings, employer details, application requirements,
visa/work eligibility, salary terms, course details, and all information before relying on it or applying.
You are also responsible for the resumes, cover letters, notes, and other content you submit or generate.</p>

<h2>4. AI and Automated Matching</h2>
<p>The service may use automated extraction, AI models, heuristics, and third-party data. These tools can
make mistakes. You should review all generated or suggested content before using it. Do not submit
sensitive information unless you are comfortable with it being processed to provide the service.</p>

<h2>5. Email Alerts</h2>
<p>Job match alerts are optional and disabled by default. If you enable them, we may email you digests
based on your saved resume, alert preferences, and available job data. You can disable alerts from your
Account page or unsubscribe using the link in an alert email. Alerts are informational and are not job offers.</p>

<h2>6. Third-Party Services and Links</h2>
<p>The service may link to third-party job boards, employers, course providers, AI services, hosting
providers, email providers, and public datasets. We do not control those services and are not responsible
for their content, availability, decisions, fees, policies, or actions.</p>

<h2>7. Acceptable Use</h2>
<p>You must not misuse the service, attempt to break authentication or rate limits, scrape excessively,
upload unlawful content, impersonate others, or use the service for spam, fraud, harassment, or unlawful
activities. We may suspend or remove access if we reasonably believe the service is being misused.</p>

<h2>8. Availability and Changes</h2>
<p>The service is provided on a best-effort basis and may be changed, interrupted, rate-limited,
disabled, or discontinued at any time. Support and uptime are not guaranteed.</p>

<h2>9. Disclaimer of Warranties</h2>
<p>To the maximum extent permitted by law, the service is provided "as is" and "as available" without
warranties of any kind, whether express, implied, statutory, or otherwise.</p>

<h2>10. Limitation of Liability</h2>
<p>To the maximum extent permitted by law, Job Hunter SG and its operator will not be liable for indirect,
incidental, special, consequential, exemplary, or punitive damages, loss of opportunity, loss of income,
loss of data, application mistakes, missed deadlines, employer decisions, or reliance on inaccurate information.</p>
<p>To the maximum extent permitted by law, any total liability arising from the service is limited to the
amount you paid to use the service in the three months before the claim, or SGD 10 if you paid nothing.</p>

<h2>11. Governing Law</h2>
<p>These Terms are governed by the laws of Singapore, unless applicable consumer protection laws require otherwise.</p>

<h2>12. Contact</h2>
<p>For questions, account deletion, privacy requests, or support, {contact}.</p>

"""
    return _page("Terms of Service", body)


def render_privacy_html(contact_line: str) -> str:
    contact = html.escape(contact_line)
    body = f"""
<h1>Privacy Notice</h1>
<p class="updated">Last updated: {LEGAL_UPDATED}</p>

<p>This Privacy Notice explains how Job Hunter SG collects, uses, stores, and protects personal data.</p>

<h2>1. Data We Collect</h2>
<ul>
  <li>Account data such as name, email address, signup time, and login activity.</li>
  <li>Authentication data such as hashed passwords for password accounts. We do not store plain-text passwords.</li>
  <li>Resume and profile data you upload, paste, edit, score, or save.</li>
  <li>Tracked jobs, application statuses, notes, saved resume versions, stories, and related usage data.</li>
  <li>Job alert preferences, delivery history, unsubscribe status, and suppression records.</li>
  <li>Technical and usage logs needed for rate limiting, security, debugging, analytics, and abuse prevention.</li>
</ul>

<h2>2. Why We Use Data</h2>
<ul>
  <li>To provide resume review, tailoring, matching, market insights, job tracking, and alert features.</li>
  <li>To remember your saved resume/profile so the app can work across sessions.</li>
  <li>To send optional job match alert emails only when you enable them.</li>
  <li>To maintain security, diagnose errors, prevent abuse, and improve reliability.</li>
  <li>To respond to contact, support, deletion, or correction requests.</li>
</ul>

<h2>3. Email Alerts and Consent</h2>
<p>Job match alerts are disabled by default. If you enable alerts, you consent to receiving digest emails
based on your saved resume and alert settings. You can turn alerts off from Account or use the unsubscribe
link in an alert email. We record deliveries and suppressions so the same job is not repeatedly emailed.</p>

<h2>4. AI and Third-Party Processing</h2>
<p>When you use AI features, relevant resume text, job descriptions, or prompts may be sent to AI providers
to generate the requested output. The app may also use hosting, database, email, analytics, public data,
and job-source providers. These providers may process data outside Singapore.</p>

<h2>5. What We Do Not Do</h2>
<ul>
  <li>We do not sell your personal data.</li>
  <li>We do not show your resume or tracked applications to other users.</li>
  <li>We do not auto-submit job applications for you.</li>
  <li>We do not intentionally use your resume for advertising targeting.</li>
</ul>

<h2>6. Retention</h2>
<p>We keep account, resume, tracked-job, alert, and usage data while your account is active or as needed
to provide the service, maintain security, resolve issues, comply with law, or handle deletion requests.
You may ask us to delete your account data.</p>

<h2>7. Your Controls</h2>
<p>You can edit or delete stored memory/resume content in the app where available. You can disable job
alerts at any time. You can request access, correction, deletion, or withdrawal of consent by contacting us.</p>

<h2>8. Security</h2>
<p>We use reasonable technical measures such as password hashing, access controls, and hosted database
security. No internet service is perfectly secure, so you should avoid uploading unnecessary sensitive data.</p>

<h2>9. Contact</h2>
<p>For privacy requests, account deletion, or questions, {contact}.</p>

"""
    return _page("Privacy Notice", body)
