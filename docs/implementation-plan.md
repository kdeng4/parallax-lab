# Patrick Intelligent Trading Research Platform · Implementation Plan

## Product goal

Help researchers answer: which model performs better with **identical market data, capital, transaction costs, and strategy versions**? Does changing the strategy script improve the results for the same model? Every conclusion must be traceable to a market-data snapshot, a decision summary, fills, and account changes.

Deliver a verifiable end-to-end workflow first. Split components into separate services when actual workload warrants it. Milestone 1 is a single-user local research workbench; it is not ready for public, multi-tenant, or real-money deployment.

## Technology choices

| Layer | Choice | Rationale |
| --- | --- | --- |
| Web | Next.js 16.4, React 19.3, TypeScript 7 | App Router, type safety, and a same-origin proxy to the API |
| Styling | CSS design tokens, responsive CSS, Lucide | A restrained interface, responsive layout, and accessible controls |
| API | Python 3.12, FastAPI 0.143, Pydantic 2 | Strict request validation, OpenAPI, and an extensible model ecosystem |
| Dependencies | npm and uv lockfiles | Exact installation and a reproducible development environment |
| Local persistence | SQLite | Full experiments without credentials or external services |
| Future shared storage | PostgreSQL with TimescaleDB | Relational transactions, audit records, and market time series in one stack; validate version compatibility at the required scale |
| Future event bus | NATS JetStream with a transactional outbox | Durable consumption, deduplication, replay, and service decoupling |
| Tests | pytest, Playwright, and a production build | Account conservation, correct event timing, and complete API/browser workflows |
| Delivery | Docker Compose and GitHub Actions | Reproducible local deployment and continuous validation |

Application dependency versions were checked against stable npm and PyPI releases during implementation and locked in the repository. Infrastructure versions will be chosen for compatibility and security updates, without unbounded `latest` tags. Every upgrade must pass the same validation suite.

## Milestone 1 · Implemented: reproducible paper-trading research

- A fixed random seed produces deterministic synthetic OHLCV data. All participants share the same dataset and content hash.
- Local momentum, mean-reversion, and buy-and-hold baselines use versioned Markdown strategies.
- Model comparison changes only the model; strategy comparison changes only the strategy. The API rejects experiments that change both factors.
- Each participant has independent cash and positions. Trading is long only, without leverage. A signal at candle close can fill no earlier than the next candle's open, with fees and slippage.
- The system saves equity, returns, maximum drawdown, the proportion of profitable sell fills (including partial exits), and a documented Sharpe ratio.
- Market events, decision summaries, orders, fills, risk refusals, and completion events are saved and can be filtered by participant, event type, and time.
- The web app provides comparison curves, a metrics table, experiment history, strategy inspection, audit filters, experiment creation, and JSON export.
- API credentials remain on the server. OpenAI and Anthropic adapters are tested independently; milestone 1 experiments do not call paid services.

**Acceptance:** locked dependencies install; engine and API tests pass; the production frontend builds; browser tests create both experiment types, show their results, filter the audit log, and export a reproducibility file; experiments survive a restart.

## Milestone 2 · Live market data and cloud models

1. Choose licensed market data and the market scope. Implement an adapter for one source that normalizes updates into events with exchange timestamps. Account for latency, gaps, splits, adjusted prices, and trading sessions.
2. Integrate explicit OpenAI and Anthropic model versions with structured outputs. Set timeouts, retries, concurrency, spending limits, and handling for refusals and invalid instructions. Record a model failure as a failure; never silently substitute a baseline.
3. Create an immutable shared input snapshot for each decision round, recording its data cutoff and budget. Gather model decisions at a common deadline so model latency cannot change trading opportunities.
4. Turn runs into durable tasks. Implement cancellation, resumption, and idempotency before introducing NATS JetStream workers. Publish transaction events atomically through an outbox and deduplicate by event ID in consumers.
5. Use the same engine interface for market replay and live experiments. Add server-sent status updates and reconnection recovery.
6. Before shared deployment, implement OIDC sign-in, protected sessions, tenant isolation, experiment permissions, CSRF protection, abuse prevention, secret management, and TLS.

**Acceptance:** provider contract tests cover success, refusal, timeout, and rate limits; paid runs require explicit configuration and do not expose secrets; two models receive the same snapshot; retries cannot duplicate a fill; authorization tests cover cross-user access.

## Milestone 3 · Research reliability and production operations

- Add a transactional PostgreSQL ledger, migrations, TimescaleDB market-data partitioning, and retention policies. Keep Decimal account calculations and add market-specific tick-size and minimum trade-unit rules.
- Separate training, validation, and out-of-sample results. Add walk-forward analysis, confidence intervals, and multiple-comparison corrections; do not claim strategy superiority from short replays.
- Record model versions, prompts, tool-call summaries, parameters, data versions, and costs. Add MLflow when cross-team research needs it; the current JSON export and content hashes form the initial record.
- Add OpenTelemetry tracing, Prometheus metrics, and Grafana dashboards. Monitor consumer lag, data gaps, decision costs, failure rates, and ledger invariants.
- Add container-image scanning, controlled image publishing, Kubernetes deployment, resource limits, service authentication, database backups, and restore drills.

**Acceptance:** fault injection confirms orders cannot be duplicated; restore drills meet agreed recovery point and recovery time objectives (RPO/RTO); load tests establish throughput and latency baselines; an independent security review is complete.

## Milestone 4 · Real-money trading (separate project)

Milestone 1 has no interface for real orders. Before any limited-capital trial, a later project must complete broker sandbox testing, human approval, maximum-loss, position, and exposure limits, a kill switch, reconciliation, market-rule review, and compliance assessment. Simulation results do not guarantee live returns.

## Key architecture constraints

- Audit events contain observable decision summaries and structured reasons. They do not require or store a model's private chain of thought.
- Every comparison chart identifies its data source. Local algorithms must not be labelled as OpenAI, Claude, or other cloud models.
- Do not combine one model's account returns across different strategies into a single “model performance” figure. Each curve belongs to a clearly identified experiment participant.
- Split services according to deployment, fault-isolation, and throughput needs. Milestone 1 module boundaries must not be described as deployed distributed services.
- In-memory objects and running processes are not a persistence guarantee. Save experiment results to storage and explicitly start services in each new environment.
