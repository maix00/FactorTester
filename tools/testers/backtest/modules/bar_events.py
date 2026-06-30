"""BarEventModule — schedules market BAR replay events only when needed."""

from __future__ import annotations

from typing import Any, ClassVar, cast

import pandas as pd

from tools.testers.backtest.engines.native.events import EventDraft, EventKind
from tools.testers.backtest.engines.native.fields import ExecutableModule, FieldDefinition, FieldRef
from tools.testers.backtest.engines.native.flow import Flow, Phase
from tools.testers.backtest.modules.market_data import MarketDataModule


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
    """Register one BAR event per live factor and timestamp.

    EventDraft still carries a representative strategy because the scheduler
    dispatches through strategy-scoped batches. FactorSignalModule groups BAR
    handlers by factor identity, so a shared factor executor is updated once.
    """
    table = getattr(account, "current_prices_table", None)
    if table is None:
        return
    representative_by_factor: dict[int, Any] = {}
    for strategy in account.strategy_configs:
        config = account.config_for(strategy)
        if not config.uses_flow("signal_live"):
            continue
        factor = config.get(FieldRef("factor", owner="FactorModule"))
        representative_by_factor.setdefault(id(factor), strategy)
    if not representative_by_factor:
        return
    drafts = [
        EventDraft(EventKind.BAR, cast(pd.Timestamp, pd.Timestamp(ts)), strategy)
        for ts in table.index
        for strategy in representative_by_factor.values()
    ]
    ctx.set(BarEventModule.dispatched_bar_events, drafts)
