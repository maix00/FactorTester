"""FactorSignalModule — schedules SIGNAL events and publishes signal values.

"signal_live" observes BAR events scheduled by BarEventModule into per-factor
causal state, then emits signal values only when its scheduled SIGNAL events fire.
"signal_precomputed" evaluates once over the whole backtest range and looks
values up at SIGNAL events.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, ClassVar

import pandas as pd

from tools.data.types.time_freq import DataFreq
from tools.factors.expr.signal_align import signal_align
from tools.testers.backtest.engines.native.events import EventDraft, EventKind
from tools.testers.backtest.engines.native.fields import ExecutableModule, FieldDefinition, FieldRef
from tools.testers.backtest.engines.native.flow import Flow, Phase
from tools.testers.backtest.modules.factor import FactorModule
from tools.testers.backtest.modules.time_index_lookup import row_at, signal_timestamps


class FactorSignalModule(ExecutableModule):
    key: ClassVar[str] = "factor_execution"
    label: ClassVar[str] = "信号时机"

    signal_freq: ClassVar[FieldRef[Any]] = FieldRef("signal_freq")
    basepoint: ClassVar[FieldRef[Any]] = FieldRef("basepoint")
    daily_basepoint: ClassVar[FieldRef[Any]] = FieldRef("daily_basepoint")
    end_session_skip: ClassVar[FieldRef[bool]] = FieldRef("end_session_skip")
    end_session_gap: ClassVar[FieldRef[Any]] = FieldRef("end_session_gap")
    calendar_frequency: ClassVar[FieldRef[Any]] = FieldRef("calendar_frequency")
    signal_value: ClassVar[FieldRef[Any]] = FieldRef("signal_value")  # dict[Product, float]
    factor_mode: ClassVar[FieldRef[str]] = FieldRef("factor_mode")
        # "auto"|"precomputed"|"incremental" -- selects which of
        # "signal_precomputed"/"signal_live" this strategy activates; read
        # directly off the resolved settings dict by
        # strategy_config_builder._resolve_active_flow_names (it determines
        # *which Flow runs at all*, not a Flow's input value, so it isn't
        # consumed via StrategyConfig.get like an ordinary field).

    fields: ClassVar[dict[str, FieldDefinition]] = {
        "signal_freq": FieldDefinition(
            public=True, control_template="select", default="1d", tab="frequency",
            chip_template="信号频率: {value}", tab_label="数据频率", tab_order=36,
        ),
        "basepoint": FieldDefinition(
            public=True, control_template="select", default="last", tab="frequency",
            chip_template="信号点: {value}", tab_label="数据频率", tab_order=36,
        ),
        "daily_basepoint": FieldDefinition(
            public=True, control_template="text", default=None, tab="frequency",
            chip_template="日内点: {value}", tab_label="数据频率", tab_order=36,
        ),
        "end_session_skip": FieldDefinition(
            public=True, control_template="boolean", default=True, tab="frequency",
            chip_template="尾盘跳过: {value}", tab_label="数据频率", tab_order=36,
        ),
        "end_session_gap": FieldDefinition(
            public=True, control_template="text", default="3h", tab="frequency",
            chip_template="尾盘间隔: {value}", tab_label="数据频率", tab_order=36,
        ),
            # plain pd.Timedelta-parseable string ("3h" -> pd.Timedelta("3h"));
            # JSON-serializable as-is, parsed back via pd.Timedelta(value)
            # wherever this field is actually used (signal_align needs a real
            # Timedelta, not a string)
        "factor_mode": FieldDefinition(
            public=True, control_template="select", default="auto", tab="factor",
            options=(("auto", "自动选择"), ("precomputed", "预计算后按事件回放"), ("incremental", "随事件增量计算")),
            chip_template="因子模式: {value}", tab_label="因子执行", tab_order=20,
        ),
        "calendar_frequency": FieldDefinition(
            public=True, control_template="select", default="auto", tab="calendar",
            options=(("auto", "按因子频率自动判断"), ("1min", "1 分钟"), ("5min", "5 分钟"), ("1day", "1 天")),
            chip_template="时钟: {value}", tab_label="回测时钟", tab_order=190,
        ),
    }

    signal_live: ClassVar[Flow] = Flow(
        "signal_live", inputs=(), outputs=(),
        phase=Phase.PRE_REPLAY, order=50,
        compute=lambda account, ctx: _schedule_signal_live_timestamps(account, ctx),
    )
    signal_precomputed: ClassVar[Flow] = Flow(
        "signal_precomputed", inputs=(FactorModule.factor,), outputs=(),
        phase=Phase.PRE_REPLAY, order=50,
        compute=lambda account, ctx: _schedule_signal_precomputed_timestamps(account, ctx),
    )

    signal_live_on_event: ClassVar[Flow] = Flow(
        "signal_live", inputs=(FactorModule.factor,), outputs=(signal_value,),
        phase=Phase.PER_EVENT, event_kind=EventKind.SIGNAL, order=5,
        compute=lambda account, ctx: _evaluate_signal_live(account, ctx),
    )
    signal_live_on_bar: ClassVar[Flow] = Flow(
        "signal_live", inputs=(FactorModule.factor,), outputs=(),
        phase=Phase.PER_EVENT, event_kind=EventKind.BAR, order=5,
        compute=lambda account, ctx: _observe_signal_live_bar(account, ctx),
    )
    signal_precomputed_on_event: ClassVar[Flow] = Flow(
        "signal_precomputed", inputs=(), outputs=(signal_value,),
        phase=Phase.PER_EVENT, event_kind=EventKind.SIGNAL, order=5,
        compute=lambda account, ctx: _evaluate_signal_precomputed(account, ctx),
    )

    flows: ClassVar[tuple[Flow, ...]] = (
        signal_live, signal_precomputed, signal_live_on_bar,
        signal_live_on_event, signal_precomputed_on_event,
    )
    # signal_live_on_event/signal_precomputed_on_event share the same
    # `name` as their PRE_REPLAY counterparts ("signal_live"/
    # "signal_precomputed") -- both halves are gated by the same
    # StrategyConfig.active_flow_names entry by design. FlowRegistry keys
    # by (name, phase, event_kind), so registering all four together here
    # is not a collision.


def normalize_signal_timestamp(raw_ts: pd.Timestamp, freq: "DataFreq", last_minute_lookup=None) -> pd.Timestamp:
    """Minute-level (or finer): floor to that minute (HH:MM:00.000000).
    Day-or-coarser with a non-midnight time component: same floor-to-minute
    rule. Day-or-coarser at exactly midnight (no time info attached):
    that's not a real intraday moment -- look up the session's last trading
    minute via `last_minute_lookup(raw_ts) -> pd.Timestamp` and use that
    instead."""
    raw_ts = pd.Timestamp(raw_ts)
    is_day_multiple = freq.is_day_multiple() if hasattr(freq, "is_day_multiple") else False
    if is_day_multiple and raw_ts.time() == pd.Timestamp("00:00:00").time():
        if last_minute_lookup is None:
            raise ValueError(
                "day-level timestamp with no time-of-day component requires "
                "last_minute_lookup to resolve the session's last trading minute")
        raw_ts = pd.Timestamp(last_minute_lookup(raw_ts))
    return raw_ts.floor("min")


def _group_strategies_by_signal_align_params(account):
    groups: dict[tuple, list] = defaultdict(list)
    for strategy in account.strategy_configs:
        config = account.config_for(strategy)
        key = (
            _effective_signal_frequency(config),
            config.get(FactorSignalModule.basepoint, "last"),
            config.get(FactorSignalModule.daily_basepoint),
            config.get(FactorSignalModule.end_session_skip, True),
            config.get(FactorSignalModule.end_session_gap, "3h"),
        )
        groups[key].append(strategy)
    return groups


def _effective_signal_frequency(config) -> Any:
    calendar_frequency = config.get(FactorSignalModule.calendar_frequency, "auto")
    if calendar_frequency and str(calendar_frequency) != "auto":
        return calendar_frequency
    return config.get(FactorSignalModule.signal_freq, "1d")


def _schedule_signal_live_timestamps(account, ctx) -> None:
    """Schedule live strategy SIGNAL timestamps.

    No factor value is computed here. BarEventModule schedules BAR events to
    update live factor state; SIGNAL events read that state and publish the
    strategy-facing value.
    Strategies sharing identical signal_align parameters are grouped so
    signal_align() runs once per unique parameter combination, not once per
    strategy."""
    data = getattr(account, "current_prices_table", None)
    if data is None:
        return
    drafts: list[EventDraft] = []
    groups = _group_strategies_by_signal_align_params(account)
    for (freq, basepoint, daily_basepoint, end_session_skip, end_session_gap), strategies in groups.items():
        strategies = [s for s in strategies if account.config_for(s).uses_flow("signal_live")]
        if not strategies:
            continue
        aligned = signal_align(
            data, freq, basepoint=basepoint, daily_basepoint=daily_basepoint,
            end_session_skip=end_session_skip, end_session_gap=pd.Timedelta(end_session_gap),
        )
        for ts in signal_timestamps(aligned):
            for strategy in strategies:
                drafts.append(EventDraft(EventKind.SIGNAL, pd.Timestamp(ts), strategy))
    ctx.set(FactorSignalModule.signal_value, drafts)  # pushes every draft via FlowContext._push_if_event


def _schedule_signal_precomputed_timestamps(account, ctx) -> None:
    """Groups strategies by factor identity -- a shared factor's
    `evaluate()` runs once for the whole backtest range, not once per
    strategy. The resulting table's own index is the signal schedule
    (already at the factor's native frequency, no separate signal_align
    pass needed) and gets cached on `account.precomputed_factor_tables`
    for the PER_EVENT lookup Flow to read."""
    by_factor: dict[int, list] = defaultdict(list)
    factor_by_id: dict[int, Any] = {}
    for strategy in account.strategy_configs:
        if not account.config_for(strategy).uses_flow("signal_precomputed"):
            continue
        factor = account.config_for(strategy).get(FactorModule.factor)
        by_factor[id(factor)].append(strategy)
        factor_by_id[id(factor)] = factor

    tables = getattr(account, "precomputed_factor_tables", None)
    if tables is None:
        tables = {}
        account.precomputed_factor_tables = tables
    table_keys = getattr(account, "precomputed_factor_table_keys", None)
    if table_keys is None:
        table_keys = {}
        account.precomputed_factor_table_keys = table_keys

    drafts: list[EventDraft] = []
    for factor_id, strategies in by_factor.items():
        factor = factor_by_id[factor_id]
        table = factor.evaluate()
        for strategy in strategies:
            config = account.config_for(strategy)
            schedule_key = _precomputed_schedule_key(factor_id, config)
            if schedule_key not in tables:
                tables[schedule_key] = _precomputed_schedule_table(table, config)
            table_keys[strategy] = schedule_key
            for ts in signal_timestamps(tables[schedule_key]):
                drafts.append(EventDraft(EventKind.SIGNAL, pd.Timestamp(ts), strategy))
    ctx.set(FactorSignalModule.signal_value, drafts)


def _precomputed_schedule_key(factor_id: int, config) -> tuple:
    calendar_frequency = config.get(FactorSignalModule.calendar_frequency, "auto")
    if not calendar_frequency or str(calendar_frequency) == "auto":
        return (factor_id, "factor")
    return (
        factor_id,
        str(calendar_frequency),
        config.get(FactorSignalModule.basepoint, "last"),
        config.get(FactorSignalModule.daily_basepoint),
        config.get(FactorSignalModule.end_session_skip, True),
        config.get(FactorSignalModule.end_session_gap, "3h"),
    )


def _precomputed_schedule_table(table: pd.DataFrame, config) -> pd.DataFrame:
    calendar_frequency = config.get(FactorSignalModule.calendar_frequency, "auto")
    if not calendar_frequency or str(calendar_frequency) == "auto":
        return table
    return signal_align(
        table,
        calendar_frequency,
        basepoint=config.get(FactorSignalModule.basepoint, "last"),
        daily_basepoint=config.get(FactorSignalModule.daily_basepoint),
        end_session_skip=config.get(FactorSignalModule.end_session_skip, True),
        end_session_gap=pd.Timedelta(config.get(FactorSignalModule.end_session_gap, "3h")),
    )


def _evaluate_signal_live(account, ctx) -> None:
    """Publish the current live signal from per-factor BAR state.

    FactorExpr/Factor values are compiled into per-run incremental executors.
    A non-FactorExpr live adapter can still implement one of these methods:
    `on_signal(timestamp, price_table)`, `evaluate_live(price_table, timestamp)`.
    Older table-style factors still fall back to `evaluate()` for compatibility.
    Shared factor objects are evaluated once per dispatch.
    """
    by_factor: dict[int, list] = defaultdict(list)
    factor_by_id: dict[int, Any] = {}
    for strategy in ctx.active_strategies:
        factor = account.config_for(strategy).get(FactorModule.factor)
        by_factor[id(factor)].append(strategy)
        factor_by_id[id(factor)] = factor

    price_tables = getattr(account, "live_factor_price_tables", {})
    executors = getattr(account, "live_factor_executors", {})
    for factor_id, strategies in by_factor.items():
        factor = factor_by_id[factor_id]
        executor = executors.get(factor_id)
        if executor is not None:
            values = _row_to_signal_values(executor.on_signal(ctx.timestamp))
        else:
            values = _live_signal_values(factor, ctx.timestamp, price_tables.get(factor_id))
        for strategy in strategies:
            ctx.set_for(FactorSignalModule.signal_value, strategy, values)


def _evaluate_signal_precomputed(account, ctx) -> None:
    """Looks up a value from the table cached once in PRE_REPLAY
    (`account.precomputed_factor_tables`, keyed by id(factor)) -- no
    re-evaluation here."""
    tables = getattr(account, "precomputed_factor_tables", {})
    table_keys = getattr(account, "precomputed_factor_table_keys", {})
    for strategy in ctx.active_strategies:
        factor = account.config_for(strategy).get(FactorModule.factor)
        table = tables.get(table_keys.get(strategy, (id(factor), "factor")))
        if table is None:
            ctx.set_for(FactorSignalModule.signal_value, strategy, {})
            continue
        try:
            row = row_at(table, ctx.timestamp)
        except KeyError:
            ctx.set_for(FactorSignalModule.signal_value, strategy, {})
            continue
        ctx.set_for(FactorSignalModule.signal_value, strategy,
                     {product: float(row[product]) for product in table.columns})


def _observe_signal_live_bar(account, ctx) -> None:
    """Feed one bar of current market data into each active live factor."""
    prices = ctx.get(FieldRef("current_prices", owner="MarketDataModule"), {})
    if not prices:
        return
    tables = getattr(account, "live_factor_price_tables", None)
    if tables is None:
        tables = {}
        account.live_factor_price_tables = tables
    executors = getattr(account, "live_factor_executors", None)
    if executors is None:
        executors = {}
        account.live_factor_executors = executors

    by_factor: dict[int, list] = defaultdict(list)
    factor_by_id: dict[int, Any] = {}
    for strategy in ctx.active_strategies:
        factor = account.config_for(strategy).get(FactorModule.factor)
        by_factor[id(factor)].append(strategy)
        factor_by_id[id(factor)] = factor

    row = pd.DataFrame([prices], index=[pd.Timestamp(ctx.timestamp)])
    for factor_id in by_factor:
        factor = factor_by_id[factor_id]
        table = tables.get(factor_id)
        if table is None:
            tables[factor_id] = row
        else:
            updated = pd.concat([table, row])
            tables[factor_id] = updated.iloc[~updated.index.duplicated(keep="last")]
        executor = executors.get(factor_id)
        if executor is None:
            executor = _compile_live_factor_executor(
                factor,
                by_factor[factor_id][0],
                prices.keys(),
                getattr(account, "source_freq", None),
            )
            if executor is not None:
                executors[factor_id] = executor
        if executor is not None:
            executor.on_bar(pd.Timestamp(ctx.timestamp), prices)
            continue
        on_bar = getattr(factor, "on_bar", None)
        if callable(on_bar):
            on_bar(pd.Timestamp(ctx.timestamp), dict(prices))


def _live_signal_values(factor: Any, timestamp: pd.Timestamp, price_table: pd.DataFrame | None) -> dict:
    timestamp = pd.Timestamp(timestamp)
    on_signal = getattr(factor, "on_signal", None)
    if callable(on_signal):
        return _row_to_signal_values(on_signal(timestamp, price_table))

    evaluate_live = getattr(factor, "evaluate_live", None)
    if callable(evaluate_live):
        return _row_to_signal_values(evaluate_live(price_table, timestamp))

    if hasattr(factor, "evaluate"):
        table = factor.evaluate()
        try:
            row = row_at(table, timestamp)
        except KeyError:
            row = None
        return _row_to_signal_values(row)
    return {}


def _compile_live_factor_executor(
    factor: Any,
    strategy: Any,
    products: Any,
    source_freq: Any,
) -> Any | None:
    compiler = getattr(factor, "compile_incremental", None)
    if not callable(compiler):
        return None
    alias = getattr(strategy, "alias", "factor")
    return compiler(
        factor_alias=str(alias),
        products=tuple(products),
        source_freq=source_freq,
    )


def _row_to_signal_values(value: Any) -> dict:
    if value is None:
        return {}
    if isinstance(value, pd.DataFrame):
        if value.empty:
            return {}
        value = value.iloc[-1]
    if isinstance(value, pd.Series):
        return {product: float(score) for product, score in value.items()}
    if isinstance(value, dict):
        return {product: float(score) for product, score in value.items()}
    return {}
