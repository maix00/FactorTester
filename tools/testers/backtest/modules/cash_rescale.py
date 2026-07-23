"""LedgerCashConstraintModule — cash and margin availability checks.

The SIGNAL flow is an early estimate: it uses the signal timestamp prices
because that is all order construction is allowed to know. The ORDER-stage
helper below is the final broker constraint: after the real execution price,
slippage and fee are known, it proportionally haircuts orders that would make
their shared ledger cash negative.
"""

from __future__ import annotations

from typing import ClassVar
from tools.testers.backtest.engines.native.events import EventKind
from tools.testers.backtest.engines.native.fields import ExecutableModule
from tools.testers.backtest.engines.native.flow import Flow, Phase
from tools.testers.backtest.modules.market_data import MarketDataModule
from tools.testers.backtest.modules.order_construct import OrderConstructModule
from tools.testers.backtest.modules.strategy_book import StrategyBookModule
from tools.testers.backtest.modules.engine import EngineModule
from tools.testers.backtest.modules.fee import FeeModule
from tools.testers.backtest.modules.margin import MarginModule
from tools.testers.backtest.modules.trading_rule import TradingRuleModule
from tools.testers.backtest.modules.cash_constraint.bounds import (
    execution_cash_required_upper_bound as _execution_cash_required_upper_bound,
)
from tools.testers.backtest.modules.cash_constraint.rounding import (
    round_execution_scaled_quantity as _round_execution_scaled_quantity,
    scale_linear_fee_fields as _scale_linear_fee_fields,
)
from tools.testers.backtest.modules.cash_constraint.simulation import (
    clone_positions as _clone_positions_for_cash_check,
    estimated_execution_cash_delta as _estimated_execution_cash_delta,
)


class LedgerCashConstraintModule(ExecutableModule):
    key: ClassVar[str] = "cash_rescale"
    label: ClassVar[str] = "现金调整"

    constrain_to_ledger_cash: ClassVar[Flow] = Flow(
        "constrain_to_ledger_cash",
        inputs=(
            OrderConstructModule.orders,
            EngineModule.engine_mode,
            MarketDataModule.current_prices,
            MarketDataModule.current_historical_fields,
            FeeModule.fee_mode,
            FeeModule.fixed_fee_rate,
            MarginModule.margin_mode,
            MarginModule.fixed_margin_ratio,
            TradingRuleModule.accounting_mode,
            TradingRuleModule.cost_basis_method,
            TradingRuleModule.daily_mark_to_market_enabled,
            OrderConstructModule.quantity_rounding_policy,
            TradingRuleModule.use_int_position,
            StrategyBookModule.cash_reserve_ratio,
            StrategyBookModule.cash_reserve_major,
        ),
        outputs=(OrderConstructModule.orders,),
        phase=Phase.PER_EVENT, event_kind=EventKind.SIGNAL,
        order=35,  # between construct_orders (30) and
                    # GroupMembershipModule.schedule_order_execution (40) --
                    # must haircut buy-side quantities BEFORE they're
                    # scheduled for execution, not after
        after=(OrderConstructModule.construct_orders,),
        description="按现金约束调整订单",
        compute=lambda state, ctx: _constrain_to_ledger_cash(state, ctx),
    )
    constrain_execution_to_ledger_cash: ClassVar[Flow] = Flow(
        "constrain_execution_to_ledger_cash",
        inputs=(
            MarketDataModule.current_prices,
            MarketDataModule.current_historical_fields,
            EngineModule.engine_mode,
            FeeModule.fee_mode,
            FeeModule.fixed_fee_rate,
            MarginModule.margin_mode,
            MarginModule.fixed_margin_ratio,
            TradingRuleModule.accounting_mode,
            TradingRuleModule.cost_basis_method,
            TradingRuleModule.daily_mark_to_market_enabled,
            OrderConstructModule.quantity_rounding_policy,
            TradingRuleModule.use_int_position,
            StrategyBookModule.cash_reserve_ratio,
            StrategyBookModule.cash_reserve_major,
        ),
        outputs=(OrderConstructModule.orders,),
        phase=Phase.PER_EVENT,
        event_kind=EventKind.ORDER,
        order=9,
        after=(FeeModule.resolve_fee_cost,),
        description="成交现金约束",
        event_payload_inputs=("order",),
        compute=lambda state, ctx: constrain_order_batch_to_execution_cash(state, ctx),
    )

    flows: ClassVar[tuple[Flow, ...]] = (constrain_to_ledger_cash, constrain_execution_to_ledger_cash)


def _constrain_to_ledger_cash(state, ctx) -> None:
    """Groups by ledger, not by strategy: two strategies sharing one
    CustomBroker ledger_id draw on the same pool of cash in this batch, so
    the haircut must be computed against their COMBINED buy cost vs that one
    ledger's cash -- computing it per strategy against the ledger's full
    balance would let each strategy independently assume it can spend the
    whole pool, jointly overspending it."""
    from tools.testers.backtest.modules.cash_constraint.signal import constrain_signal_orders

    constrain_signal_orders(state, ctx)


def constrain_order_batch_to_execution_cash(state, ctx) -> None:
    """Final ORDER-stage broker cash/margin check.

    This runs after execution price, slippage and fee have been resolved and
    before LedgerModule.apply_order_fill mutates the ledger. It is deliberately
    grouped by cash pool, so distinct ledgers that share capital receive one
    authoritative batch decision.
    """
    from tools.testers.backtest.modules.cash_constraint.execution import constrain_execution_orders

    constrain_execution_orders(state, ctx)
