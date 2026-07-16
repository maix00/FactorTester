from __future__ import annotations

import sys
import threading
import time

import pytest

from server.services import test_jobs, backtest_runs
from tools.testers.backtest.engines.cancellation import BacktestCancelled
from tools.testers.backtest.engines.workers.dispatcher import EngineWorkerDispatcher


def test_page_scoped_run_can_only_be_cancelled_by_its_owner() -> None:
    run = backtest_runs.register("cancel-run", "page-a", "alice")
    try:
        with pytest.raises(PermissionError):
            backtest_runs.cancel("cancel-run", "page-a", "bob")
        assert run.cancelled.is_set() is False
        assert backtest_runs.cancel("cancel-run", "page-a", "alice") is True
        assert run.cancelled.is_set() is True
    finally:
        backtest_runs.finish("cancel-run")


def test_backtest_job_reuses_run_cancel_event_for_compatibility() -> None:
    run = backtest_runs.register("job-cancel-run", "page-a", "alice")
    try:
        job = test_jobs.create_job(
            run_token="job-cancel-run",
            page_uuid="page-a",
            owner="alice",
            payload={"run_token": "job-cancel-run", "page_uuid": "page-a"},
            cancel_event=run.cancelled,
        )
        assert test_jobs.cancel_run_token("job-cancel-run", "page-a", "alice") is True
        assert run.cancelled.is_set() is True
        assert job.cancel_event.is_set() is True
        assert job.cancel_requested is True
    finally:
        backtest_runs.finish("job-cancel-run")


def test_page_cancel_marks_backtest_job_cancelled() -> None:
    run = backtest_runs.register("page-cancel-run", "page-cancel", "alice")
    try:
        job = test_jobs.create_job(
            run_token="page-cancel-run",
            page_uuid="page-cancel",
            owner="alice",
            payload={"run_token": "page-cancel-run", "page_uuid": "page-cancel"},
            cancel_event=run.cancelled,
        )
        assert test_jobs.cancel_page("page-cancel") == 1
        assert job.cancel_requested is True
        assert job.cancel_event.is_set() is True
    finally:
        backtest_runs.finish("page-cancel-run")


def test_streaming_worker_process_is_terminated_on_cancel() -> None:
    cancelled = threading.Event()
    timer = threading.Timer(0.15, cancelled.set)
    timer.start()
    started = time.monotonic()
    try:
        with pytest.raises(BacktestCancelled):
            EngineWorkerDispatcher._run_streaming(
                [sys.executable, "-c", "import time; time.sleep(30)"],
                "{}",
                10.0,
                None,
                cancelled,
            )
    finally:
        timer.cancel()

    assert time.monotonic() - started < 3.0
