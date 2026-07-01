"""BarEventModule — schedules market BAR replay events only when needed."""

from __future__ import annotations

from typing import Any, ClassVar

import pandas as pd

from tools.testers.backtest.engines.native.events import EventDraft, EventKind
from tools.testers.backtest.engines.native.fields import ExecutableModule, FieldDefinition, FieldRef
from tools.testers.backtest.engines.native.flow import Flow, Phase
from tools.testers.backtest.modules.factor import FactorModule
from tools.testers.backtest.modules.factor_signal import (
    _clip_table_to_strategy_warmup_window,
    _live_factor_state_key,
)
from tools.testers.backtest.modules.market_data import MarketDataModule, current_prices_table_for
from tools.testers.backtest.modules.time_index_lookup import signal_event_times


class BarEventModule(ExecutableModule):
    key: ClassVar[str] = "bar_events"
    label: ClassVar[str] = "行情事件"

    dispatched_bar_events: ClassVar[FieldRef[Any]] = FieldRef("dispatched_bar_events")

    fields: ClassVar[dict[str, FieldDefinition]] = {
        "dispatched_bar_events": FieldDefinition(public=False),
    }

    schedule_bar_events: ClassVar[Flow] = Flow(
        "schedule_bar_events",
        inputs=(),
        outputs=(dispatched_bar_events,),
        phase=Phase.PRE_REPLAY,
        order=49,
        after=(MarketDataModule.causal_valuation,),
        compute=lambda account, ctx: _schedule_bar_events(account, ctx),
        strategy_scoped=True,
    )

    flows: ClassVar[tuple[Flow, ...]] = (schedule_bar_events,)


def _schedule_bar_events(account, ctx) -> None:
    """Register one BAR event per live factor calculation group and timestamp.

    EventDraft still carries a representative strategy because the scheduler
    dispatches through strategy-scoped batches.  Warm-up is strategy-local:
    strategies only share BAR replay state when factor identity, formal run
    window, and warm-up window all match.
    """
    table = current_prices_table_for(account)
    if table is None:
        return
    representative_by_calculation: dict[Any, Any] = {}
    for strategy in account.strategy_configs:
        config = account.config_for(strategy)
        if not config.uses_flow("signal_live"):
            continue
        factor = config.get(FactorModule.factor)
        representative_by_calculation.setdefault(_live_factor_state_key(factor, config), strategy)
    if not representative_by_calculation:
        return
    drafts = []
    for strategy in representative_by_calculation.values():
        strategy_table = _clip_table_to_strategy_warmup_window(table, account.config_for(strategy))
        drafts.extend(
            EventDraft(
                EventKind.BAR,
                event_time.timestamp,
                strategy,
                index_key=event_time.index_key,
                index_names=event_time.index_names,
            )
            for event_time in signal_event_times(strategy_table)
        )
    ctx.set(BarEventModule.dispatched_bar_events, drafts)
