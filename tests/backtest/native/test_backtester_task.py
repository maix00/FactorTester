"""run_backtest_task is the "backtester" FactorTester.dispatch("backtest",
...) calls. This locks down the exact `execution` dict shape that
server/modules/single_factor_test/group.py's _serialize_event_execution/
_event_group_snapshot/_event_group_detail/_event_group_ranking_detail
already read -- that contract predates this function.
"""

from __future__ import annotations

import uuid

import pandas as pd
import pytest

from tools.factors.factor_tester_state import FactorTesterState
from tools.products.Product import Product
from tools.testers.backtest.engines.native.backtester import run_backtest_task
from tools.testers.backtest.engines.native.ledger import AccountState
from tools.testers.backtest.engines.native.strategy_config_builder import apply_strategy_configs


def _product() -> Product:
    return Product(name=f"P-{uuid.uuid4().hex}", point_value=1, currency="CNY")


class _FakeProductPathSelection:
    def __init__(self, selection_id, products):
        self.selection_id = selection_id
        self._products = products

    @property
    def products(self):
        return self._products


class _FakeFactor:
    def __init__(self, table: pd.DataFrame) -> None:
        self._table = table

    def evaluate(self):
        return self._table


def test_run_backtest_task_produces_the_execution_dict_contract():
    p1, p2 = _product(), _product()
    idx = pd.date_range("2024-01-01", periods=3, freq="D")
    raw_prices = pd.DataFrame({p1: [10.0, 11.0, 12.0], p2: [20.0, 19.0, 18.0]}, index=idx)
    factor_table = pd.DataFrame({p1: [1.0, 2.0, 1.0], p2: [2.0, 1.0, 2.0]}, index=idx)
    selection = _FakeProductPathSelection("sel-1", [p1, p2])
    factor = _FakeFactor(factor_table)

    resolved_settings = {
        "A1": {
            "product_path_selection": selection, "factor": factor, "factor_mode": "precomputed",
            "split_count": 2, "group_index": 1, "initial_capital_major": 1_000_000.0,
            "base_currency": "CNY", "engine_mode": "basic",
        },
    }
    account = AccountState()
    apply_strategy_configs(account, resolved_settings)
    account.raw_market_data = {"raw_prices": raw_prices}

    state = FactorTesterState(products=[])
    execution = run_backtest_task(
        state, account=account,
        group_owner=[{"group_id": "A1", "group_name": "A1", "group_index": 0,
                      "product_path_selection_id": "sel-1", "factor_alias": "f1", "is_ls": False}],
        settings_by_strategy=resolved_settings, run_id="run-1",
    )

    assert execution["run_id"] == "run-1"
    assert execution["group_owner"][0]["group_id"] == "A1"
    assert execution["settings_by_strategy"] is resolved_settings
    assert execution["payload"] == {"run_id": "run-1", "instruments": [], "market_rules": {}}
    assert execution["signal_kind"] == "native"

    engine_result = execution["engine_result"]
    assert engine_result["engine"] == "native"
    assert isinstance(engine_result["event_count"], int)
    assert engine_result["strategy_diagnostics"] == {}

    portfolio = engine_result["portfolios"]["A1"]
    assert portfolio["equity_curve"]
    assert all(isinstance(k, str) for k in portfolio["equity_curve"])
    assert portfolio["position_curve"]
    assert portfolio["execution_trace"] == {}
    assert portfolio["initial_value"] == pytest.approx(1_000_000.0, rel=0.05)
    assert portfolio["market_rule_approximation_count"] == 0

    assert "A1" in engine_result["target_trace"]

    # state.account must be set so a later snapshot/detail request can
    # read the same run without re-executing anything.
    assert state.account is account
