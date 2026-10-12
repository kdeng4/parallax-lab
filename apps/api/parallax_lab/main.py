import json
import os
import sqlite3
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID

from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .engine import MODELS, run_experiment
from .schemas import SYMBOLS, ExperimentInput
from .storage import Store
from .strategy import load_strategies

DEMO_ID = "d93865f4-352f-5a14-b80d-e0453b018540"


def default_database_url() -> str:
    current = Path(".data/parallax-lab.db")
    legacy = Path(".data/patrick.db")
    # Keep reading an existing local database after the product rename.
    path = legacy if legacy.exists() and not current.exists() else current
    return f"sqlite:///./{path.as_posix()}"


def create_app(database_url: str | None = None, seed_demo: bool | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        store = Store(database_url or os.getenv("PARALLAX_DATABASE_URL") or
                      os.getenv("PATRICK_DATABASE_URL") or default_database_url())
        store.initialize()
        app.state.store = store
        seed_setting = os.getenv("PARALLAX_SEED_DEMO")
        if seed_setting is None:
            seed_setting = os.getenv("PATRICK_SEED_DEMO", "1")
        should_seed = seed_demo if seed_demo is not None else seed_setting == "1"
        if should_seed and not store.has(DEMO_ID):
            try:
                store.save(run_experiment(ExperimentInput(name="Opening bell · baseline study"), DEMO_ID))
            except sqlite3.IntegrityError:
                # Concurrent worker startup may have committed this exact seed first.
                if not store.has(DEMO_ID):
                    raise
        yield

    app = FastAPI(title="Parallax Lab · paper-trading research", version="0.1.0", lifespan=lifespan,
                  description="Single-user research API. Synthetic data and local baselines; no live orders.")

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
        return {"status": "ok", "mode": "paper", "storage": "sqlite"}

    @app.get("/api/v1/catalog")
    def catalog():
        return {"models": list(MODELS.values()),
                "strategies": [s.model_dump(exclude={"config"}) for s in load_strategies().values()],
                "symbols": list(SYMBOLS), "data_source": "synthetic"}

    @app.get("/api/v1/experiments")
    def list_experiments():
        return {"experiments": store().list_experiments()}

    @app.post("/api/v1/experiments", status_code=201)
    def create_experiment(request: ExperimentInput):
        detail = run_experiment(request)
        store().save(detail)
        return detail

    @app.get("/api/v1/experiments/{experiment_id}")
    def experiment(experiment_id: UUID):
        return get_or_404(experiment_id)

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
        return Response(json.dumps(detail, ensure_ascii=False, indent=2, allow_nan=False), media_type="application/json",
                        headers={"Content-Disposition": f'attachment; filename="parallax-lab-{experiment_id}.json"'})

    return app


app = create_app()
