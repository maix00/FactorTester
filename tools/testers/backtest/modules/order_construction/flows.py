"""Flow declarations for OrderConstructModule."""

from __future__ import annotations

from tools.testers.backtest.engines.native.events import EventKind
from tools.testers.backtest.engines.native.flow import Flow, Phase
from tools.testers.backtest.modules.engine import EngineModule
from tools.testers.backtest.modules.ledger_module import LedgerModule
from tools.testers.backtest.modules.market_data import MarketDataModule
from tools.testers.backtest.modules.target import TargetStrategyModule
from tools.testers.backtest.modules.trading_rule import TradingRuleModule
from tools.testers.backtest.modules.volume_capacity import VolumeCapacityMode

from .build import construct_orders
from .rounding import round_to_lot_sizes
from .sizing import basic_size_order


def build_order_construct_flows(module):
    size = Flow(
        "size_order",
        inputs=(
            TargetStrategyModule.trade_intent, TargetStrategyModule.target_weights,
            LedgerModule.equity, MarketDataModule.current_prices,
            MarketDataModule.current_historical_fields,
            MarketDataModule.current_tradable_status, MarketDataModule.volume,
            VolumeCapacityMode.liquidity_mode, VolumeCapacityMode.participation_rate,
            LedgerModule.positions,
        ),
        outputs=(module.raw_deltas,),
        phase=Phase.PER_EVENT, event_kind=EventKind.SIGNAL, order=20,
        after=(LedgerModule.equity_on_signal,), description="计算原始目标下单量",
        owner=module.__name__,
        compute=lambda state, ctx: basic_size_order(state, ctx, module),
    )
    rounding = Flow(
        "round_order_quantity",
        inputs=(
            module.raw_deltas, MarketDataModule.lot_sizes,
            module.quantity_rounding_policy, EngineModule.engine_mode,
            TradingRuleModule.accounting_mode, TradingRuleModule.use_int_position,
        ),
        outputs=(module.sized_deltas, module.deltas),
        phase=Phase.PER_EVENT, event_kind=EventKind.SIGNAL, order=22,
        after=(size,), description="按最小买入手数取整",
        owner=module.__name__,
        compute=lambda state, ctx: round_to_lot_sizes(state, ctx, module),
    )
    construct = Flow(
        "construct_orders",
        inputs=(
            module.deltas, LedgerModule.positions,
            TradingRuleModule.cost_basis_method,
            TradingRuleModule.daily_mark_to_market_enabled,
        ),
        outputs=(module.orders,),
        phase=Phase.PER_EVENT, event_kind=EventKind.SIGNAL, order=30,
        after=(rounding,), description="构造订单", owner=module.__name__,
        compute=lambda state, ctx: construct_orders(state, ctx, module),
    )
    return size, rounding, construct
