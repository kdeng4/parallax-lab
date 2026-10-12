"""Storage contracts for concurrent experiments and all-or-nothing audit writes."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from patrick.engine import run_experiment
from patrick.schemas import ExperimentInput
from patrick.storage import Store


@pytest.fixture
def store(tmp_path):
    instance = Store(f"sqlite:///{tmp_path / 'concurrent.db'}")
    instance.initialize()
    return instance


def test_parallel_experiments_commit_complete_independent_audits(store):
    details = [run_experiment(ExperimentInput(seed=100 + index, bars=60)) for index in range(6)]
    start = Barrier(len(details))

    def save_at_once(detail):
        start.wait(timeout=30)
        store.save(detail)

    with ThreadPoolExecutor(max_workers=len(details)) as pool:
        futures = [pool.submit(save_at_once, detail) for detail in details]
        for future in futures:
            future.result(timeout=60)

    assert {item["id"] for item in store.list_experiments()} == {detail["id"] for detail in details}
    for detail in details:
        assert store.get(detail["id"]) == detail
        events = store.filter_events(detail["id"], run_id=None, event_type=None,
                                     from_time=None, to_time=None, limit=2000, offset=0)
        assert events["total"] == len(detail["events"])
        assert events["events"] == detail["events"]
    with store.connection() as connection:
        assert connection.execute("SELECT count(*) FROM experiments").fetchone()[0] == len(details)
        assert connection.execute("SELECT count(*) FROM events").fetchone()[0] == sum(len(detail["events"]) for detail in details)


def test_late_audit_collision_rolls_back_new_experiment_and_earlier_events(store):
    saved = run_experiment(ExperimentInput(seed=7, bars=60))
    store.save(saved)
    rejected = run_experiment(ExperimentInput(seed=8, bars=60))
    rejected["events"][-1]["id"] = saved["events"][-1]["id"]

    with pytest.raises(sqlite3.IntegrityError):
        store.save(rejected)

    assert store.get(rejected["id"]) is None
    assert store.get(saved["id"]) == saved
    assert [summary["id"] for summary in store.list_experiments()] == [saved["id"]]
    with store.connection() as connection:
        assert connection.execute("SELECT count(*) FROM experiments").fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM events").fetchone()[0] == len(saved["events"])
        assert connection.execute("SELECT count(*) FROM events WHERE experiment_id=?", (rejected["id"],)).fetchone()[0] == 0
