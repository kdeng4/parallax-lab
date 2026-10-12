# Housekeeping audit — October 12, 2026

Reviewed base: `48d7a194db969eeae165a4f5814920d64c995bf2` on `main`.
The review covered repository governance, application startup, public/private
read boundaries, storage calls, unused imports and current setup documentation.
It is a targeted code review, not a certification of trading performance.

| Finding | Evidence | Resolution |
| --- | --- | --- |
| Default branch has no safeguards | GitHub reported `protected: false` and no rulesets. | Prepared an active default-branch ruleset requiring PRs and the verified Actions checks. Application is blocked by missing connector Administration access and browser credential protection. |
| Sample generation remains in application startup | `create_app` accepts a seed override and two environment names solely to create an example run. | Removed the parameter, seed ID, seed branches and now-unused integrity-error aliases. Browser fixtures now run only from a guarded test helper. |
| Public projection reads unnecessary research history | The application sliced summaries after fetching all of them, then loaded full audit logs without using any event. | Limit the database query to twenty candidates and retrieve results without events. Private export behaviour is preserved. |
| Unused frontend import | TypeScript reported `Clock3` as unused. | Removed it and enabled unused-local and unused-parameter checks in CI. |
| Duplicate feature-branch CI | Push and PR events run the same workflow for the same change. | Keep main push checks and PR checks; remove feature-branch push duplication. |
| Setup documentation describes an old milestone | API README says SQLite only and describes first-start sample creation; root README says all hosted URLs use Vercel Authentication. | Updated the current PostgreSQL, empty-startup and public/private deployment boundaries. |

CODEOWNERS and a short PR template record responsibility and review evidence.
The sole maintainer cannot approve their own PR, so the prepared rule requires
zero external approvals while still enforcing a PR, current-base checks, resolved
threads and linear history. It grants no bypass actor, force push or deletion.

The legacy local database fallback remains to preserve existing research.
OpenAI/Anthropic adapters and their contract tests remain because they support
the explicitly requested next integration. They are not enabled by this cleanup.
Production data, provider quotas and credentials are not rewritten or deleted.

Local verification includes the non-provider backend suite, owner authorization
regressions, TypeScript checks, a production frontend build, whitespace and
release-language checks. PostgreSQL and browser contracts are CI gates. Actual
owner OAuth-session verification remains pending from the previous deployment;
this cleanup does not weaken or bypass it.

See [repository safeguards](repository-safeguards.md) for importing and checking
the prepared rule. A committed JSON file is not an active GitHub setting.
