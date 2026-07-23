from tools.testers.backtest.engines.native.strategy_config_builder import (
    build_strategy_configs,
)


def test_carry_strategy_activates_only_carry_intent_flow():
    config = next(iter(build_strategy_configs({
        "CARRY": {
            "strategy_kind": "carry",
            "factor_mode": "precomputed",
        },
    }).values()))

    assert config.uses_flow("carry_target")
    assert not config.uses_flow("group_quantile_membership")
    assert not config.uses_flow("threshold_signal_target")
    assert not config.uses_flow("compose_long_short_target")
