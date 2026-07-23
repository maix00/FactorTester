"""StrategyBook policy adapter for the built-in group plan."""

from collections.abc import Sequence

from tools.testers.backtest.modules.strategy_book import StrategyIntentPolicy
from tools.testers.backtest.modules.group.precompute import precompute_group_target_intents
from tools.testers.backtest.modules.group.runtime import group_quantile_membership


class GroupMembershipIntentPolicy(StrategyIntentPolicy):
    def generate_strategy_intents(
        self, state: object, ctx: object, strategies: Sequence[object],
    ) -> None:
        group_quantile_membership(state, ctx, strategies)

    def precompute_strategy_intents(
        self, state: object, ctx: object, strategies: Sequence[object],
    ) -> None:
        precompute_group_target_intents(state, ctx, strategies)
