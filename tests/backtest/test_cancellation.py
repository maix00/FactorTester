from __future__ import annotations

import sys
import threading
import time

import pytest

from server.services import backtest_runs
from tools.backtest.cancellation import BacktestCancelled
from tools.backtest.workers.dispatcher import EngineWorkerDispatcher


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
