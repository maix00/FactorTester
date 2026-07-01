"""EquityCurveModule — records each strategy's equity/positions/notional/
margin over time into ResultStore. The recording itself always happens
per-event (there is no separate "recompute the whole curve after the fact
from scratch" algorithm -- the per-event state already computed by
LedgerModule is the only source of truth). `compute_live` only controls
whether ResultStore is also updated incrementally *during* the run (useful
for a streaming UI) or only once, in POST_REPLAY, from the buffered history
-- both modes produce the exact same final curves, since both read from the
same per-event buffer.

Recorded per (strategy, timestamp): `equity` (float), `positions` (dict
str(Product) -> quantity, zero positions omitted), `notional` (dict
str(Product) -> quantity*price), and `margin` (dict str(Product) ->
equity_occupied, present only for products where TradingRuleModule has
actually been tracking it -- omitted entirely for a strategy that never
populates `equity_occupied`, matching the old "margin_curve is None unless
margin is tracked" contract).
"""

from __future__ import annotations

from typing import ClassVar

import pandas as pd

from tools.testers.backtest.engines.native.events import EventKind
from tools.testers.backtest.engines.native.fields import ExecutableModule, FieldDefinition, FieldRef
from tools.testers.backtest.engines.native.flow import Flow, Phase
from tools.testers.backtest.modules.ledger_module import LedgerModule
from tools.testers.backtest.modules.market_data import MarketDataModule, contract_notional


class EquityCurveModule(ExecutableModule):
    key: ClassVar[str] = "equity_curve"
    label: ClassVar[str] = "净值曲线"

    compute_live: ClassVar[FieldRef[bool]] = FieldRef("compute_live")

    fields: ClassVar[dict[str, FieldDefinition]] = {
        "compute_live": FieldDefinition(
            public=True, label="实时净值", default=True, control_template="boolean", tab="evaluation",
            chip_template="实时净值: {value}", tab_label="样本划分", tab_order=200,
        ),
    }

    record_equity_on_signal: ClassVar[Flow] = Flow(
        "record_equity_on_signal", inputs=(LedgerModule.equity, MarketDataModule.current_historical_fields), outputs=(),
        phase=Phase.PER_EVENT, event_kind=EventKind.SIGNAL, order=20,
        after=(LedgerModule.equity_on_signal,),
        compute=lambda account, ctx: _record_equity(account, ctx),
    )
    record_equity_on_order: ClassVar[Flow] = Flow(
        "record_equity_on_order", inputs=(LedgerModule.equity, MarketDataModule.current_historical_fields), outputs=(),
        phase=Phase.PER_EVENT, event_kind=EventKind.ORDER, order=920,
        after=(LedgerModule.equity_on_order,),
        compute=lambda account, ctx: _record_equity(account, ctx),
    )
    flush_equity_post_replay: ClassVar[Flow] = Flow(
        "flush_equity_post_replay", inputs=(), outputs=(),
        phase=Phase.POST_REPLAY, order=10,
        compute=lambda account, ctx: _flush_equity_post_replay(account, ctx),
    )

    flows: ClassVar[tuple[Flow, ...]] = (
        record_equity_on_signal, record_equity_on_order, flush_equity_post_replay,
    )


def _ensure_buffer(account) -> dict:
    buffer = getattr(account, "equity_buffer", None)
    if buffer is None:
        buffer = {}
        account.equity_buffer = buffer
    return buffer


def _snapshot_strategy_state(account, strategy, prices: dict, historical_fields: dict) -> dict | None:
    equity = None  # filled by caller; this only builds positions/notional/margin
    ledger = account.ledgers.get(strategy)
    if ledger is None:
        return None
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
        if entry.equity_occupied is not None:
            margin[name] = entry.equity_occupied.to_major()
    record: dict = {"positions": positions, "notional": notional}
    if margin:
        record["margin"] = margin
    return record


def _record_equity(account, ctx) -> None:
    buffer = _ensure_buffer(account)
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
        record = _snapshot_strategy_state(account, strategy, prices, historical_fields) or {}
        record["equity"] = equity
        buffer.setdefault(strategy, []).append((ctx.timestamp, record))
        if account.config_for(strategy).get(EquityCurveModule.compute_live, True):
            account.results.append(strategy, ctx.timestamp, **record)


def _flush_equity_post_replay(account, ctx) -> None:
    buffer = _ensure_buffer(account)
    for strategy, points in buffer.items():
        if account.config_for(strategy).get(EquityCurveModule.compute_live, True):
            continue  # already streamed in during PER_EVENT
        for timestamp, record in points:
            account.results.append(strategy, timestamp, **record)


def equity_curve_for(account, strategy) -> pd.Series:
    history = account.results.history(strategy)
    if not history:
        return pd.Series(dtype=float)
    index = [ts for ts, _ in history]
    values = [v.get("equity") for _, v in history]
    return pd.Series(values, index=pd.Index(index))


def returns_for(account, strategy) -> pd.Series:
    return equity_curve_for(account, strategy).pct_change().dropna()


def position_curve_for(account, strategy) -> dict:
    """{timestamp.isoformat(): {product_name: quantity}} -- matches the old
    portfolio["position_curve"] shape."""
    return {ts.isoformat(): v.get("positions", {}) for ts, v in account.results.history(strategy)}


def notional_curve_for(account, strategy) -> dict:
    return {ts.isoformat(): v.get("notional", {}) for ts, v in account.results.history(strategy)}


def margin_curve_for(account, strategy) -> dict | None:
    history = account.results.history(strategy)
    if not any("margin" in v for _, v in history):
        return None
    return {ts.isoformat(): v.get("margin", {}) for ts, v in history}
