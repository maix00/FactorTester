import pandas as pd
import pytest

from tools.testers.backtest.engines.native.events import EventKind
from tools.testers.backtest.engines.native.strategy import (
    Strategy,
    overridden_strategy_callbacks,
)
from tools.testers.backtest.engines.native.strategy_hooks import (
    ExecutionCapabilities,
    StrategyContext,
    StrategyRequirements,
    intent_payload,
    normalize_hook_result,
    validate_strategy_capabilities,
)
from tools.testers.backtest.engines.native.strategy_commands import SubmitOrderCommand
from tools.testers.backtest.engines.native.market_events import MarketFeedEventKind


def test_legacy_strategy_has_noop_hooks():
    strategy = Strategy(alias="legacy")
    context = StrategyContext(strategy, pd.Timestamp("2025-01-01"), EventKind.BAR, {}, {})

    assert strategy.on_start(context) is None
    assert strategy.on_bar(context, {}) is None
    assert strategy.on_order_event(context, {}) is None


def test_strategy_actor_is_the_single_user_hook_surface():
    class Actor(Strategy):
        def on_bar(self, ctx, bar):
            return None

        def on_order_filled(self, ctx, order):
            return None

    actor = Actor(alias="actor")

    assert isinstance(actor, Strategy)
    assert overridden_strategy_callbacks(actor) == frozenset({"on_bar", "on_order_filled"})


def test_generic_on_event_is_used_by_default_adapters():
    class GenericStrategy(Strategy):
        def on_event(self, ctx, event):
            return event

    strategy = GenericStrategy(alias="generic-event")
    context = StrategyContext(strategy, None, EventKind.BAR, {}, {})

    assert strategy.on_bar(context, {"bar": 1}) == {"bar": 1}
    assert strategy.on_market_feed(context, {"quote": 1}) == {"quote": 1}
    assert strategy.on_order_event(context, {"order": 1}) == {"order": 1}


def test_on_order_event_is_the_public_generic_order_callback():
    class OrderStrategy(Strategy):
        def on_order_event(self, ctx, order):
            return order

    strategy = OrderStrategy(alias="generic-order")
    context = StrategyContext(strategy, None, EventKind.ORDER, {}, {})

    assert strategy.on_order_event(context, {"order": 1}) == {"order": 1}
    assert "on_order_event" in overridden_strategy_callbacks(strategy)


def test_context_returns_typed_intents_without_mutating_inputs():
    strategy = Strategy(alias="custom")
    context = StrategyContext(strategy, pd.Timestamp("2025-01-01"), EventKind.BAR, {}, {})
    weights = {"P1": 0.5}

    intent = context.target_weights(weights, reason="entry")
    weights["P1"] = 0.9

    assert intent.weights == {"P1": 0.5}
    assert intent_payload(intent) == {
        "kind": "strategy_runtime_intent",
        "intent_kind": "target_weights",
        "weights": {"P1": 0.5},
        "reason": "entry",
    }


def test_context_order_helpers_return_serializable_commands():
    strategy = Strategy(alias="command-context")
    context = StrategyContext(strategy, pd.Timestamp("2025-01-01"), EventKind.BAR, {}, {})

    command = context.submit_order("P1", 2, side="sell", reason="risk")

    assert isinstance(command, SubmitOrderCommand)
    assert intent_payload(command) == {
        "kind": "strategy_runtime_command",
        "command_kind": "submit_order",
        "product": "P1",
        "quantity": 2.0,
        "side": "sell",
        "reason": "risk",
    }


def test_context_market_views_are_read_only():
    strategy = Strategy(alias="readonly-context")
    context = StrategyContext(strategy, None, None, {"P1": 1.0}, {"P1": 10.0})

    with pytest.raises(TypeError):
        context.current_prices["P1"] = 11.0


def test_hook_result_accepts_one_or_many_typed_intents():
    strategy = Strategy(alias="custom-result")
    context = StrategyContext(strategy, None, None, {}, {})
    first = context.order_deltas({"P1": 1.0})
    second = context.target_weights({"P2": -0.5})

    assert normalize_hook_result(first) == (first,)
    assert normalize_hook_result([first, second]) == (first, second)


def test_hook_result_rejects_untyped_commands():
    with pytest.raises(TypeError, match="typed intents"):
        normalize_hook_result({"P1": 1.0})


def test_capability_validation_reports_missing_data_and_execution_features():
    report = validate_strategy_capabilities(
        StrategyRequirements(
            feed_events=frozenset({MarketFeedEventKind.BOOK_DELTA}),
            needs_partial_fills=True,
            needs_order_events=True,
        ),
        ExecutionCapabilities(),
    )

    assert report["ok"] is False
    assert report["missing_feed_events"] == ["book_delta"]
    assert len(report["errors"]) == 3


def test_capability_validation_reports_missing_order_status_and_position_axes():
    report = validate_strategy_capabilities(
        StrategyRequirements(
            needs_order_status_events=True,
            needs_position_events=True,
        ),
        ExecutionCapabilities(),
    )

    assert report["ok"] is False
    assert report["errors"] == [
        "strategy requires order status events",
        "strategy requires position lifecycle events",
    ]
