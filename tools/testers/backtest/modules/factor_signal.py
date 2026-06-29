"""FactorSignalModule — decides WHEN a signal event should fire
("signal_live"/"signal_precomputed" PRE_REPLAY Flows, timestamp scheduling
only) and WHAT the signal value is at that moment ("signal_live"/
"signal_precomputed" PER_EVENT Flows, same names, mutually exclusive per
strategy via StrategyConfig.active_flow_names).

"signal_live" evaluates the factor fresh every time it fires (no caching
across events); "signal_precomputed" evaluates the factor expression once
over the whole backtest range in PRE_REPLAY and just looks values up by
timestamp afterward — same data, different evaluation cadence.
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


class FactorSignalModule(ExecutableModule):
    key: ClassVar[str] = "factor_signal"
    label: ClassVar[str] = "信号时机"

    signal_freq: ClassVar[FieldRef[Any]] = FieldRef("signal_freq")
    basepoint: ClassVar[FieldRef[Any]] = FieldRef("basepoint")
    daily_basepoint: ClassVar[FieldRef[Any]] = FieldRef("daily_basepoint")
    end_session_skip: ClassVar[FieldRef[bool]] = FieldRef("end_session_skip")
    end_session_gap: ClassVar[FieldRef[Any]] = FieldRef("end_session_gap")
    signal_value: ClassVar[FieldRef[Any]] = FieldRef("signal_value")  # dict[Product, float]
    factor_mode: ClassVar[FieldRef[str]] = FieldRef("factor_mode")
        # "auto"|"precomputed"|"incremental" -- selects which of
        # "signal_precomputed"/"signal_live" this strategy activates; read
        # directly off the resolved settings dict by
        # strategy_config_builder._resolve_active_flow_names (it determines
        # *which Flow runs at all*, not a Flow's input value, so it isn't
        # consumed via StrategyConfig.get like an ordinary field).

    fields: ClassVar[dict[str, FieldDefinition]] = {
        "signal_freq": FieldDefinition(public=True, control_template="select", default="1d", tab="frequency"),
        "basepoint": FieldDefinition(public=True, control_template="select", default="last", tab="frequency"),
        "daily_basepoint": FieldDefinition(public=True, control_template="text", default=None, tab="frequency"),
        "end_session_skip": FieldDefinition(public=True, control_template="boolean", default=True, tab="frequency"),
        "end_session_gap": FieldDefinition(
            public=True, control_template="text", default="3h", tab="frequency"),
            # plain pd.Timedelta-parseable string ("3h" -> pd.Timedelta("3h"));
            # JSON-serializable as-is, parsed back via pd.Timedelta(value)
            # wherever this field is actually used (signal_align needs a real
            # Timedelta, not a string)
        "factor_mode": FieldDefinition(
            public=True, control_template="select", default="auto", tab="factor",
            options=(("auto", "自动选择"), ("precomputed", "预计算后按事件回放"), ("incremental", "随事件增量计算")),
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
    signal_precomputed_on_event: ClassVar[Flow] = Flow(
        "signal_precomputed", inputs=(), outputs=(signal_value,),
        phase=Phase.PER_EVENT, event_kind=EventKind.SIGNAL, order=5,
        compute=lambda account, ctx: _evaluate_signal_precomputed(account, ctx),
    )

    flows: ClassVar[tuple[Flow, ...]] = (
        signal_live, signal_precomputed, signal_live_on_event, signal_precomputed_on_event,
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
            config.get(FactorSignalModule.signal_freq, "1d"),
            config.get(FactorSignalModule.basepoint, "last"),
            config.get(FactorSignalModule.daily_basepoint),
            config.get(FactorSignalModule.end_session_skip, True),
            config.get(FactorSignalModule.end_session_gap, "3h"),
        )
        groups[key].append(strategy)
    return groups


def _schedule_signal_live_timestamps(account, ctx) -> None:
    """Timestamp scheduling only -- no factor value is computed here.
    Strategies sharing identical signal_align parameters are grouped so
    signal_align() runs once per unique parameter combination, not once per
    strategy."""
    data = getattr(account, "current_prices_table", None)
    if data is None:
        return
    groups = _group_strategies_by_signal_align_params(account)
    drafts: list[EventDraft] = []
    for (freq, basepoint, daily_basepoint, end_session_skip, end_session_gap), strategies in groups.items():
        strategies = [s for s in strategies if account.config_for(s).uses_flow("signal_live")]
        if not strategies:
            continue
        aligned = signal_align(
            data, freq, basepoint=basepoint, daily_basepoint=daily_basepoint,
            end_session_skip=end_session_skip, end_session_gap=pd.Timedelta(end_session_gap),
        )
        for ts in aligned.index:
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

    drafts: list[EventDraft] = []
    for factor_id, strategies in by_factor.items():
        factor = factor_by_id[factor_id]
        table = factor.evaluate()
        tables[factor_id] = table
        for ts in table.index:
            for strategy in strategies:
                drafts.append(EventDraft(EventKind.SIGNAL, pd.Timestamp(ts), strategy))
    ctx.set(FactorSignalModule.signal_value, drafts)


def _evaluate_signal_live(account, ctx) -> None:
    """Same factor, evaluated fresh (no caching) each time it fires --
    groups active strategies by their `factor` object so a shared factor
    is only evaluated once per dispatch, not once per strategy."""
    by_factor: dict[int, list] = defaultdict(list)
    factor_by_id: dict[int, Any] = {}
    for strategy in ctx.active_strategies:
        factor = account.config_for(strategy).get(FactorModule.factor)
        by_factor[id(factor)].append(strategy)
        factor_by_id[id(factor)] = factor

    for factor_id, strategies in by_factor.items():
        factor = factor_by_id[factor_id]
        table = factor.evaluate()
        row = table.loc[ctx.timestamp] if ctx.timestamp in table.index else None
        values = {} if row is None else {product: float(row[product]) for product in table.columns}
        for strategy in strategies:
            ctx.set_for(FactorSignalModule.signal_value, strategy, values)


def _evaluate_signal_precomputed(account, ctx) -> None:
    """Looks up a value from the table cached once in PRE_REPLAY
    (`account.precomputed_factor_tables`, keyed by id(factor)) -- no
    re-evaluation here."""
    tables = getattr(account, "precomputed_factor_tables", {})
    for strategy in ctx.active_strategies:
        factor = account.config_for(strategy).get(FactorModule.factor)
        table = tables.get(id(factor))
        if table is None or ctx.timestamp not in table.index:
            ctx.set_for(FactorSignalModule.signal_value, strategy, {})
            continue
        row = table.loc[ctx.timestamp]
        ctx.set_for(FactorSignalModule.signal_value, strategy,
                     {product: float(row[product]) for product in table.columns})
