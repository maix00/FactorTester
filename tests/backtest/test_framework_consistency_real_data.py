"""Native vs framework-bridge consistency on real LocalCNFutures price data.

test_framework_consistency.py proves the replay semantics agree on tiny
synthetic prices. This drives the same comparison off real daily bars (two
liquid DCE/SHF products, most recent ~40 trading days) with a real momentum
factor computed from those prices — the closest thing to a production
scenario this repo can exercise without a live page/session. Skips cleanly
if the local data mirror isn't present (this is a data-dependent, not a
hermetic unit, test).
"""

from __future__ import annotations

from pathlib import Path
import time

import pandas as pd
import pytest

from tools.products.Product import Product
from tools.testers.backtest.engines.native.state import BacktestRunState
from tools.testers.backtest.engines.native.scheduler import EventQueue, FlowRegistry, run
from tools.testers.backtest.engines.native.strategy_config_builder import apply_strategy_configs
from tools.testers.backtest.engines.workers.bridge import run_framework_backtest_task
from tools.testers.backtest.engines.workers.contracts import WorkerResponse
from tools.testers.backtest.engines.workers.dispatcher import EngineWorkerDispatcher
from tools.testers.backtest.engines.workers.runners.reference import (
    run_group_strategy as reference_run_group_strategy,
)
from tools.testers.backtest.modules.equity_curve import equity_curve_for, position_curve_for
from tools.testers.backtest.modules.registry import _ALL_MODULE_CLASSES

try:
    from sources.LocalCNFutures import SOURCE_DATA_DIR
except Exception:  # pragma: no cover - source module itself unavailable
    SOURCE_DATA_DIR = None

_INSTRUMENTS = ("A.DCE", "AG.SHF")


def _local_data_available() -> bool:
    if not SOURCE_DATA_DIR:
        return False
    root = Path(SOURCE_DATA_DIR) / "main_dayk"
    return all((root / f"{name}.parquet").is_file() for name in _INSTRUMENTS)


pytestmark = pytest.mark.skipif(
    not _local_data_available(),
    reason="LocalCNFutures main_dayk parquet mirror not present on this machine",
)


def _load_real_prices(name: str, periods: int = 40) -> pd.Series:
    root = Path(SOURCE_DATA_DIR) / "main_dayk"
    frame = pd.read_parquet(root / f"{name}.parquet", columns=["trading_day", "close_price"])
    frame = frame.dropna(subset=["close_price"]).tail(periods)
    series = pd.Series(
        frame["close_price"].to_numpy(dtype=float),
        index=pd.DatetimeIndex(pd.to_datetime(frame["trading_day"])),
    )
    return series[~series.index.duplicated(keep="last")].sort_index()


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


class _InProcessReferenceDispatcher:
    def dispatch(self, request, *, timeout_seconds=0.0, progress=None, cancel_event=None):
        def _progress(completed, total, timestamp):
            if progress is not None:
                progress({
                    "completed": completed, "total": total,
                    "event_timestamp": timestamp.isoformat(),
                })

        result = reference_run_group_strategy(request.payload, _progress, engine=request.engine)
        return WorkerResponse(request.request_id, request.engine, True, result)


class _State:
    account = None


def _real_scenario(engine: str, products: tuple[Product, Product]):
    p1, p2 = products
    close_1 = _load_real_prices("A.DCE")
    close_2 = _load_real_prices("AG.SHF")
    idx = close_1.index.intersection(close_2.index).sort_values()
    assert len(idx) >= 20, f"not enough overlapping real trading days: {len(idx)}"
    raw_prices = pd.DataFrame({p1: close_1.reindex(idx), p2: close_2.reindex(idx)})

    # 5-day momentum on real closes -- a real (if simple) signal, not
    # contrived alternating numbers.
    factor_table = raw_prices.pct_change(5).fillna(0.0)

    settings = {
        "G1": {
            "product_path_selection": _FakeProductPathSelection("sel-real", [p1, p2]),
            "factor": _FakeFactor(factor_table),
            "factor_mode": "precomputed",
            "split_count": 2,
            "group_index": 1,
            "allocation_policy": "equal_notional",
            "initial_capital_major": 1_000_000.0,
            "base_currency": "CNY",
            "engine_mode": "basic",
            "engine": engine,
        },
    }
    run_state = BacktestRunState()
    apply_strategy_configs(run_state, settings)
    run_state.raw_market_data = {
        "raw_prices": raw_prices,
        "price_tables": {"open": raw_prices, "close": raw_prices},
        "lot_sizes": {p1: 1.0, p2: 1.0},
    }
    return run_state, settings


def _shared_products() -> tuple[Product, Product]:
    return (
        Product(name="A.DCE-real", point_value=1, currency="CNY"),
        Product(name="AG.SHF-real", point_value=1, currency="CNY"),
    )


def _native_curves(products):
    run_state, _ = _real_scenario("native", products)
    registry = FlowRegistry()
    for cls in _ALL_MODULE_CLASSES:
        for flow in getattr(cls, "flows", ()):
            registry.register_flow(flow)
    run(run_state, EventQueue(), registry.resolve())
    strategy = next(iter(run_state.strategy_configs))
    equity = {
        pd.Timestamp(ts).isoformat(): float(value)
        for ts, value in equity_curve_for(run_state, strategy).items()
    }
    return equity, position_curve_for(run_state, strategy)


def _bridge_curves(products, engine="backtrader", dispatcher=None):
    run_state, settings = _real_scenario(engine, products)
    execution = run_framework_backtest_task(
        _State(),
        run_state=run_state,
        engine=engine,
        group_owner=[{"group_id": "G1"}],
        settings_by_strategy=settings,
        run_id="real-data-consistency",
        dispatcher=dispatcher or _InProcessReferenceDispatcher(),
        timeout_seconds=120.0,
    )
    portfolio = execution["engine_result"]["portfolios"]["G1"]
    return dict(portfolio["equity_curve"]), dict(portfolio["position_curve"])


def test_native_and_worker_agree_on_real_price_equity_curve():
    """Bit-exact equality is not the right claim here: native maintains
    equity incrementally through its Ledger across the whole replay, while
    the worker path recomputes portfolio_value from scratch each bar. Over
    real (noisy, non-round) prices the two accumulate floating-point error
    differently and can occasionally floor a target to a different lot count
    at an exact boundary -- a one-lot difference at isolated bars, not a
    systematic drift. This asserts trajectories track tightly and reports the
    actual divergence rather than silently loosening the bound to hide a
    real regression."""
    products = _shared_products()
    native_equity, _ = _native_curves(products)
    bridge_equity, _ = _bridge_curves(products)

    assert native_equity and bridge_equity
    shared = sorted(set(native_equity) & set(bridge_equity))
    assert len(shared) >= 10, f"too few shared timestamps: {len(shared)}"
    diffs = {ts: abs(native_equity[ts] - bridge_equity[ts]) for ts in shared}
    max_ts, max_diff = max(diffs.items(), key=lambda kv: kv[1])
    max_relative = max_diff / native_equity[max_ts]
    exact_matches = sum(1 for d in diffs.values() if d < 1e-6)
    assert max_relative < 0.01, (
        f"equity diverges by {max_relative:.4%} at {max_ts} "
        f"(native={native_equity[max_ts]}, bridge={bridge_equity[max_ts]}); "
        f"{exact_matches}/{len(shared)} points matched exactly"
    )


def test_native_and_worker_agree_on_real_price_positions():
    """Same one-lot-boundary caveat as the equity test: at most a handful of
    bars may floor to a lot count 1 apart. Anything more suggests the
    replay semantics themselves diverged, not just a rounding boundary."""
    products = _shared_products()
    _, native_positions = _native_curves(products)
    _, bridge_positions = _bridge_curves(products)

    shared = sorted(set(native_positions) & set(bridge_positions))
    assert len(shared) >= 10
    boundary_mismatches = []
    for ts in shared:
        native_row = {str(k): float(v) for k, v in native_positions[ts].items() if abs(float(v)) > 1e-9}
        bridge_row = {str(k): float(v) for k, v in bridge_positions[ts].items() if abs(float(v)) > 1e-9}
        if native_row.keys() != bridge_row.keys():
            boundary_mismatches.append((ts, native_row, bridge_row))
            continue
        for instrument, native_qty in native_row.items():
            if abs(native_qty - bridge_row[instrument]) > 1.0 + 1e-6:
                boundary_mismatches.append((ts, native_row, bridge_row))
                break
    assert len(boundary_mismatches) <= 2, (
        f"more than an isolated lot-boundary difference: "
        f"{len(boundary_mismatches)}/{len(shared)} points diverged by >1 lot: "
        f"{boundary_mismatches[:5]}"
    )


def test_native_and_external_framework_workers_agree_on_real_price_bridge(record_property):
    """Production bridge + real framework subprocesses on real daily bars.

    The earlier tests isolate either native-vs-reference semantics or direct
    worker payload parity. This one keeps the production bridge in the loop and
    dispatches to each framework worker process, while recording wall-clock
    timings so native/reference/framework speed can be compared over time.
    """
    products = _shared_products()
    timings: dict[str, float] = {}

    started = time.perf_counter()
    native_equity, native_positions = _native_curves(products)
    timings["native"] = time.perf_counter() - started

    dispatcher = EngineWorkerDispatcher()
    framework_results = {}
    for engine in ("backtrader", "qlib", "zipline"):
        started = time.perf_counter()
        framework_results[engine] = _bridge_curves(products, engine=engine, dispatcher=dispatcher)
        timings[engine] = time.perf_counter() - started

    record_property("real_bridge_framework_timings_seconds", {
        engine: round(elapsed, 6) for engine, elapsed in timings.items()
    })

    assert native_equity and native_positions
    for engine, (framework_equity, framework_positions) in framework_results.items():
        shared_equity = sorted(set(native_equity) & set(framework_equity))
        assert len(shared_equity) >= 10, f"{engine}: too few shared timestamps"
        diffs = {ts: abs(native_equity[ts] - framework_equity[ts]) for ts in shared_equity}
        max_ts, max_diff = max(diffs.items(), key=lambda kv: kv[1])
        assert max_diff / native_equity[max_ts] < 0.01, (
            f"{engine}: equity diverges at {max_ts}: "
            f"native={native_equity[max_ts]} framework={framework_equity[max_ts]}"
        )

        shared_positions = sorted(set(native_positions) & set(framework_positions))
        assert len(shared_positions) >= 10, f"{engine}: too few position timestamps"
        boundary_mismatches = []
        for ts in shared_positions:
            native_row = {
                str(k): float(v)
                for k, v in native_positions[ts].items()
                if abs(float(v)) > 1e-9
            }
            framework_row = {
                str(k): float(v)
                for k, v in framework_positions[ts].items()
                if abs(float(v)) > 1e-9
            }
            if native_row.keys() != framework_row.keys():
                boundary_mismatches.append((ts, native_row, framework_row))
                continue
            for instrument, native_qty in native_row.items():
                if abs(native_qty - framework_row[instrument]) > 1.0 + 1e-6:
                    boundary_mismatches.append((ts, native_row, framework_row))
                    break
        assert len(boundary_mismatches) <= 2, (
            f"{engine}: more than isolated lot-boundary differences: "
            f"{len(boundary_mismatches)}/{len(shared_positions)}; "
            f"{boundary_mismatches[:5]}"
        )
