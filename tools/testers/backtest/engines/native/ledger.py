"""Ledger and BacktestRunState primitives for the native backtest engine.

`Ledger` is per-strategy account state. `BacktestRunState` is the whole native run's
long-lived container: strategy registry, ledgers, result store, and module
caches that must survive across FlowContext batches.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
import warnings

if TYPE_CHECKING:
    from tools.data.types.data_money import DataMoney
    from tools.testers.backtest.engines.native.order import Order
    from tools.testers.backtest.engines.native.strategy import Strategy
    from tools.testers.backtest.engines.native.fields import FieldRef


@dataclass
class Lot:
    """One open-position batch (FIFO/LIFO/HIFO share this — they only
    differ in which end of the queue/which cost is consumed first, the
    underlying data structure is the same one). Part of the Ledger schema
    (owned by LedgerModule, step 3.1) — TradingRuleModule only reads/writes
    it, doesn't own it."""
    quantity: float | int
    entry_price: float
    multiplier: float


@dataclass
class ProductPosition:
    """One product's position record. `quantity` is the single source of
    truth (always updated regardless of cost-basis method); `average_cost`/
    `lots` are only populated for the method this product actually resolved
    to — this class itself never records which method is in use (that's
    derived from the Product/StrategyConfig, not stored here).

    `equity_occupied` applies uniformly across all five cost-basis methods
    (including DailyMarkToMarket, which doesn't use `lots`) — equals full
    notional when margin_mode="none" (margin_ratio=1.0), not absent."""
    quantity: float | int = 0.0
    average_cost: float | None = None
    lots: "deque[Lot] | None" = None
    equity_occupied: "DataMoney | None" = None
    settlement_price: float | None = None


def apply_quantity_delta(entry: ProductPosition, delta: float) -> None:
    """Preserve entry.quantity's int/float type — Python's `int += float`
    silently promotes to float, so we can't just `entry.quantity += delta`."""
    if isinstance(entry.quantity, int):
        entry.quantity += round(delta)
    else:
        entry.quantity += delta


@dataclass
class Ledger:
    strategy: "Strategy"
    base_currency: str
    fields: dict["FieldRef", Any] = field(default_factory=dict)

    def get(self, ref: "FieldRef", default: Any = None) -> Any:
        return self.fields.get(ref, default)

    def set(self, ref: "FieldRef", value: Any) -> None:
        self.fields[ref] = value


@dataclass(frozen=True)
class StrategyConfig:
    strategy: "Strategy"
    active_flow_names: frozenset[str] = field(default_factory=frozenset)
    field_values: dict["FieldRef", Any] = field(default_factory=dict)

    def get(self, ref: "FieldRef", default: Any = None) -> Any:
        return self.field_values.get(ref, default)

    def uses_flow(self, flow_name: str) -> bool:
        return flow_name in self.active_flow_names


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
    })

    def __init__(
        self,
        ledgers: dict["Strategy", Ledger] | None = None,
        strategy_configs: dict["Strategy", StrategyConfig] | None = None,
    ) -> None:
        from tools.testers.backtest.engines.native.result_store import ResultStore  # local import:
            # result_store.py has no reverse dependency on ledger.py, but kept
            # local here purely to avoid widening this file's module-level
            # import surface for a peer (not core-state) concern.

        self._initializing = True
        self._audit_dynamic_writes = False
        self._warned_dynamic_writes: set[str] = set()
        self.ledgers: dict["Strategy", Ledger] = ledgers if ledgers is not None else {}
        self.strategy_configs: dict["Strategy", StrategyConfig] = (
            strategy_configs if strategy_configs is not None else {}
        )
        self.results = ResultStore()
        self.runtime_info_rows: list[dict[str, Any]] = []
        self.runtime_info_sink: Any = None
        from tools.testers.backtest.modules.equity_curve import EquityCurveStore
        from tools.testers.backtest.modules.factor_signal import FactorSignalStore
        from tools.testers.backtest.modules.market_data import MarketDataStore
        from tools.testers.backtest.modules.order_lifecycle import OrderStore
        from tools.testers.backtest.modules.order_flow import OrderFlowStore
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

    def ledger_for(self, order: "Order") -> Ledger:
        return self.ledgers[order.strategy]

    def config_for(self, strategy: "Strategy") -> StrategyConfig:
        return self.strategy_configs[strategy]

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
        warned = getattr(self, "_warned_dynamic_writes", set())
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
