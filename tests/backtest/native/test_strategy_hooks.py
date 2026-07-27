import pandas as pd
import pytest

from tools.testers.backtest.engines.native.events import EventKind
from tools.testers.backtest.engines.native.strategy import Strategy
from tools.testers.backtest.engines.native.strategy_hooks import (
    StrategyContext,
    intent_payload,
    normalize_hook_result,
)


def test_legacy_strategy_has_noop_hooks():
    strategy = Strategy(alias="legacy")
    context = StrategyContext(strategy, pd.Timestamp("2025-01-01"), EventKind.BAR, {}, {})

    assert strategy.on_start(context) is None
    assert strategy.on_bar(context, {}) is None
    assert strategy.on_order_event(context, {}) is None


def test_context_returns_typed_intents_without_mutating_inputs():
    strategy = Strategy(alias="custom")
    context = StrategyContext(strategy, pd.Timestamp("2025-01-01"), EventKind.BAR, {}, {})
    weights = {"P1": 0.5}

    intent = context.target_weights(weights, reason="entry")
    weights["P1"] = 0.9

    assert intent.weights == {"P1": 0.5}
    assert intent_payload(intent) == {
        "kind": "strategy_hook_intent",
        "intent_kind": "target_weights",
        "weights": {"P1": 0.5},
        "reason": "entry",
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
