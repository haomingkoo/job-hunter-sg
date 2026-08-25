# Production release

Production is one GitHub-to-Railway path. GitHub validates the commit; Railway
builds that same commit; the `Production acceptance` workflow waits until the
public health response reports that exact SHA.

## One-time settings

Repository code cannot enforce these provider settings. Configure and review
them in the provider audit logs rather than storing credentials in GitHub.

### GitHub `main`

Create a branch protection rule or ruleset for the default branch:

- require a pull request before merge;
- require the branch to be current before merge;
- require `Backend lint, type check, tests`, `Frontend tests and build`, and
  `Secret scan`;
- block force pushes and deletion; and
- allow repository administrators to bypass only for an incident. Open an
  incident issue first and reference it in the emergency commit and follow-up
  pull request so the reason is auditable.

Do not create a second deployment workflow. The existing `CI` workflow is the
merge gate.

### Railway production services

For every service linked to this repository, select the `main` trigger branch
and enable **Wait for CI**. Railway then holds a deployment while the push
workflow runs, skips it when a workflow fails, and proceeds only when all push
workflows succeed.

The services are defined in `.railway/railway.ts`. Railway provides
`RAILWAY_GIT_COMMIT_SHA`; `/api/health` publishes it as `commit`. No secret or
user-provided version variable is required.

The scheduled services are defined in version control:

| Service | Config | UTC schedule | Singapore time | Kill switch |
| --- | --- | --- | --- | --- |
| Full crawl | `.railway/railway.ts` | `0 22 * * *` | 06:00 daily | Clear its Railway Cron Schedule |
| Job alerts | `.railway/railway.ts` | `0 23 * * *` | 07:00 daily | Clear its Railway Cron Schedule |

Each live scheduled service must show this repository, the released commit, and
the matching config file in Railway. A trigger-only curl service is not equivalent
to the full-crawl service because the admin endpoint returns as soon as it starts
the background task. Rotate any credential that has ever appeared literally in
deployment metadata; service commands may reference Railway variables but must
never embed their values.

After each release, record each scheduled service's configured schedule,
latest successful execution time, latest deployment status, and any failure or
still-running state from its Railway deployment history. Railway skips a cron
invocation while its previous execution is still active, so `Active` is not a
successful receipt.

## Release evidence

The gates prove different things and must not be collapsed into one green tick:

1. Local tests validate the working tree only.
2. Required pull-request checks validate the reviewed commit.
3. Railway **Wait for CI** decides whether that commit may deploy.
4. `Production acceptance` polls production for the GitHub SHA, database
   connectivity, a non-empty and recently scraped public corpus from both maintained
   sources, the SPA shell and its hashed JavaScript
   asset, `robots.txt`, `sitemap.xml`, and `llms.txt`. Its JSON output is the
   public receipt. Rendering the `#jobs` SPA route remains part of browser
   acceptance; an HTTP client cannot observe a URL fragment.
5. Signed-in browser acceptance verifies authentication and user journeys; the
   public smoke does not claim this.
6. Issue #99 owns a future isolated staging and model-backed promotion gate.

The production workflow runs automatically after successful `CI` on `main`.
It can also be rerun from GitHub Actions with `workflow_dispatch`, supplying a
full `expected_sha` and the production base URL. Manual runs use the verifier
from the immutable workflow-dispatch commit (normally the current default-branch
commit), so they can validate rollback commits that predate the verifier.

### Scheduled-service receipt

Record the live values during external settings acceptance in the release's
GitHub issue using this template, and include links to the production workflow
run and pull request in that comment:

```text
Release SHA: <full SHA>
Recorded at: <UTC timestamp>
| Service | Live repo commit/config | Repo schedule | Live Railway schedule | Latest execution/deployment ID | Status | Finished at | Failure detail | Kill switch checked |
| Full crawl | <SHA / .railway/railway.ts> | 0 22 * * * | <live value> | <ID> | <SUCCESS/FAILED/ACTIVE> | <UTC or n/a> | <none or summary> | <clear Cron Schedule verified> |
| Job alerts | <SHA / .railway/railway.ts> | 0 23 * * * | <live value> | <ID> | <SUCCESS/FAILED/ACTIVE> | <UTC or n/a> | <none or summary> | <clear Cron Schedule verified> |
```

The repository supplies only the expected schedules and commands above. The live service source,
commit and config file, schedule,
execution IDs, timestamps, and failure state must come from Railway during
acceptance; do not copy placeholders into a completed receipt.

For the controlled negative check, confirm a pull request with a deliberately
failing required check cannot merge. Then verify Railway records no production
deployment for that SHA. Do not push a known failing commit directly to
production merely to test the provider toggle.

## Rollback

1. In Railway's production deployment history, identify the last known-good
   deployment by its full immutable Git SHA.
2. Select that deployment and choose **Redeploy**. Do not rebuild an arbitrary
   local checkout or use `railway up`.
3. Run `Production acceptance` manually with that SHA and the production URL.
4. Repeat the signed-in browser acceptance needed for the affected journey.
5. Record the failed SHA, rollback deployment ID, accepted SHA, workflow run,
   and browser receipt in the incident issue.
