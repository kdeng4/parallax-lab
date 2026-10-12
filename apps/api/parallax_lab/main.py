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

from .engine import MODELS, run_experiment
from .market_feeds import FeedError, MarketService, MAX_REPLAY_BARS
from .schemas import SYMBOLS, ExperimentInput
from .storage import Store, open_store
from .strategy import load_strategies

DEMO_ID = "d93865f4-352f-5a14-b80d-e0453b018540"


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


def create_app(database_url: str | None = None, seed_demo: bool | None = None) -> FastAPI:
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
        seed_setting = os.getenv("PARALLAX_SEED_DEMO")
        if seed_setting is None:
            seed_setting = os.getenv("PATRICK_SEED_DEMO", "0")
        should_seed = os.getenv("VERCEL") != "1" and (
            seed_demo if seed_demo is not None else seed_setting == "1"
        )
        if should_seed and not store.has(DEMO_ID):
            try:
                store.save(run_experiment(ExperimentInput(name="Opening bell · baseline study"), DEMO_ID))
            except store.integrity_error:
                # Concurrent worker startup may have committed this exact seed first.
                if not store.has(DEMO_ID):
                    raise
        yield

    app = FastAPI(title="Parallax Lab · paper-trading research", version="0.1.0", lifespan=lifespan,
                  description="Private research API. Real daily market snapshots and local baselines; no live orders.")

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
        return {"models": list(MODELS.values()),
                "strategies": [s.model_dump(exclude={"config"}) for s in load_strategies().values()],
                "symbols": list(SYMBOLS), "data_source": "synthetic" if fixture_mode else "tiingo",
                "interval": "1m" if fixture_mode else "1d", "max_bars": 1440 if fixture_mode else MAX_REPLAY_BARS,
                "replay_available": fixture_mode or bool(app.state.market.network and app.state.market.token)}

    @app.get("/api/v1/market/overview")
    def market_overview():
        return app.state.market.overview()

    @app.get("/api/v1/experiments")
    def list_experiments():
        return {"experiments": store().list_experiments()}

    @app.post("/api/v1/experiments", status_code=201)
    def create_experiment(request: ExperimentInput):
        try:
            dataset = None if fixture_mode else app.state.market.replay(request.symbol, request.bars)
        except ValueError as error:
            raise HTTPException(422, str(error)) from None
        except FeedError:
            raise HTTPException(503, "Verified daily market history is unavailable. Connect Tiingo or wait for the next refresh; no synthetic fallback is used.") from None
        detail = run_experiment(request, dataset=dataset)
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
