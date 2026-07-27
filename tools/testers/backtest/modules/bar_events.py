"""BarEventModule — schedules market BAR replay events only when needed."""

from __future__ import annotations

from typing import Any, ClassVar

import pandas as pd

from tools.testers.backtest.engines.native.events import EventDraft, EventKind
from tools.testers.backtest.engines.native.fields import ExecutableModule, FieldDefinition, FieldRef
from tools.testers.backtest.engines.native.flow import Flow, Phase
from tools.testers.backtest.modules.factor import FactorModule
from tools.testers.backtest.modules.factor_signal import (
    FactorSignalModule,
    _clip_table_to_strategy_warmup_window,
    _live_factor_state_key,
)
from tools.testers.backtest.modules.market_data import (
    MarketDataModule,
    current_prices_table_for,
    resolved_bar_frequency_for_strategy,
)
from tools.testers.backtest.modules.engine import EngineModule, bar_price_visibility_timestamp
from tools.testers.backtest.modules.run_window import RunWindowModule
from tools.testers.backtest.modules.time_index_lookup import signal_event_times


class BarEventModule(ExecutableModule):
    key: ClassVar[str] = "bar_events"
    label: ClassVar[str] = "行情事件"

    bar_price_bases: ClassVar[FieldRef[Any]] = FieldRef("bar_price_bases")
    dispatched_bar_events: ClassVar[FieldRef[Any]] = FieldRef("dispatched_bar_events")

    fields: ClassVar[dict[str, FieldDefinition]] = {
        "bar_price_bases": FieldDefinition(
            public=False,
            default=("close",),
            control_template="custom",
            help_text="BAR 事件订阅的价格字段；每个字段按 Engine 的 bar proxy 可见时间 policy 单独注册事件。",
        ),
        "dispatched_bar_events": FieldDefinition(public=False),
    }

    schedule_bar_events: ClassVar[Flow] = Flow(
        "schedule_bar_events",
        inputs=(
            FactorModule.factor,
            bar_price_bases,
            EngineModule.engine_mode,
            EngineModule.bar_open_visibility_delay,
            EngineModule.bar_end_visibility_delay,
            RunWindowModule.start_date,
            RunWindowModule.end_date,
            RunWindowModule.start_time,
            RunWindowModule.end_time,
            RunWindowModule.timezone,
            RunWindowModule.time_precision,
            FactorSignalModule.warmup_mode,
            FactorSignalModule.warmup_window,
            FactorSignalModule.calendar_frequency,
            FactorSignalModule.signal_freq,
            FactorSignalModule.basepoint,
            FactorSignalModule.daily_basepoint,
            FactorSignalModule.end_session_skip,
            FactorSignalModule.end_session_gap,
            MarketDataModule.required_frequency,
            MarketDataModule.causal_valuation_table,
        ),
        outputs=(dispatched_bar_events,),
        phase=Phase.PRE_REPLAY,
        order=49,
        after=(MarketDataModule.causal_valuation,),
        description="登记行情事件",
        compute=lambda state, ctx: _schedule_bar_events(state, ctx),
        strategy_scoped=True,
    )

    flows: ClassVar[tuple[Flow, ...]] = (schedule_bar_events,)


def _schedule_bar_events(state, ctx) -> None:
    """Register BAR events for live factors and custom bar strategies.

    EventDraft still carries a representative strategy because the scheduler
    dispatches through strategy-scoped batches.  Warm-up is strategy-local:
    strategies only share BAR replay state when factor identity, formal run
    window, and warm-up window all match.
    """
    table = current_prices_table_for(state)
    if table is None:
        return
    representative_by_calculation: dict[Any, Any] = {}
    from tools.testers.backtest.engines.native.strategy import overridden_strategy_callbacks

    for strategy in state.strategy_configs:
        config = state.config_for(strategy)
        live_factor = config.uses_flow("signal_live")
        custom_bar = (
            config.uses_flow("strategy_runtime_on_bar")
            and "on_bar" in overridden_strategy_callbacks(strategy)
        )
        if not (live_factor or custom_bar):
            continue
        factor = config.get(FactorModule.factor)
        representative_by_calculation.setdefault(_live_factor_state_key(factor, config), strategy)
    if not representative_by_calculation:
        return
    drafts: list[EventDraft] = []
    for strategy in representative_by_calculation.values():
        config = state.config_for(strategy)
        strategy_table = _clip_table_to_strategy_warmup_window(table, config)
        drafts.extend(
            _bar_event_drafts_for_strategy(
                strategy_table,
                strategy,
                config,
                bar_freq=resolved_bar_frequency_for_strategy(state, strategy),
            )
        )
    ctx.set(BarEventModule.dispatched_bar_events, drafts)


def _bar_event_drafts_for_strategy(
    table: pd.DataFrame,
    strategy: Any,
    config: Any,
    *,
    bar_freq: object | None = None,
) -> list[EventDraft]:
    event_times = signal_event_times(table)
    if not event_times:
        return []
    index = pd.DatetimeIndex([event_time.timestamp for event_time in event_times])
    drafts: list[EventDraft] = []
    for basis in _bar_price_bases(config):
        normalized_basis = str(basis or "").lower()
        for price_pos, event_time in enumerate(event_times):
            if normalized_basis == "open" and price_pos == 0:
                continue
            visible_ts = bar_price_visibility_timestamp(
                index,
                price_pos=price_pos,
                basis=normalized_basis,
                config=config,
                bar_freq=bar_freq,
            )
            drafts.append(
                EventDraft(
                    EventKind.BAR,
                    visible_ts,
                    strategy,
                    payload={"bar_basis": normalized_basis},
                    index_key=event_time.index_key,
                    index_names=event_time.index_names,
                )
            )
    return sorted(drafts, key=lambda draft: (draft.timestamp, str(draft.payload or "")))


def _bar_price_bases(config: Any) -> tuple[str, ...]:
    raw = config.get(BarEventModule.bar_price_bases, ("close",))
    if isinstance(raw, str):
        values = [part.strip() for part in raw.split(",")]
    else:
        values = [str(value).strip() for value in (raw or ())]
    bases = tuple(value.lower() for value in values if value)
    return bases or ("close",)
