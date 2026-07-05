"""BacktestRunState: long-lived native run container."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Mapping
import warnings

from tools.testers.backtest.engines.native.config import LedgerConfig, StrategyConfig
from tools.testers.backtest.engines.native.ledger import Ledger, LedgerState, ledger_identity

if TYPE_CHECKING:
    from tools.testers.backtest.engines.native.order import Order
    from tools.testers.backtest.engines.native.strategy import Strategy


class BacktestRunState:
    _declared_runtime_attrs = frozenset({
        "ledgers",
        "strategy_configs",
        "raw_market_data",
        "market_data_request",
        "runtime_info_rows",
        "runtime_info_sink",
        "results",
        "run_window_store",
        "factor_signal_store",
        "target_store",
        "order_store",
        "order_flow_store",
        "equity_curve_store",
        "term_structure_store",
        "market_data_store",
        "strategy_book_store",
        "cash_pool_store",
        "ledger_configs",
    })

    def __init__(
        self,
        ledgers: Mapping[str | Ledger, LedgerState] | None = None,
        strategy_configs: dict["Strategy", StrategyConfig] | None = None,
    ) -> None:
        from tools.testers.backtest.engines.native.result_store import ResultStore

        self._initializing = True
        self._audit_dynamic_writes = False
        self._warned_dynamic_writes: set[str] = set()
        self.ledgers: dict[Ledger, LedgerState] = _normalize_ledger_states(ledgers)
        self.ledger_configs: dict[Ledger, LedgerConfig] = {}
        self.strategy_configs: dict["Strategy", StrategyConfig] = (
            strategy_configs if strategy_configs is not None else {}
        )
        self.results = ResultStore()
        self.runtime_info_rows: list[dict[str, Any]] = []
        self.runtime_info_sink: Any = None
        from tools.testers.backtest.modules.cash_pool import CashPoolStore
        from tools.testers.backtest.modules.equity_curve import EquityCurveStore
        from tools.testers.backtest.modules.factor_signal import FactorSignalStore
        from tools.testers.backtest.modules.market_data import MarketDataStore
        from tools.testers.backtest.modules.order_flow import OrderFlowStore
        from tools.testers.backtest.modules.order_lifecycle import OrderStore
        from tools.testers.backtest.modules.run_window import RunWindowStore
        from tools.testers.backtest.modules.target import TargetStore
        from tools.testers.backtest.modules.term_structure import TermStructureStore

        self.run_window_store = RunWindowStore()
        self.factor_signal_store = FactorSignalStore()
        self.target_store = TargetStore()
        self.order_store = OrderStore()
        self.order_flow_store = OrderFlowStore()
        self.equity_curve_store = EquityCurveStore()
        self.term_structure_store = TermStructureStore()
        self.market_data_store = MarketDataStore()
        self.cash_pool_store = CashPoolStore()
        self._initializing = False

    @property
    def raw_market_data(self) -> dict[str, Any]:
        return self.market_data_store.raw_input

    @raw_market_data.setter
    def raw_market_data(self, value: dict[str, Any]) -> None:
        self.market_data_store.raw_input = value

    @property
    def market_data_request(self) -> dict[str, Any]:
        return self.market_data_store.request

    @market_data_request.setter
    def market_data_request(self, value: dict[str, Any]) -> None:
        self.market_data_store.request = value

    def ledger_for(self, order: "Order") -> LedgerState:
        from tools.testers.backtest.modules.strategy_book import assign_ledger_for_strategy

        config = self.config_for(order.strategy)
        ledger_key = assign_ledger_for_strategy(self, order.strategy, config, order)
        ledger = self.ledgers.get(ledger_key)
        if ledger is None:
            ledger = self._empty_ledger_for(order.strategy, ledger_key)
            self.ledgers[ledger_key] = ledger
        return ledger

    def ledger_for_strategy(self, strategy: "Strategy") -> LedgerState:
        from tools.testers.backtest.modules.strategy_book import assign_ledger_for_strategy, strategy_book_store_for

        store = strategy_book_store_for(self)
        try:
            config = self.config_for(strategy)
        except KeyError:
            ledger_key = store.default_ledger_for_strategy(self, strategy)
        else:
            ledger_key = assign_ledger_for_strategy(self, strategy, config)
        ledger = self.ledgers.get(ledger_key)
        if ledger is None:
            ledger = self._empty_ledger_for(strategy, ledger_key)
            self.ledgers[ledger_key] = ledger
        return ledger

    def _empty_ledger_for(self, strategy: "Strategy", ledger: str | Ledger) -> LedgerState:
        from tools.testers.backtest.modules.cash_pool import cash_pool_config_for_ledger

        ledger = ledger_identity(ledger)
        pool_config = cash_pool_config_for_ledger(self, ledger)
        base_currency = pool_config.base_currency or "CNY"
        return LedgerState(strategy=strategy, base_currency=base_currency, ledger=ledger)

    def config_for(self, strategy: "Strategy") -> StrategyConfig:
        return self.strategy_configs[strategy]

    def ledger_config_for(self, ledger: str | Ledger | LedgerState) -> LedgerConfig:
        if isinstance(ledger, LedgerState):
            ledger_key = ledger.ledger
        else:
            ledger_key = ledger_identity(ledger)
        return self.ledger_configs.get(ledger_key, LedgerConfig())

    def enable_dynamic_write_audit(self, enabled: bool = True) -> None:
        self._audit_dynamic_writes = enabled

    def __setattr__(self, name: str, value: Any) -> None:
        object.__setattr__(self, name, value)
        if not getattr(self, "_audit_dynamic_writes", False):
            return
        if name.startswith("_"):
            return
        if getattr(self, "_initializing", False):
            return
        if name in self._declared_runtime_attrs:
            return
        warned: set[str] = getattr(self, "_warned_dynamic_writes", set())
        if name in warned:
            return
        warned.add(name)
        object.__setattr__(self, "_warned_dynamic_writes", warned)
        warnings.warn(
            f"BacktestRunState dynamic attribute write is not declared: {name!r}. "
            "Move this state into FlowContext output or a domain store.",
            RuntimeWarning,
            stacklevel=2,
        )


def _normalize_ledger_states(raw: Mapping[str | Ledger, LedgerState] | None) -> dict[Ledger, LedgerState]:
    result: dict[Ledger, LedgerState] = {}
    for key, state in (raw or {}).items():
        ledger = ledger_identity(key)
        if state.ledger != ledger:
            state.ledger = ledger
        result[ledger] = state
    return result
