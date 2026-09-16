"""Queueing must stay memory-safe: the pool's budgets are configurable.

Each execution worker keeps warm datasets and its own working set while the
website shares the same host, so the ceiling, the cache size and the worker
count all have to be tunable per deployment instead of hard-coded for a large
machine.
"""

from __future__ import annotations

from server.jobs.scheduling.worker_pool import env_positive_int


def test_env_budget_reads_positive_integer(monkeypatch):
    monkeypatch.setenv("GTHT_TEST_BUDGET", "16")
    assert env_positive_int("GTHT_TEST_BUDGET", 128) == 16


def test_env_budget_falls_back_on_missing_or_invalid(monkeypatch):
    monkeypatch.delenv("GTHT_TEST_BUDGET", raising=False)
    assert env_positive_int("GTHT_TEST_BUDGET", 128) == 128
    for raw in ("", "  ", "abc", "0", "-3", "1.5"):
        monkeypatch.setenv("GTHT_TEST_BUDGET", raw)
        assert env_positive_int("GTHT_TEST_BUDGET", 128) == 128


def test_worker_pool_defaults_are_read_at_construction(monkeypatch):
    """The pool resolves its budgets from the environment, not at import."""
    import inspect

    from server.jobs.scheduling import worker_pool as module

    source = inspect.getsource(module.LongLivedWorkerPool.__init__)
    assert "GTHT_JOB_WORKER_MAX_CACHE_KEYS" in source
    assert "GTHT_JOB_WORKER_RECYCLE_PEAK_RSS_BYTES" in source
    daemon_source = inspect.getsource(
        __import__("server.jobs.scheduling.daemon", fromlist=["x"]).ResearchJobScheduler.__init__
    )
    assert "GTHT_JOB_PLANNER_WORKERS" in daemon_source
    assert "GTHT_JOB_EXECUTION_WORKERS" in daemon_source
