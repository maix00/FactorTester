"""Startup warmup builds the cold projections once and reports failures."""

from __future__ import annotations

from types import SimpleNamespace

from server.manager.services.startup_warmup import (
    start_warmup,
    warm_caches,
)


class _Research:
    def __init__(self, calls, fail=False):
        self.calls = calls
        self.fail = fail

    def list_visible(self, viewer):
        self.calls.append(("research", viewer))
        if self.fail:
            raise RuntimeError("peer is offline")
        return []


class _Catalog:
    def __init__(self, calls):
        self.calls = calls

    def list_reports_for_scope(self, *, viewer, scope):
        self.calls.append(("catalog", viewer, scope))
        return []


class _Factors:
    def __init__(self, calls):
        self.calls = calls

    def factor_library(self, principal):
        self.calls.append(("factors", principal))
        return {}


def test_warm_caches_builds_the_visitor_and_every_account_projection():
    calls: list[tuple] = []
    state = SimpleNamespace(
        federated_public_data=_Research(calls),
        research_catalog=_Catalog(calls),
        client_state=_Factors(calls),
    )
    timings = warm_caches(
        state, principals=["GTHT@maxa@1", "GTHT@maxb@2"], log=lambda _m: None,
    )
    # The shared (visitor) view and both accounts are warmed.
    assert ("research", None) in calls
    assert ("research", "GTHT@maxa@1") in calls
    assert ("catalog", "GTHT@maxb@2", "all") in calls
    # A factor projection is only meaningful for a real account.
    assert ("factors", "GTHT@maxa@1") in calls
    assert ("factors", None) not in calls
    assert set(timings) == {
        "research:visitor", "catalog:visitor",
        "research:GTHT@maxa@1", "catalog:GTHT@maxa@1", "factors:GTHT@maxa@1",
        "research:GTHT@maxb@2", "catalog:GTHT@maxb@2", "factors:GTHT@maxb@2",
    }
    assert all(value >= 0 for value in timings.values())


def test_warm_caches_reports_a_failure_without_raising():
    calls: list[tuple] = []
    messages: list[str] = []
    state = SimpleNamespace(
        federated_public_data=_Research(calls, fail=True),
        research_catalog=_Catalog(calls),
        client_state=_Factors(calls),
    )
    timings = warm_caches(
        state, principals=["GTHT@maxa@1"], log=messages.append,
    )
    assert timings["research:visitor"] < 0
    assert any("research:visitor failed" in message for message in messages)
    # The remaining projections still warm.
    assert timings["catalog:visitor"] >= 0


def test_start_warmup_can_be_disabled(monkeypatch):
    monkeypatch.setenv("FACTORTESTER_STARTUP_WARMUP", "0")
    assert start_warmup(SimpleNamespace(), delay_seconds=0, log=lambda _m: None) is None


def test_start_warmup_runs_in_the_background(monkeypatch):
    monkeypatch.delenv("FACTORTESTER_STARTUP_WARMUP", raising=False)
    calls: list[tuple] = []
    state = SimpleNamespace(
        federated_public_data=_Research(calls),
        research_catalog=_Catalog(calls),
        client_state=_Factors(calls),
    )
    thread = start_warmup(
        state, delay_seconds=0, log=lambda _m: None,
    )
    assert thread is not None
    thread.join(timeout=10)
    assert not thread.is_alive()
    assert ("research", None) in calls
