from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from tools.testers.backtest.engines.native.ledger import BacktestRunState, StrategyConfig
from tools.testers.backtest.engines.native.scheduler import EventQueue, FlowContext
from tools.testers.backtest.engines.native.strategy import Strategy
from tools.testers.backtest.modules.market_data import (
    _check_market_data_coverage, _load_raw_market_data, _resolve_market_data_request,
)
from tools.testers.backtest.modules.product_selection import ProductSelectionModule
from tools.testers.backtest.modules.run_window import RunWindowModule, strategy_run_window_datetimes
from tools.testers.backtest.modules.term_structure import TermStructureExpandModule, _expand_term_structure
from tools.data.types.time_freq import DataFreq


@dataclass(frozen=True)
class _Product:
    name: str

    def list_available_freqs(self):
        return [DataFreq.MIN1]


def test_market_data_coverage_uses_resolved_product_selection_context():
    strategy = Strategy(alias="A")
    selected = _Product("SELECTED")
    stale_request_product = _Product("STALE")
    account = BacktestRunState(strategy_configs={strategy: StrategyConfig(strategy=strategy)})
    account.market_data_request = {"products": [stale_request_product]}
    ctx = FlowContext(timestamp=None, event_queue=EventQueue())
    ctx.set_for(ProductSelectionModule.products, strategy, frozenset({selected}))

    _resolve_market_data_request(account, ctx)
    _check_market_data_coverage(account, ctx)

    assert account.market_data_store.load_plan == [(selected, DataFreq.MIN1, None)]


@dataclass(frozen=True)
class _Contract:
    name: str

    def list_available_freqs(self):
        return [DataFreq.MIN1]


class _TermProduct(_Product):
    """A term-structure product: its own frequencies are just for the
    tradability check in _tradable_signal_values -- the price series real
    orders execute against belongs to each expanded concrete contract."""

    contract_class = _Contract

    def supports_term_structure(self) -> bool:
        return True

    def get_contract_list(self, start_date=None, end_date=None):
        return [
            {"uid": "P2601.DCE", "contract": "P2601", "start": "2026-01-01", "end": "2026-01-31"},
            {"uid": "P2602.DCE", "contract": "P2602", "start": "2026-01-20", "end": "2026-02-28"},
        ]


def test_market_data_coverage_plans_expanded_contracts_alongside_the_abstract_product():
    """A term-structure product's own load plan entry must stay (needed for
    _tradable_signal_values, which still keys signal_value by the abstract
    product before rollover remaps it) -- but each concrete contract
    TermStructureExpandModule.expand_term_structure found must ALSO get
    planned, or a rolled-to order has nowhere to load its own price from
    (the bug this test guards: current_prices[concrete_contract] KeyError'd
    in production because only the abstract product was ever planned)."""
    strategy = Strategy(alias="A")
    product = _TermProduct("P.DCE")
    account = BacktestRunState(strategy_configs={
        strategy: StrategyConfig(strategy=strategy, field_values={
            RunWindowModule.start_date: "2026-01-01",
            RunWindowModule.start_time: "09:00",
            RunWindowModule.end_date: "2026-02-05",
            RunWindowModule.end_time: "15:00",
            RunWindowModule.timezone: "Asia/Shanghai",
        }),
    })
    account.run_window_store.envelope = strategy_run_window_datetimes(account.config_for(strategy))
    ctx = FlowContext(timestamp=None, event_queue=EventQueue(), active_strategies=frozenset({strategy}))
    ctx.set_for(ProductSelectionModule.products, strategy, frozenset({product}))

    _expand_term_structure(account, ctx)
    _resolve_market_data_request(account, ctx)
    _check_market_data_coverage(account, ctx)

    planned = {item[0] for item in account.market_data_store.load_plan}
    assert product in planned
    assert _Contract("P2601.DCE") in planned
    assert _Contract("P2602.DCE") in planned
    assert len(account.market_data_store.load_plan) == 3


class _FakeDataView:
    """Minimal stand-in for ProductDataView.get_and_adjust_cols: returns a
    flat close-price series (all requested price columns equal) so the real
    _load_raw_market_data live-loading branch (not the raw_market_data test
    shortcut) has something concrete to build raw_prices/price_tables from."""

    def __init__(self, index: pd.DatetimeIndex, close: float):
        self._index = index
        self._close = close

    def get_and_adjust_cols(self, columns, *, copy=False, start_dt=None, end_dt=None, warmup_window=None, source=None):
        from tools.data.types import DataColumn

        data = {}
        for column in columns:
            if column == DataColumn.VOLUME.name:
                data[column] = [1000.0] * len(self._index)
            else:
                data[column] = [self._close] * len(self._index)
        return pd.DataFrame(data, index=self._index)


class _PricedContract(_Contract):
    # _Contract is a frozen dataclass -- object.__setattr__ bypasses its
    # patched __setattr__ to attach a non-field attribute after construction.
    def __init__(self, name: str, index: pd.DatetimeIndex, close: float):
        super().__init__(name)
        object.__setattr__(self, "_view", _FakeDataView(index, close))

    @property
    def MIN1(self):
        return self._view


class _PricedTermProduct(_TermProduct):
    def __init__(self, name: str, index: pd.DatetimeIndex, close: float, contracts):
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "_view", _FakeDataView(index, close))
        object.__setattr__(self, "_contracts", contracts)
        by_uid = {contract.name: contract for contract, _start, _end, _end_ts in contracts}
        object.__setattr__(self, "contract_class", lambda uid: by_uid[uid])

    @property
    def MIN1(self):
        return self._view

    def get_contract_list(self, start_date=None, end_date=None):
        return [
            {"uid": c.name, "contract": c.name.split(".")[0], "start": start, "end": end,
             "end_ts": end_ts, "last_trade_ts": end_ts}
            for c, start, end, end_ts in self._contracts
        ]


def test_load_raw_market_data_live_path_resolves_price_for_each_concrete_contract():
    """The bug this guards: current_prices[concrete_contract] KeyError'd in
    production once TermStructureExpandModule.resolve_tradable_target_weights
    rekeyed a target to a concrete contract object, because
    _load_raw_market_data's live branch never requested that object's own
    price series -- only the abstract product's continuous one. Drives the
    REAL live-loading branch (not the raw_market_data shortcut every other
    term-structure test uses) end to end."""
    from tools.testers.backtest.modules.market_data import (
        MarketDataModule, _causal_valuation, _check_market_data_coverage, current_prices_table_for,
    )

    strategy = Strategy(alias="A")
    idx = pd.date_range("2026-01-01", periods=5, freq="D")
    contract_1601 = _PricedContract("P2601.DCE", idx, close=10.0)
    contract_1602 = _PricedContract("P2602.DCE", idx, close=20.0)
    end_ts_1601 = int(pd.Timestamp("2026-01-20 15:00").timestamp() * 1000)
    end_ts_1602 = int(pd.Timestamp("2026-02-10 15:00").timestamp() * 1000)
    product = _PricedTermProduct("P.DCE", idx, close=15.0, contracts=[
        (contract_1601, "2026-01-01", "2026-01-20", end_ts_1601),
        (contract_1602, "2026-01-10", "2026-02-10", end_ts_1602),
    ])

    account = BacktestRunState(strategy_configs={
        strategy: StrategyConfig(strategy=strategy, field_values={
            RunWindowModule.start_date: "2026-01-01",
            RunWindowModule.start_time: "09:00",
            RunWindowModule.end_date: "2026-02-05",
            RunWindowModule.end_time: "15:00",
            RunWindowModule.timezone: "Asia/Shanghai",
        }),
    })
    account.market_data_request = {"start_dt": idx[0], "end_dt": idx[-1]}
    account.run_window_store.envelope = strategy_run_window_datetimes(account.config_for(strategy))
    ctx = FlowContext(timestamp=None, event_queue=EventQueue(), active_strategies=frozenset({strategy}))
    ctx.set_for(ProductSelectionModule.products, strategy, frozenset({product}))

    _expand_term_structure(account, ctx)
    _resolve_market_data_request(account, ctx)
    _check_market_data_coverage(account, ctx)
    _load_raw_market_data(account, ctx)
    _causal_valuation(account, ctx)

    table = current_prices_table_for(account)
    assert product in table.columns
    assert contract_1601 in table.columns
    assert contract_1602 in table.columns
    assert table[contract_1601].iloc[0] == 10.0
    assert table[contract_1602].iloc[0] == 20.0
    assert table[product].iloc[0] == 15.0
