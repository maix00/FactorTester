"""FeeModule — transaction cost, applied as a FlowOverride on
LedgerModule.cash_update.

`fee_mode` mirrors the old fee_mode/custom_fee_rate UI contract:
- "none": no fee at all.
- "custom": flat `custom_fee_rate` applied to every trade's notional.
- "market": per-product real fee rate, read from
  `MarketDataModule.fee_rate_table` (supplied by the data-prep stage,
  same pattern as margin_ratio/lot_sizes) -- not yet wired to a real
  data source this round, so selecting "market" without that table
  populated raises clearly rather than silently charging zero fee.
"""

from __future__ import annotations

from typing import ClassVar

from tools.testers.backtest.engines.native.fields import ExecutableModule, FieldDefinition, FieldRef
from tools.testers.backtest.engines.native.flow import FlowOverride
from tools.testers.backtest.modules.ledger_module import LedgerModule
from tools.testers.backtest.modules.market_data import MarketDataModule


class FeeModule(ExecutableModule):
    key: ClassVar[str] = "transaction_cost"
    label: ClassVar[str] = "交易费用"

    fee_mode: ClassVar[FieldRef[str]] = FieldRef("fee_mode")
    custom_fee_rate: ClassVar[FieldRef[float]] = FieldRef("custom_fee_rate")

    fields: ClassVar[dict[str, FieldDefinition]] = {
        "fee_mode": FieldDefinition(
            public=True, default="none", control_template="select", tab="cost",
            options=(("none", "不计费用"), ("custom", "自定义费率"), ("market", "市场真实费率")),
        ),
        "custom_fee_rate": FieldDefinition(
            public=True, default=0.0, control_template="number", tab="cost",
            visible_when={"fee_mode": ("custom",)},
        ),
    }

    overrides: ClassVar[tuple[FlowOverride, ...]] = (
        FlowOverride(
            flow_names=(LedgerModule.cash_update.name,),
            extra_inputs=(fee_mode, custom_fee_rate),
            compute=lambda account, ctx, base_compute: _apply_fee(account, ctx, base_compute),
        ),
    )


def _resolve_fee_rate(mode: str, custom_rate: float, account, product) -> float:
    if mode == "none":
        return 0.0
    if mode == "custom":
        return custom_rate
    # mode == "market"
    table = getattr(account, "fee_rate_table", None)
    if table is None or product not in table:
        raise NotImplementedError(
            f'fee_mode="market" requires account.fee_rate_table[{product!r}] to be '
            "populated by the data-prep stage -- not wired to a real fee-schedule "
            "data source this round")
    return table[product]


def _apply_fee(account, ctx, base_compute) -> None:
    prices = ctx.get(MarketDataModule.current_prices)
    for strategy in ctx.active_strategies:
        # mode/custom_rate are strategy-level (not order-level) -- resolved
        # once per strategy, not once per order, even when a strategy has
        # several simultaneous orders in this batch.
        config = account.config_for(strategy)
        mode = config.get(FeeModule.fee_mode, "none")
        custom_rate = config.get(FeeModule.custom_fee_rate, 0.0)
        for order in ctx.payloads_for(strategy):
            fee_rate = _resolve_fee_rate(mode, custom_rate, account, order.instrument)
            price = order.get("effective_price", prices[order.instrument])
            order.set("fee_cost", abs(order.quantity) * price * fee_rate)
    base_compute(account, ctx)
