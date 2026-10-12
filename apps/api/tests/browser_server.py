"""Browser-test fixtures live outside the application startup path."""

import os
from pathlib import Path
from tempfile import gettempdir

import uvicorn

from parallax_lab.engine import run_experiment
from parallax_lab.main import create_app
from parallax_lab.schemas import ExperimentInput
from parallax_lab.storage import Store


def browser_app():
    url = os.environ.get("PARALLAX_DATABASE_URL", "")
    if os.getenv("VERCEL") == "1" or not url.startswith("sqlite:///"):
        raise RuntimeError("Browser fixtures require an isolated local SQLite database")
    database = Path(url.removeprefix("sqlite:///")).resolve()
    if (database.parent.parent != Path(gettempdir()).resolve()
            or not database.parent.name.startswith("parallax-lab-e2e-")
            or database.name != "research.db"):
        raise RuntimeError("Browser fixtures require a Playwright temporary directory")
    os.environ["PARALLAX_MARKET_SOURCE"] = "synthetic"
    os.environ["PARALLAX_MARKET_NETWORK"] = "0"
    store = Store(url)
    store.initialize()
    store.save(run_experiment(ExperimentInput(name="Opening bell · baseline study")))
    return create_app(url)


if __name__ == "__main__":
    uvicorn.run(browser_app(), host="127.0.0.1", port=8010)
