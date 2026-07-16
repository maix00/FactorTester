"""FactorSignalModule — schedules SIGNAL events and publishes signal values.

"signal_live" observes BAR events scheduled by BarEventModule into per-factor
causal state, then emits signal values only when its scheduled SIGNAL events fire.
"signal_precomputed" evaluates once over the whole backtest range and looks
values up at SIGNAL events.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
import inspect
from typing import Any, ClassVar, cast

import pandas as pd

from tools.data.types import DataIndex, DataTime
from tools.data.types.time_freq import DataFreq
from tools.factors.expr.signal_align import signal_align
from tools.testers.backtest.engines.native.events import EventDraft, EventKind
from tools.testers.backtest.engines.native.fields import ExecutableModule, FieldDefinition, FieldRef
from tools.testers.backtest.engines.native.flow import Flow, Phase
from tools.testers.backtest.modules.factor import FactorModule, factor_runtime_key
from tools.testers.backtest.modules.market_data import (
    MarketDataModule,
    current_prices_table_for,
    resolved_bar_frequency_for_strategy,
)
from tools.testers.backtest.modules.product_selection import ProductSelectionModule
from tools.testers.backtest.modules.run_window import (
    RunWindowModule,
    _expr_operands as _run_window_expr_operands,
    _expr_window_to_timedelta as _run_window_expr_window_to_timedelta,
    _infer_expr_warmup_window as _run_window_infer_expr_warmup_window,
    _max_timedelta as _run_window_max_timedelta,
    auto_warmup_window,
    parse_warmup_window,
    run_window_envelope_for_strategies,
    run_window_key_for_config,
    strategy_run_window_datetimes,
    warmup_window_for_strategy,
    warmup_window_for_strategies,
)
from tools.testers.backtest.modules.time_index_lookup import (
    IndexEventTime,
    row_at,
    row_at_index_key,
    signal_event_times,
)


@dataclass
class FactorSignalStore:
    precomputed_tables: dict[Any, Any] = field(default_factory=dict)
    precomputed_table_keys: dict[Any, Any] = field(default_factory=dict)
    precomputed_signal_value_cache: dict[Any, dict[Any, float]] = field(default_factory=dict)
    live_price_tables: dict[Any, Any] = field(default_factory=dict)
    live_executors: dict[Any, Any] = field(default_factory=dict)

    def put_precomputed_table(self, key: Any, table: Any) -> None:
        self.precomputed_tables[key] = table
        self.precomputed_signal_value_cache.clear()

    def bind_precomputed_table(self, strategy: Any, key: Any) -> None:
        self.precomputed_table_keys[strategy] = key

    def precomputed_table_for(self, strategy: Any) -> Any:
        key = self.precomputed_table_keys.get(strategy)
        if key is None:
            raise KeyError(f"precomputed signal table is not bound for strategy {strategy!r}")
        return self.precomputed_tables.get(key)


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
    live_factor_state: ClassVar[FieldRef[Any]] = FieldRef("live_factor_state")
    factor_mode: ClassVar[FieldRef[str]] = FieldRef("factor_mode")
    warmup_mode: ClassVar[FieldRef[str]] = FieldRef("warmup_mode")
    warmup_window: ClassVar[FieldRef[Any]] = FieldRef("warmup_window")
        # "auto"|"precomputed"|"incremental" -- selects which of
        # "signal_precomputed"/"signal_live" this strategy activates; read
        # directly off the resolved settings dict by
        # strategy_config_builder._resolve_active_flow_names (it determines
        # *which Flow runs at all*, not a Flow's input value, so it isn't
        # consumed via StrategyConfig.get like an ordinary field).

    fields: ClassVar[dict[str, FieldDefinition]] = {
        "signal_freq": FieldDefinition(
            public=True, label="信号频率", control_template="select", default="1d", tab="frequency",
            chip_template="信号频率: {value}", tab_label="数据频率", tab_order=36,
        ),
        "basepoint": FieldDefinition(
            public=True, label="信号点", control_template="select", default="last", tab="frequency",
            chip_template="信号点: {value}", tab_label="数据频率", tab_order=36,
        ),
        "daily_basepoint": FieldDefinition(
            public=True, label="日内点", control_template="text", default=None, tab="frequency",
            chip_template="日内点: {value}", tab_label="数据频率", tab_order=36,
        ),
        "end_session_skip": FieldDefinition(
            public=True, label="尾盘跳过", control_template="boolean", default=True, tab="frequency",
            chip_template="尾盘跳过: {value}", tab_label="数据频率", tab_order=36,
        ),
        "end_session_gap": FieldDefinition(
            public=True, label="尾盘间隔", control_template="text", default="3h", tab="frequency",
            chip_template="尾盘间隔: {value}", tab_label="数据频率", tab_order=36,
        ),
            # plain pd.Timedelta-parseable string ("3h" -> pd.Timedelta("3h"));
            # JSON-serializable as-is, parsed back via pd.Timedelta(value)
            # wherever this field is actually used (signal_align needs a real
            # Timedelta, not a string)
        "factor_mode": FieldDefinition(
            public=True, label="因子模式", control_template="select", default="auto", tab="factor",
            options=(("auto", "自动选择"), ("precomputed", "预计算后按事件回放"), ("incremental", "随事件增量计算")),
            chip_template="因子模式: {value}", tab_label="因子执行", tab_order=20,
        ),
        "warmup_mode": FieldDefinition(
            public=True, label="前摇窗口", control_template="select", default="auto", tab="factor",
            options=(("none", "不使用"), ("fixed", "固定时间"), ("auto", "按因子表达式自动推导")),
            chip_template="前摇窗口: {value}", tab_label="因子执行", tab_order=20,
            default_when={"engine_mode": {"basic": "none", "auto": "auto", "custom": "auto", "exact": "auto"}},
            help_text="只用于扩大因子计算窗口和 live bar 预热事件；正式信号窗口、绩效统计窗口不随之改变。",
        ),
        "warmup_window": FieldDefinition(
            public=True, label="前摇时长", control_template="text", default="30d", tab="factor",
            visible_when={"warmup_mode": ("fixed",)},
            chip_template="前摇时长: {value}", tab_label="因子执行", tab_order=20,
            help_text="固定前摇窗口必须是时间值，例如 30min、5d、60d；不接受前端以 bar 数作为业务语义。",
        ),
        "calendar_frequency": FieldDefinition(
            public=True, label="时钟", control_template="select", default="auto", tab="calendar",
            options=(("auto", "按因子频率自动判断"), ("1min", "1 分钟"), ("5min", "5 分钟"), ("1day", "1 天")),
            chip_template="时钟: {value}", tab_label="回测时钟", tab_order=190,
        ),
        "live_factor_state": FieldDefinition(public=False),
    }

    signal_live: ClassVar[Flow] = Flow(
        "signal_live",
        inputs=(
            FactorModule.factor,
            calendar_frequency,
            signal_freq,
            basepoint,
            daily_basepoint,
            end_session_skip,
            end_session_gap,
            RunWindowModule.start_date,
            RunWindowModule.end_date,
            RunWindowModule.start_time,
            RunWindowModule.end_time,
            RunWindowModule.timezone,
            RunWindowModule.time_precision,
            warmup_mode,
            warmup_window,
            MarketDataModule.required_frequency,
            MarketDataModule.causal_valuation_table,
        ),
        outputs=(),
        phase=Phase.PRE_REPLAY, order=50,
        description="登记实时因子信号",
        compute=lambda state, ctx: _schedule_signal_live_timestamps(state, ctx),
        strategy_scoped=True,
    )
    signal_precomputed: ClassVar[Flow] = Flow(
        "signal_precomputed",
        inputs=(
            FactorModule.factor,
            ProductSelectionModule.products,
            ProductSelectionModule.product_path_selection,
            calendar_frequency,
            signal_freq,
            basepoint,
            daily_basepoint,
            end_session_skip,
            end_session_gap,
            RunWindowModule.start_date,
            RunWindowModule.end_date,
            RunWindowModule.start_time,
            RunWindowModule.end_time,
            RunWindowModule.timezone,
            RunWindowModule.time_precision,
            warmup_mode,
            warmup_window,
            MarketDataModule.data_source_mode,
            MarketDataModule.data_source,
            MarketDataModule.freq_mode,
            MarketDataModule.freq_fixed,
            MarketDataModule.required_data_source,
            MarketDataModule.required_frequency,
        ),
        outputs=(signal_value,),
        phase=Phase.PRE_REPLAY, order=50,
        description="登记预计算信号",
        compute=lambda state, ctx: _schedule_signal_precomputed_timestamps(state, ctx),
        strategy_scoped=True,
    )

    signal_live_on_event: ClassVar[Flow] = Flow(
        "signal_live", inputs=(FactorModule.factor, live_factor_state), outputs=(signal_value,),
        phase=Phase.PER_EVENT, event_kind=EventKind.SIGNAL, order=5,
        description="读取实时因子信号",
        compute=lambda state, ctx: _evaluate_signal_live(state, ctx),
    )
    signal_live_on_bar: ClassVar[Flow] = Flow(
        "signal_live", inputs=(
            FactorModule.factor,
            MarketDataModule.required_frequency,
            MarketDataModule.required_factor_columns,
            MarketDataModule.current_market_snapshot,
        ), outputs=(live_factor_state,),
        phase=Phase.PER_EVENT, event_kind=EventKind.BAR, order=5,
        description="更新实时因子状态",
        compute=lambda state, ctx: _observe_signal_live_bar(state, ctx),
    )
    signal_precomputed_on_event: ClassVar[Flow] = Flow(
        "signal_precomputed", inputs=(signal_value,), outputs=(signal_value,),
        phase=Phase.PER_EVENT, event_kind=EventKind.SIGNAL, order=5,
        description="读取预计算信号",
        compute=lambda state, ctx: _evaluate_signal_precomputed(state, ctx),
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
    raw_ts = cast(pd.Timestamp, pd.Timestamp(raw_ts))
    midnight = cast(pd.Timestamp, pd.Timestamp("00:00:00"))
    is_day_multiple = freq.is_day_multiple() if hasattr(freq, "is_day_multiple") else False
    if is_day_multiple and raw_ts.time() == midnight.time():
        if last_minute_lookup is None:
            raise ValueError(
                "day-level timestamp with no time-of-day component requires "
                "last_minute_lookup to resolve the session's last trading minute")
        raw_ts = cast(pd.Timestamp, pd.Timestamp(last_minute_lookup(raw_ts)))
    return raw_ts.floor("min")


def _group_strategies_by_signal_align_params(state):
    groups: dict[tuple, list] = defaultdict(list)
    for strategy in state.strategy_configs:
        config = state.config_for(strategy)
        key = (
            _effective_signal_frequency(config),
            config.get(FactorSignalModule.basepoint, "last"),
            config.get(FactorSignalModule.daily_basepoint),
            config.get(FactorSignalModule.end_session_skip, True),
            config.get(FactorSignalModule.end_session_gap, "3h"),
            _strategy_run_window_key(config),
        )
        groups[key].append(strategy)
    return groups


def _effective_signal_frequency(config) -> Any:
    calendar_frequency = config.get(FactorSignalModule.calendar_frequency, "auto")
    if calendar_frequency and str(calendar_frequency) != "auto":
        return calendar_frequency
    return config.get(FactorSignalModule.signal_freq, "1d")


def _schedule_signal_live_timestamps(state, ctx) -> None:
    """Schedule live strategy SIGNAL timestamps.

    No factor value is computed here. BarEventModule schedules BAR events to
    update live factor state; SIGNAL events read that state and publish the
    strategy-facing value.
    Strategies sharing identical signal_align parameters are grouped so
    signal_align() runs once per unique parameter combination, not once per
    strategy."""
    data = current_prices_table_for(state)
    if data is None:
        return
    drafts: list[EventDraft] = []
    groups = _group_strategies_by_signal_align_params(state)
    for (freq, basepoint, daily_basepoint, end_session_skip, end_session_gap, _window_key), strategies in groups.items():
        strategies = [s for s in strategies if state.config_for(s).uses_flow("signal_live")]
        if not strategies:
            continue
        aligned = signal_align(
            data, freq, basepoint=basepoint, daily_basepoint=daily_basepoint,
            end_session_skip=end_session_skip,
            end_session_gap=cast(pd.Timedelta, pd.Timedelta(end_session_gap)),
        )
        config = state.config_for(strategies[0])
        aligned = _table_with_exact_event_index(aligned, config, state)
        scheduled = _clip_scheduled_table_to_strategy_window(aligned, config)
        _append_signal_drafts(drafts, signal_event_times(scheduled), strategies)
    ctx.set(FactorSignalModule.signal_value, drafts)  # pushes every draft via FlowContext._push_if_event


def _schedule_signal_precomputed_timestamps(state, ctx) -> None:
    """Evaluate precomputable factors by calculation key.

    A factor object can be shared, but run-window and warm-up semantics are
    strategy inputs.  Strategies only share one evaluated table when the
    factor identity and calculation inputs match; schedule/alignment grouping
    remains a second step over that table.
    """
    by_calculation: dict[tuple, list] = defaultdict(list)
    factor_by_calculation: dict[tuple, Any] = {}
    for strategy in state.strategy_configs:
        if not state.config_for(strategy).uses_flow("signal_precomputed"):
            continue
        config = state.config_for(strategy)
        factor = config.get(FactorModule.factor)
        factor_key = factor_runtime_key(factor)
        calculation_key = _factor_calculation_key(factor_key, config)
        by_calculation[calculation_key].append(strategy)
        factor_by_calculation[calculation_key] = factor

    store = state.factor_signal_store
    tables = store.precomputed_tables

    drafts: list[EventDraft] = []
    for calculation_key, strategies in by_calculation.items():
        factor = factor_by_calculation[calculation_key]
        table = _evaluate_factor_for_strategies(factor, strategies, state, ctx)
        for schedule_key, scheduled_strategies in _group_strategies_by_precomputed_schedule(
            calculation_key, strategies, state,
        ).items():
            first_config = state.config_for(scheduled_strategies[0])
            if schedule_key not in tables:
                store.put_precomputed_table(schedule_key, _schedule_table_for_strategy(table, first_config, state))
            for strategy in scheduled_strategies:
                store.bind_precomputed_table(strategy, schedule_key)
            _append_signal_drafts(drafts, signal_event_times(tables[schedule_key]), scheduled_strategies)
    ctx.set(FactorSignalModule.signal_value, drafts)


def _append_signal_drafts(drafts: list[EventDraft], event_times: list[IndexEventTime], strategies: list) -> None:
    for event_time in event_times:
        for strategy in strategies:
            drafts.append(
                EventDraft(
                    EventKind.SIGNAL,
                    event_time.timestamp,
                    strategy,
                    index_key=event_time.index_key,
                    index_names=event_time.index_names,
                )
            )


def _group_strategies_by_precomputed_schedule(
    calculation_key: tuple,
    strategies: list,
    state,
) -> dict[tuple, list]:
    groups: dict[tuple, list] = defaultdict(list)
    for strategy in strategies:
        config = state.config_for(strategy)
        groups[_precomputed_schedule_key(calculation_key, config)].append(strategy)
    return groups


def _factor_calculation_key(factor_key: Any, config) -> tuple:
    return (
        factor_key,
        "calculation",
        _strategy_product_selection_key(config),
        _strategy_run_window_key(config),
        _strategy_warmup_key(config),
        _strategy_market_data_key(config),
    )


def _strategy_product_selection_key(config) -> tuple:
    selection = config.get(ProductSelectionModule.product_path_selection)
    products = tuple(
        sorted(str(getattr(product, "name", product)) for product in getattr(selection, "products", ()))
    )
    return ("products", str(getattr(selection, "selection_id", "")), products)


def _strategy_market_data_key(config) -> tuple:
    return (
        "market_data",
        str(config.get(MarketDataModule.data_source_mode, "auto") or "auto"),
        _market_data_source_key(config.get(MarketDataModule.data_source)),
        str(config.get(MarketDataModule.freq_mode, "auto") or "auto"),
        str(config.get(MarketDataModule.freq_fixed, "") or ""),
    )


def _market_data_source_key(raw: Any) -> tuple[str, ...]:
    if raw is None:
        return ()
    if isinstance(raw, str):
        values = [item.strip() for item in raw.split(",")]
    elif isinstance(raw, (list, tuple, set, frozenset)):
        values = [str(item).strip() for item in raw]
    else:
        values = [str(raw).strip()]
    return tuple(dict.fromkeys(item for item in values if item and item != "auto"))


def _strategy_warmup_key(config) -> tuple:
    factor = config.get(FactorModule.factor)
    window = warmup_window_for_strategy(config, factor)
    return ("warmup", int(window.value))


def _live_factor_state_key(factor: Any, config) -> tuple:
    return _factor_calculation_key(factor_runtime_key(factor), config)


def _precomputed_schedule_key(calculation_key: tuple, config) -> tuple:
    calendar_frequency = config.get(FactorSignalModule.calendar_frequency, "auto")
    if not calendar_frequency or str(calendar_frequency) == "auto":
        return (calculation_key, "factor")
    return (
        calculation_key,
        str(calendar_frequency),
        config.get(FactorSignalModule.basepoint, "last"),
        config.get(FactorSignalModule.daily_basepoint),
        config.get(FactorSignalModule.end_session_skip, True),
        config.get(FactorSignalModule.end_session_gap, "3h"),
    )


def _evaluate_factor_for_strategies(factor: Any, strategies: list, state, ctx) -> pd.DataFrame:
    start_dt, end_dt = _run_window_envelope_for_strategies(strategies, state)
    warmup_window = _warmup_window_for_strategies(factor, strategies, state)
    frequency = _market_data_frequency_for_strategies(strategies, ctx)
    _market_data_source_for_strategies(strategies, ctx)
    products = _products_for_strategies(strategies, ctx)
    evaluate = getattr(factor, "evaluate")
    try:
        signature = inspect.signature(evaluate)
    except (TypeError, ValueError):
        return evaluate()
    params = signature.parameters
    accepts_kwargs = any(param.kind is inspect.Parameter.VAR_KEYWORD for param in params.values())
    kwargs: dict[str, Any] = {}
    if accepts_kwargs or "warmup_window" in params:
        kwargs["warmup_window"] = warmup_window
    if frequency is not None and (accepts_kwargs or "freq" in params):
        kwargs["freq"] = frequency
    if start_dt is not None and end_dt is not None:
        if accepts_kwargs or "start_dt" in params or "end_dt" in params:
            kwargs.update(start_dt=start_dt, end_dt=end_dt)
        elif "run_window" in params:
            kwargs["run_window"] = (start_dt, end_dt)
    if accepts_kwargs or "products" in params:
        return evaluate(products=products, **kwargs)
    positional_parameters = [
        parameter
        for parameter in params.values()
        if parameter.kind in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        )
    ]
    if positional_parameters:
        return evaluate(products, **kwargs)
    return evaluate(**kwargs)


def _products_for_strategies(strategies: list, ctx) -> tuple[Any, ...]:
    products_by_strategy = {
        strategy: tuple(sorted(ctx.get_for(ProductSelectionModule.products, strategy) or (), key=str))
        for strategy in strategies
    }
    distinct = {products for products in products_by_strategy.values()}
    if len(distinct) != 1:
        raise ValueError("共享因子计算要求策略使用相同的产品路径")
    return next(iter(distinct), ())


def _market_data_frequency_for_strategies(strategies: list, ctx) -> Any | None:
    frequencies = [
        ctx.get_for(MarketDataModule.required_frequency, strategy)
        for strategy in strategies
        if ctx.get_for(MarketDataModule.required_frequency, strategy) is not None
    ]
    unique = {getattr(freq, "name", str(freq)): freq for freq in frequencies}
    if len(unique) > 1:
        labels = ", ".join(sorted(unique))
        raise ValueError(f"同一因子计算组包含多个 Bar 频率: {labels}")
    return next(iter(unique.values()), None)


def _market_data_source_for_strategies(strategies: list, ctx) -> tuple[str, ...] | None:
    sources = [
        _market_data_source_key(source)
        for strategy in strategies
        if (source := ctx.get_for(MarketDataModule.required_data_source, strategy)) is not None
    ]
    unique = set(sources)
    if len(unique) > 1:
        labels = ", ".join("auto" if not source else "+".join(source) for source in sorted(unique))
        raise ValueError(f"同一因子计算组包含多个数据源集合: {labels}")
    return next(iter(unique), None)


def _warmup_window_for_strategies(factor: Any, strategies: list, state) -> pd.Timedelta | None:
    return warmup_window_for_strategies(strategies, state)


def _zero_warmup() -> pd.Timedelta:
    return cast(pd.Timedelta, pd.Timedelta(0))


def _parse_warmup_window(value: Any) -> pd.Timedelta:
    return parse_warmup_window(value)


def _auto_warmup_window(factor: Any) -> pd.Timedelta | None:
    return auto_warmup_window(factor)


def _infer_expr_warmup_window(expr: Any, seen: set[int] | None = None) -> pd.Timedelta | None:
    return _run_window_infer_expr_warmup_window(expr, seen)


def _expr_operands(expr: Any) -> tuple[Any, ...]:
    return _run_window_expr_operands(expr)


def _expr_window_to_timedelta(expr: Any) -> pd.Timedelta | None:
    return _run_window_expr_window_to_timedelta(expr)


def _max_timedelta(values: Any) -> pd.Timedelta | None:
    return _run_window_max_timedelta(values)


def _run_window_envelope_for_strategies(strategies: list, state) -> tuple[DataTime | None, DataTime | None]:
    return run_window_envelope_for_strategies(strategies, state)


def _schedule_table_for_strategy(table: pd.DataFrame, config, state=None) -> pd.DataFrame:
    calendar_frequency = config.get(FactorSignalModule.calendar_frequency, "auto")
    table = _table_with_exact_event_index(table, config, state)
    run_table = _clip_signal_table_to_strategy_window(table, config)
    if not calendar_frequency or str(calendar_frequency) == "auto":
        scheduled = run_table
    else:
        scheduled = signal_align(
            run_table,
            calendar_frequency,
            basepoint=config.get(FactorSignalModule.basepoint, "last"),
            daily_basepoint=config.get(FactorSignalModule.daily_basepoint),
            end_session_skip=config.get(FactorSignalModule.end_session_skip, True),
            end_session_gap=cast(pd.Timedelta, pd.Timedelta(config.get(FactorSignalModule.end_session_gap, "3h"))),
        )
    clipped = _clip_scheduled_table_to_strategy_window(scheduled, config)
    return _table_with_strategy_event_timezone(clipped, config)


def _table_with_exact_event_index(table: pd.DataFrame, config, state=None) -> pd.DataFrame:
    start_dt, end_dt = _strategy_run_window_datetimes(config)
    if table.empty or start_dt is None or end_dt is None:
        return table
    if start_dt.precision == "trading_day" or end_dt.precision == "trading_day":
        return table
    data_index = DataIndex(table.index)
    explicit_day_level = bool(
        data_index.signal_name
        and "_SIGNAL@" in str(data_index.signal_name)
        and DataFreq(str(data_index.signal_name).split("@", 1)[-1]).is_day_multiple()
    )
    inferred_day_level = (
        not data_index.signal_name
        and data_index.freq is not None
        and DataFreq(data_index.freq).is_day_multiple()
        and bool((data_index.signal_index == data_index.signal_index.normalize()).all())
    )
    if not explicit_day_level and not inferred_day_level:
        return table
    lookup = _last_market_event_lookup_by_trading_day(state)
    if lookup is None:
        raise ValueError("日级信号在 exact 回测中需要已加载的日内 market-data 事件时间")
    trading_days = DataIndex.trading_day_index_from_index(table.index)
    start_day = _naive_trading_day(start_dt.ts)
    end_day = _naive_trading_day(end_dt.ts)
    day_mask = (trading_days >= start_day) & (trading_days <= end_day)
    table = table.loc[day_mask]
    trading_days = pd.DatetimeIndex(trading_days[day_mask])
    mapped = [lookup.get(pd.Timestamp(day).normalize()) for day in trading_days]
    if any(value is None for value in mapped):
        missing = next(pd.Timestamp(day).date() for day, value in zip(trading_days, mapped) if value is None)
        raise ValueError(f"日级信号缺少 trading_day={missing} 的 market-data 事件时间")
    result = table.copy(deep=False)
    result.index = pd.DatetimeIndex(cast(list[pd.Timestamp], mapped))
    return result


def _naive_trading_day(value: Any) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tzinfo is not None:
        ts = ts.tz_localize(None)
    return ts.normalize()


def _last_market_event_lookup_by_trading_day(state) -> dict[pd.Timestamp, pd.Timestamp] | None:
    if state is None:
        return None
    table = current_prices_table_for(state)
    if table is None or getattr(table, "empty", True):
        return None
    days = DataIndex.trading_day_index_from_index(table.index)
    timestamps = DataIndex.event_timestamps_from_index(table.index)
    lookup: dict[pd.Timestamp, pd.Timestamp] = {}
    for day, timestamp in zip(days, timestamps):
        if pd.isna(day) or pd.isna(timestamp):
            continue
        key = pd.Timestamp(day).normalize()
        ts = pd.Timestamp(timestamp)
        previous = lookup.get(key)
        if previous is None or ts > previous:
            lookup[key] = ts
    return lookup


def _table_with_strategy_event_timezone(table: pd.DataFrame, config) -> pd.DataFrame:
    timezone = str(config.get(RunWindowModule.timezone, "Asia/Shanghai") or "Asia/Shanghai")
    if table.empty:
        return table
    index = table.index
    if isinstance(index, pd.MultiIndex):
        event_values = _timestamps_in_timezone(pd.DatetimeIndex(index.get_level_values(-1)), timezone)
        arrays = [
            event_values if pos == index.nlevels - 1 else index.get_level_values(pos)
            for pos in range(index.nlevels)
        ]
        result = table.copy(deep=False)
        result.index = pd.MultiIndex.from_arrays(arrays, names=index.names)
        return result
    result = table.copy(deep=False)
    result.index = _timestamps_in_timezone(pd.DatetimeIndex(index), timezone)
    return result


def _timestamps_in_timezone(index: pd.DatetimeIndex, timezone: str) -> pd.DatetimeIndex:
    if index.tz is None:
        return pd.DatetimeIndex(index.tz_localize(timezone))
    return pd.DatetimeIndex(index.tz_convert(timezone))


def _clip_signal_table_to_strategy_window(table: pd.DataFrame, config) -> pd.DataFrame:
    start_dt, end_dt = _strategy_run_window_datetimes(config)
    if start_dt is None or end_dt is None:
        return table
    if start_dt.precision == "trading_day" or end_dt.precision == "trading_day":
        mask = DataIndex(table.index).slice_by_datatime(start_dt, end_dt)
    else:
        event_index = DataIndex(table.index).finest_index
        mask = DataIndex(event_index).slice_by_datatime(start_dt, end_dt)
    return table.loc[mask]


def _clip_scheduled_table_to_strategy_window(table: pd.DataFrame, config) -> pd.DataFrame:
    """Clip a scheduled table by the timestamp that will enter EventQueue.

    ``signal_align(..., "1d")`` deliberately keeps both a semantic
    ``_SIGNAL@DAY1`` level and the selected intraday bar timestamp.  Exact run
    windows must therefore compare the finest/event-time level, while
    trading-day windows retain DataIndex's trading-day-aware slicing.
    """
    start_dt, end_dt = _strategy_run_window_datetimes(config)
    if start_dt is None or end_dt is None:
        return table
    if start_dt.precision == "trading_day" or end_dt.precision == "trading_day":
        mask = DataIndex(table.index).slice_by_datatime(start_dt, end_dt)
    else:
        event_index = DataIndex(table.index).finest_index
        mask = DataIndex(event_index).slice_by_datatime(start_dt, end_dt)
    return table.loc[mask]


def _clip_table_to_strategy_warmup_window(table: pd.DataFrame, config) -> pd.DataFrame:
    start_dt, end_dt = _strategy_run_window_datetimes(config)
    if table.empty:
        return table
    if start_dt is None or end_dt is None:
        return table
    data_index = DataIndex(table.index)
    mask = data_index.slice_by_datatime(start_dt, end_dt)
    warmup_window = warmup_window_for_strategy(config, config.get(FactorModule.factor))
    if warmup_window <= pd.Timedelta(0) or not mask.any():
        return table.loc[mask]
    positions = mask.nonzero()[0]
    warmup_bars = _warmup_window_to_bars_for_table(warmup_window, table)
    if warmup_bars <= 0:
        return table.loc[mask]
    expanded = mask.copy()
    expanded[max(0, int(positions[0]) - warmup_bars):int(positions[0])] = True
    return table.loc[expanded]


def _warmup_window_to_bars_for_table(warmup_window: pd.Timedelta, table: pd.DataFrame) -> int:
    data_freq = DataIndex(table.index).freq
    if data_freq is None:
        return 0
    products = list(table.columns)
    try:
        from tools.factors.expr.rolling import _resolve_windows

        common, periods, product_periods = _resolve_windows(warmup_window, data_freq, products)
        if common:
            return max(0, int(periods))
        return max((int(value) for value in product_periods.values()), default=0)
    except Exception:
        freq_delta = DataFreq(data_freq).value
        if freq_delta <= pd.Timedelta(0):
            return 0
        return max(0, int((warmup_window + freq_delta - pd.Timedelta(1, "ns")) / freq_delta))


def _strategy_run_window_datetimes(config) -> tuple[DataTime | None, DataTime | None]:
    return strategy_run_window_datetimes(config)


def _strategy_run_window_key(config) -> tuple:
    return run_window_key_for_config(config)


def _evaluate_signal_live(state, ctx) -> None:
    """Publish the current live signal from per-factor BAR state.

    FactorExpr/Factor values are compiled into per-run incremental executors.
    A non-FactorExpr live adapter can still implement one of these methods:
    `on_signal(timestamp, price_table)`, `evaluate_live(price_table, timestamp)`.
    Shared factor objects are evaluated once per dispatch.
    """
    by_factor: dict[Any, list] = defaultdict(list)
    factor_by_key: dict[Any, Any] = {}
    for strategy in ctx.active_strategies:
        config = state.config_for(strategy)
        factor = config.get(FactorModule.factor)
        state_key = _live_factor_state_key(factor, config)
        by_factor[state_key].append(strategy)
        factor_by_key[state_key] = factor

    store = state.factor_signal_store
    price_tables = store.live_price_tables
    executors = store.live_executors
    for factor_key, strategies in by_factor.items():
        factor = factor_by_key[factor_key]
        executor = executors.get(factor_key)
        if executor is not None:
            values = _row_to_signal_values(executor.on_signal(ctx.timestamp))
        else:
            values = _live_signal_values(factor, ctx.timestamp, price_tables.get(factor_key))
        for strategy in strategies:
            ctx.set_for(FactorSignalModule.signal_value, strategy, values)


def _evaluate_signal_precomputed(state, ctx) -> None:
    """Looks up a value from the table cached once in PRE_REPLAY
    (`BacktestRunState.factor_signal_store.precomputed_tables`, keyed by calculation/schedule key) -- no
    re-evaluation here."""
    store = state.factor_signal_store
    for strategy in ctx.active_strategies:
        table = store.precomputed_table_for(strategy)
        if table is None:
            raise KeyError(f"precomputed signal table is missing for strategy {strategy!r}")
        ctx.set_for(FactorSignalModule.signal_value, strategy, _precomputed_signal_values_for_event(store, table, ctx, strategy))


def _precomputed_signal_values_for_event(store: FactorSignalStore, table: pd.DataFrame, ctx, strategy) -> dict[Any, float]:
    try:
        draft = ctx.draft_for(strategy)
        index_key = draft.index_key
    except Exception:
        index_key = None
    cache_key = (id(table), _precomputed_signal_cache_key(index_key if index_key is not None else ctx.timestamp))
    cached = store.precomputed_signal_value_cache.get(cache_key)
    if cached is not None:
        return cached
    try:
        row = row_at_index_key(table, index_key) if index_key is not None else row_at(table, ctx.timestamp)
    except KeyError:
        values: dict[Any, float] = {}
    else:
        values = {product: float(cast(Any, row[product])) for product in table.columns}
    store.precomputed_signal_value_cache[cache_key] = values
    return values


def _precomputed_signal_cache_key(index_key: Any) -> Any:
    try:
        hash(index_key)
    except TypeError:
        return repr(index_key)
    return index_key


def _observe_signal_live_bar(state, ctx) -> None:
    """Feed one bar of current market data into each active live factor."""
    snapshot = ctx.get(MarketDataModule.current_market_snapshot, {}) or {}
    fields_by_product = _factor_fields_by_product(snapshot)
    term_curves_by_product = _factor_term_curves_by_product(snapshot)
    if not fields_by_product and not term_curves_by_product:
        return
    store = state.factor_signal_store
    tables = store.live_price_tables
    executors = store.live_executors

    by_factor: dict[Any, list] = defaultdict(list)
    factor_by_key: dict[Any, Any] = {}
    for strategy in ctx.active_strategies:
        config = state.config_for(strategy)
        factor = config.get(FactorModule.factor)
        state_key = _live_factor_state_key(factor, config)
        by_factor[state_key].append(strategy)
        factor_by_key[state_key] = factor

    close_prices = snapshot.get("close", {})
    row = pd.DataFrame([close_prices], index=[pd.Timestamp(ctx.timestamp)])
    for factor_key in by_factor:
        factor = factor_by_key[factor_key]
        table = tables.get(factor_key)
        if table is None:
            tables[factor_key] = row
        else:
            updated = pd.concat([table, row])
            tables[factor_key] = updated.iloc[~updated.index.duplicated(keep="last")]
        executor = executors.get(factor_key)
        if executor is None:
            products = _live_products_for_strategies(by_factor[factor_key], ctx)
            executor = _compile_live_factor_executor(
                factor,
                by_factor[factor_key][0],
                products if products else (set(fields_by_product) | set(term_curves_by_product)),
                resolved_bar_frequency_for_strategy(state, by_factor[factor_key][0]),
            )
            if executor is not None:
                executors[factor_key] = executor
        if executor is not None:
            _call_live_executor_on_bar(
                executor,
                pd.Timestamp(ctx.timestamp),
                fields_by_product,
                term_curves_by_product,
            )
            current_value = getattr(executor, "on_signal", None)
            if callable(current_value):
                values = _row_to_signal_values(current_value(ctx.timestamp))
                for strategy in by_factor[factor_key]:
                    ctx.set_for(FactorSignalModule.live_factor_state, strategy, values)
            continue
        on_bar = getattr(factor, "on_bar", None)
        if callable(on_bar):
            # Preserve the public live-adapter contract: custom factors receive
            # the scalar close-price map. Compiled FactorExpr executors consume
            # the richer canonical DataColumn mapping above.
            on_bar(pd.Timestamp(ctx.timestamp), dict(close_prices))


def _live_products_for_strategies(strategies: list, ctx) -> tuple[Any, ...]:
    products_by_strategy = {
        strategy: tuple(sorted(ctx.get_for(ProductSelectionModule.products, strategy) or (), key=str))
        for strategy in strategies
    }
    distinct = {products for products in products_by_strategy.values() if products}
    if not distinct:
        return ()
    if len(distinct) != 1:
        raise ValueError("共享 live FactorExpr executor 要求策略使用相同的产品集合")
    return next(iter(distinct))


def _factor_fields_by_product(snapshot: dict[str, dict[Any, float]]) -> dict[Any, dict[str, float]]:
    fields: dict[Any, dict[str, float]] = defaultdict(dict)
    for column_name, values in snapshot.items():
        if column_name == "TERM_STRUCTURE":
            continue
        if not str(column_name).isupper() or not isinstance(values, dict):
            continue
        for product, value in values.items():
            fields[product][str(column_name)] = float(value)
    return dict(fields)


def _factor_term_curves_by_product(snapshot: dict[str, dict[Any, Any]]) -> dict[Any, Any]:
    values = snapshot.get("TERM_STRUCTURE", {})
    return dict(values) if isinstance(values, dict) else {}


def _call_live_executor_on_bar(
    executor: Any,
    timestamp: pd.Timestamp,
    fields_by_product: dict[Any, dict[str, float]],
    term_curves_by_product: dict[Any, Any],
) -> None:
    on_bar = executor.on_bar
    signature = inspect.signature(on_bar)
    accepts_varargs = any(
        parameter.kind is inspect.Parameter.VAR_POSITIONAL
        for parameter in signature.parameters.values()
    )
    if accepts_varargs or len(signature.parameters) >= 3:
        on_bar(timestamp, fields_by_product, term_curves_by_product)
    else:
        on_bar(timestamp, fields_by_product)


def _live_signal_values(factor: Any, timestamp: pd.Timestamp, price_table: pd.DataFrame | None) -> dict:
    timestamp = cast(pd.Timestamp, pd.Timestamp(timestamp))
    on_signal = getattr(factor, "on_signal", None)
    if callable(on_signal):
        return _row_to_signal_values(on_signal(timestamp, price_table))

    evaluate_live = getattr(factor, "evaluate_live", None)
    if callable(evaluate_live):
        return _row_to_signal_values(evaluate_live(price_table, timestamp))

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
