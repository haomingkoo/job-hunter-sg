"""HTML legal pages for the hosted app.

These pages are practical product notices, not a substitute for legal advice.
"""

from __future__ import annotations

import html


LEGAL_UPDATED = "25 October 2026"
OPERATOR = "Koo Haoming (individual, Singapore)"


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
    table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
    th, td {{ text-align: left; vertical-align: top; padding: 8px; border-bottom: 1px solid #dbe7f3; }}
    .table-wrap {{ overflow-x: auto; }}
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


def _mailto(email: str) -> str:
    safe = html.escape(email)
    return f'<a href="mailto:{safe}">{safe}</a>'


def render_terms_html(contact_email: str) -> str:
    contact = _mailto(contact_email)
    body = f"""
<h1>Terms of Service</h1>
<p class="updated">Last updated: {LEGAL_UPDATED}</p>

<p>These Terms apply when you use Job Hunter SG, which is operated by {OPERATOR}. By creating an account,
using the service, or enabling job alerts, you agree to these Terms and our
<a href="/api/privacy">Privacy Notice</a>.</p>

<h2>1. What This Service Is</h2>
<p>Job Hunter SG helps users search job listings, review resumes,
track applications, view market signals, and receive optional job match alerts. It is not an
employment agency, recruiter, career adviser, financial adviser, legal adviser, or job placement service.</p>

<h2>2. Minimum Age</h2>
<p>You must be at least 13 years old, or the minimum age of digital consent in your country if that is higher,
to use the service. If you are under 18, you confirm that a parent or guardian has agreed to your use of the
service and to these Terms.</p>

<h2>3. No Guarantees</h2>
<p>Job listings, salary information, matching scores, resume feedback, AI outputs, market insights,
course suggestions, and employer classifications are provided for general information only. They may be
incomplete, delayed, inaccurate, unavailable, or changed by third-party sources without notice.</p>
<p>We do not guarantee interviews, offers, employment outcomes, salary outcomes, employer responses,
job availability, eligibility, or suitability of any role.</p>

<h2>4. User Responsibility</h2>
<p>You are responsible for checking job postings, employer details, application requirements,
visa/work eligibility, salary terms, course details, and all information before relying on it or applying.
You are also responsible for the resumes, cover letters, notes, and other content you submit or generate.</p>

<h2>5. Your Content and Our Licence to Process It</h2>
<p>You keep ownership of the resumes, notes, and other content you upload or enter. You grant the operator a
limited, non-exclusive, royalty-free licence to store, copy, process, and transmit that content only as needed
to provide the service to you. This includes sending it to the service providers named in the Privacy Notice.
The licence ends when the content is deleted, except for copies that remain in backups until they expire.
We do not use your content to train AI models, for advertising, or for any purpose unrelated to the service.</p>

<h2>6. AI and Automated Matching</h2>
<p>The service may use automated extraction, AI models, heuristics, and third-party data. These tools can
make mistakes. You should review all generated or suggested content before using it. Do not submit
sensitive information unless you are comfortable with it being processed to provide the service.</p>

<h2>7. Email Alerts</h2>
<p>Job match alerts are optional and disabled by default. If you enable them, we may email you digests
based on your saved resume, alert preferences, and available job data. You can disable alerts from your
Account page or unsubscribe using the link in an alert email. Alerts are informational and are not job offers.</p>

<h2>8. Third-Party Services and Links</h2>
<p>The service may link to third-party job boards, employers, course providers, AI services, hosting
providers, email providers, and public datasets. We do not control those services and are not responsible
for their content, availability, decisions, fees, policies, or actions.</p>

<h2>9. Acceptable Use</h2>
<p>You must not misuse the service, attempt to break authentication or rate limits, scrape excessively,
upload unlawful content, impersonate others, or use the service for spam, fraud, harassment, or unlawful
activities. We may suspend or remove access if we reasonably believe the service is being misused.</p>

<h2>10. Availability and Changes</h2>
<p>The service is provided on a best-effort basis and may be changed, interrupted, rate-limited,
disabled, or discontinued at any time. Support and uptime are not guaranteed.</p>

<h2>11. Disclaimer of Warranties</h2>
<p>To the maximum extent permitted by law, the service is provided "as is" and "as available" without
warranties of any kind, whether express, implied, statutory, or otherwise.</p>

<h2>12. Limitation of Liability</h2>
<p>To the maximum extent permitted by law, Job Hunter SG and its operator will not be liable for indirect,
incidental, special, consequential, exemplary, or punitive damages, loss of opportunity, loss of income,
loss of data, application mistakes, missed deadlines, employer decisions, or reliance on inaccurate information.</p>
<p>To the maximum extent permitted by law, any total liability arising from the service is limited to the
amount you paid to use the service in the three months before the claim, or SGD 10 if you paid nothing.</p>

<h2>13. Governing Law</h2>
<p>These Terms are governed by the laws of Singapore, unless applicable consumer protection laws require otherwise.</p>

<h2>14. Contact</h2>
<p>For questions, privacy requests, or support, email {contact}.</p>

"""
    return _page("Terms of Service", body)


def render_privacy_html(contact_email: str, *, llm_tracing_enabled: bool = False) -> str:
    contact = _mailto(contact_email)
    if llm_tracing_enabled:
        tracing = (
            "<li><strong>LangSmith (LangChain, Inc.), United States.</strong> LLM debugging traces are currently "
            "enabled. Traces can include the prompts and outputs of AI features, which may contain resume text.</li>"
        )
        tracing_note = ""
    else:
        tracing = ""
        tracing_note = (
            "<p>Third-party LLM tracing (such as LangSmith) is switched off in code. If we ever turn it on, "
            "we will list the provider here first.</p>"
        )
    body = f"""
<h1>Privacy Notice</h1>
<p class="updated">Last updated: {LEGAL_UPDATED}</p>

<p>This Privacy Notice explains how Job Hunter SG collects, uses, stores, shares, and protects personal data.
The service is operated by {OPERATOR}, who is responsible for your personal data under the Singapore
Personal Data Protection Act 2012 (PDPA).</p>

<h2>1. Contact and Data Protection Officer</h2>
<p>Our Data Protection Officer can be reached at {contact}. Use this address for access, correction,
export, deletion, consent withdrawal, or any other privacy question. You do not need an account to write to us.
We aim to reply within 30 days.</p>

<h2>2. Data We Collect</h2>
<ul>
  <li>Account data: name, email address, signup time, last sign-in time, and when you accepted these terms.</li>
  <li>Authentication data: a hashed password. We do not store plain-text passwords.</li>
  <li>Resume and profile data you upload, paste, edit, score, or save. We extract the text from uploaded
  files and do not keep the original file.</li>
  <li>AI artifacts: recruitment-team conversations, candidate and role profiles, assessments, proposed edits,
  tailored resumes, and cover letters.</li>
  <li>Tracked jobs, application statuses, notes, submitted resume copies, interview stories, and related data.</li>
  <li>Job alert preferences, delivery history, and unsubscribe status.</li>
  <li>Usage logs: which features you used and when. Failed sign-ins and reset requests are logged with a
  shortened hash of the email address.</li>
  <li>Technical data: your IP address, used in server memory for rate limiting and seen in hosting and
  network logs, plus browser error reports with the page address (sign-in tokens removed) and browser type.</li>
</ul>

<h2>3. Using the Service Without an Account</h2>
<p>You can upload a resume without signing in. We ask for your consent first. The file is parsed on our
server and the extracted text is sent back to your browser, where it stays in session storage until you close
the tab. We do not save the resume text to our database. We only log the file type, word count, and parse
quality. If you then use an AI feature, the relevant resume text is sent to AI Singapore's SEA-LION API to
produce the result.</p>

<h2>4. Why We Use Data</h2>
<ul>
  <li>To provide resume review, tailoring, matching, market insights, job tracking, and alert features.</li>
  <li>To remember your saved resume and profile across sessions.</li>
  <li>To send account emails (verification and password reset) and optional job alerts.</li>
  <li>To keep the service secure, diagnose errors, prevent abuse, and keep it reliable.</li>
  <li>To respond to support, access, correction, export, and deletion requests.</li>
</ul>

<h2>5. Email Alerts and Consent</h2>
<p>Job match alerts are disabled by default. If you enable alerts, you consent to receiving digest emails
based on your saved resume and alert settings. You can turn alerts off from Account or use the unsubscribe
link in an alert email. We record deliveries so the same job is not emailed twice.</p>

<h2>6. AI and Third-Party Processing</h2>
<p>We share personal data only with the service providers below, and only so they can run the service for us.
Some are based outside Singapore, so your data may be transferred overseas. We rely on each provider's
contractual data protection commitments to give your data a standard of protection comparable to the PDPA.</p>
<ul>
  <li><strong>AI Singapore (SEA-LION API), Singapore.</strong> Receives resume text, job descriptions,
  and prompts when you use an AI feature. It does not receive your password. Processing and retention on its
  side follow AI Singapore's terms.</li>
  <li><strong>Railway Corporation, United States company.</strong> Hosts the application servers and the
  PostgreSQL database in its Singapore region. All stored account data, server logs, and database backups
  sit with Railway.</li>
  <li><strong>Resend, United States.</strong> Sends verification, password-reset, and job alert emails.
  It receives your name, email address, and the email content.</li>
  <li><strong>Google (Gmail), United States.</strong> Cloudflare Email Routing forwards privacy requests
  to the operator's Gmail (Google).</li>
  <li><strong>Cloudflare, United States.</strong> Provides DNS, network security, and content delivery for our
  domain. All web traffic passes through Cloudflare, which processes your IP address and request details.
  We also use Cloudflare Web Analytics, which counts page views without cookies or cross-site tracking.</li>
  {tracing}
</ul>
<p>Resume embeddings are computed on our own servers and are not sent to a third party. Job listings come
from public sources such as MyCareersFuture and Careers@Gov. We do not send them your personal data. When you
click a job link you go to that site, and its own privacy policy applies.</p>
{tracing_note}

<h2>7. What We Do Not Do</h2>
<ul>
  <li>We do not sell your personal data.</li>
  <li>We do not show your resume or tracked applications to other users.</li>
  <li>We do not auto-submit job applications for you.</li>
  <li>We do not use your resume for advertising or to train AI models.</li>
  <li>We do not set advertising or tracking cookies.</li>
</ul>

<h2>8. Retention</h2>
<div class="table-wrap"><table>
  <tr><th>Data</th><th>How long we keep it</th></tr>
  <tr><td>Account details (name, email, password hash)</td><td>Until you delete your account.</td></tr>
  <tr><td>Resumes, resume versions, saved profile, and AI artifacts</td><td>Until you delete them or your
  account. If you have not signed in or used the service for 12 months, they are deleted automatically.
  We email you 30 days before that happens. Accounts with job alerts switched on count as active.</td></tr>
  <tr><td>Submitted resume copies stored with tracked jobs</td><td>Same as resumes. The tracked job itself
  stays until you delete it or your account.</td></tr>
  <tr><td>Usage logs for your account</td><td>Until you delete your account, or after 12 months of inactivity
  as above.</td></tr>
  <tr><td>Usage logs not linked to an account (anonymous uploads, failed sign-ins)</td><td>12 months.</td></tr>
  <tr><td>Anonymous resume uploads</td><td>Not stored on our servers. The text stays in your browser tab.</td></tr>
  <tr><td>IP addresses for rate limiting</td><td>In server memory only, cleared within hours.</td></tr>
  <tr><td>Server logs and browser error reports</td><td>Railway's log retention period.</td></tr>
  <tr><td>Database backups</td><td>Railway's backup retention period. Deleted data can remain in a backup
  until that backup expires.</td></tr>
  <tr><td>Sent emails</td><td>Resend's log retention period, and your own mailbox.</td></tr>
</table></div>

<h2>9. Your Rights and Controls</h2>
<ul>
  <li><strong>Access and export.</strong> Account → Privacy → Export my data downloads everything linked to
  your account as a JSON file. You can also email us for a copy.</li>
  <li><strong>Correction.</strong> You can edit your resume, profile, stories, and tracked jobs in the app.
  For anything you cannot edit yourself, email us.</li>
  <li><strong>Deletion.</strong> Account → Delete account removes your account and all linked data from the
  live database straight away. Copies can remain in Railway backups until they expire, in server logs until
  they rotate, and with Resend or AI Singapore under their own retention policies. You can also delete
  individual resumes and tracked jobs at any time.</li>
  <li><strong>Withdrawing consent.</strong> You can switch off job alerts, stop using AI features, or delete
  your account. Withdrawing consent may mean some features stop working.</li>
  <li>If you are in the EU, UK, or California, you may also have rights to restrict or object to processing
  and to complain to your local data protection authority. Email us and we will help.</li>
</ul>

<h2>10. Children</h2>
<p>The service is not meant for children under 13. Users under 18 need a parent or guardian's consent.
If you think a child under 13 has given us personal data, email us and we will delete it.</p>

<h2>11. Security</h2>
<p>We use reasonable technical measures such as password hashing, access controls, encrypted connections,
and hosted database security. No internet service is perfectly secure, so avoid uploading sensitive data
that a job application does not need.</p>

<h2>12. Changes</h2>
<p>We will update the date at the top of this page when this notice changes. For significant changes we will
tell signed-in users in the app or by email.</p>

"""
    return _page("Privacy Notice", body)
