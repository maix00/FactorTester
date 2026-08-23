"""BacktestRunState: long-lived native run container."""

from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING, Any, Mapping
import warnings
import weakref

from tools.testers.backtest.engines.native.config import LedgerConfig, StrategyConfig
from tools.testers.backtest.engines.native.fields import FieldRef
from tools.testers.backtest.engines.native.ledger import Ledger, LedgerState, ledger_identity

if TYPE_CHECKING:
    from tools.testers.backtest.engines.native.order import Order
    from tools.testers.backtest.engines.native.strategy import Strategy


class BacktestRunState:
    _declared_runtime_attrs = frozenset({
        "ledgers",
        "strategy_configs",
        "strategy_static_routing_identity_decisions",
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
        "backtest_profiler",
        "margin_execution_observer",
        "result_retention_mode",
    })

    def __init__(
        self,
        ledgers: Mapping[str | Ledger, LedgerState] | None = None,
        strategy_configs: dict["Strategy", StrategyConfig] | None = None,
        *,
        result_retention_mode: str = "full",
    ) -> None:
        from tools.testers.backtest.engines.native.result_store import ResultStore

        if result_retention_mode not in {"summary", "full"}:
            raise ValueError(
                "result_retention_mode must be 'summary' or 'full'"
            )
        self._initializing = True
        self._audit_dynamic_writes = False
        self._flow_contract_audit: tuple[Any, object] | None = None
        self._warned_dynamic_writes: set[str] = set()
        self.ledgers: dict[Ledger, LedgerState] = _normalize_ledger_states(ledgers)
        self.ledger_configs: dict[Ledger, LedgerConfig] = {}
        self.strategy_configs: dict["Strategy", StrategyConfig] = (
            strategy_configs if strategy_configs is not None else {}
        )
        # The normal object-key routing cache remains the inspectable
        # compatibility surface.  This parallel identity cache avoids
        # recomputing UniqueNameObject.__hash__ on every product leg while
        # retaining object references so an id cannot be reused incorrectly.
        self.strategy_static_routing_identity_decisions: dict[
            tuple[int, int], tuple[object, object, object]
        ] = {}
        self.result_retention_mode = result_retention_mode
        self.results = ResultStore(retention_mode=result_retention_mode)
        self.runtime_info_rows: list[dict[str, Any]] = []
        self.runtime_info_sink: Any = None
        self.backtest_profiler: Any = None
        self.margin_execution_observer: Any = None
        from tools.testers.backtest.modules.cash_pool import CashPoolStore
        from tools.testers.backtest.modules.equity_curve import EquityCurveStore
        from tools.testers.backtest.modules.factor_signal import FactorSignalStore
        from tools.testers.backtest.modules.market_data import MarketDataStore
        from tools.testers.backtest.modules.order_flow import OrderFlowStore, OrderStore
        from tools.testers.backtest.modules.run_window import RunWindowStore
        from tools.testers.backtest.modules.target import TargetStore
        from tools.testers.backtest.modules.term_structure import TermStructureStore

        self.run_window_store = RunWindowStore()
        self.factor_signal_store = FactorSignalStore()
        self.target_store = TargetStore(retention_mode=result_retention_mode)
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

        cache = getattr(self.order_store, "ledger_by_order_object", None)
        object_key = id(order)
        if cache is not None:
            cached = cache.get(object_key)
            if cached is not None:
                cached_order = cached[0]()
                if cached_order is order:
                    return cached[1]
                if cached_order is None:
                    cache.pop(object_key, None)
        config = self.config_for(order.strategy)
        ledger_key = assign_ledger_for_strategy(self, order.strategy, config, order)
        ledger = self.ledgers.get(ledger_key)
        if ledger is None:
            ledger = self._empty_ledger_for(order.strategy, ledger_key)
            self.ledgers[ledger_key] = ledger
        if cache is not None:
            try:
                cache[object_key] = (weakref.ref(order), ledger)
            except TypeError:
                # Lightweight slot-based test doubles may not support weak
                # references; correctness wins over this optional cache.
                pass
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
        ledger_config = self.ledger_configs.get(ledger, LedgerConfig())
        account_currency = ledger_config.account_currency or pool_config.base_currency or "CNY"
        ledger_state = LedgerState(strategy=strategy, base_currency=account_currency, ledger=ledger)
        if getattr(self, "_store_guards_enabled", False):
            ledger_state.set_guarded_writes_enabled(True)
        audit = getattr(self, "_flow_contract_audit", None)
        if audit is not None:
            ctx, token = audit
            ledger_state.enter_flow_contract_audit(ctx, token)
        return ledger_state

    def config_for(self, strategy: "Strategy") -> StrategyConfig:
        config = self.strategy_configs[strategy]
        audit = getattr(self, "_flow_contract_audit", None)
        if audit is None:
            return config
        ctx, token = audit
        return _AuditedStrategyConfig(config, ctx, token)  # type: ignore[return-value]

    def ledger_config_for(self, ledger: str | Ledger | LedgerState) -> LedgerConfig:
        if isinstance(ledger, LedgerState):
            cached = getattr(ledger, "_resolved_ledger_config", None)
            if cached is not None:
                config = cached
            else:
                ledger_key = ledger.ledger
                config = self.ledger_configs.get(ledger_key, LedgerConfig())
                # Ledger configuration is a pre-replay contract.  Cache it on
                # the state object once the ledger is materialized; ORDER and
                # cash/margin flows ask for it repeatedly for the same ledger.
                object.__setattr__(ledger, "_resolved_ledger_config", config)
        else:
            ledger_key = ledger_identity(ledger)
            config = self.ledger_configs.get(ledger_key, LedgerConfig())
        audit = getattr(self, "_flow_contract_audit", None)
        if audit is None:
            return config
        ctx, token = audit
        return _AuditedLedgerConfig(config, ctx, token)  # type: ignore[return-value]

    def enable_dynamic_write_audit(self, enabled: bool = True) -> None:
        self._audit_dynamic_writes = enabled

    def enter_flow_contract_audit(self, ctx: Any, token: object) -> tuple[Any, object] | None:
        previous = getattr(self, "_flow_contract_audit", None)
        object.__setattr__(self, "_flow_contract_audit", (ctx, token))
        for ledger in getattr(self, "ledgers", {}).values():
            ledger.enter_flow_contract_audit(ctx, token)
        cash_pool_store = getattr(self, "cash_pool_store", None)
        if cash_pool_store is not None:
            cash_pool_store.enter_flow_contract_audit(ctx, token)
        return previous

    def restore_flow_contract_audit(self, previous: tuple[Any, object] | None) -> None:
        object.__setattr__(self, "_flow_contract_audit", previous)
        for ledger in getattr(self, "ledgers", {}).values():
            ledger.restore_flow_contract_audit(previous)
        cash_pool_store = getattr(self, "cash_pool_store", None)
        if cash_pool_store is not None:
            cash_pool_store.restore_flow_contract_audit(previous)

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


class _AuditedStrategyConfig:
    """Read-only StrategyConfig proxy used during flow-contract audits.

    FlowContext already audits ctx.get()/ctx.get_for().  Many module helpers
    read configuration directly with state.config_for(strategy).get(FieldRef),
    so those reads must be routed into the same declaration check.
    """

    def __init__(self, config: StrategyConfig, ctx: Any, token: object) -> None:
        object.__setattr__(self, "_config", config)
        object.__setattr__(self, "_ctx", ctx)
        object.__setattr__(self, "_token", token)

    def get(self, ref: FieldRef, default: Any = None) -> Any:
        if isinstance(ref, FieldRef):
            self._ctx.record_external_contract_read(ref, self._token)
        return self._config.get(ref, default)

    def uses_flow(self, flow_name: str) -> bool:
        return self._config.uses_flow(flow_name)

    def __getattr__(self, name: str) -> Any:
        if name == "field_values":
            return _AuditedStrategyFieldValues(self._config.field_values, self._ctx, self._token)
        return getattr(self._config, name)


class _AuditedStrategyFieldValues(Mapping[FieldRef, Any]):
    """Read-only FieldRef mapping proxy for direct StrategyConfig.field_values access."""

    def __init__(self, values: Mapping[FieldRef, Any], ctx: Any, token: object) -> None:
        self._values = values
        self._ctx = ctx
        self._token = token

    def __getitem__(self, ref: FieldRef) -> Any:
        if isinstance(ref, FieldRef):
            self._ctx.record_external_contract_read(ref, self._token)
        return self._values[ref]

    def __iter__(self) -> Iterator[FieldRef]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

    def get(self, ref: FieldRef, default: Any = None) -> Any:
        if isinstance(ref, FieldRef):
            self._ctx.record_external_contract_read(ref, self._token)
        return self._values.get(ref, default)


_LEDGER_CONFIG_FIELD_REFS: dict[str, FieldRef[Any]] = {
    "fee_mode": FieldRef("fee_mode", owner="FeeModule"),
    "transaction_fee_source": FieldRef("transaction_fee_source", owner="FeeModule"),
    "fixed_fee_rate": FieldRef("fixed_fee_rate", owner="FeeModule"),
    "margin_mode": FieldRef("margin_mode", owner="MarginModule"),
    "fixed_margin_ratio": FieldRef("fixed_margin_ratio", owner="MarginModule"),
    "margin_call_mode": FieldRef("margin_call_mode", owner="MarginModule"),
    "liquidation_target_buffer": FieldRef("liquidation_target_buffer", owner="MarginModule"),
    "accounting_mode": FieldRef("accounting_mode", owner="TradingRuleModule"),
    "daily_mark_to_market_enabled": FieldRef("daily_mark_to_market_enabled", owner="TradingRuleModule"),
    "cost_basis_method": FieldRef("cost_basis_method", owner="TradingRuleModule"),
    "use_int_position": FieldRef("use_int_position", owner="TradingRuleModule"),
    "cash_reserve_ratio": FieldRef("cash_reserve_ratio", owner="StrategyBookModule"),
    "cash_reserve_major": FieldRef("cash_reserve_major", owner="StrategyBookModule"),
}


class _AuditedLedgerConfig:
    """Read-only LedgerConfig proxy that audits direct ledger-level inputs."""

    def __init__(self, config: LedgerConfig, ctx: Any, token: object) -> None:
        object.__setattr__(self, "_config", config)
        object.__setattr__(self, "_ctx", ctx)
        object.__setattr__(self, "_token", token)

    def __getattr__(self, name: str) -> Any:
        ref = _LEDGER_CONFIG_FIELD_REFS.get(name)
        if ref is not None:
            self._ctx.record_external_contract_read(ref, self._token)
        return getattr(self._config, name)
