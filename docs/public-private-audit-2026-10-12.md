# Public dashboard and private research audit — 2026-10-12

Baseline: main `73d09b21b19277d46e831c99db8bb43570ff209d`.

Before implementation, the audit found:

1. The Next proxy authorizes writes only; every read, including exports and raw
   experiment candles, depends on Vercel's whole-site gate. Removing that gate
   without application authorization would expose research data and settings.
2. There is no public response schema or benchmark. Returning existing experiment
   objects would expose strategy configuration, input prices, quantities and cash.
3. Google sign-in is not configured. A valid login must also pass the owner
   allowlist; client-side button visibility is not authorization.
4. The news and event providers discussed with the owner are not integrated.
5. Tiingo's terms, last updated October 6, explicitly prohibit durable storage of
   both source data and derived results on Starter/Trial. The existing durable
   stock cache is therefore not compatible with that plan. The pricing-page
   audit missed this restriction. A rebased single-security benchmark is
   explicitly prohibited from redistribution without a suitable agreement.

Implementation must deny private reads as well as writes, construct public output
from an explicit allowlist, avoid publishing unlicensed or synthetic results,
keep provider quotas durable but restricted content transient/disabled by
default, and show honest empty/configuration states. No demo research may be
created in production. API integrations do not imply that baseline algorithms
consume news or that cloud AI experiments are implemented.

References:
- https://app.tiingo.com/tos/ (sections 1.4 and 1.6)
- https://neon.com/docs/auth/guides/setup-oauth
- https://vercel.com/docs/deployment-protection/methods-to-protect-deployments/vercel-authentication

Implementation verification:

- Local backend: 156 tests passed; five PostgreSQL cases require the CI service.
- Twenty authorization/proxy tests passed; type checking and production build
  passed. Production npm audit reported no vulnerabilities.
- Live SEC integration returned actual filings for all three company symbols;
  test requests used a temporary store, not production research records.
- Browser validation is delegated to the existing CI job: this container's
  Chromium download was invalid, and system installation is unavailable.
- Neon Auth and the production trusted origin are provisioned. Production
  Google activation remains disabled until custom OAuth credentials and owner
  sign-in/sign-out verification are complete. Unapproved identities fail closed.
- Marketaux, Alpha Vantage and FRED credentials are still required. Tiingo
  storage and public-performance approval remain disabled. No production
  experiment or synthetic result has been created.

The rollout must retain Vercel protection on old deployment URLs and verify
public/private HTTP boundaries before exposing the new production alias.
