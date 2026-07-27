from tools.testers.backtest.modules.strategy_book import (
    AccountRouter,
    PortfolioTopology,
    StrategyBookStore,
)


def test_account_topology_aliases_do_not_create_new_runtime_types():
    assert PortfolioTopology is StrategyBookStore
    assert AccountRouter is StrategyBookStore
