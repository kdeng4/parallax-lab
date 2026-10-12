import asyncio
import json
import os
import secrets
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse

from .cloud_replay import CloudReplay, ProviderBudgetError
from .engine import run_experiment
from .market_feeds import FeedError, MarketService, MAX_REPLAY_BARS
from .context_feeds import ContextFeeds
from .public_dashboard import attach_benchmark, public_dashboard
from .model_catalog import MAX_CLOUD_CALLS, OPENAI_LIMITS, OPENAI_MODELS, available_models, available_openai_models
from .providers import ProviderConfigurationError, ProviderError
from .schemas import SYMBOLS, ExperimentInput, WatchlistInput
from .storage import Store, open_store
from .strategy import load_strategies
from .live_schemas import StudyInput
from .live_service import LiveService

def stream_json(value: dict, *, status_code: int = 200, headers: dict | None = None, indent=None):
    def chunks():
        parts, length = [], 0
        for part in json.JSONEncoder(ensure_ascii=False, allow_nan=False, indent=indent).iterencode(value):
            parts.append(part)
            length += len(part)
            if length >= 65_536:
                yield "".join(parts)
                parts, length = [], 0
        if parts:
            yield "".join(parts)
    return StreamingResponse(chunks(), status_code=status_code, media_type="application/json", headers=headers)


def default_database_url() -> str:
    current = Path(".data/parallax-lab.db")
    legacy = Path(".data/patrick.db")
    # Keep reading an existing local database after the product rename.
    path = legacy if legacy.exists() and not current.exists() else current
    return f"sqlite:///./{path.as_posix()}"


def create_app(database_url: str | None = None) -> FastAPI:
    api_token = os.getenv("PARALLAX_API_TOKEN", "")
    fixture_mode = os.getenv("VERCEL") != "1" and os.getenv("PARALLAX_MARKET_SOURCE") == "synthetic"

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        url = (database_url or os.getenv("PARALLAX_DATABASE_URL") or
               os.getenv("PATRICK_DATABASE_URL") or default_database_url())
        if os.getenv("VERCEL") == "1":
            if len(api_token) < 32 or not url.startswith(("postgresql://", "postgres://")):
                raise RuntimeError("Hosted API requires PostgreSQL and a PARALLAX_API_TOKEN of at least 32 characters")
        store = open_store(url)
        store.initialize()
        app.state.store = store
        app.state.market = MarketService(store)
        if not app.state.market.persistent_tiingo:
            app.state.market.cache.discard_tiingo_content()
        app.state.context = ContextFeeds(app.state.market)
        yield

    app = FastAPI(title="Parallax Lab · paper-trading research", version="0.1.0", lifespan=lifespan,
                  description="Private research API. Real daily market snapshots, local controls and bounded OpenAI decisions; no live orders.")

    @app.middleware("http")
    async def protect_api(request: Request, call_next):
        if api_token and not secrets.compare_digest(
            request.headers.get("authorization", "").encode(), f"Bearer {api_token}".encode()
        ):
            return JSONResponse({"detail": "Authentication required"}, status_code=401,
                                headers={"WWW-Authenticate": "Bearer", "Cache-Control": "no-store"})
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request, error: RequestValidationError):
        # Do not reflect arbitrary request contents or non-finite values into JSON.
        return JSONResponse(status_code=422, content={"detail": [
            {"type": item["type"], "loc": item["loc"], "msg": item["msg"]}
            for item in error.errors()
        ]})

    def store() -> Store:
        return app.state.store

    def live():
        return LiveService(store(), app.state.market, client=getattr(app.state, 'openai_client', None))

    def study_or_404(study_id):
        detail = live().db.get(str(study_id))
        if detail is None:
            raise HTTPException(404, 'Study not found')
        return detail

    def get_or_404(experiment_id: UUID) -> dict:
        detail = store().get(str(experiment_id))
        if detail is None:
            raise HTTPException(404, "Experiment not found")
        return detail

    @app.get("/api/v1/health")
    def health():
        with store().connection() as connection:
            connection.execute("SELECT 1").fetchone()
        return {"status": "ok", "mode": "paper", "storage": store().dialect}

    @app.get("/api/v1/catalog")
    def catalog():
        return {"models": available_models(),
                "openai": {"configured": bool(available_openai_models()), "max_calls_per_experiment": MAX_CLOUD_CALLS,
                           "max_calls_per_minute": OPENAI_LIMITS[0][1], "max_calls_per_day": OPENAI_LIMITS[1][1]},
                "live": {"available": live().readiness() is None, "requirement": live().readiness(),
                         "scheduler_configured": len(os.getenv('PARALLAX_SCHEDULER_TOKEN', '')) >= 32,
                         "max_active_studies": 2, "max_tickers": 10, "max_pairs": 9,
                         "mark_interval_minutes": 5, "cloud_calls_per_tick": 2},
                "strategies": [s.model_dump(exclude={"config"}) for s in load_strategies().values()],
                "symbols": app.state.market.watchlist.get()["symbols"], "data_source": "synthetic" if fixture_mode else "tiingo",
                "interval": "1m" if fixture_mode else "1d", "max_bars": 1440 if fixture_mode else MAX_REPLAY_BARS,
                "replay_available": fixture_mode or bool(app.state.market.network and app.state.market.token and app.state.market.persistent_tiingo),
                "replay_requirement": None if fixture_mode or app.state.market.persistent_tiingo else 'A market-data licence permitting persistent research is required.'}

    @app.get('/api/v1/public/dashboard')
    def public_summary():
        return public_dashboard(store())

    @app.get('/api/v1/studies')
    def list_studies():
        return {'studies': live().db.list()}

    @app.post('/api/v1/studies', status_code=201)
    def start_study(request: StudyInput):
        try:
            detail = live().create(request)
        except ProviderConfigurationError as error:
            raise HTTPException(503, str(error)) from None
        except ValueError as error:
            raise HTTPException(422, str(error)) from None
        except FeedError:
            raise HTTPException(503, 'A current, verified quote for every selected ticker and SPY is required. No study was created.') from None
        return stream_json(detail, status_code=201)

    @app.get('/api/v1/studies/{study_id}')
    def study(study_id: UUID):
        return stream_json(study_or_404(study_id))

    @app.get('/api/v1/studies/{study_id}/snapshots/{snapshot_id}')
    def study_snapshot(study_id: UUID, snapshot_id: UUID):
        detail = live().db.snapshot_detail(str(study_id), str(snapshot_id))
        if not detail:
            raise HTTPException(404, 'Snapshot not found')
        return stream_json(detail)

    @app.post('/api/v1/studies/{study_id}/{action}')
    def study_action(study_id: UUID, action: Literal['pause', 'resume', 'check']):
        study_or_404(study_id)
        try:
            if action == 'check':
                live().tick(str(study_id))
                detail = study_or_404(study_id)
            else:
                detail = live().control(str(study_id), action)
        except ValueError as error:
            raise HTTPException(422, str(error)) from None
        return stream_json(detail)

    @app.get('/api/v1/scheduler/plan')
    def scheduler_plan():
        return {'studies': live().plan()}

    @app.post('/api/v1/scheduler/tick')
    def scheduler_tick():
        return live().tick()

    @app.get('/api/v1/context/overview')
    def private_context():
        return app.state.context.overview()

    @app.get("/api/v1/market/overview")
    def market_overview():
        return app.state.market.overview()

    @app.get("/api/v1/market/watchlist")
    def watchlist():
        return app.state.market.watchlist.get()

    @app.post("/api/v1/market/watchlist")
    def update_watchlist(request: WatchlistInput):
        return app.state.market.watchlist.replace(request)

    @app.get("/api/v1/experiments")
    def list_experiments():
        return {"experiments": store().list_experiments()}

    @app.post("/api/v1/experiments", status_code=201)
    def create_experiment(request: ExperimentInput):
        if fixture_mode and request.symbol not in SYMBOLS:
            raise HTTPException(422, "Synthetic fixtures support only their predefined test symbols; use verified market history for other tickers.")
        cloud = None
        if any(model in OPENAI_MODELS for model in request.model_ids):
            try:
                cloud = CloudReplay(request, store(), client=getattr(app.state, "openai_client", None))
            except ProviderConfigurationError as error:
                raise HTTPException(503, str(error)) from None
            except ValueError as error:
                raise HTTPException(422, str(error)) from None
        try:
            dataset = None if fixture_mode else app.state.market.replay(request.symbol, request.bars)
        except ValueError as error:
            raise HTTPException(422, str(error)) from None
        except FeedError as error:
            if error.code == 'storage_license_required':
                raise HTTPException(503, "Persistent experiments require a market-data licence permitting storage. No experiment was created.") from None
            raise HTTPException(503, "Verified daily market history is unavailable. Connect Tiingo or wait for the next refresh; no synthetic fallback is used.") from None
        try:
            detail = asyncio.run(cloud.run(dataset=dataset)) if cloud else run_experiment(request, dataset=dataset)
        except ProviderBudgetError as error:
            raise HTTPException(429, str(error)) from None
        except ProviderError as error:
            raise HTTPException(503, f"{error} No experiment was saved; already attempted calls can still be billed.") from None
        if dataset is not None:
            try:
                benchmark = app.state.market.replay('SPY', request.bars)
                attach_benchmark(detail, benchmark)
            except (FeedError, ValueError):
                pass  # Never invent a missing benchmark or substitute the traded stock.
        detail['metadata']['public_performance_approved'] = (dataset is not None and os.getenv('PARALLAX_PUBLIC_PERFORMANCE_APPROVED') == '1')
        store().save(detail)
        return stream_json(detail, status_code=201)

    @app.get("/api/v1/experiments/{experiment_id}")
    def experiment(experiment_id: UUID):
        return stream_json(get_or_404(experiment_id))

    @app.get("/api/v1/experiments/{experiment_id}/events")
    def events(experiment_id: UUID, run_id: UUID | None = None,
               type: Literal["market", "decision", "order", "fill", "risk", "completed"] | None = None,
               from_time: datetime | None = None, to_time: datetime | None = None,
               limit: Annotated[int, Query(ge=1, le=2000)] = 200,
               offset: Annotated[int, Query(ge=0)] = 0):
        if not store().has(str(experiment_id)):
            raise HTTPException(404, "Experiment not found")
        for bound in (from_time, to_time):
            if bound is not None and bound.tzinfo is None:
                raise HTTPException(422, "Time filters require a timezone offset or Z")
        if from_time is not None and to_time is not None and from_time > to_time:
            raise HTTPException(422, "from_time must be at or before to_time")
        def utc(value: datetime | None):
            return value.astimezone(UTC).isoformat().replace("+00:00", "Z") if value else None
        return store().filter_events(str(experiment_id), run_id=str(run_id) if run_id else None, event_type=type,
                                     from_time=utc(from_time), to_time=utc(to_time), limit=limit, offset=offset)

    @app.get("/api/v1/experiments/{experiment_id}/export")
    def export(experiment_id: UUID):
        detail = get_or_404(experiment_id)
        return stream_json(detail, indent=2,
                           headers={"Content-Disposition": f'attachment; filename="parallax-lab-{experiment_id}.json"'})

    return app


app = create_app()
