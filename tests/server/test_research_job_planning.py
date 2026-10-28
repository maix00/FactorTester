from __future__ import annotations

from types import SimpleNamespace

import pytest

from server.modules.single_factor_test.planning import (
    build_execution_plan,
    verify_execution_plan,
)
from server.services.research_run_identity import NAUTILUS_RUN_SPEC_VERSION


def _run_spec():
    adapter = {
        "adapter_id": "local_cnfutures_contract_minute_parquet_v1",
        "frequency": "MIN1",
        "feed_kind": "bar",
        "clock_policy": "end_label_utc_ns_validated_from_exchange_wall_time",
    }
    return {
        "run_spec_version": NAUTILUS_RUN_SPEC_VERSION,
        "configuration": {
            "shared": {
                "factors": [{"ref": "factor:v2:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}],
                "product_selections": {
                    "scope:t": {
                        "paths": ["Product/Futures/CNFutures/_products/T.CFE"],
                        "resolution_sha256": "scope-resolution-sha256",
                    },
                },
            },
            "analyses": {
                "backtest": {
                    "groups": [{
                        "id": "strategy:t",
                        "product_path_selection_id": "scope:t",
                    }],
                    "execution": {
                        "backend": "nautilus_trader",
                        "contract_version": 4,
                        "settings": {},
                        "nautilus_contract": {
                            "contract_version": 2,
                            "blockers": [],
                            "source_adapter": adapter,
                            "settings": {
                                "data_source_ref": "LocalCNFuturesContractMIN1",
                                "product_scope_refs": ["scope:t"],
                                "start_utc": "2025-04-01T01:00:00+00:00",
                                "end_utc": "2025-05-01T07:15:00+00:00",
                                "strategy_venue_bindings": [{
                                    "strategy_id": "strategy:t",
                                    "venue_ids": ["CFFEX"],
                                }],
                            },
                        },
                    },
                },
            },
        },
    }


def _install_compiler_mocks(monkeypatch):
    from server.services.nautilus_bridge import config, source_registry
    from server.services import factor_revisions

    adapter = SimpleNamespace(
        adapter_id="local_cnfutures_contract_minute_parquet_v1",
        frequency="MIN1",
        instrument_scope="physical_contract",
        clock_policy="end_label_utc_ns_validated_from_exchange_wall_time",
    )
    registry = SimpleNamespace(adapter_for=lambda **_: adapter)
    monkeypatch.setattr(source_registry, "from_server_sources", lambda: registry)
    monkeypatch.setattr(
        factor_revisions, "assert_run_spec_factor_revisions_resolvable",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(config, "compile_frozen_execution_plan", lambda *_args, **_kwargs:
                        SimpleNamespace(
                            start_utc="2025-04-01T01:00:00+00:00",
                            end_utc="2025-05-01T07:15:00+00:00",
                            manifest=lambda: {"timing": "next_bar_open"},
                        ))


def test_backtest_plan_uses_only_immutable_nautilus_runspec(monkeypatch):
    _install_compiler_mocks(monkeypatch)
    run_spec = _run_spec()

    plan = build_execution_plan("backtest", {"_owner": "alice", "run_spec": run_spec})

    assert plan["resolved"]["run_spec_version"] == NAUTILUS_RUN_SPEC_VERSION
    assert plan["resolved"]["run_spec_sha256"]
    assert plan["resolved"]["source_adapter"] == {
        "member_key": "LocalCNFuturesContractMIN1",
        "adapter_id": "local_cnfutures_contract_minute_parquet_v1",
        "frequency": "MIN1",
        "instrument_scope": "physical_contract",
        "clock_policy": "end_label_utc_ns_validated_from_exchange_wall_time",
    }
    assert plan["resolved"]["strategies"] == [{
        "strategy_id": "strategy:t",
        "product_scope_ref": "scope:t",
        "venue_ids": ["CFFEX"],
    }]
    assert plan["resolved"]["factor_refs"] == ["factor:v2:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"]
    assert plan["resolved"]["data_requirements"] == [{
        "product_scope_ref": "scope:t",
        "resolution_sha256": "scope-resolution-sha256",
        "path_count": 1,
        "source_member": "LocalCNFuturesContractMIN1",
        "adapter_id": "local_cnfutures_contract_minute_parquet_v1",
        "frequency": "MIN1",
        "start_utc": "2025-04-01T01:00:00+00:00",
        "end_utc": "2025-05-01T07:15:00+00:00",
    }]

    payload = {"_owner": "alice", "run_spec": run_spec, "execution_plan": plan}
    verify_execution_plan("backtest", payload)
    run_spec["configuration"]["shared"]["product_selections"]["scope:t"]["paths"].append(
        "Product/Futures/CNFutures/_products/TL.CFE",
    )
    with pytest.raises(RuntimeError, match="changed after planning"):
        verify_execution_plan("backtest", payload)


@pytest.mark.parametrize("run_spec", [None, {
    "run_spec_version": 4,
    "configuration": {"shared": {"factors": []}},
}])
def test_backtest_plan_rejects_retired_or_missing_runspec(run_spec):
    with pytest.raises(ValueError, match="frozen NautilusTrader RunSpec|read-only"):
        build_execution_plan("backtest", {"run_spec": run_spec})


def test_backtest_plan_rejects_scope_that_was_not_frozen(monkeypatch):
    _install_compiler_mocks(monkeypatch)
    run_spec = _run_spec()
    run_spec["configuration"]["shared"]["product_selections"] = {}

    with pytest.raises(ValueError, match="product scope is not frozen"):
        build_execution_plan("backtest", {"run_spec": run_spec})


def test_backtest_plan_rejects_source_adapter_drift(monkeypatch):
    _install_compiler_mocks(monkeypatch)
    run_spec = _run_spec()
    run_spec["configuration"]["analyses"]["backtest"]["execution"][
        "nautilus_contract"]["source_adapter"]["adapter_id"] = "other-adapter"

    with pytest.raises(ValueError, match="differs from the registered adapter"):
        build_execution_plan("backtest", {"run_spec": run_spec})


def test_backtest_plan_fails_closed_on_frozen_execution_blockers(monkeypatch):
    _install_compiler_mocks(monkeypatch)
    run_spec = _run_spec()
    run_spec["configuration"]["analyses"]["backtest"]["execution"][
        "nautilus_contract"]["blockers"] = [{"reason": "official settlement rules missing"}]

    with pytest.raises(ValueError, match="official settlement rules missing"):
        build_execution_plan("backtest", {"run_spec": run_spec})
