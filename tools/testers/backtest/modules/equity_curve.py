"""EquityCurveModule — records each strategy's equity/positions/notional/
margin over time into ResultStore. The recording itself always happens
per-event (there is no separate "recompute the whole curve after the fact
from scratch" algorithm -- the per-event state already computed by
LedgerModule is the only source of truth). `equity_compute_live` only controls
whether ResultStore is also updated incrementally *during* the run (useful
for a streaming UI) or only once, in POST_REPLAY, from the buffered history
-- both modes produce the exact same final curves, since both read from the
same per-event buffer.

Recorded per (strategy, timestamp): `equity` (float), `positions` (dict
str(Product) -> quantity, zero positions omitted), `notional` (dict
str(Product) -> quantity*price), and `margin` (dict str(Product) ->
    margin_reserved, present only for products where margin accounting has
    actually reserved cash -- omitted entirely for a strategy that never
    tracks margin.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar

import pandas as pd

from tools.testers.backtest.engines.native.events import EventKind
from tools.testers.backtest.engines.native.fields import ExecutableModule, FieldDefinition, FieldRef
from tools.testers.backtest.engines.native.flow import Flow, Phase
from tools.testers.backtest.modules.ledger_module import LedgerModule
from tools.testers.backtest.modules.market_data import MarketDataModule, contract_notional


@dataclass
class EquityCurveStore:
    buffer: dict[Any, list[tuple[Any, dict[str, Any]]]] = field(default_factory=dict)


class EquityCurveModule(ExecutableModule):
    key: ClassVar[str] = "equity_curve"
    label: ClassVar[str] = "净值曲线"

    equity_compute_live: ClassVar[FieldRef[bool]] = FieldRef("equity_compute_live")

    fields: ClassVar[dict[str, FieldDefinition]] = {
        "equity_compute_live": FieldDefinition(
            public=True,
            label="净值实时计算",
            default=True,
            control_template="boolean",
            tab="engine",
            chip_template="净值实时计算: {value}",
            tab_label="执行引擎",
            tab_order=10,
            help_text="控制回放过程中是否向结果存储实时写入净值曲线；关闭后仍会在回放结束后从事件缓冲生成同一条最终净值曲线。",
            serialization={"display_order": 30},
        ),
    }

    record_equity_on_signal: ClassVar[Flow] = Flow(
        "record_equity_on_signal", inputs=(LedgerModule.equity, MarketDataModule.current_historical_fields), outputs=(),
        phase=Phase.PER_EVENT, event_kind=EventKind.SIGNAL, order=20,
        after=(LedgerModule.equity_on_signal,),
        description="记录信号时点净值",
        compute=lambda state, ctx: _record_equity(state, ctx),
    )
    record_equity_on_order: ClassVar[Flow] = Flow(
        "record_equity_on_order", inputs=(LedgerModule.equity, MarketDataModule.current_historical_fields), outputs=(),
        phase=Phase.PER_EVENT, event_kind=EventKind.ORDER, order=920,
        after=(LedgerModule.equity_on_order,),
        description="记录订单后净值",
        compute=lambda state, ctx: _record_equity(state, ctx),
    )
    flush_equity_post_replay: ClassVar[Flow] = Flow(
        "flush_equity_post_replay", inputs=(), outputs=(),
        phase=Phase.POST_REPLAY, order=10,
        description="整理净值曲线",
        compute=lambda state, ctx: _flush_equity_post_replay(state, ctx),
    )

    flows: ClassVar[tuple[Flow, ...]] = (
        record_equity_on_signal, record_equity_on_order, flush_equity_post_replay,
    )


def _ensure_buffer(state) -> dict:
    return state.equity_curve_store.buffer


def _snapshot_strategy_state(state, strategy, prices: dict, historical_fields: dict) -> dict | None:
    equity = None  # filled by caller; this only builds positions/notional/margin
    ledger = state.ledger_for_strategy(strategy)
    positions_obj = ledger.get(LedgerModule.positions, {})
    positions: dict[str, float] = {}
    notional: dict[str, float] = {}
    margin: dict[str, float] = {}
    for product, entry in positions_obj.items():
        if not entry.quantity:
            continue
        name = str(product)
        positions[name] = entry.quantity
        price = prices.get(product)
        if price is not None:
            notional[name] = contract_notional(price, entry.quantity, historical_fields, product)
        if entry.margin_reserved is not None:
            margin[name] = entry.margin_reserved.to_major()
    if not positions and not notional and not margin:
        return None
    record: dict = {"positions": positions, "notional": notional}
    if margin:
        record["margin"] = margin
    return record


def _record_equity(state, ctx) -> None:
    buffer = _ensure_buffer(state)
    prices = ctx.get(MarketDataModule.current_prices, {})
    for strategy in ctx.active_strategies:
        equity = ctx.get_for(LedgerModule.equity, strategy)
        if equity is None:
            continue
        historical_fields = ctx.get_for(
            MarketDataModule.current_historical_fields,
            strategy,
            ctx.get(MarketDataModule.current_historical_fields, {}),
        )
        record = _snapshot_strategy_state(state, strategy, prices, historical_fields) or {}
        record["equity"] = equity
        buffer.setdefault(strategy, []).append((ctx.timestamp, record))
        if state.config_for(strategy).get(EquityCurveModule.equity_compute_live, True):
            state.results.append(strategy, ctx.timestamp, **record)


def _flush_equity_post_replay(state, ctx) -> None:
    buffer = _ensure_buffer(state)
    for strategy, points in buffer.items():
        if state.config_for(strategy).get(EquityCurveModule.equity_compute_live, True):
            continue  # already streamed in during PER_EVENT
        for timestamp, record in points:
            state.results.append(strategy, timestamp, **record)


def equity_curve_for(state, strategy) -> pd.Series:
    history = state.results.history(strategy)
    if not history:
        return pd.Series(dtype=float)
    index = [ts for ts, _ in history]
    values = [v.get("equity") for _, v in history]
    return pd.Series(values, index=pd.Index(index))


def returns_for(state, strategy) -> pd.Series:
    return equity_curve_for(state, strategy).pct_change().dropna()


def position_curve_for(state, strategy) -> dict:
    """{timestamp.isoformat(): {product_name: quantity}} -- matches the old
    portfolio["position_curve"] shape."""
    return {ts.isoformat(): v.get("positions", {}) for ts, v in state.results.history(strategy)}


def notional_curve_for(state, strategy) -> dict:
    return {ts.isoformat(): v.get("notional", {}) for ts, v in state.results.history(strategy)}


def margin_curve_for(state, strategy) -> dict | None:
    history = state.results.history(strategy)
    if not any("margin" in v for _, v in history):
        return None
    return {ts.isoformat(): v.get("margin", {}) for ts, v in history}
