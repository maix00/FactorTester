"""Ledger identity, LedgerState and BacktestRunState primitives.

`Ledger` is a lightweight identity object, analogous to `Strategy` and
`Product`. `LedgerState` is the mutable account book keyed by that identity.
`BacktestRunState` is the whole native run's long-lived container: strategy
registry, ledgers, result store, and module caches that must survive across
FlowContext batches.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Mapping
import warnings

from tools.data.types.base import UniqueNameObject

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
    is_today: bool | None = None


@dataclass
class ProductPosition:
    """One product's position record. `quantity` is the single source of
    truth (always updated regardless of cost-basis method); `average_cost`/
    `lots` are only populated for the method this product actually resolved
    to — this class itself never records which method is in use (that's
    derived from the Product/StrategyConfig, not stored here).

    `margin_reserved` is the product-level margin actually locked from ledger
    cash. Cash-accounted products leave it absent; margin-accounted products
    keep it here so ledger-level margin_reserved can be aggregated without
    losing per-product attribution."""
    quantity: float | int = 0.0
    average_cost: float | None = None
    lots: "deque[Lot] | None" = None
    margin_reserved: "DataMoney | None" = None
    settlement_price: float | None = None


def apply_quantity_delta(entry: ProductPosition, delta: float) -> None:
    """Preserve entry.quantity's int/float type — Python's `int += float`
    silently promotes to float, so we can't just `entry.quantity += delta`."""
    if isinstance(entry.quantity, int):
        entry.quantity += round(delta)
    else:
        entry.quantity += delta


class Ledger(UniqueNameObject):
    """Stable ledger identity.

    External declarations still use ledger_id strings; bootstrap immediately
    resolves them to `Ledger(name=ledger_id)` so runtime stores can use object
    identity just like Strategy/Product.
    """


@dataclass(init=False)
class LedgerState:
    strategy: "Strategy"
    base_currency: str
    fields: dict["FieldRef", Any] = field(default_factory=dict)
    ledger: Ledger = field(default_factory=lambda: Ledger(name="ledger:default"))

    def __init__(
        self,
        strategy: "Strategy",
        base_currency: str,
        ledger: Ledger | str | None = None,
        ledger_id: str | None = None,
        fields: dict["FieldRef", Any] | None = None,
    ) -> None:
        self.strategy = strategy
        self.base_currency = base_currency
        if ledger_id not in (None, ""):
            self.ledger = ledger_identity(str(ledger_id))
        elif ledger is not None:
            self.ledger = ledger_identity(ledger)
        else:
            self.ledger = Ledger(name="ledger:default")
        self.fields = fields if fields is not None else {}

    @property
    def ledger_id(self) -> str:
        return self.ledger.name

    def get(self, ref: "FieldRef", default: Any = None) -> Any:
        return self.fields.get(ref, default)

    def set(self, ref: "FieldRef", value: Any) -> None:
        self.fields[ref] = value


@dataclass(frozen=True)
class LedgerConfig:
    """Ledger-owned accounting and execution-rule configuration.

    StrategyBook is a construction-time routing description. Runtime rules
    belong to ledger_id, so fee/margin/settlement/tradability settings live
    here and are looked up from BacktestRunState by ledger_id.
    """

    initial_capital_major: float | None = None
    base_currency: str | None = None
    fee_mode: str | None = None
    fixed_fee_rate: float | None = None
    margin_mode: str | None = None
    fixed_margin_ratio: float | None = None
    margin_call_mode: str | None = None
    liquidation_target_buffer: float | None = None
    accounting_mode: str | None = None
    daily_mark_to_market_enabled: bool | None = None
    cost_basis_method: str | None = None
    use_int_position: bool | None = None
    tradability_policy: str | None = None
    clearing_rounding_policy: str | None = None
    cash_reserve_ratio: float | None = None
    cash_reserve_major: float | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


def ledger_config_from_mapping(raw: Mapping[str, Any] | "LedgerConfig" | None) -> LedgerConfig:
    if raw is None:
        return LedgerConfig()
    if isinstance(raw, LedgerConfig):
        return raw
    known = {
        "initial_capital_major",
        "base_currency",
        "fee_mode",
        "fixed_fee_rate",
        "margin_mode",
        "fixed_margin_ratio",
        "margin_call_mode",
        "liquidation_target_buffer",
        "accounting_mode",
        "daily_mark_to_market_enabled",
        "cost_basis_method",
        "use_int_position",
        "tradability_policy",
        "clearing_rounding_policy",
        "cash_reserve_ratio",
        "cash_reserve_major",
    }
    return LedgerConfig(
        initial_capital_major=_optional_float(raw.get("initial_capital_major")),
        base_currency=_optional_str(raw.get("base_currency")),
        fee_mode=_optional_str(raw.get("fee_mode")),
        fixed_fee_rate=_optional_float(raw.get("fixed_fee_rate")),
        margin_mode=_optional_str(raw.get("margin_mode")),
        fixed_margin_ratio=_optional_float(raw.get("fixed_margin_ratio")),
        margin_call_mode=_optional_str(raw.get("margin_call_mode")),
        liquidation_target_buffer=_optional_float(raw.get("liquidation_target_buffer")),
        accounting_mode=_optional_str(raw.get("accounting_mode")),
        daily_mark_to_market_enabled=_optional_bool(raw.get("daily_mark_to_market_enabled")),
        cost_basis_method=_optional_str(raw.get("cost_basis_method")),
        use_int_position=_optional_bool(raw.get("use_int_position")),
        tradability_policy=_optional_str(raw.get("tradability_policy")),
        clearing_rounding_policy=_optional_str(raw.get("clearing_rounding_policy")),
        cash_reserve_ratio=_optional_float(raw.get("cash_reserve_ratio")),
        cash_reserve_major=_optional_float(raw.get("cash_reserve_major")),
        metadata={str(key): value for key, value in raw.items() if key not in known},
    )


def merge_ledger_configs(*configs: LedgerConfig) -> LedgerConfig:
    merged: dict[str, Any] = {}
    metadata: dict[str, Any] = {}
    for config in configs:
        for field_name in (
            "initial_capital_major",
            "base_currency",
            "fee_mode",
            "fixed_fee_rate",
            "margin_mode",
            "fixed_margin_ratio",
            "margin_call_mode",
            "liquidation_target_buffer",
            "accounting_mode",
            "daily_mark_to_market_enabled",
            "cost_basis_method",
            "use_int_position",
            "tradability_policy",
            "clearing_rounding_policy",
            "cash_reserve_ratio",
            "cash_reserve_major",
        ):
            value = getattr(config, field_name)
            if value is not None:
                merged[field_name] = value
        metadata.update(config.metadata)
    return LedgerConfig(**merged, metadata=metadata)


def ledger_config_field_values(config: LedgerConfig) -> dict[str, Any]:
    return {
        key: value
        for key in (
            "initial_capital_major",
            "base_currency",
            "fee_mode",
            "fixed_fee_rate",
            "margin_mode",
            "fixed_margin_ratio",
            "margin_call_mode",
            "liquidation_target_buffer",
            "accounting_mode",
            "daily_mark_to_market_enabled",
            "cost_basis_method",
            "use_int_position",
            "tradability_policy",
            "clearing_rounding_policy",
            "cash_reserve_ratio",
            "cash_reserve_major",
        )
        if (value := getattr(config, key)) is not None
    }


def _optional_str(value: object) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _optional_float(value: object) -> float | None:
    if value in (None, ""):
        return None
    return float(value)  # type: ignore[arg-type]


def _optional_bool(value: object) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    return bool(value)


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
        "strategy_book_store",
        "ledger_configs",
    })

    def __init__(
        self,
        ledgers: Mapping[str | Ledger, LedgerState] | None = None,
        strategy_configs: dict["Strategy", StrategyConfig] | None = None,
    ) -> None:
        from tools.testers.backtest.engines.native.result_store import ResultStore  # local import:
            # result_store.py has no reverse dependency on ledger.py, but kept
            # local here purely to avoid widening this file's module-level
            # import surface for a peer (not core-state) concern.

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
        from tools.testers.backtest.modules.strategy_book import strategy_book_store_for, assign_ledger_for_strategy

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
        ledger = ledger_identity(ledger)
        base_currency = self.ledger_config_for(ledger).base_currency or "CNY"
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


def ledger_identity(value: str | Ledger) -> Ledger:
    if isinstance(value, Ledger):
        return value
    return Ledger(name=str(value))


def _normalize_ledger_states(raw: Mapping[str | Ledger, LedgerState] | None) -> dict[Ledger, LedgerState]:
    result: dict[Ledger, LedgerState] = {}
    for key, state in (raw or {}).items():
        ledger = ledger_identity(key)
        if state.ledger != ledger:
            state.ledger = ledger
        result[ledger] = state
    return result
