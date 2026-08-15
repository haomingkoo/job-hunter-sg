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

The web service uses `railway.toml`. Railway provides
`RAILWAY_GIT_COMMIT_SHA`; `/api/health` publishes it as `commit`. No secret or
user-provided version variable is required.

The scheduled services are defined in version control:

| Service | Config | UTC schedule | Singapore time | Kill switch |
| --- | --- | --- | --- | --- |
| Full crawl | `railway.seed.toml` | `0 22 * * *` | 06:00 daily | Clear its Railway Cron Schedule |
| Job alerts | `railway.alerts.toml` | `0 23 * * *` | 07:00 daily | Clear its Railway Cron Schedule |

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
   connectivity, the public jobs feed, the SPA shell, `robots.txt`,
   `sitemap.xml`, and `llms.txt`. Its JSON output is the public receipt.
5. Signed-in browser acceptance verifies authentication and user journeys; the
   public smoke does not claim this.
6. Issue #99 owns a future isolated staging and model-backed promotion gate.

The production workflow runs automatically after successful `CI` on `main`.
It can also be rerun from GitHub Actions with `workflow_dispatch`, supplying a
full `expected_sha` and the production base URL.

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
