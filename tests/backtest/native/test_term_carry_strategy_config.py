from tools.testers.backtest.engines.native.strategy_config_builder import (
    build_strategy_configs,
)
from tools.testers.backtest.modules.term_carry import TermCarryStrategyModule


def test_frontend_term_carry_fields_materialize_in_strategy_config():
    config = next(iter(build_strategy_configs({
        "CarryPair": {
            "strategy_intent_mode": "term_carry",
            "term_carry_near_rank": 0,
            "term_carry_far_rank": 1,
            "term_carry_entry_threshold": 0.05,
            "term_carry_exit_threshold": 0.01,
            "term_carry_gross_weight": 1.0,
        },
    }).values()))

    assert config.get(TermCarryStrategyModule.term_carry_near_rank) == 0
    assert config.get(TermCarryStrategyModule.term_carry_far_rank) == 1
    assert config.get(
        TermCarryStrategyModule.term_carry_entry_threshold,
    ) == 0.05
    assert config.get(
        TermCarryStrategyModule.term_carry_exit_threshold,
    ) == 0.01
    assert config.get(TermCarryStrategyModule.term_carry_gross_weight) == 1.0
