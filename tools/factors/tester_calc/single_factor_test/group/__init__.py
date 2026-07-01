"""Group-test support package.

`_FactorGroupTestGroup`/`GroupRunResult`/`FactorGroupTester` (the old
flat-group-construction + matrix-simulation pipeline) were deleted here as
part of the issue-114 rewrite -- the new Event/Order/Flow engine
(`tools/testers/backtest/engines/native/backtester.py`) replaces them
entirely. `detail.py`/`metadata.py`/`monotonicity.py` remain: they're used by
the new event-execution read routes
(`server/modules/single_factor_test/group.py`'s `_event_group_detail`/
`_event_group_ranking_detail`).
"""
