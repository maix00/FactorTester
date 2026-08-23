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

from typing import TYPE_CHECKING, Any, cast

import numpy as np
import pandas as pd

from tools.testers.backtest.engines.adapters.frameworks import UnsupportedFrameworkPlan
from tools.testers.backtest.engines.workers.runners.common import WORKER_EXECUTION_POLICY_DEFAULTS
from tools.testers.backtest.modules.engine import engine_mode_for
from tools.testers.backtest.modules.group_membership import GroupMembershipModule
from tools.testers.backtest.modules.fee import FeeModule
from tools.testers.backtest.modules.ledger_module import LedgerModule
from tools.testers.backtest.modules.volume_capacity import VolumeCapacityMode
from tools.testers.backtest.modules.margin import MarginModule
from tools.testers.backtest.modules.minor_unit import (
    MinorUnitModule,
    resolve_use_minor_units,
)
from tools.testers.backtest.modules.order_execution import OrderExecutionModule
from tools.testers.backtest.modules.order_construct import OrderConstructModule
from tools.testers.backtest.modules.slippage import SlippageModule
from tools.testers.backtest.modules.term_structure import (
    DeliveryForceCloseModule,
    RolloverModule,
    _parse_time_offset,
    _tradable_contract_row,
)

if TYPE_CHECKING:
    from tools.testers.backtest.engines.native.state import BacktestRunState
    from tools.testers.backtest.engines.native.config import LedgerConfig, StrategyConfig


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
    VolumeCapacityMode.liquidity_mode,
    VolumeCapacityMode.participation_rate,
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
    ledger_config: "LedgerConfig | None" = None,
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

    out["fee_rate"] = _translate_fee(alias, config, ledger_config, framework=framework, fallbacks=fallbacks)
    _translate_margin(alias, config, ledger_config, out, framework=framework, fallbacks=fallbacks)
    out.update(_worker_execution_policy_selectors(alias, config, framework=framework))
    _note_minor_unit_precision(alias, config, framework=framework, fallbacks=fallbacks)

    if fallbacks:
        out["_setting_fallbacks"] = fallbacks
    return out


def _note_minor_unit_precision(
    alias: str, config: "StrategyConfig", *, framework: str, fallbacks: list[dict[str, Any]]
) -> None:
    """Worker runners always
    compute in plain major-unit floats -- there is no integer-minor-unit
    ledger to route into on the framework side -- so a True value can't be
    silently honored (ADR-024). This isn't a different algorithm the way
    fee_mode/margin_mode are, just coarser (cent-level, not float-epsilon)
    precision, so it's recorded as a fallback rather than rejected outright.
    """
    if not resolve_use_minor_units(config):
        return
    requested = config.get(MinorUnitModule.use_minor_units, "auto")
    fallbacks.append({
        "setting_key": "use_minor_units",
        "module": "minor_unit",
        "engine": framework,
        "requested_value": requested,
        "applied_value": "engine_native",
        "reason": "engine_disabled_value",
    })


def _worker_execution_policy_selectors(
    alias: str, config: "StrategyConfig", *, framework: str
) -> dict[str, str]:
    """Worker execution policy selectors from the real module fields.

    ``min_lot_policy`` comes from ``OrderConstructModule.
    quantity_rounding_policy`` and ``fill_cap_policy`` from
    ``VolumeCapacityMode.liquidity_mode`` -- these are the only two selectors any runner actually
    checks (see ADR-032; this is deliberately not a general broker/account
    policy object). Runners re-validate on their side
    (require_worker_execution_policies).
    """
    selectors = dict(WORKER_EXECUTION_POLICY_DEFAULTS)
    rounding = str(config.get(OrderConstructModule.quantity_rounding_policy, "floor_to_lot") or "floor_to_lot")
    if rounding != "floor_to_lot":
        # Workers implement only the floor; nearest_lot would silently change
        # committed quantities relative to what the user configured.
        raise UnsupportedFrameworkPlan(
            f"strategy {alias!r}: quantity_rounding_policy={rounding!r} is not "
            f"expressible in {framework} workers (min_lot_policy supports floor_to_lot only)"
        )
    liquidity = str(config.get(VolumeCapacityMode.liquidity_mode, "infinite") or "infinite")
    selectors["fill_cap_policy"] = (
        "volume_participation" if liquidity == "volume_participation" else "no_cap"
    )
    return selectors


def _translate_fee(
    alias: str,
    config: "StrategyConfig",
    ledger_config: "LedgerConfig | None",
    *,
    framework: str,
    fallbacks: list[dict[str, Any]],
) -> float:
    mode = str(getattr(ledger_config, "fee_mode", None) or "auto")
    if mode in {"zero", "none"}:
        return 0.0
    if mode == "fixed":
        return float(getattr(ledger_config, "fixed_fee_rate", None) or 0.0)
    # auto/exact/custom/close_yesterday/close_today are CTP per-leg fee
    # schedules; workers only understand one proportional fee_rate. Silently
    # flattening them would produce a different cost than the user configured.
    raise UnsupportedFrameworkPlan(
        f"strategy {alias!r}: fee_mode={mode!r} uses per-leg exchange fee "
        f"schedules that {framework} workers cannot represent; use "
        "fee_mode='fixed' or 'zero' for framework runs"
    )


def _translate_margin(
    alias: str,
    config: "StrategyConfig",
    ledger_config: "LedgerConfig | None",
    out: dict[str, Any],
    *,
    framework: str,
    fallbacks: list[dict[str, Any]],
) -> None:
    mode = str(getattr(ledger_config, "margin_mode", None) or "none")
    if mode == "none":
        out["margin_mode"] = "none"
        return
    if mode == "fixed":
        out["margin_mode"] = "fixed"
        out["fixed_margin_ratio"] = float(
            getattr(ledger_config, "fixed_margin_ratio", None)
            or 1.0
        )
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
        ledger = run_state.ledger_for_strategy(strategy)
        ledger_config = run_state.ledger_config_for(ledger)
        configs.append(translate_strategy_config(
            strategy.alias,
            config,
            raw,
            framework=framework,
            membership_index=index,
            ledger_config=ledger_config,
        ))
    return configs


# ── market data payload ────────────────────────────────────────────


def translate_market_payload(run_state: "BacktestRunState") -> dict[str, Any]:
    """Serialize the already-loaded market data stores into the worker payload.

    Must be called after the PRE_REPLAY flows have populated
    ``market_data_store`` (the bridge does this; see bridge.py).
    """
    from tools.data.types.time_index import DataIndex
    from tools.testers.backtest.modules.market_data import (
        current_prices_table_for,
        volume_table_for,
    )

    prices_table = current_prices_table_for(run_state)
    if prices_table is None or prices_table.empty:
        raise ValueError("framework bridge requires loaded market data (current_prices_table is empty)")
    # current_prices_table's index can be a _SIGNAL@-prefixed MultiIndex
    # (custom/exact engine_mode market data carries a trading-day level
    # alongside the event-time level) -- iterating a MultiIndex directly
    # yields tuples of level values per row, not scalar Timestamps, which
    # pd.Timestamp(...) can't parse. DataIndex.event_timestamps() extracts
    # just the signal time level for both plain DatetimeIndex and
    # MultiIndex inputs.
    event_index = DataIndex(prices_table.index).event_timestamps()
    timestamps = [pd.Timestamp(ts).isoformat() for ts in event_index]
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
    descending -- group_index=0 is the highest-factor-value bucket,
    ``bucket_size = n/n_groups``, ``round`` boundaries) so the
    membership a framework consumes is generated from the same FactorExpr
    result as native — ADR-024's equivalence requirement.

    Bucketing happens on the abstract product (signals are computed on the
    continuous series), but the instrument actually written into ``membership``
    is whatever ``TermStructureExpandModule._tradable_contract_row`` — the
    same function native's ``resolve_tradable_target_weights`` calls per
    SIGNAL event — resolves for that (strategy, timestamp): the concrete
    rolled-to/force-closed contract, or the abstract product itself outside
    a term structure. Without this remap, bridged frameworks would trade the
    abstract continuous product forever and never roll, diverging from native.
    """
    from tools.testers.backtest.modules.market_data import current_prices_table_for

    prices_table = current_prices_table_for(run_state)
    instruments = [_instrument_name(col) for col in prices_table.columns]
    instrument_index = {name: idx for idx, name in enumerate(instruments)}
    n_rows = len(event_timestamps)
    n_groups_axis = len(strategy_dialects)
    membership: Any = np.zeros((n_rows, n_groups_axis, len(instruments)), dtype=bool)
    signal_updates: Any = np.zeros((n_rows, n_groups_axis), dtype=bool)

    strategies_by_alias = {strategy.alias: strategy for strategy in run_state.strategy_configs}
    signal_tables = _signal_tables_by_strategy(run_state)
    # Strategies sharing a factor's precomputed schedule get the exact same
    # DataFrame object back from _signal_tables_by_strategy (the store hands
    # out one shared table per schedule key, not a copy per strategy) -- only
    # group_index/split_count differ per dialect. Cache the reindexed numpy
    # view and the per-row descending ranking by table identity so this
    # O(n log n) work happens once per distinct table+row, not once per
    # dialect, matching the equivalent native-side optimization in
    # GroupMembershipModule._group_quantile_membership.
    table_prep_cache: dict[int, tuple[Any, list[int | None]]] = {}
    rank_cache: dict[tuple[int, int], list[tuple[int, float]]] = {}
    # A dialect sharing (table, row, split_count, group_index) with another
    # gets the identical raw bucket slice before term-structure resolution
    # (resolver differs per strategy -- each can have its own rollover
    # policy -- so this only caches the pre-resolver selection, matching
    # native's split between the shared raw bucket and per-strategy
    # product_mask_names application).
    bucket_cache: dict[tuple[int, int, int, int], list[tuple[int, float]]] = {}
    for g_index, dialect in enumerate(strategy_dialects):
        if str(dialect.get("strategy_kind") or "group") == "long_short":
            continue  # composes source-group memberships; no bucket of its own
        alias = str(dialect["strategy_id"])
        table = signal_tables.get(alias)
        if table is None or table.empty:
            raise ValueError(f"strategy {alias!r} has no precomputed factor signal table")
        strategy = strategies_by_alias.get(alias)
        resolver = _term_structure_resolver_for(run_state, strategy) if strategy is not None else None
        split_count = int(dialect.get("split_count") or 1)
        group_index = int(dialect.get("group_index") or 0)
        table_id = id(table)
        prepared = table_prep_cache.get(table_id)
        if prepared is None:
            signal_rows = table.reindex(index=event_timestamps).to_numpy(dtype=float)
            signal_columns = [_instrument_name(col) for col in table.columns]
            col_positions = [
                signal_columns.index(name) if name in signal_columns else None
                for name in instruments
            ]
            prepared = (signal_rows, col_positions)
            table_prep_cache[table_id] = prepared
        signal_rows, col_positions = prepared
        last_members: frozenset[int] | None = None
        for row in range(n_rows):
            rank_key = (table_id, row)
            ranked = rank_cache.get(rank_key)
            if ranked is None:
                values: dict[int, float] = {
                    n_index: float(signal_rows[row][pos])
                    for n_index, pos in enumerate(col_positions)
                    if pos is not None and np.isfinite(signal_rows[row][pos])
                }
                # Descending, matching GroupMembershipModule._group_quantile_membership:
                # group_index=0 ("第1组") is the highest-factor-value bucket.
                # Secondary key on instrument name makes tie-breaking
                # deterministic by construction, not an accident of dict
                # iteration order.
                ranked = sorted(values.items(), key=lambda kv: (-kv[1], instruments[kv[0]]))
                rank_cache[rank_key] = ranked
            if not ranked:
                continue
            bucket_key = (table_id, row, split_count, group_index)
            selected = bucket_cache.get(bucket_key)
            if selected is None:
                bucket_size = len(ranked) / split_count
                start = round(group_index * bucket_size)
                end = round((group_index + 1) * bucket_size)
                selected = ranked[start:end]
                bucket_cache[bucket_key] = selected
            members: set[int] = set()
            for n_index, _value in selected:
                target_idx = n_index
                if resolver is not None:
                    product = table.columns[cast(int, col_positions[n_index])]
                    target_idx = resolver(product, event_timestamps[row], instrument_index)
                members.add(target_idx)
            frozen_members = frozenset(members)
            for idx in frozen_members:
                membership[row, g_index, idx] = True
            if frozen_members != last_members or last_members is None:
                signal_updates[row, g_index] = True
            else:
                trigger = str(dialect.get("rebalance_trigger") or "on_factor_signal")
                signal_updates[row, g_index] = trigger == "on_factor_signal"
            last_members = frozen_members

    return {
        "membership": membership.tolist(),
        "signal_updates": signal_updates.tolist(),
    }


def _term_structure_resolver_for(run_state: "BacktestRunState", strategy: Any):
    """Build a (product, timestamp, instrument_index) -> instrument-index
    resolver reusing native's own ``_tradable_contract_row``, or ``None`` if
    the strategy has no term-structure metadata to resolve against."""
    store = run_state.term_structure_store
    metadata = tuple(store.contract_metadata.get(strategy, ()))
    metadata_by_product = store.metadata_by_product.get(strategy) or None
    metadata_intervals_by_product = (
        store.metadata_intervals_by_product.get(strategy) or None
    )
    metadata_interval_end_keys_by_product = (
        store.metadata_interval_end_keys_by_product.get(strategy) or None
    )
    metadata_interval_end_monotonic_by_product = (
        store.metadata_interval_end_monotonic_by_product.get(strategy) or None
    )
    if not metadata:
        return None
    config = run_state.config_for(strategy)
    rollover_policy = str(config.get(RolloverModule.rollover_policy, "none") or "none")
    rollover_offset = (
        _parse_time_offset(
            config.get(RolloverModule.rollover_before_expiry, "5d"),
            field_name="rollover_before_expiry",
        )
        if rollover_policy == "date_before_expiry"
        else None
    )
    force_close_offset = _parse_time_offset(
        config.get(DeliveryForceCloseModule.force_close_before_expiry, "2d"),
        field_name="force_close_before_expiry",
    )
    engine_mode = engine_mode_for(config)

    def resolve(product: Any, timestamp: pd.Timestamp, instrument_index: dict[str, int]) -> int:
        row = _tradable_contract_row(
            product,
            metadata,
            timestamp=timestamp,
            rollover_offset=rollover_offset,
            force_close_offset=force_close_offset,
            state=run_state,
            engine_mode=engine_mode,
            metadata_by_product=metadata_by_product,
            metadata_intervals_by_product=metadata_intervals_by_product,
            metadata_interval_end_keys_by_product=(
                metadata_interval_end_keys_by_product
            ),
            metadata_interval_end_monotonic_by_product=(
                metadata_interval_end_monotonic_by_product
            ),
        )
        target = row.get("contract_object", product) if row is not None else product
        name = _instrument_name(target)
        idx = instrument_index.get(name)
        if idx is None:
            raise ValueError(
                f"term structure resolved {product!r} to instrument {name!r} at {timestamp}, "
                "but no price series was loaded for it"
            )
        return idx

    return resolve


def _signal_tables_by_strategy(run_state: "BacktestRunState") -> dict[str, pd.DataFrame]:
    store = run_state.factor_signal_store
    out: dict[str, pd.DataFrame] = {}
    for strategy in run_state.strategy_configs:
        table = store.precomputed_table_for(strategy)
        if isinstance(table, pd.DataFrame):
            out[strategy.alias] = table
    return out
