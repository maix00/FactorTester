"""FactorSignalModule — schedules SIGNAL events and publishes signal values.

"signal_live" observes BAR events scheduled by BarEventModule into per-factor
causal state, then emits signal values only when its scheduled SIGNAL events fire.
"signal_precomputed" evaluates once over the whole backtest range and looks
values up at SIGNAL events.
"""

from __future__ import annotations

from collections import defaultdict
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
from tools.testers.backtest.modules.run_window import RunWindowModule
from tools.testers.backtest.modules.time_index_lookup import (
    IndexEventTime,
    row_at,
    row_at_index_key,
    signal_event_times,
)


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
    }

    signal_live: ClassVar[Flow] = Flow(
        "signal_live", inputs=(), outputs=(),
        phase=Phase.PRE_REPLAY, order=50,
        compute=lambda account, ctx: _schedule_signal_live_timestamps(account, ctx),
        strategy_scoped=True,
    )
    signal_precomputed: ClassVar[Flow] = Flow(
        "signal_precomputed", inputs=(FactorModule.factor,), outputs=(),
        phase=Phase.PRE_REPLAY, order=50,
        compute=lambda account, ctx: _schedule_signal_precomputed_timestamps(account, ctx),
        strategy_scoped=True,
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
            _strategy_run_window_key(config),
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
    for (freq, basepoint, daily_basepoint, end_session_skip, end_session_gap, _window_key), strategies in groups.items():
        strategies = [s for s in strategies if account.config_for(s).uses_flow("signal_live")]
        if not strategies:
            continue
        aligned = signal_align(
            data, freq, basepoint=basepoint, daily_basepoint=daily_basepoint,
            end_session_skip=end_session_skip,
            end_session_gap=cast(pd.Timedelta, pd.Timedelta(end_session_gap)),
        )
        scheduled = _clip_signal_table_to_strategy_window(aligned, account.config_for(strategies[0]))
        _append_signal_drafts(drafts, signal_event_times(scheduled), strategies)
    ctx.set(FactorSignalModule.signal_value, drafts)  # pushes every draft via FlowContext._push_if_event


def _schedule_signal_precomputed_timestamps(account, ctx) -> None:
    """Groups strategies by factor identity -- a shared factor's
    `evaluate()` runs once for the whole backtest range, not once per
    strategy. The resulting table's own index is the signal schedule
    (already at the factor's native frequency, no separate signal_align
    pass needed) and gets cached on `account.precomputed_factor_tables`
    for the PER_EVENT lookup Flow to read."""
    by_factor: dict[Any, list] = defaultdict(list)
    factor_by_key: dict[Any, Any] = {}
    for strategy in account.strategy_configs:
        if not account.config_for(strategy).uses_flow("signal_precomputed"):
            continue
        factor = account.config_for(strategy).get(FactorModule.factor)
        factor_key = factor_runtime_key(factor)
        by_factor[factor_key].append(strategy)
        factor_by_key[factor_key] = factor

    tables = getattr(account, "precomputed_factor_tables", None)
    if tables is None:
        tables = {}
        account.precomputed_factor_tables = tables
    table_keys = getattr(account, "precomputed_factor_table_keys", None)
    if table_keys is None:
        table_keys = {}
        account.precomputed_factor_table_keys = table_keys

    drafts: list[EventDraft] = []
    for factor_key, strategies in by_factor.items():
        factor = factor_by_key[factor_key]
        table = _evaluate_factor_for_strategies(factor, strategies, account)
        for schedule_key, scheduled_strategies in _group_strategies_by_precomputed_schedule(
            factor_key, strategies, account,
        ).items():
            first_config = account.config_for(scheduled_strategies[0])
            if schedule_key not in tables:
                tables[schedule_key] = _schedule_table_for_strategy(table, first_config)
            for strategy in scheduled_strategies:
                table_keys[strategy] = schedule_key
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
    factor_key: Any,
    strategies: list,
    account,
) -> dict[tuple, list]:
    groups: dict[tuple, list] = defaultdict(list)
    for strategy in strategies:
        config = account.config_for(strategy)
        groups[_precomputed_schedule_key(factor_key, config)].append(strategy)
    return groups


def _precomputed_schedule_key(factor_key: Any, config) -> tuple:
    calendar_frequency = config.get(FactorSignalModule.calendar_frequency, "auto")
    window_key = _strategy_run_window_key(config)
    if not calendar_frequency or str(calendar_frequency) == "auto":
        return (factor_key, "factor", window_key)
    return (
        factor_key,
        str(calendar_frequency),
        config.get(FactorSignalModule.basepoint, "last"),
        config.get(FactorSignalModule.daily_basepoint),
        config.get(FactorSignalModule.end_session_skip, True),
        config.get(FactorSignalModule.end_session_gap, "3h"),
        window_key,
    )


def _evaluate_factor_for_strategies(factor: Any, strategies: list, account) -> pd.DataFrame:
    start_dt, end_dt = _run_window_envelope_for_strategies(strategies, account)
    calc_start_dt = _calc_start_for_strategies(factor, strategies, account, start_dt)
    evaluate = getattr(factor, "evaluate")
    if start_dt is None or end_dt is None:
        return evaluate()
    try:
        signature = inspect.signature(evaluate)
    except (TypeError, ValueError):
        return evaluate()
    params = signature.parameters
    accepts_kwargs = any(param.kind is inspect.Parameter.VAR_KEYWORD for param in params.values())
    if accepts_kwargs or "start_dt" in params or "end_dt" in params:
        return evaluate(start_dt=calc_start_dt, end_dt=end_dt)
    if "run_window" in params:
        return evaluate(run_window=(calc_start_dt, end_dt))
    return evaluate()


def _calc_start_for_strategies(
    factor: Any,
    strategies: list,
    account,
    run_start_dt: DataTime | None,
) -> DataTime | None:
    """Return the left edge used only for factor calculation warm-up.

    The formal run window is still clipped before signal alignment and before
    any performance/accounting flow observes the signal.
    """
    if run_start_dt is None:
        return None
    warmup = _warmup_window_for_strategies(factor, strategies, account)
    if warmup is None or warmup <= pd.Timedelta(0):
        return run_start_dt
    if run_start_dt.ts is None:
        return run_start_dt
    return DataTime(ts=run_start_dt.ts - warmup, precision=run_start_dt.precision, tz=run_start_dt.tz)


def _warmup_window_for_strategies(factor: Any, strategies: list, account) -> pd.Timedelta | None:
    windows: list[pd.Timedelta] = []
    for strategy in strategies:
        config = account.config_for(strategy)
        mode = str(config.get(FactorSignalModule.warmup_mode, "auto") or "auto").lower()
        if mode == "none":
            windows.append(_zero_warmup())
        elif mode == "fixed":
            windows.append(_parse_warmup_window(config.get(FactorSignalModule.warmup_window)))
        elif mode == "auto":
            windows.append(_auto_warmup_window(factor) or _zero_warmup())
        else:
            windows.append(_zero_warmup())
    return max(windows) if windows else None


def _zero_warmup() -> pd.Timedelta:
    return cast(pd.Timedelta, pd.Timedelta(0))


def _parse_warmup_window(value: Any) -> pd.Timedelta:
    if value is None or str(value).strip() == "":
        return _zero_warmup()
    value_text = str(value).strip()
    if value_text.endswith("d"):
        value_text = f"{value_text[:-1]}D"
    try:
        delta = pd.Timedelta(value_text)
    except Exception as exc:
        raise ValueError(f"invalid fixed warmup_window={value!r}; expected a time value such as '30min' or '5d'") from exc
    if pd.isna(delta):
        raise ValueError(f"invalid fixed warmup_window={value!r}; expected a concrete time value")
    if delta < pd.Timedelta(0):
        raise ValueError(f"warmup_window must be non-negative, got {value!r}")
    return cast(pd.Timedelta, delta)


def _auto_warmup_window(factor: Any) -> pd.Timedelta | None:
    """Infer expression warm-up for constant time-valued rolling/shift windows.

    Dynamic parameters and integer bar windows are intentionally not guessed:
    fixed bar counts require a product calendar/frequency context, while this
    setting is registered as a time-valued field.
    """
    for obj in (factor, getattr(factor, "_expr", None), getattr(factor, "expression", None)):
        if obj is None:
            continue
        required = getattr(obj, "required_warmup_window", None) or getattr(obj, "required_lookback", None)
        if callable(required):
            value = required()
            return _parse_warmup_window(value)
        if required is not None:
            return _parse_warmup_window(required)
        inferred = _infer_expr_warmup_window(obj)
        if inferred is not None:
            return inferred
    return None


def _infer_expr_warmup_window(expr: Any, seen: set[int] | None = None) -> pd.Timedelta | None:
    if expr is None:
        return None
    seen = seen or set()
    expr_id = id(expr)
    if expr_id in seen:
        return None
    seen.add(expr_id)

    cls_name = type(expr).__name__
    if cls_name == "RollingOp":
        window = _expr_window_to_timedelta(getattr(expr, "window", None))
        if window is None:
            return None
        child_window = _max_timedelta(
            _infer_expr_warmup_window(child, seen)
            for child in _expr_operands(expr)
            if child is not getattr(expr, "window", None)
        )
        return window + (child_window or _zero_warmup())
    if cls_name == "ShiftOp":
        shift = _expr_window_to_timedelta(getattr(expr, "periods", None))
        if shift is None:
            return None
        child_window = _infer_expr_warmup_window(getattr(expr, "operand", None), seen)
        return shift + (child_window or _zero_warmup())
    return _max_timedelta(_infer_expr_warmup_window(child, seen) for child in _expr_operands(expr))


def _expr_operands(expr: Any) -> tuple[Any, ...]:
    operands = getattr(expr, "_operands", None)
    if operands is None:
        operands = getattr(expr, "operands", ())
    try:
        return tuple(operands)
    except TypeError:
        return ()


def _expr_window_to_timedelta(expr: Any) -> pd.Timedelta | None:
    value = getattr(expr, "value", expr)
    if isinstance(value, (int, float)):
        return None
    freq_value = getattr(value, "value", None)
    if isinstance(freq_value, pd.Timedelta):
        return cast(pd.Timedelta, freq_value)
    try:
        return _parse_warmup_window(value)
    except ValueError:
        return None


def _max_timedelta(values: Any) -> pd.Timedelta | None:
    concrete = [value for value in values if value is not None]
    return max(concrete) if concrete else None


def _run_window_envelope_for_strategies(strategies: list, account) -> tuple[DataTime | None, DataTime | None]:
    starts: list[DataTime] = []
    ends: list[DataTime] = []
    for strategy in strategies:
        start_dt, end_dt = _strategy_run_window_datetimes(account.config_for(strategy))
        if start_dt is None or end_dt is None:
            return None, None
        starts.append(start_dt)
        ends.append(end_dt)
    if not starts or not ends:
        return None, None
    return (
        min(starts, key=lambda dt: cast(pd.Timestamp, dt.sort_key())),
        max(ends, key=lambda dt: cast(pd.Timestamp, dt.sort_key())),
    )


def _schedule_table_for_strategy(table: pd.DataFrame, config) -> pd.DataFrame:
    calendar_frequency = config.get(FactorSignalModule.calendar_frequency, "auto")
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
    return _clip_signal_table_to_strategy_window(scheduled, config)


def _clip_signal_table_to_strategy_window(table: pd.DataFrame, config) -> pd.DataFrame:
    start_dt, end_dt = _strategy_run_window_datetimes(config)
    if start_dt is None or end_dt is None:
        return table
    mask = DataIndex(table.index).slice_by_datatime(start_dt, end_dt)
    return table.loc[mask]


def _strategy_run_window_datetimes(config) -> tuple[DataTime | None, DataTime | None]:
    start_date = str(config.get(RunWindowModule.start_date, "") or "").strip()
    end_date = str(config.get(RunWindowModule.end_date, "") or "").strip()
    if not start_date or not end_date:
        return None, None
    precision = str(config.get(RunWindowModule.time_precision, "exact") or "exact")
    timezone = str(config.get(RunWindowModule.timezone, "Asia/Shanghai") or "Asia/Shanghai")
    if precision == "trading_day":
        return (
            DataTime.from_dict({"date": start_date}, precision="trading_day"),
            DataTime.from_dict({"date": end_date}, precision="trading_day"),
        )
    start_time = str(config.get(RunWindowModule.start_time, "00:00") or "00:00")
    end_time = str(config.get(RunWindowModule.end_time, "23:59") or "23:59")
    return (
        DataTime.from_dict({"date": start_date, "time": start_time, "tz": timezone}, precision="exact"),
        DataTime.from_dict({"date": end_date, "time": end_time, "tz": timezone}, precision="exact"),
    )


def _strategy_run_window_key(config) -> tuple:
    start_dt, end_dt = _strategy_run_window_datetimes(config)
    if start_dt is None or end_dt is None:
        return ("unbounded",)
    return (str(start_dt.precision), start_dt.ts, end_dt.ts)


def _evaluate_signal_live(account, ctx) -> None:
    """Publish the current live signal from per-factor BAR state.

    FactorExpr/Factor values are compiled into per-run incremental executors.
    A non-FactorExpr live adapter can still implement one of these methods:
    `on_signal(timestamp, price_table)`, `evaluate_live(price_table, timestamp)`.
    Shared factor objects are evaluated once per dispatch.
    """
    by_factor: dict[Any, list] = defaultdict(list)
    factor_by_key: dict[Any, Any] = {}
    for strategy in ctx.active_strategies:
        factor = account.config_for(strategy).get(FactorModule.factor)
        factor_key = factor_runtime_key(factor)
        by_factor[factor_key].append(strategy)
        factor_by_key[factor_key] = factor

    price_tables = getattr(account, "live_factor_price_tables", {})
    executors = getattr(account, "live_factor_executors", {})
    for factor_key, strategies in by_factor.items():
        factor = factor_by_key[factor_key]
        executor = executors.get(factor_key)
        if executor is not None:
            values = _row_to_signal_values(executor.on_signal(ctx.timestamp))
        else:
            values = _live_signal_values(factor, ctx.timestamp, price_tables.get(factor_key))
        for strategy in strategies:
            ctx.set_for(FactorSignalModule.signal_value, strategy, values)


def _evaluate_signal_precomputed(account, ctx) -> None:
    """Looks up a value from the table cached once in PRE_REPLAY
    (`account.precomputed_factor_tables`, keyed by id(factor)) -- no
    re-evaluation here."""
    tables = getattr(account, "precomputed_factor_tables", {})
    table_keys = getattr(account, "precomputed_factor_table_keys", {})
    for strategy in ctx.active_strategies:
        config = account.config_for(strategy)
        factor = config.get(FactorModule.factor)
        fallback_key = _precomputed_schedule_key(factor_runtime_key(factor), config)
        table = tables.get(table_keys.get(strategy, fallback_key))
        if table is None:
            ctx.set_for(FactorSignalModule.signal_value, strategy, {})
            continue
        try:
            draft = ctx.draft_for(strategy)
            row = row_at_index_key(table, draft.index_key) if draft.index_key is not None else row_at(table, ctx.timestamp)
        except KeyError:
            ctx.set_for(FactorSignalModule.signal_value, strategy, {})
            continue
        ctx.set_for(FactorSignalModule.signal_value, strategy,
                     {product: float(cast(Any, row[product])) for product in table.columns})


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

    by_factor: dict[Any, list] = defaultdict(list)
    factor_by_key: dict[Any, Any] = {}
    for strategy in ctx.active_strategies:
        factor = account.config_for(strategy).get(FactorModule.factor)
        factor_key = factor_runtime_key(factor)
        by_factor[factor_key].append(strategy)
        factor_by_key[factor_key] = factor

    row = pd.DataFrame([prices], index=[pd.Timestamp(ctx.timestamp)])
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
            executor = _compile_live_factor_executor(
                factor,
                by_factor[factor_key][0],
                prices.keys(),
                getattr(account, "source_freq", None),
            )
            if executor is not None:
                executors[factor_key] = executor
        if executor is not None:
            executor.on_bar(pd.Timestamp(ctx.timestamp), prices)
            continue
        on_bar = getattr(factor, "on_bar", None)
        if callable(on_bar):
            on_bar(pd.Timestamp(ctx.timestamp), dict(prices))


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
