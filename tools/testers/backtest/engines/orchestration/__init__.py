"""Backtest application orchestration.

`execute_group_plan` lived in orchestration/group.py, deleted in the
issue-114 Event/Order/Flow rewrite (step 0) -- the new engine's
equivalent is `tools.testers.backtest.engines.native.scheduler.run`,
driven by `strategy_config_builder.build_strategy_configs`. Nothing
imports this package anymore (server/group.py's deferred import of
execute_group_plan is the one remaining caller, already accepted as
broken pending the production-route rewrite).
"""

__all__: list[str] = []
