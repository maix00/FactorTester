"""Flow bindings for strategy lifecycle and market/order callbacks."""

from __future__ import annotations

from typing import Any, ClassVar

from tools.testers.backtest.engines.native.events import EventKind
from tools.testers.backtest.engines.native.fields import ExecutableModule, FieldDefinition
from tools.testers.backtest.engines.native.flow import Flow, Phase
from tools.testers.backtest.modules.market_data import MarketDataModule
from tools.testers.backtest.modules.target import TargetStrategyModule

from .dispatch import _call_bar, _call_market_feed, _call_order_event, _call_start, _call_stop
from .fields import emitted_signal
from .intent import _apply_signal_intent


class StrategyRuntime(ExecutableModule):
    """Invoke optional Strategy methods without exposing Flow internals."""

    key: ClassVar[str] = "strategy_runtime"
    label: ClassVar[str] = "自定义策略事件"

    emitted_signal: ClassVar = emitted_signal
    fields: ClassVar[dict[str, FieldDefinition]] = {
        "hook_emitted_signal": FieldDefinition(public=False, display_value_kind="event_draft"),
    }

    on_start: ClassVar[Flow] = Flow(
        "strategy_runtime_on_start", inputs=(), outputs=(), phase=Phase.PRE_REPLAY,
        order=1000, strategy_scoped=True, description="初始化自定义策略",
        compute=lambda state, ctx: _call_start(state, ctx),
    )
    on_market_feed: ClassVar[Flow] = Flow(
        "strategy_runtime_on_market_feed", inputs=(MarketDataModule.current_prices,),
        outputs=(emitted_signal,), phase=Phase.PER_EVENT, event_kind=EventKind.MARKET_FEED,
        order=1000, strategy_scoped=True, event_payload_inputs=("market_feed",),
        description="处理原始行情源事件", compute=lambda state, ctx: _call_market_feed(state, ctx),
    )
    on_bar: ClassVar[Flow] = Flow(
        "strategy_runtime_on_bar", inputs=(MarketDataModule.current_prices,),
        outputs=(emitted_signal,), phase=Phase.PER_EVENT, event_kind=EventKind.BAR,
        order=50, strategy_scoped=True, event_payload_inputs=("bar",),
        description="处理 BAR 策略事件", compute=lambda state, ctx: _call_bar(state, ctx),
    )
    on_signal_intent: ClassVar[Flow] = Flow(
        "strategy_runtime_on_signal_intent", inputs=(),
        outputs=(
            TargetStrategyModule.trade_intent,
            TargetStrategyModule.target_weights,
            emitted_signal,
        ),
        phase=Phase.PER_EVENT, event_kind=EventKind.SIGNAL, order=1,
        strategy_scoped=True,
        event_payload_inputs=("strategy_runtime_intent", "strategy_runtime_command"),
        description="接收自定义策略意图",
        compute=lambda state, ctx: _apply_signal_intent(state, ctx),
    )
    on_order_event: ClassVar[Flow] = Flow(
        "strategy_runtime_on_order_event", inputs=(MarketDataModule.current_prices,),
        outputs=(emitted_signal,), phase=Phase.PER_EVENT, event_kind=EventKind.ORDER,
        order=950, strategy_scoped=True, event_payload_inputs=("order",),
        description="处理订单生命周期事件",
        compute=lambda state, ctx: _call_order_event(state, ctx),
    )
    on_order_status_event: ClassVar[Flow] = Flow(
        "strategy_runtime_on_order_status_event", inputs=(MarketDataModule.current_prices,),
        outputs=(emitted_signal,), phase=Phase.PER_EVENT, event_kind=EventKind.ORDER_STATUS,
        order=950, strategy_scoped=True, event_payload_inputs=("order_status",),
        description="处理订单状态变化事件",
        compute=lambda state, ctx: _call_order_event(state, ctx),
    )
    on_stop: ClassVar[Flow] = Flow(
        "strategy_runtime_on_stop", inputs=(), outputs=(), phase=Phase.POST_REPLAY,
        order=1000, strategy_scoped=True, description="结束自定义策略",
        compute=lambda state, ctx: _call_stop(state, ctx),
    )

    flows: ClassVar[tuple[Flow, ...]] = (
        on_start, on_market_feed, on_bar, on_signal_intent,
        on_order_event, on_order_status_event, on_stop,
    )
