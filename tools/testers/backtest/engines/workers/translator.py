"""StrategyConfig/BacktestRunState → framework-worker payload translation (ADR-030).

External frameworks consume the flat resolved-settings vocabulary that
``runners/common.py`` parses (fee_rate, slippage_mode, liquidity_mode,
execution_timing, ...). Native strategies carry the same values as
FieldRef-keyed ``StrategyConfig.field_values``. This module is the one place
that maps between the two, honoring ADR-024's rule: a framework must never
silently ignore a user setting — every value is either passed through,
explicitly mapped (recorded in ``_setting_fallbacks``), or rejected with
``UnsupportedFrameworkPlan``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd

from tools.testers.backtest.engines.adapters.frameworks import UnsupportedFrameworkPlan
from tools.testers.backtest.engines.workers.runners.common import BROKER_POLICY_DEFAULTS
from tools.testers.backtest.modules.group_membership import GroupMembershipModule
from tools.testers.backtest.modules.fee import FeeModule
from tools.testers.backtest.modules.ledger_module import LedgerModule
from tools.testers.backtest.modules.liquidity import LiquidityModule
from tools.testers.backtest.modules.margin import MarginModule
from tools.testers.backtest.modules.order_execution import OrderExecutionModule
from tools.testers.backtest.modules.position_sizing import PositionSizingModule
from tools.testers.backtest.modules.slippage import SlippageModule

if TYPE_CHECKING:
    from tools.testers.backtest.engines.native.ledger import BacktestRunState, StrategyConfig


# FieldRefs whose value passes through unchanged under the same key. The
# worker dialect deliberately reuses registered setting names, so ref.name is
# the payload key.
_PASSTHROUGH_REFS = (
    GroupMembershipModule.split_count,
    GroupMembershipModule.group_index,
    GroupMembershipModule.position_policy,
    GroupMembershipModule.rebalance_trigger,
    GroupMembershipModule.allocation_policy,
    GroupMembershipModule.volatility_lookback,
    GroupMembershipModule.volatility_warmup,
    GroupMembershipModule.execution_timing,
    GroupMembershipModule.execution_delay_bars,
    LiquidityModule.liquidity_mode,
    LiquidityModule.participation_rate,
    SlippageModule.slippage_mode,
    SlippageModule.slippage_bps,
    OrderExecutionModule.execution_price_basis,
)

# Raw resolved-settings keys copied verbatim when present (not FieldRefs —
# long-short composition wiring lives outside module fields).
_RAW_SETTING_KEYS = ("strategy_kind", "long_indices", "short_indices", "collect_execution_trace")


def translate_strategy_config(
    alias: str,
    config: "StrategyConfig",
    raw_settings: dict[str, Any],
    *,
    framework: str,
    membership_index: int,
) -> dict[str, Any]:
    """One strategy's worker-dialect config dict, or raise UnsupportedFrameworkPlan."""
    out: dict[str, Any] = {"strategy_id": alias, "membership_index": membership_index}
    fallbacks: list[dict[str, Any]] = []

    for ref in _PASSTHROUGH_REFS:
        value = config.get(ref, None)
        if value is not None:
            out[ref.name] = value

    for key in _RAW_SETTING_KEYS:
        if key in raw_settings:
            out[key] = raw_settings[key]

    capital = config.get(LedgerModule.initial_capital_major, None)
    if capital is not None:
        out["initial_capital"] = float(capital)

    out["fee_rate"] = _translate_fee(alias, config, framework=framework, fallbacks=fallbacks)
    _translate_margin(alias, config, out, framework=framework, fallbacks=fallbacks)
    out.update(_broker_policy_selectors(alias, config, framework=framework))

    if fallbacks:
        out["_setting_fallbacks"] = fallbacks
    return out


def _broker_policy_selectors(
    alias: str, config: "StrategyConfig", *, framework: str
) -> dict[str, str]:
    """ADR-028 broker policy selectors from the real module fields.

    Per ADR-028's mapping table: ``min_lot_policy`` comes from
    ``PositionSizingModule.quantity_rounding_policy`` and ``fill_cap_policy``
    from ``LiquidityModule.liquidity_mode``; the remaining selectors have no
    owning fields yet (BrokerModule is a separate migration, see
    028-native-broker-policy-implementation-plan) so they carry NativeBroker
    defaults. Runners re-validate on their side (require_broker_policies).
    """
    selectors = dict(BROKER_POLICY_DEFAULTS)
    rounding = str(config.get(PositionSizingModule.quantity_rounding_policy, "floor_to_lot") or "floor_to_lot")
    if rounding != "floor_to_lot":
        # Workers implement only the floor; nearest_lot would silently change
        # committed quantities relative to what the user configured.
        raise UnsupportedFrameworkPlan(
            f"strategy {alias!r}: quantity_rounding_policy={rounding!r} is not "
            f"expressible in {framework} workers (min_lot_policy supports floor_to_lot only)"
        )
    liquidity = str(config.get(LiquidityModule.liquidity_mode, "infinite") or "infinite")
    selectors["fill_cap_policy"] = (
        "volume_participation" if liquidity == "volume_participation" else "no_cap"
    )
    return selectors


def _translate_fee(
    alias: str, config: "StrategyConfig", *, framework: str, fallbacks: list[dict[str, Any]]
) -> float:
    mode = str(config.get(FeeModule.fee_mode, "auto") or "auto")
    if mode in {"zero", "none"}:
        return 0.0
    if mode == "fixed":
        return float(config.get(FeeModule.fixed_fee_rate, 0.0) or 0.0)
    # auto/exact/custom/close_yesterday/close_today are CTP per-leg fee
    # schedules; workers only understand one proportional fee_rate. Silently
    # flattening them would produce a different cost than the user configured.
    raise UnsupportedFrameworkPlan(
        f"strategy {alias!r}: fee_mode={mode!r} uses per-leg exchange fee "
        f"schedules that {framework} workers cannot represent; use "
        "fee_mode='fixed' or 'zero' for framework runs"
    )


def _translate_margin(
    alias: str, config: "StrategyConfig", out: dict[str, Any], *, framework: str,
    fallbacks: list[dict[str, Any]],
) -> None:
    mode = str(config.get(MarginModule.margin_mode, "none") or "none")
    if mode == "none":
        out["margin_mode"] = "none"
        return
    if mode == "fixed":
        out["margin_mode"] = "fixed"
        out["fixed_margin_ratio"] = float(config.get(MarginModule.fixed_margin_ratio, 1.0) or 1.0)
        return
    raise UnsupportedFrameworkPlan(
        f"strategy {alias!r}: margin_mode={mode!r} needs historical margin "
        f"fields that {framework} workers do not load; use margin_mode='fixed' "
        "or 'none' for framework runs"
    )


def translate_strategy_configs(
    run_state: "BacktestRunState",
    settings_by_strategy: dict[str, dict[str, Any]],
    *,
    framework: str,
) -> list[dict[str, Any]]:
    configs: list[dict[str, Any]] = []
    for index, (strategy, config) in enumerate(run_state.strategy_configs.items()):
        raw = settings_by_strategy.get(strategy.alias, {})
        configs.append(translate_strategy_config(
            strategy.alias, config, raw, framework=framework, membership_index=index,
        ))
    return configs


# ── market data payload ────────────────────────────────────────────


def translate_market_payload(run_state: "BacktestRunState") -> dict[str, Any]:
    """Serialize the already-loaded market data stores into the worker payload.

    Must be called after the PRE_REPLAY flows have populated
    ``market_data_store`` (the bridge does this; see bridge.py).
    """
    from tools.testers.backtest.modules.market_data import (
        current_prices_table_for,
        volume_table_for,
    )

    prices_table = current_prices_table_for(run_state)
    if prices_table is None or prices_table.empty:
        raise ValueError("framework bridge requires loaded market data (current_prices_table is empty)")
    timestamps = [pd.Timestamp(ts).isoformat() for ts in prices_table.index]
    instruments = [_instrument_name(col) for col in prices_table.columns]
    prices = {
        _instrument_name(col): [float(v) for v in prices_table[col].to_list()]
        for col in prices_table.columns
    }
    payload: dict[str, Any] = {
        "timestamps": timestamps,
        "instruments": instruments,
        "prices": prices,
        "market_rules": _market_rules_matrices(run_state, prices_table),
    }
    volume_table = volume_table_for(run_state)
    if volume_table is not None and not volume_table.empty:
        payload["volumes"] = {
            _instrument_name(col): [float(v) if pd.notna(v) else 0.0 for v in volume_table[col].to_list()]
            for col in volume_table.columns
        }
    return payload


def _instrument_name(column: Any) -> str:
    return str(getattr(column, "name", column))


def _market_rules_matrices(run_state: "BacktestRunState", prices_table: pd.DataFrame) -> dict[str, Any]:
    """(T, N) multiplier/lot/margin matrices from the same sources native reads.

    Priority per cell: static per-product dict from ``raw_market_data``
    (``lot_sizes``/``margin_ratio`` — what MarketDataModule publishes into its
    ctx fields) → historical-field frames → the same 1.0 defaults native's
    aligned fill uses. Workers cannot express "no lot constraint" (their
    ``target_quantities`` always floors), so lot 1.0 is both the worker floor
    unit and native's whole-contract default.
    """
    from tools.testers.backtest.modules.market_data import market_data_store_for

    n_rows = len(prices_table.index)
    columns = list(prices_table.columns)
    store = market_data_store_for(run_state)
    frames = getattr(store, "historical_field_frames", None) or {}
    raw_input = getattr(store, "raw_input", None) or {}

    def matrix(raw_key: str, field_name: str, default: float) -> list[list[float]]:
        static = raw_input.get(raw_key)
        if isinstance(static, dict) and static:
            row = [float(static.get(col, default) or default) for col in columns]
            return [list(row) for _ in range(n_rows)]
        frame = frames.get(field_name)
        if isinstance(frame, pd.DataFrame) and not frame.empty:
            aligned = frame.reindex(index=prices_table.index, columns=columns).ffill()
            filled = aligned.fillna(default).to_numpy(dtype=float)
            return [[float(v) for v in row] for row in filled]
        return [[default] * len(columns) for _ in range(n_rows)]

    return {
        "multipliers": matrix("multipliers", "VolumeMultiple", 1.0),
        "lot_sizes": matrix("lot_sizes", "MinLimitOrderVolume", 1.0),
        "margin_ratios": matrix("margin_ratio", "LongMarginRatioByMoney", 1.0),
    }


# ── membership tensor ──────────────────────────────────────────────


def build_membership_payload(
    run_state: "BacktestRunState",
    strategy_dialects: list[dict[str, Any]],
    event_timestamps: pd.DatetimeIndex,
) -> dict[str, Any]:
    """(T, G, N) membership + (T, G) signal_updates from precomputed signals.

    Replicates ``_group_quantile_membership``'s bucketing math exactly (rank
    ascending, ``bucket_size = n/n_groups``, ``round`` boundaries) so the
    membership a framework consumes is generated from the same FactorExpr
    result as native — ADR-024's equivalence requirement.
    """
    from tools.testers.backtest.modules.market_data import current_prices_table_for

    prices_table = current_prices_table_for(run_state)
    instruments = [_instrument_name(col) for col in prices_table.columns]
    n_rows = len(event_timestamps)
    n_groups_axis = len(strategy_dialects)
    membership = np.zeros((n_rows, n_groups_axis, len(instruments)), dtype=bool)
    signal_updates = np.zeros((n_rows, n_groups_axis), dtype=bool)

    signal_tables = _signal_tables_by_strategy(run_state)
    for g_index, dialect in enumerate(strategy_dialects):
        if str(dialect.get("strategy_kind") or "group") == "long_short":
            continue  # composes source-group memberships; no bucket of its own
        alias = str(dialect["strategy_id"])
        table = signal_tables.get(alias)
        if table is None or table.empty:
            raise ValueError(f"strategy {alias!r} has no precomputed factor signal table")
        split_count = int(dialect.get("split_count") or 1)
        group_index = int(dialect.get("group_index") or 0)
        signal_rows = table.reindex(index=event_timestamps).to_numpy(dtype=float)
        signal_columns = [_instrument_name(col) for col in table.columns]
        col_positions = [
            signal_columns.index(name) if name in signal_columns else None
            for name in instruments
        ]
        last_members: frozenset[int] | None = None
        for row in range(n_rows):
            values = {
                n_index: signal_rows[row][pos]
                for n_index, pos in enumerate(col_positions)
                if pos is not None and np.isfinite(signal_rows[row][pos])
            }
            if not values:
                continue
            ranked = sorted(values.items(), key=lambda kv: kv[1])
            bucket_size = len(ranked) / split_count
            start = round(group_index * bucket_size)
            end = round((group_index + 1) * bucket_size)
            members = frozenset(idx for idx, _ in ranked[start:end])
            for idx in members:
                membership[row, g_index, idx] = True
            if members != last_members or last_members is None:
                signal_updates[row, g_index] = True
            else:
                trigger = str(dialect.get("rebalance_trigger") or "on_factor_signal")
                signal_updates[row, g_index] = trigger == "on_factor_signal"
            last_members = members

    return {
        "membership": membership.tolist(),
        "signal_updates": signal_updates.tolist(),
    }


def _signal_tables_by_strategy(run_state: "BacktestRunState") -> dict[str, pd.DataFrame]:
    store = run_state.factor_signal_store
    out: dict[str, pd.DataFrame] = {}
    for strategy in run_state.strategy_configs:
        table = store.precomputed_table_for(strategy)
        if isinstance(table, pd.DataFrame):
            out[strategy.alias] = table
    return out
