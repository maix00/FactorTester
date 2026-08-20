"""Unit-level coverage for the flattened groups -> ls_configs -> BacktestRunState
pipeline that replaced _run_group_test_core (now inlined directly into
/run_group_test_stream). These exercise the new glue helpers
(_resolve_group_strategy_settings/_build_group_owner_rows/
_get_or_create_group_test_tester) without needing a full HTTP request or
real product/factor data -- the engine-level contract itself is already
covered by tests/backtest/native/test_backtester_task.py.
"""

from __future__ import annotations

import uuid

import pandas as pd
import pytest

from server.modules.single_factor_test import group as group_module
from tools.products.Product import Product


def _product() -> Product:
    return Product(name=f"P-{uuid.uuid4().hex}", point_value=1, currency="CNY")


class _FakeSelection:
    def __init__(self, selection_id: str, products: list[Product]) -> None:
        self.selection_id = selection_id
        self._products = products

    @property
    def products(self):
        return self._products


class _FakeFactor:
    """Stands in for the resolved Factor/FactorExpr evaluation contract."""

    def __init__(self, table: pd.DataFrame) -> None:
        self._table = table
        self.table = table
        self.last_products: list[Product] | None = None

    def evaluate(self, products, **kwargs) -> None:
        self.last_products = list(products)
        self.table = self._table


def test_resolve_group_strategy_settings_converts_index_and_resolves_objects(monkeypatch):
    p1, p2 = _product(), _product()
    selection = _FakeSelection("sel-1", [p1, p2])
    monkeypatch.setattr(
        "server.modules.shared.factor_tester_runtime.selection_for_product_path_selection",
        lambda data, selection_id, *, page_uuid: selection,
    )

    factor_table = pd.DataFrame({p1: [1.0], p2: [2.0]})
    factor = _FakeFactor(factor_table)
    entry_factor = _FakeFactor(factor_table)
    exit_factor = _FakeFactor(factor_table)
    page_factors_dict = {
        "FactorA": factor,
        "EntryFactor": entry_factor,
        "ExitFactor": exit_factor,
    }

    g = {
        "id": "group-1",
        "product_path_selection_id": "sel-1",
        "factor_candidate_refs": ["FactorA"],
        "factorRoleBindings": {
            "entry": "EntryFactor",
            "exit": {"factor_ref": "ExitFactor"},
        },
        "splitCount": 5,
        "groupIndex": 2,  # 1-based
    }
    selection_cache: dict = {}
    settings = group_module._resolve_group_strategy_settings(
        g, resolved_backtest_settings={"group-1": {"engine_mode": "basic"}},
        fallback_group_settings={}, page_uuid="page-1", data={}, page_factors_dict=page_factors_dict,
        selection_cache=selection_cache,
    )

    assert settings["split_count"] == 5
    assert settings["group_index"] == 1  # 0-based
    assert settings["engine_mode"] == "basic"
    assert settings["product_path_selection"] is selection
    assert selection_cache["sel-1"] is selection

    assert settings["factor"] is factor
    assert settings["factor_role_bindings"] == {
        "entry": entry_factor,
        "exit": exit_factor,
    }


def test_resolve_group_strategy_settings_strips_implicit_auto_cost_basis_default(monkeypatch):
    p1 = _product()
    selection = _FakeSelection("sel-1", [p1])
    monkeypatch.setattr(
        "server.modules.shared.factor_tester_runtime.selection_for_product_path_selection",
        lambda data, selection_id, *, page_uuid: selection,
    )
    factor = _FakeFactor(pd.DataFrame({p1: [1.0]}))
    g = {
        "id": "group-1",
        "product_path_selection_id": "sel-1",
        "factor_candidate_refs": ["FactorA"],
        "splitCount": 5,
        "groupIndex": 1,
    }

    settings = group_module._resolve_group_strategy_settings(
        g,
        resolved_backtest_settings={
            "group-1": {
                "engine_mode": "auto",
                "cost_basis_method": "WeightAverage",
                "daily_mark_to_market_enabled": False,
            }
        },
        fallback_group_settings={},
        page_uuid="page-1",
        data={},
        page_factors_dict={"FactorA": factor},
        selection_cache={},
    )

    assert "cost_basis_method" not in settings
    assert "daily_mark_to_market_enabled" not in settings


def test_resolve_group_strategy_settings_keeps_explicit_cost_basis_default(monkeypatch):
    p1 = _product()
    selection = _FakeSelection("sel-1", [p1])
    monkeypatch.setattr(
        "server.modules.shared.factor_tester_runtime.selection_for_product_path_selection",
        lambda data, selection_id, *, page_uuid: selection,
    )
    factor = _FakeFactor(pd.DataFrame({p1: [1.0]}))
    g = {
        "id": "group-1",
        "product_path_selection_id": "sel-1",
        "factor_candidate_refs": ["FactorA"],
        "splitCount": 5,
        "groupIndex": 1,
        "cost_basis_method": "WeightAverage",
    }

    settings = group_module._resolve_group_strategy_settings(
        g,
        resolved_backtest_settings={
            "group-1": {
                "engine_mode": "auto",
                "cost_basis_method": "WeightAverage",
            }
        },
        fallback_group_settings={},
        page_uuid="page-1",
        data={},
        page_factors_dict={"FactorA": factor},
        selection_cache={},
    )

    assert settings["cost_basis_method"] == "WeightAverage"


def test_resolve_group_strategy_settings_reuses_cached_selection(monkeypatch):
    p1 = _product()
    selection = _FakeSelection("sel-shared", [p1])
    calls = []

    def _fake_resolve(data, selection_id, *, page_uuid):
        calls.append(selection_id)
        return selection

    monkeypatch.setattr(
        "server.modules.shared.factor_tester_runtime.selection_for_product_path_selection",
        _fake_resolve,
    )
    page_factors_dict = {"FactorA": _FakeFactor(pd.DataFrame({p1: [1.0]}))}
    selection_cache: dict = {}

    for group_id in ("group-1", "group-2"):
        g = {
            "id": group_id, "product_path_selection_id": "sel-shared",
            "factor_candidate_refs": ["FactorA"], "splitCount": 2, "groupIndex": 1,
        }
        group_module._resolve_group_strategy_settings(
            g, resolved_backtest_settings={}, fallback_group_settings={},
            page_uuid="page-1", data={}, page_factors_dict=page_factors_dict,
            selection_cache=selection_cache,
        )

    assert calls == ["sel-shared"]  # only resolved once, second group reused the cache


def test_resolve_group_strategy_settings_keeps_full_factor_pool_and_passes_product_mask(monkeypatch):
    p1, p2, p3 = _product(), _product(), _product()
    selection = _FakeSelection("sel-1", [p1, p2, p3])
    monkeypatch.setattr(
        "server.modules.shared.factor_tester_runtime.selection_for_product_path_selection",
        lambda data, selection_id, *, page_uuid: selection,
    )
    factor = _FakeFactor(pd.DataFrame({p1: [1.0], p2: [2.0], p3: [3.0]}))
    g = {
        "id": "group-1",
        "product_path_selection_id": "sel-1",
        "factor_candidate_refs": ["FactorA"],
        "splitCount": 2,
        "groupIndex": 1,
        "productMask": {p2.name: True, p3.name: True},
    }

    settings = group_module._resolve_group_strategy_settings(
        g, resolved_backtest_settings={}, fallback_group_settings={},
        page_uuid="page-1", data={}, page_factors_dict={"FactorA": factor},
        selection_cache={},
    )

    assert settings["product_path_selection"] is selection
    assert settings["product_mask_names"] == (p2.name, p3.name)
    assert settings["factor"] is factor


def test_resolve_group_strategy_settings_missing_factor_raises(monkeypatch):
    monkeypatch.setattr(
        "server.modules.shared.factor_tester_runtime.selection_for_product_path_selection",
        lambda data, selection_id, *, page_uuid: _FakeSelection(selection_id, []),
    )
    g = {
        "id": "group-1", "product_path_selection_id": "sel-1",
        "factor_candidate_refs": ["Missing"], "splitCount": 2, "groupIndex": 1,
    }
    with pytest.raises(ValueError, match="未找到因子"):
        group_module._resolve_group_strategy_settings(
            g, resolved_backtest_settings={}, fallback_group_settings={},
            page_uuid="page-1", data={}, page_factors_dict={}, selection_cache={},
        )


def test_build_group_owner_rows_shape():
    groups = [
        {"id": "g1", "name": "batch:1/g1", "groupIndex": 1,
         "product_path_selection_id": "sel-1", "factor_candidate_refs": ["FactorA"]},
        {"id": "g2", "name": "G2", "groupIndex": 3,
         "product_path_selection_id": "sel-1", "factor_candidate_refs": ["FactorA"]},
    ]
    rows = group_module._build_group_owner_rows(groups, is_ls=False)
    assert rows == [
        {"strategy_id": "g1", "display_name": "batch:1/g1",
         "group_id": "g1", "group_name": "batch:1/g1", "group_index": 0,
         "product_path_selection_id": "sel-1", "factor_ref": "FactorA", "is_ls": False},
        {"strategy_id": "g2", "display_name": "G2",
         "group_id": "g2", "group_name": "G2", "group_index": 2,
         "product_path_selection_id": "sel-1", "factor_ref": "FactorA", "is_ls": False},
    ]


def test_serialize_event_execution_accepts_orderflow_trace_list():
    execution = {
        "group_owner": [
            {
                "group_id": "g1",
                "group_name": "A1",
                "group_index": 0,
                "product_path_selection_id": "sel-1",
                "factor_alias": "FactorA",
                "is_ls": False,
            },
        ],
        "engine_result": {
            "engine": "native",
            "portfolios": {
                "g1": {
                    "equity_curve": {
                        "2026-01-01T09:01:00+08:00": 100.0,
                        "2026-01-01T09:02:00+08:00": 101.0,
                    },
                    "position_curve": {},
                    "execution_trace": [
                        {
                            "timestamp": "2026-01-01T09:02:00+08:00",
                            "order_id": "o2",
                            "step": "finalize_order",
                            "details": {"status": "filled"},
                        },
                        {
                            "timestamp": "2026-01-01T09:01:00+08:00",
                            "order_id": "o1",
                            "step": "construct_order",
                            "details": {"quantity": 1.0},
                        },
                    ],
                },
            },
            "target_trace": {"g1": {}},
            "strategy_diagnostics": {},
        },
    }

    serialized = group_module._serialize_event_execution(
        execution,
        settings_by_group={
            "g1": {
                "allocation_policy": "equal_notional",
                "rebalance_trigger": "on_factor_signal",
                "position_policy": "rebalance_to_target",
            },
        },
        evaluation_split=None,
    )

    strategy = serialized["engine_result"]["comparison"]["strategies"][0]
    assert strategy["execution_trace_points"] == 2
    assert strategy["execution_trace_checksum"]
    assert set(serialized["metrics"]) == {"A1"}
    assert serialized["groups"][0]["strategy_id"] == "g1"
    assert serialized["groups"][0]["display_name"] == "A1"
    assert serialized["groups"][0]["metrics_key"] == "A1"
    assert "key" not in serialized["groups"][0]
    assert "name" not in serialized["groups"][0]


def test_serialize_event_execution_reports_event_notional_turnover():
    execution = {
        "group_owner": [{
            "group_id": "g1", "group_name": "A1", "group_index": 0,
            "product_path_selection_id": "sel-1", "factor_alias": "FactorA",
            "is_ls": False,
        }],
        "engine_result": {
            "engine": "native",
            "portfolios": {"g1": {
                "equity_curve": {
                    "2026-01-01T09:01:00+08:00": 100.0,
                    "2026-01-01T09:02:00+08:00": 100.0,
                },
                "display_equity_curve": {
                    "2026-01-01T09:01:00+08:00": 100.0,
                    "2026-01-01T09:02:00+08:00": 100.0,
                },
                "notional_curve": {
                    "2026-01-01T09:01:00+08:00": {"A": 0.0},
                    "2026-01-01T09:02:00+08:00": {"A": 200.0},
                },
                "position_curve": {
                    "2026-01-01T09:01:00+08:00": {"A": 0.0},
                    "2026-01-01T09:02:00+08:00": {"A": 1.0},
                },
            }},
            "target_trace": {"g1": {}}, "strategy_diagnostics": {},
        },
    }
    serialized = group_module._serialize_event_execution(
        execution,
        settings_by_group={"g1": {
            "allocation_policy": "equal_notional",
            "rebalance_trigger": "on_factor_signal",
            "position_policy": "rebalance_to_target",
        }},
        evaluation_split=None,
    )
    assert serialized["metrics"]["A1"]["Avg Turnover"] == 1.0
    assert serialized["groups"][0]["turnover_source"] == "event_notional_curve"
    assert "not fill-only" in serialized["groups"][0]["turnover_semantics"]


def test_serialize_event_execution_prefers_fill_audit_turnover():
    execution = {
        "group_owner": [{
            "group_id": "g1", "group_name": "A1", "group_index": 0,
            "product_path_selection_id": "sel-1", "factor_alias": "FactorA",
            "is_ls": False,
        }],
        "engine_result": {
            "engine": "native",
            "portfolios": {"g1": {
                "equity_curve": {
                    "2026-01-01T09:01:00+08:00": 100.0,
                    "2026-01-01T09:02:00+08:00": 100.0,
                },
                "fill_turnover": {
                    "average": 0.25, "observations": 1, "source": "fill_audit",
                },
                "notional_curve": {
                    "2026-01-01T09:01:00+08:00": {"A": 0.0},
                    "2026-01-01T09:02:00+08:00": {"A": 900.0},
                },
            }},
            "target_trace": {"g1": {}}, "strategy_diagnostics": {},
        },
    }
    serialized = group_module._serialize_event_execution(
        execution,
        settings_by_group={"g1": {
            "allocation_policy": "equal_notional",
            "rebalance_trigger": "on_factor_signal",
            "position_policy": "rebalance_to_target",
        }},
        evaluation_split=None,
    )
    assert serialized["metrics"]["A1"]["Avg Turnover"] == 0.25
    assert serialized["groups"][0]["turnover_source"] == "fill_audit"
    assert "fill_notional_over_equity" in serialized["groups"][0]["turnover_semantics"]


def test_serialize_event_execution_can_omit_summary_trace_checksum():
    execution = {
        "group_owner": [{
            "group_id": "g1", "group_name": "A1", "group_index": 0,
            "product_path_selection_id": "sel-1", "factor_alias": "FactorA",
            "is_ls": False,
        }],
        "engine_result": {
            "engine": "native",
            "portfolios": {
                "g1": {
                    "equity_curve": {
                        "2026-01-01T09:01:00+08:00": 100.0,
                        "2026-01-01T09:02:00+08:00": 101.0,
                    },
                    "execution_trace": [{
                        "timestamp": "2026-01-01T09:02:00+08:00",
                        "order_id": "o1", "step": "fill",
                    }],
                },
            },
            "target_trace": {"g1": {}},
            "strategy_diagnostics": {},
        },
    }
    serialized = group_module._serialize_event_execution(
        execution,
        settings_by_group={"g1": {
            "allocation_policy": "equal_notional",
            "rebalance_trigger": "on_factor_signal",
            "position_policy": "rebalance_to_target",
        }},
        evaluation_split=None,
        include_execution_trace_checksums=False,
    )
    strategy = serialized["engine_result"]["comparison"]["strategies"][0]
    assert strategy["execution_trace_points"] == 1
    assert strategy["execution_trace_checksum"] is None


def test_serialize_event_execution_keeps_duplicate_display_metrics_distinct():
    owners = [
        {
            "group_id": group_id,
            "group_name": "A1",
            "group_index": 0,
            "product_path_selection_id": "sel-1",
            "factor_alias": factor_alias,
            "is_ls": False,
        }
        for group_id, factor_alias in (("factor-a-a1", "FactorA"), ("factor-b-a1", "FactorB"))
    ]
    portfolios = {
        "factor-a-a1": {
            "equity_curve": {
                "2026-01-01T09:01:00+08:00": 100.0,
                "2026-01-01T09:02:00+08:00": 101.0,
            },
        },
        "factor-b-a1": {
            "equity_curve": {
                "2026-01-01T09:01:00+08:00": 100.0,
                "2026-01-01T09:02:00+08:00": 99.0,
            },
        },
    }
    settings = {
        owner["group_id"]: {
            "allocation_policy": "equal_notional",
            "rebalance_trigger": "on_factor_signal",
            "position_policy": "rebalance_to_target",
        }
        for owner in owners
    }

    serialized = group_module._serialize_event_execution(
        {
            "group_owner": owners,
            "engine_result": {
                "engine": "native",
                "portfolios": portfolios,
                "target_trace": {},
                "strategy_diagnostics": {},
            },
        },
        settings_by_group=settings,
        evaluation_split=None,
    )

    assert set(serialized["metrics"]) == {"factor-a-a1", "factor-b-a1"}
    assert [group["metrics_key"] for group in serialized["groups"]] == [
        "factor-a-a1",
        "factor-b-a1",
    ]
    assert serialized["metrics"]["factor-a-a1"]["Total Return"] > 0
    assert serialized["metrics"]["factor-b-a1"]["Total Return"] < 0


def test_event_order_flow_detail_filters_by_group_and_timestamp_ms():
    execution = {
        "group_owner": [
            {
                "group_id": "g1",
                "group_name": "A1",
                "group_index": 0,
                "product_path_selection_id": "sel-1",
                "is_ls": False,
            },
            {
                "group_id": "g2",
                "group_name": "A2",
                "group_index": 1,
                "product_path_selection_id": "sel-1",
                "is_ls": False,
            },
        ],
        "engine_result": {
            "portfolios": {
                "g1": {
                    "execution_trace": [
                        {
                            "timestamp": "2026-01-01T09:01:00.000000001+08:00",
                            "order_id": "o1",
                            "step": "construct_order",
                        },
                        {
                            "timestamp": "2026-01-01T09:02:00+08:00",
                            "order_id": "o2",
                            "step": "construct_order",
                        },
                    ],
                },
                "g2": {
                    "execution_trace": [
                        {
                            "timestamp": "2026-01-01T09:01:00+08:00",
                            "order_id": "other",
                            "step": "construct_order",
                        },
                    ],
                },
            },
        },
    }

    timestamp_ms = int(pd.Timestamp("2026-01-01T09:01:00+08:00").timestamp() * 1000)
    detail = group_module._event_order_flow_detail(
        execution,
        group_id="g1",
        timestamp_ms=timestamp_ms,
    )

    assert detail["success"] is True
    assert detail["record_count"] == 1
    assert detail["groups"][0]["records"][0]["order_id"] == "o1"


def test_long_short_default_id_matches_settings_and_owner_rows():
    source_settings = {
        f"g{i}": {
            "strategy_id": f"g{i}",
            "factor": object(),
            "product_path_selection": object(),
            "strategy_intent_mode": "group",
            "strategy_kind": "group",
        }
        for i in range(7)
    }
    ls_config = {
        "name": "",
        "long_group_id": "g0",
        "short_group_id": "g6",
    }
    normalized = dict(ls_config)
    strategy_id = group_module._long_short_strategy_id(normalized, 0)
    normalized["strategy_id"] = strategy_id
    normalized.setdefault("id", strategy_id)

    settings = group_module._resolve_long_short_strategy_settings(
        normalized,
        resolved_backtest_settings={},
        source_settings_by_alias=source_settings,
        fallback_group_settings={
            "engine_mode": "auto",
            "cost_basis_method": "WeightAverage",
        },
    )
    assert "cost_basis_method" not in settings
    owner_rows = group_module._build_long_short_owner_rows(
        [normalized],
        source_owner_by_id={
            "g0": {
                "group_id": "g0",
                "product_path_selection_id": "sel-1",
                "factor_alias": "FactorA",
            },
            "g6": {
                "group_id": "g6",
                "product_path_selection_id": "sel-1",
                "factor_alias": "FactorA",
            },
        },
    )

    assert strategy_id == "ls-0"
    assert settings["strategy_id"] == "ls-0"
    assert settings["strategy_intent_mode"] == "long_short"
    assert settings["strategy_kind"] == "long_short"
    assert settings["long_leg_strategy_ids"] == [{"strategy_id": "g0", "group_id": "g0", "weight": 1.0}]
    assert settings["short_leg_strategy_ids"] == [{"strategy_id": "g6", "group_id": "g6", "weight": 1.0}]
    assert owner_rows[0]["group_id"] == "ls-0"


def test_get_or_create_group_test_tester_reuses_same_instance_per_page():
    import server.services.page_runtime as runtime_state

    page_uuid = f"page-{uuid.uuid4().hex}"
    try:
        first = group_module._get_or_create_group_test_tester(page_uuid)
        second = group_module._get_or_create_group_test_tester(page_uuid)
        assert first is second
    finally:
        runtime_state.page_objects.pop(page_uuid, None)
