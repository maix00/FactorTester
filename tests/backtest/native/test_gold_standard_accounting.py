"""Gold-standard accounting E2E: drives the REAL scheduler (every module in
_ALL_MODULE_CLASSES, real build_strategy_configs, real run()) through a
hand-computable margin-accounting scenario and asserts the exact ledger
trajectory for each cost-basis method.

The scenario is designed so the cost-basis methods MUST diverge on realized
P&L (two opens at different prices, then a partial close) while total equity
MUST stay method-independent (realized + floating always sums to the same
total) -- both are industry clearing semantics (futures margin accounting),
not descriptions of what the current code happens to do.

Scenario (margin_mode=fixed 0.1, no fees, no slippage, multiplier 1,
initial capital 1,000,000, two products in one group at 0.5/0.5 equal
notional, signals on D1/D3/D5, next-bar-open fills on D2/D4/D6):

    prices      D1      D2      D3      D4      D5      D6
    p1         100     100      80      80     120     120
    p2         100     100     100     100     100     100

    D1 signal: equity 1,000,000 -> targets q1=5,000@100, q2=5,000@100
    D2 fill:   margin 50,000+50,000 locked -> cash 900,000
    D3 signal: floating p1 = 5,000*(80-100) = -100,000
               equity = 900,000 + 100,000 (margin) - 100,000 = 900,000
               targets q1 = 0.5*900,000/80 = 5,625 (+625 @80, second lot)
                       q2 = 0.5*900,000/100 = 4,500 (-500, realized 0)
    D4 fill:   p1 margin keeps each lot's execution-cost basis:
                         5,000*100*0.1 + 625*80*0.1 = 55,000
               p2 margin 4,500*100*0.1 = 45,000 (releases 5,000)
               cash = 900,000
    D5 signal: floating p1 = 120*5,625 - (5,000*100 + 625*80) = +125,000
               equity = 900,000 + 100,000 + 125,000 = 1,125,000
               targets q1 = 0.5*1,125,000/120 = 4,687.5 (-937.5 @120)
                       q2 = 0.5*1,125,000/100 = 5,625   (+1,125 @100)
    D6 fill:   p1 partial close 937.5 @120 -- THE method-divergent trade:
                 WeightAverage: cost 550,000/5,625 = 97.7778
                                realized = 937.5*(120-97.7778) = 20,833.33
                 FIFO: consumes the 5,000@100 lot first
                                realized = 937.5*(120-100)     = 18,750
                 LIFO: consumes the 625@80 lot first, then 312.5@100
                                realized = 625*40 + 312.5*20   = 31,250
                 HIFO: consumes the highest-cost (100) lot first
                                realized = 937.5*(120-100)     = 18,750
               p1 margin releases the consumed lots' execution-cost margin:
                 WeightAverage: 937.5*97.7778*0.1 = 9,166.67
                 FIFO/HIFO:     937.5*100*0.1     = 9,375
                 LIFO:          (625*80 + 312.5*100)*0.1 = 8,125
               p2 margin locks 1,125*100*0.1 = 11,250
               final cash = 900,000 + realized + p1 margin released
                            - 11,250
               final equity = cash + remaining cost-basis margin + floating
                            = 1,125,000 for EVERY method (invariant)
"""

from __future__ import annotations

import uuid

import pandas as pd
import pytest

from tools.products.Product import Product
from tools.testers.backtest.engines.native.state import BacktestRunState
from tools.testers.backtest.engines.native.scheduler import EventQueue, FlowRegistry, run
from tools.testers.backtest.engines.native.strategy_config_builder import apply_strategy_configs
from tools.testers.backtest.modules.cash_pool import cash_for_ledger
from tools.testers.backtest.modules.equity_curve import equity_curve_for
from tools.testers.backtest.modules.ledger_module import LedgerModule
from tools.testers.backtest.modules.registry import _ALL_MODULE_CLASSES


def _product() -> Product:
    return Product(name=f"P-{uuid.uuid4().hex}", point_value=1, currency="CNY")


class _FakeProductPathSelection:
    def __init__(self, selection_id: str, products: list[Product]) -> None:
        self.selection_id = selection_id
        self._products = products

    @property
    def products(self):
        return self._products


class _FakeFactor:
    def __init__(self, table: pd.DataFrame) -> None:
        self._table = table

    def evaluate(self) -> pd.DataFrame:
        return self._table


def _build_registry() -> FlowRegistry:
    registry = FlowRegistry()
    for cls in _ALL_MODULE_CLASSES:
        for flow in getattr(cls, "flows", ()):
            registry.register_flow(flow)
    return registry


def _run_gold_standard(
    cost_basis_method: str,
    step_records: list[dict] | None = None,
) -> tuple[BacktestRunState, object]:
    p1, p2 = _product(), _product()
    idx = pd.date_range("2024-01-01", periods=6, freq="D")
    raw_prices = pd.DataFrame(
        {p1: [100.0, 100.0, 80.0, 80.0, 120.0, 120.0],
         p2: [100.0] * 6},
        index=idx,
    )
    # signals only on D1/D3/D5 -> fills land on D2/D4/D6 (next bar open)
    factor_table = pd.DataFrame(
        {p1: [1.0, 1.0, 1.0], p2: [1.0, 1.0, 1.0]},
        index=idx[[0, 2, 4]],
    )

    resolved_settings = {
        "GOLD": {
            "product_path_selection": _FakeProductPathSelection("sel-gold", [p1, p2]),
            "factor": _FakeFactor(factor_table),
            "factor_mode": "precomputed",
            "split_count": 1,
            "group_index": 0,  # single bucket containing both products
            "initial_capital_major": 1_000_000.0,
            "base_currency": "CNY",
            "engine_mode": "custom",
            "accounting_mode": "Custom",
            "cost_basis_method": cost_basis_method,
            "use_int_position": False,
            "margin_mode": "fixed",
            "fixed_margin_ratio": 0.1,
            # This fixture isolates cost-basis accounting at 1x gross.
            # Margin-enabled production defaults are tested separately at 80/85%.
            "target_margin_utilization": 0.1,
            "max_margin_utilization": 0.85,
        },
    }

    account = BacktestRunState()
    apply_strategy_configs(account, resolved_settings)
    account.raw_market_data = {
        "raw_prices": raw_prices,
        "price_tables": {"open": raw_prices, "close": raw_prices},
    }

    registry = _build_registry()
    run(
        account, EventQueue(), registry.resolve(),
        step_mode=step_records is not None,
        step_callback=step_records.append if step_records is not None else None,
    )
    strategy = next(iter(account.strategy_configs))
    return account, strategy


# Ordinary fills preserve each lot's execution-cost margin basis.  Closing p1
# releases the consumed lots' margin; opening more p2 locks 11,250.  Repricing
# all remaining p1 lots at 120 here would be a DMTM operation and is therefore
# intentionally not part of this ORDER settlement.
_EXPECTED_FINAL_CASH = {
    "WeightAverage": (
        900_000.0
        + 937.5 * (120.0 - 550_000.0 / 5_625.0)
        + 937.5 * (550_000.0 / 5_625.0) * 0.1
        - 11_250.0
    ),  # 918,750
    "FIFO": 900_000.0 + 18_750.0 + 9_375.0 - 11_250.0,  # 916,875
    "LIFO": 900_000.0 + 31_250.0 + 8_125.0 - 11_250.0,  # 928,125
    "HIFO": 900_000.0 + 18_750.0 + 9_375.0 - 11_250.0,  # 916,875
}


@pytest.mark.parametrize("method", ["WeightAverage", "FIFO", "LIFO", "HIFO"])
def test_equity_trajectory_is_cost_basis_independent(method: str):
    """Total equity (cash + margin + floating P&L) never depends on the
    cost-basis method -- realized and floating P&L are two halves of the
    same total. A method whose floating P&L reads as zero (e.g. lots that
    were never populated) breaks this invariant immediately."""
    account, strategy = _run_gold_standard(method)
    curve = equity_curve_for(account, strategy)
    idx = pd.date_range("2024-01-01", periods=6, freq="D")

    # Fills execute at signal_time + 1ns (next-bar-open boundary event, at
    # the next row's price), so each signal day carries two curve points:
    # pre-trade (signal) and post-trade (order). Normalizing keeps the
    # post-trade value per day.
    by_day = {ts.normalize(): value for ts, value in curve.items()}
    assert by_day[idx[0]] == pytest.approx(1_000_000.0, abs=1.0)
    assert by_day[idx[2]] == pytest.approx(900_000.0, abs=1.0), (
        "D3 equity must reflect the -100,000 floating loss on p1")
    assert by_day[idx[4]] == pytest.approx(1_125_000.0, abs=1.0), (
        "D5 equity must reflect the +125,000 floating gain on p1")
    assert curve.iloc[-1] == pytest.approx(1_125_000.0, abs=1.0), (
        "final equity is method-independent: realized+floating always sum "
        "to the same total")


@pytest.mark.parametrize("method", ["WeightAverage", "FIFO", "LIFO", "HIFO"])
def test_final_cash_reflects_per_method_realized_pnl(method: str):
    """The D6 partial close of p1 (937.5 of a 5,000@100 + 625@80 position
    at 120) realizes a different P&L under each cost-basis method; the
    realized amount is swept into cash at the fill. This is the industry
    lot-accounting contract -- weighted-average realized P&L under a FIFO
    setting is wrong even though total equity hides the difference."""
    account, strategy = _run_gold_standard(method)
    cash = cash_for_ledger(account, account.ledger_for_strategy(strategy)).to_major()
    assert cash == pytest.approx(_EXPECTED_FINAL_CASH[method], abs=1.0)


def test_fill_settlement_records_realized_pnl_from_ledger_accounting():
    account, _ = _run_gold_standard("FIFO")

    realized = [
        settlement.realized_pnl
        for settlement in account.order_store.settlements_by_fill.values()
        if abs(settlement.realized_pnl) > 1e-12
    ]

    assert realized == [pytest.approx(18_750.0)]


@pytest.mark.parametrize("method", ["FIFO", "LIFO", "HIFO"])
def test_lot_methods_track_open_lots_in_the_ledger(method: str):
    """After D6 the p1 position is 4,687.5 held across the surviving lots.
    Lot-based methods must actually maintain the lot queue through engine
    fills -- an empty lot queue means floating P&L silently reads as zero."""
    account, strategy = _run_gold_standard(method)
    positions = account.ledger_for_strategy(strategy).get(LedgerModule.positions)
    lot_totals = sorted(
        float(sum(abs(lot.quantity) for lot in entry.lots or ()))
        for entry in positions.values()
        if float(getattr(entry, "quantity", 0.0) or 0.0) > 0
    )
    # p1 holds 4,687.5 and p2 holds 5,625 -- both must be fully lot-backed.
    assert lot_totals == [pytest.approx(4_687.5), pytest.approx(5_625.0)]


def test_real_scheduler_step_reports_margin_budget_gross_leverage() -> None:
    records: list[dict] = []

    _run_gold_standard("FIFO", records)

    target_steps = [row for row in records if row["flow_id"] == "apply_target_margin_budget"]
    assert target_steps
    changes = {
        row["field"]: row["after"]
        for row in target_steps[0]["output_changes"]
    }
    summary = changes["MarginBudgetModule.margin_budget_summary"]
    assert next(iter(summary.values()))["gross_leverage"] == pytest.approx(1.0)
