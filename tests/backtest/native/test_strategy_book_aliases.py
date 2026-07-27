import tools.testers.backtest.modules.strategy_book as strategy_book


def test_account_topology_uses_one_internal_store_type():
    assert hasattr(strategy_book, "StrategyBookStore")
    assert not hasattr(strategy_book, "PortfolioTopology")
    assert not hasattr(strategy_book, "AccountRouter")
