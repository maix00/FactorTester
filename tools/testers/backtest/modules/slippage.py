"""SlippageModule — worsens the effective fill price by slippage_bps,
applied as a FlowOverride on LedgerModule.cash_update.

`slippage_mode="none"` (the default) trades at the unadjusted market price;
`slippage_mode="fixed_bps"` applies a flat `slippage_bps` adjustment."""

from __future__ import annotations

from typing import ClassVar

from tools.testers.backtest.engines.native.fields import ExecutableModule, FieldDefinition, FieldRef
from tools.testers.backtest.engines.native.flow import FlowOverride
from tools.testers.backtest.modules.ledger_module import LedgerModule
from tools.testers.backtest.modules.market_data import MarketDataModule


class SlippageModule(ExecutableModule):
    key: ClassVar[str] = "slippage"
    label: ClassVar[str] = "滑点"

    slippage_mode: ClassVar[FieldRef[str]] = FieldRef("slippage_mode")
    slippage_bps: ClassVar[FieldRef[float]] = FieldRef("slippage_bps")

    fields: ClassVar[dict[str, FieldDefinition]] = {
        "slippage_mode": FieldDefinition(
            public=True, label="滑点", default="none", control_template="select", tab="cost",
            options=(("none", "不计滑点"), ("fixed_bps", "固定基点")),
            chip_template="滑点: {value}", tab_label="费用", tab_order=100,
        ),
        "slippage_bps": FieldDefinition(
            public=True, label="滑点bps", default=0.0, control_template="number", tab="cost",
            visible_when={"slippage_mode": ("fixed_bps",)},
            chip_template="滑点bps: {value}", tab_label="费用", tab_order=100,
        ),
    }

    overrides: ClassVar[tuple[FlowOverride, ...]] = (
        FlowOverride(
            flow_names=(LedgerModule.cash_update.name,),
            extra_inputs=(slippage_mode, slippage_bps),
            compute=lambda account, ctx, base_compute: _apply_slippage(account, ctx, base_compute),
        ),
    )


def _apply_slippage(account, ctx, base_compute) -> None:
    prices = ctx.get(MarketDataModule.current_prices)
    for strategy in ctx.active_strategies:
        # mode/bps are strategy-level -- resolved once per strategy, not
        # once per order, even when a strategy has several simultaneous
        # orders in this batch.
        config = account.config_for(strategy)
        mode = config.get(SlippageModule.slippage_mode, "none")
        slippage_bps = config.get(SlippageModule.slippage_bps, 0.0) if mode == "fixed_bps" else 0.0
        for order in ctx.payloads_for(strategy):
            price = prices[order.instrument]
            # buys execute at a worse (higher) price, sells at a worse
            # (lower) price -- sign of the adjustment follows the trade
            # direction, not the position direction
            sign = 1.0 if order.quantity > 0 else (-1.0 if order.quantity < 0 else 0.0)
            order.set("effective_price", price * (1.0 + sign * slippage_bps / 10_000.0))
    base_compute(account, ctx)
