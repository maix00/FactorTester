"""StrategyBookModule — strategy registration and ledger routing.

StrategyBook owns the routing decision from a strategy/order to a Ledger.
The actual cash, ProductPosition objects and lots deque live in LedgerState
objects keyed by that Ledger identity.

(Renamed from BrokerModule/NativeBroker -- "broker" is reserved for
CounterParty, the fee/margin/liquidity commercial-terms concept. The default
mode is StrategyBookSimple: one private ledger per strategy. Richer strategy
books can be attached to BacktestRunState for code/CLI-driven runs.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, ClassVar, Literal, cast

from .base import ExecutableModule, FieldDefinition, FieldRef
from tools.testers.backtest.engines.native.config import CashPoolConfig
from tools.testers.backtest.engines.native.flow import Flow, Phase
from tools.testers.backtest.engines.native.ledger import Ledger, ledger_identity
from tools.testers.backtest.modules.product_selection import ProductSelectionModule
from tools.testers.backtest.policies import (
    CashAvailabilityPolicy,
    HierarchyConstraintPolicy,
    MarginBudgetPolicy,
    OrderRoutingPolicy,
    OrderSizingPolicy,
    PendingOrderConflictPolicy,
    StrategyBookPolicies,
    StrategyIntentPolicy,
    StrategyIntentPrecomputePolicy,
    TradeDecisionMergePolicy,
)

if TYPE_CHECKING:
    from tools.testers.backtest.engines.native.config import StrategyConfig

StrategyBookMode = Literal["per_strategy_one_ledger"]
LedgerSessionPolicyMode = Literal["error", "auto_split", "custom"]

class StrategyBookModule(ExecutableModule):
    key: ClassVar[str] = "strategy_book"
    label: ClassVar[str] = "策略簿"
    order: ClassVar[int] = 155

    strategy_book_mode: ClassVar[FieldRef[StrategyBookMode]] = FieldRef("strategy_book_mode")
    ledger_session_policy: ClassVar[FieldRef[LedgerSessionPolicyMode]] = FieldRef("ledger_session_policy")
    cash_reserve_ratio: ClassVar[FieldRef[float]] = FieldRef("cash_reserve_ratio")
    cash_reserve_major: ClassVar[FieldRef[float]] = FieldRef("cash_reserve_major")
    fields: ClassVar[dict[str, FieldDefinition]] = {
        "strategy_book_mode": FieldDefinition(
            public=True,
            label="策略簿模式",
            default="per_strategy_one_ledger",
            control_template="select",
            tab="strategy_book",
            options=(("per_strategy_one_ledger", "每策略一个账本"),),
            default_when={
                "engine_mode": {
                    "basic": "per_strategy_one_ledger",
                    "auto": "per_strategy_one_ledger",
                    "exact": "per_strategy_one_ledger",
                },
            },
            chip_template="策略簿: {value}",
            tab_label="策略簿",
            tab_order=155,
            help_text="默认模式：每个 strategy 使用一个私有 ledger。共享账本或一策略多账本由 StrategyBook.from_dict 或子类提供。",
        ),
        "ledger_session_policy": FieldDefinition(
            public=True,
            label="账本交易时段策略",
            default="error",
            control_template="select",
            tab="strategy_book",
            options=(
                ("error", "发现混合交易时段即报错"),
                ("auto_split", "按交易时段自动拆账本"),
                ("custom", "自定义账本时段策略"),
            ),
            chip_template="账本时段: {value}",
            tab_label="策略簿",
            tab_order=155,
            help_text=(
                "ledger 是现金、保证金、挂单和订单冲突的共同边界。默认不允许一个 ledger "
                "混入不同交易时段产品；auto_split 仅支持原 ledger 属于单一 cash pool 的情形。"
            ),
        ),
        "cash_reserve_ratio": FieldDefinition(
            public=True,
            label="现金保留比例",
            default=0.0,
            control_template="number",
            tab="strategy_book",
            minimum=0.0,
            maximum=1.0,
            step=0.01,
            chip_template="现金保留比例: {value}",
            tab_label="策略簿",
            tab_order=155,
            help_text="ledger 级风控缓冲；交易和保证金追缴只能使用扣除该比例后的可动用现金。",
        ),
        "cash_reserve_major": FieldDefinition(
            public=True,
            label="现金保留金额",
            default=0.0,
            control_template="number",
            tab="strategy_book",
            minimum=0.0,
            step=1.0,
            chip_template="现金保留金额: {value}",
            tab_label="策略簿",
            tab_order=155,
            help_text="ledger 级固定现金缓冲；与现金保留比例同时生效。",
        ),
    }

    validate_ledger_sessions: ClassVar[Flow] = Flow(
        "validate_ledger_sessions",
        inputs=(ledger_session_policy, ProductSelectionModule.products),
        outputs=(),
        phase=Phase.PRE_REPLAY,
        order=16,
        after=(ProductSelectionModule.resolve_product_selection,),
        description="校验账本交易时段",
        compute=lambda state, ctx: _apply_ledger_session_policy(state, ctx),
    )

    flows: ClassVar[tuple[Flow, ...]] = (validate_ledger_sessions,)


@dataclass
class StrategyBookStore:
    ledgers_by_strategy: dict[object, set[Ledger]] = field(default_factory=dict)
    _default_ledger_by_strategy: dict[object, Ledger] = field(default_factory=dict)
    cash_pool_by_ledger: dict[Ledger, str] = field(default_factory=dict)
    _cash_pool_by_ledger_object: dict[int, str] = field(default_factory=dict)
    _ledgers_by_cash_pool: dict[str, set[Ledger]] = field(default_factory=dict)
    product_ledger_by_strategy: dict[tuple[object, object], Ledger] = field(default_factory=dict)
    policies: StrategyBookPolicies = field(default_factory=StrategyBookPolicies)
    display_name_by_strategy: dict[object, str] = field(default_factory=dict)

    def register_strategy_ledgers(
        self,
        strategy: object,
        ledger_ids: Sequence[str],
        *,
        default_ledger_id: str,
        cash_pool_ids_by_ledger: Mapping[str, str] | None = None,
        display_name: str | None = None,
    ) -> None:
        allowed = {ledger_identity(str(ledger_id)) for ledger_id in ledger_ids}
        if not allowed:
            raise ValueError(f"strategy {_strategy_alias(strategy)!r} must declare at least one ledger_id")
        default = ledger_identity(str(default_ledger_id))
        if default not in allowed:
            raise ValueError(
                f"strategy {_strategy_alias(strategy)!r} default ledger must be one of "
                f"{sorted(ledger.name for ledger in allowed)}"
            )
        self.ledgers_by_strategy[strategy] = allowed
        if display_name:
            self.display_name_by_strategy[strategy] = str(display_name)
        self._default_ledger_by_strategy[strategy] = default
        pool_mapping = cash_pool_ids_by_ledger or {}
        for ledger in allowed:
            self.register_ledger_cash_pool(
                ledger,
                str(pool_mapping.get(ledger.name) or ledger.name),
            )

    def ledgers_for_strategy(self, state: object, strategy: object) -> set[Ledger]:
        return self.ledgers_by_strategy.get(strategy, {ledger_identity(f"private:{_strategy_alias(strategy)}")})

    def display_name_for_strategy(self, strategy: object) -> str:
        return self.display_name_by_strategy.get(strategy, _strategy_alias(strategy))

    def default_ledger_for_strategy(self, state: object, strategy: object) -> Ledger:
        return self._default_ledger_by_strategy.get(strategy, ledger_identity(f"private:{_strategy_alias(strategy)}"))

    def ledger_for_order(self, state: object, order: object) -> Ledger:
        strategy = getattr(order, "strategy")
        order_ledger_id = getattr(order, "fields", {}).get("ledger_id")
        if order_ledger_id not in (None, ""):
            ledger = ledger_identity(str(order_ledger_id))
        elif self.policies.order_routing is not None:
            ledger = ledger_identity(str(self.policies.order_routing(state, order)))
        else:
            ledger = self.product_ledger_by_strategy.get(
                (strategy, getattr(order, "instrument", None)),
                self.default_ledger_for_strategy(state, strategy),
            )
        allowed = self.ledgers_for_strategy(state, strategy)
        if ledger not in allowed:
            raise ValueError(
                f"strategy {_strategy_alias(strategy)!r} cannot route order to undeclared ledger_id {ledger.name!r}"
            )
        return ledger

    def cash_pool_for_ledger(self, ledger: str | Ledger) -> str:
        if isinstance(ledger, Ledger):
            cached = self._cash_pool_by_ledger_object.get(id(ledger))
            if cached is not None:
                return cached
            ledger_key = ledger
        else:
            ledger_key = ledger_identity(ledger)
        return str(self.cash_pool_by_ledger.get(ledger_key) or ledger_key.name)

    def register_ledger_cash_pool(self, ledger: str | Ledger, cash_pool_id: str) -> str:
        ledger_key = ledger_identity(ledger)
        pool_id = str(self.cash_pool_by_ledger.setdefault(ledger_key, str(cash_pool_id)))
        self._cash_pool_by_ledger_object[id(ledger_key)] = pool_id
        self._ledgers_by_cash_pool.setdefault(pool_id, set()).add(ledger_key)
        return pool_id

    def ledgers_for_cash_pool(self, cash_pool_id: str) -> set[Ledger]:
        return set(self._ledgers_by_cash_pool.get(str(cash_pool_id), ()))

def strategy_book_store_for(state: object) -> StrategyBookStore:
    store = getattr(state, "strategy_book_store", None)
    if store is None:
        store = StrategyBookStore()
        setattr(state, "strategy_book_store", store)
    return store


def materialize_strategy_book_store(
    state: object,
    strategy_book: object,
    strategies: Mapping[str, object],
    resolved_settings_by_alias: Mapping[str, Mapping[str, Any]] | None = None,
) -> StrategyBookStore:
    book = strategy_book if hasattr(strategy_book, "ledger_ids_for_strategy") else StrategyBookSimple()
    store = strategy_book_store_for(state)
    store.policies = _policies_from_strategy_book(strategy_book, book)
    for alias, strategy in strategies.items():
        ledger_ids = tuple(str(value) for value in _book_ledger_ids_for_alias(book, alias))
        if not ledger_ids:
            ledger_ids = (f"private:{alias}",)
        default = str(_book_default_ledger_id_for_alias(book, alias, ledger_ids[0]))
        cash_pool_ids = {
            ledger_id: _book_cash_pool_id_for_ledger(book, ledger_id)
            for ledger_id in ledger_ids
        }
        store.register_strategy_ledgers(
            strategy,
            ledger_ids,
            default_ledger_id=default,
            cash_pool_ids_by_ledger=cash_pool_ids,
            display_name=str((resolved_settings_by_alias or {}).get(alias, {}).get("display_name") or alias),
        )
    return store


def _book_ledger_ids_for_alias(book: object, alias: str) -> tuple[str, ...]:
    mapping = getattr(book, "strategy_ledger_ids_by_alias", {})
    ledger_ids = mapping.get(str(alias))
    if ledger_ids:
        return tuple(str(value) for value in ledger_ids)
    return (_book_default_ledger_id_for_alias(book, alias, f"private:{alias}"),)


def _book_default_ledger_id_for_alias(book: object, alias: str, fallback: str) -> str:
    mapping = getattr(book, "default_ledger_id_by_alias", {})
    return str(mapping.get(str(alias), fallback))


def _book_cash_pool_id_for_ledger(book: object, ledger_id: str) -> str:
    mapping = getattr(book, "cash_pool_id_by_ledger", {})
    return str(mapping.get(str(ledger_id), ledger_id))


@dataclass(frozen=True)
class StrategyBook:
    """Declarative strategy-to-ledger topology.

    The default object is intentionally tiny: it maps strategy aliases to
    declarative ledger names at the input boundary. `StrategyBookStore`
    materializes those names into Ledger identities for runtime routing.
    LedgerModule creates the LedgerState objects; CounterParty owns commercial
    terms. Subclasses can override routing and decision-merging hooks without
    becoming a backtest runner.
    """

    strategy_ledger_ids_by_alias: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    default_ledger_id_by_alias: Mapping[str, str] = field(default_factory=dict)
    cash_pool_id_by_ledger: Mapping[str, str] = field(default_factory=dict)
    cash_pool_configs_by_id: Mapping[str, CashPoolConfig] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "StrategyBook":
        if "strategies" not in payload:
            return cls.from_mapping(payload)
        strategies = payload.get("strategies", {})
        if not isinstance(strategies, Mapping):
            raise ValueError("StrategyBook.from_dict requires a mapping at 'strategies'")
        ledger_ids_by_alias: dict[str, tuple[str, ...]] = {}
        default_by_alias: dict[str, str] = {}
        cash_pool_by_ledger = {
            str(ledger_id): str(pool_id)
            for ledger_id, pool_id in _cash_pool_mapping_from_payload(payload).items()
        }
        cash_pool_configs = {
            str(pool_id): _cash_pool_config_from_payload(raw_config)
            for pool_id, raw_config in _cash_pool_config_mapping_from_payload(payload).items()
        }
        for alias, raw in strategies.items():
            alias_text = str(alias)
            ledger_ids: tuple[str, ...]
            if isinstance(raw, str):
                ledger_ids = (raw,)
                default_ledger_id = raw
            elif isinstance(raw, Mapping):
                raw_ledger_ids = raw.get("ledger_ids", raw.get("ledgers", ()))
                if isinstance(raw_ledger_ids, str):
                    ledger_ids = (raw_ledger_ids,)
                else:
                    ledger_ids = tuple(str(value) for value in raw_ledger_ids)
                default_ledger_id = str(raw.get("default_ledger_id") or (ledger_ids[0] if ledger_ids else ""))
            else:
                raise ValueError(f"invalid StrategyBook strategy entry for {alias_text!r}")
            if not ledger_ids or not default_ledger_id:
                raise ValueError(f"strategy {alias_text!r} must declare at least one ledger_id")
            if default_ledger_id not in ledger_ids:
                raise ValueError(f"strategy {alias_text!r} default_ledger_id must be in ledger_ids")
            ledger_ids_by_alias[alias_text] = ledger_ids
            default_by_alias[alias_text] = default_ledger_id
        return cls(
            strategy_ledger_ids_by_alias=ledger_ids_by_alias,
            default_ledger_id_by_alias=default_by_alias,
            cash_pool_id_by_ledger=cash_pool_by_ledger,
            cash_pool_configs_by_id=cash_pool_configs,
        )

    @classmethod
    def from_mapping(
        cls,
        mapping: Mapping[str, str] | Callable[[str], str],
        *,
        aliases: Sequence[str] = (),
    ) -> "StrategyBook":
        if callable(mapping):
            if not aliases:
                raise ValueError("StrategyBook.from_mapping(callable) requires aliases")
            resolved = {str(alias): str(mapping(str(alias))) for alias in aliases}
        else:
            resolved = {str(alias): str(ledger_id) for alias, ledger_id in mapping.items()}
        return cls(
            strategy_ledger_ids_by_alias={alias: (ledger_id,) for alias, ledger_id in resolved.items()},
            default_ledger_id_by_alias=resolved,
            cash_pool_id_by_ledger={ledger_id: ledger_id for ledger_id in resolved.values()},
        )

    def cash_pool_config_for_strategy_settings(
        self,
        state: object,
        strategy: object,
        ledger: str | Ledger,
        resolved_settings: Mapping[str, Any],
    ) -> CashPoolConfig:
        pool_id = cash_pool_id_for_ledger(state, ledger)
        explicit = self.cash_pool_configs_by_id.get(pool_id)
        if explicit is not None:
            return explicit
        return CashPoolConfig(
            initial_capital_major=_optional_float(resolved_settings.get("initial_capital_major")),
            base_currency=_optional_str(resolved_settings.get("base_currency")),
            currency_conversion_fee_rate=_optional_float(resolved_settings.get("currency_conversion_fee_rate")),
            target_margin_utilization=_optional_float(resolved_settings.get("target_margin_utilization")),
            max_margin_utilization=_optional_float(resolved_settings.get("max_margin_utilization")),
            margin_utilization_tolerance=_optional_float(resolved_settings.get("margin_utilization_tolerance")),
        )

    def ledger_ids_for_strategy(self, state: object, strategy: object) -> tuple[str, ...]:
        alias = _strategy_alias(strategy)
        ledger_ids = self.strategy_ledger_ids_by_alias.get(alias)
        if ledger_ids:
            return ledger_ids
        return (self.default_ledger_id_for_strategy(state, strategy),)

    def default_ledger_id_for_strategy(self, state: object, strategy: object) -> str:
        alias = _strategy_alias(strategy)
        return self.default_ledger_id_by_alias.get(alias, f"private:{alias}")

    def merge_trade_decisions(self, decisions: object, ctx: object) -> object:
        return decisions

    def apply_hierarchy_constraints(self, decision: object, ctx: object) -> object:
        return decision


class StrategyBookSimple(StrategyBook):
    """Default strategy book: one private ledger per strategy.

    This is not native-engine specific; it simply says no strategies share ledgers unless a caller
    attaches a richer StrategyBook to BacktestRunState.
    """

    def resolve_strategy_book_mode(self, strategy_config: "StrategyConfig") -> StrategyBookMode:
        value = str(strategy_config.get(StrategyBookModule.strategy_book_mode, "per_strategy_one_ledger")
                    or "per_strategy_one_ledger")
        if value != "per_strategy_one_ledger":
            raise ValueError(f"unsupported strategy book mode: {value}")
        return "per_strategy_one_ledger"

    def default_ledger_id_for_strategy(self, state: object, strategy: object) -> str:
        return f"private:{_strategy_alias(strategy)}"

    def ledger_ids_for_strategy(self, state: object, strategy: object) -> tuple[str, ...]:
        return (self.default_ledger_id_for_strategy(state, strategy),)


_STRATEGY_BOOK_SIMPLE = StrategyBookSimple()


def strategy_book_for(state: object) -> StrategyBook:
    return _STRATEGY_BOOK_SIMPLE


def resolve_strategy_book_mode(strategy_config: "StrategyConfig") -> StrategyBookMode:
    return _STRATEGY_BOOK_SIMPLE.resolve_strategy_book_mode(strategy_config)


def assign_ledger_for_strategy(
    state: object,
    strategy: object,
    strategy_config: "StrategyConfig",
    order: object | None = None,
) -> Ledger:
    store = strategy_book_store_for(state)
    if strategy not in store.ledgers_by_strategy:
        default = f"private:{_strategy_alias(strategy)}"
        store.register_strategy_ledgers(
            strategy,
            (default,),
            default_ledger_id=default,
            cash_pool_ids_by_ledger={default: default},
        )
    if order is None:
        return store.default_ledger_for_strategy(state, strategy)
    return store.ledger_for_order(state, order)


def ledger_for_strategy_product(
    state: object,
    strategy: object,
    product: object,
    *,
    timestamp: Any = None,
    order: Any = None,
) -> object:
    from tools.testers.backtest.modules.strategy_routing import freeze_product_route

    target_store = getattr(state, "target_store", None)
    store = getattr(state, "strategy_book_store", None)
    # Most replay lookups are the same static strategy/product route resolved
    # by an earlier SIGNAL flow.  Check the identity cache before touching the
    # StrategyBook store or hashing the object-key compatibility cache.  The
    # cache is populated only for order=None/static routing below, so this
    # early return cannot bypass a dynamic order-routing policy.
    static_identity_cache = getattr(
        target_store,
        "static_strategy_product_ledger_identity_cache",
        None,
    )
    if (
        order is None
        and store is not None
        and store.policies.order_routing is None
        and static_identity_cache is not None
    ):
        identity_entry = static_identity_cache.get((id(strategy), id(product)))
        if (
            identity_entry is not None
            and identity_entry[0] is strategy
            and identity_entry[1] is product
        ):
            return identity_entry[2]

    if store is None:
        store = strategy_book_store_for(state)
    static_route = order is None and store.policies.order_routing is None
    if static_route:
        if static_identity_cache is not None:
            identity_key = (id(strategy), id(product))
        static_ledger_cache = getattr(target_store, "static_strategy_product_ledger_cache", None)
        if static_ledger_cache is not None:
            cached_ledger = static_ledger_cache.get((strategy, product))
            if cached_ledger is not None:
                if static_identity_cache is not None:
                    static_identity_cache[(id(strategy), id(product))] = (
                        strategy, product, cached_ledger,
                    )
                return cached_ledger
    if static_route:
        route_cache = getattr(state, "strategy_static_routing_decisions", None)
        decision = route_cache.get((strategy, product)) if route_cache is not None else None
        if decision is None:
            decision = freeze_product_route(
                state, strategy, product, timestamp=timestamp, order=order,
            )
        ledger_key = decision.ledger
    else:
        ledger_key = freeze_product_route(
            state, strategy, product, timestamp=timestamp, order=order,
        ).ledger
    ledger_cache = getattr(target_store, "strategy_product_ledger_cache", None)
    cache_key = (strategy, product, ledger_key)
    if ledger_cache is not None and cache_key in ledger_cache:
        ledger_state = ledger_cache[cache_key]
        if static_route and static_identity_cache is not None:
            static_identity_cache[(id(strategy), id(product))] = (
                strategy, product, ledger_state,
            )
        return ledger_state
    ledgers = getattr(state, "ledgers", None)
    if isinstance(ledgers, dict):
        ledger_state = ledgers.get(ledger_key)
        if ledger_state is None:
            ledger_state = ledgers.get(strategy)
        if ledger_state is None:
            empty_factory = getattr(state, "_empty_ledger_for", None)
            if not callable(empty_factory):
                return state.ledger_for_strategy(strategy)  # type: ignore[attr-defined]
            ledger_state = empty_factory(strategy, ledger_key)
            ledgers[ledger_key] = ledger_state
        if ledger_cache is not None:
            ledger_cache[cache_key] = ledger_state
        if static_route and static_ledger_cache is not None:
            static_ledger_cache[(strategy, product)] = ledger_state
        if static_route and static_identity_cache is not None:
            static_identity_cache[(id(strategy), id(product))] = (
                strategy, product, ledger_state,
            )
        return ledger_state
    ledger_state = state.ledger_for_strategy(strategy)  # type: ignore[attr-defined]
    if ledger_cache is not None:
        ledger_cache[cache_key] = ledger_state
    if static_route and static_ledger_cache is not None:
        static_ledger_cache[(strategy, product)] = ledger_state
    if static_route and static_identity_cache is not None:
        static_identity_cache[(id(strategy), id(product))] = (
            strategy, product, ledger_state,
        )
    return ledger_state


def positions_for_strategy_ledgers(state: object, strategy: object) -> dict[Any, Any]:
    from tools.testers.backtest.modules.ledger_module import LedgerModule

    store = strategy_book_store_for(state)
    positions: dict[Any, Any] = {}
    ledgers = getattr(state, "ledgers", {})
    for ledger_key in store.ledgers_for_strategy(state, strategy):
        ledger_state = ledgers.get(ledger_key) if isinstance(ledgers, dict) else None
        if ledger_state is None:
            continue
        positions.update(ledger_state.get(LedgerModule.positions, {}) or {})
    if not positions:
        ledger_state = state.ledger_for_strategy(strategy)  # type: ignore[attr-defined]
        positions.update(ledger_state.get(LedgerModule.positions, {}) or {})
    return positions


def _apply_ledger_session_policy(state: object, ctx: object) -> None:
    store = strategy_book_store_for(state)
    for strategy in getattr(state, "strategy_configs", {}):
        products = tuple(ctx.get_for(ProductSelectionModule.products, strategy, frozenset()))
        groups = _products_by_session_signature(products)
        if len(groups) <= 1:
            continue
        config = state.config_for(strategy)  # type: ignore[attr-defined]
        mode = str(config.get(StrategyBookModule.ledger_session_policy, "error") or "error").lower()
        if mode == "error":
            raise ValueError(_mixed_ledger_session_message(strategy, store.default_ledger_for_strategy(state, strategy), groups))
        if mode == "auto_split":
            _auto_split_strategy_ledger_by_session(state, store, strategy, groups)
            _validate_shared_cash_pool_requires_custom_policy(state, store, strategy)
            continue
        if mode == "custom":
            raise ValueError(
                "ledger_session_policy='custom' requires an explicit StrategyBook ledger-session policy; "
                "none is registered"
            )
        raise ValueError(f"unsupported ledger_session_policy: {mode!r}")

    for strategy in getattr(state, "strategy_configs", {}):
        _validate_shared_cash_pool_requires_custom_policy(state, store, strategy)


def _products_by_session_signature(products: Sequence[Any]) -> dict[str, list[Any]]:
    groups: dict[str, list[Any]] = {}
    for product in products:
        signature = _product_session_signature(product)
        if not signature:
            continue
        groups.setdefault(signature, []).append(product)
    return groups


def _product_session_signature(product: Any) -> str | None:
    for attr in ("trading_session_signature", "session_signature", "trading_session"):
        value = getattr(product, attr, None)
        if value not in (None, ""):
            return str(value)
    try:
        from sources.LocalCNFutures.CNFutures import (
            CNFUTURES_CATEGORY_DAYNIGHT,
            CNFutures,
            get_value_alias_for_day_night_time_category,
        )
    except Exception:
        return None
    if isinstance(product, CNFutures):
        raw = CNFUTURES_CATEGORY_DAYNIGHT.get(product)
        if raw in (None, "", "未知"):
            return None
        return get_value_alias_for_day_night_time_category(str(raw))
    return None


def _auto_split_strategy_ledger_by_session(
    state: object,
    store: StrategyBookStore,
    strategy: object,
    groups: Mapping[str, Sequence[Any]],
) -> None:
    original_ledgers = store.ledgers_for_strategy(state, strategy)
    if len(original_ledgers) != 1:
        raise ValueError(
            f"ledger_session_policy='auto_split' only supports one source ledger per strategy; "
            f"strategy {_strategy_alias(strategy)!r} declares {sorted(ledger.name for ledger in original_ledgers)}"
        )
    original = next(iter(original_ledgers))
    pool_id = store.cash_pool_for_ledger(original)
    if not pool_id:
        raise ValueError(f"ledger {original.name!r} has no cash pool; auto_split cannot decide funding")
    child_ledgers: dict[str, Ledger] = {}
    for signature, products in sorted(groups.items(), key=lambda item: item[0]):
        child = ledger_identity(f"{original.name}@session:{_safe_ledger_suffix(signature)}")
        child_ledgers[signature] = child
        store.register_ledger_cash_pool(child, pool_id)
        _copy_ledger_config(state, original, child)
        for product in products:
            store.product_ledger_by_strategy[(strategy, product)] = child
    children = set(child_ledgers.values())
    store.ledgers_by_strategy[strategy] = children
    store._default_ledger_by_strategy[strategy] = next(iter(sorted(children, key=lambda ledger: ledger.name)))
    _record_ledger_auto_split_runtime_info(state, strategy, original, pool_id, groups, children)


def _validate_shared_cash_pool_requires_custom_policy(
    state: object,
    store: StrategyBookStore,
    strategy: object,
) -> None:
    ledgers = store.ledgers_for_strategy(state, strategy)
    if len(ledgers) <= 1:
        return
    pool_counts: dict[str, int] = {}
    for ledger in ledgers:
        pool_id = store.cash_pool_for_ledger(ledger)
        pool_counts[pool_id] = pool_counts.get(pool_id, 0) + 1
    shared_pools = sorted(pool_id for pool_id, count in pool_counts.items() if count > 1)
    if not shared_pools:
        return
    if store.policies.cash_availability is not None or store.policies.order_sizing is not None:
        return
    raise ValueError(
        f"strategy {_strategy_alias(strategy)!r} routes multiple ledgers through shared cash pool(s) "
        f"{shared_pools}. Native has no default inactive-ledger cash allocation policy; "
        "register a custom StrategyBook cash_availability/order_sizing policy or use separate cash pools."
    )


def _copy_ledger_config(state: object, source: Ledger, target: Ledger) -> None:
    configs = getattr(state, "ledger_configs", None)
    if not isinstance(configs, dict):
        return
    if target in configs:
        return
    if source in configs:
        configs[target] = configs[source]


def _safe_ledger_suffix(value: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in value)[:40] or "unknown"


def _mixed_ledger_session_message(strategy: object, ledger: Ledger, groups: Mapping[str, Sequence[Any]]) -> str:
    parts = []
    for signature, products in sorted(groups.items(), key=lambda item: item[0]):
        sample = "、".join(_product_label(product) for product in list(products)[:5])
        suffix = "…" if len(products) > 5 else ""
        parts.append(f"{signature}: {sample}{suffix}")
    return (
        f"strategy {_strategy_alias(strategy)!r} routes products with multiple trading sessions into "
        f"ledger {ledger.name!r}: {'; '.join(parts)}. "
        "Set ledger_session_policy='auto_split' or define a custom StrategyBook routing policy."
    )


def _product_label(product: Any) -> str:
    name = getattr(product, "name", product)
    desc = getattr(product, "desc", "")
    return f"{name}({desc})" if desc else str(name)


def _record_ledger_auto_split_runtime_info(
    state: object,
    strategy: object,
    source_ledger: Ledger,
    pool_id: str,
    groups: Mapping[str, Sequence[Any]],
    child_ledgers: set[Ledger],
) -> None:
    rows = getattr(state, "runtime_info_rows", None)
    if not isinstance(rows, list):
        return
    detail = "；".join(
        f"{signature} -> {sorted(ledger.name for ledger in child_ledgers if f'@session:{_safe_ledger_suffix(signature)}' in ledger.name)}"
        for signature in sorted(groups)
    )
    rows.append({
        "type": "策略簿",
        "status": "已拆分",
        "level": "info",
        "code": "ledger_session_auto_split",
        "message": (
            f"strategy {_strategy_alias(strategy)!r} 的 ledger {source_ledger.name!r} "
            f"已按交易时段拆分，并继续共享 cash pool {pool_id!r}"
        ),
        "details": detail,
        "strategy": _strategy_alias(strategy),
        "aggregation_key": f"ledger_session_auto_split:{_strategy_alias(strategy)}:{source_ledger.name}",
    })


def apply_order_sizing_policy(
    state: object,
    ctx: object,
    strategy: object,
    deltas: dict[Any, float],
) -> dict[Any, float]:
    policy = strategy_book_store_for(state).policies.order_sizing
    if policy is not None:
        return policy(state, ctx, strategy, deltas)
    from tools.testers.backtest.modules.volume_capacity import apply_volume_capacity_policy

    return apply_volume_capacity_policy(state, ctx, strategy, deltas)


def apply_pending_order_conflict_policy(
    state: object,
    strategy: object,
    order: object,
    signal_timestamp: object,
) -> None:
    policy = strategy_book_store_for(state).policies.pending_order_conflict
    if policy is not None:
        policy(state, strategy, order, signal_timestamp)
        return
    from tools.testers.backtest.modules.order_flow import default_pending_order_conflict_policy

    default_pending_order_conflict_policy(state, strategy, order, signal_timestamp)


def apply_strategy_intent_precompute_policy(
    state: object,
    ctx: object,
    strategies: Sequence[object],
    default_policy: StrategyIntentPolicy,
) -> None:
    policy = strategy_book_store_for(state).policies.strategy_intent_precompute
    if policy is not None:
        policy(state, ctx, strategies, default_policy)
        return
    default_policy.precompute_strategy_intents(state, ctx, strategies)


def resolve_strategy_intent_policy(
    state: object,
    strategy: object,
    default_policy: StrategyIntentPolicy,
) -> StrategyIntentPolicy:
    return strategy_book_store_for(state).policies.strategy_intent_for(strategy, default_policy)


def _strategy_alias(strategy: object) -> str:
    return str(getattr(strategy, "alias", strategy))


def available_cash_for_ledger(state: object, ledger_state: object, cash_major: float, *, reason: str) -> float:
    store = strategy_book_store_for(state)
    if store.policies.cash_availability is not None:
        return max(0.0, float(store.policies.cash_availability(state, ledger_state, cash_major, reason)))
    ledger_config = state.ledger_config_for(ledger_state)  # type: ignore[attr-defined]
    ratio = max(0.0, min(1.0, float(getattr(ledger_config, "cash_reserve_ratio", None) or 0.0)))
    fixed = max(0.0, float(getattr(ledger_config, "cash_reserve_major", None) or 0.0))
    reserve = cash_major * ratio + fixed
    return max(0.0, cash_major - reserve)


def _policies_from_strategy_book(strategy_book: object, book: object) -> StrategyBookPolicies:
    explicit = getattr(strategy_book, "policies", None)
    if isinstance(explicit, StrategyBookPolicies):
        return explicit
    return StrategyBookPolicies(
        trade_decision_merge=getattr(book, "merge_trade_decisions", None),
        hierarchy_constraints=getattr(book, "apply_hierarchy_constraints", None),
        strategy_intent_precompute=getattr(book, "precompute_strategy_intents", None),
        margin_budget=getattr(book, "apply_margin_budget", None),
    )


def cash_pool_id_for_ledger(state: object, ledger: str | Ledger | object) -> str:
    ledger_key = _ledger_identity_from_any(ledger)
    return strategy_book_store_for(state).cash_pool_for_ledger(ledger_key)


def ledgers_for_cash_pool(state: object, ledger: str | Ledger | object) -> set[Ledger]:
    store = strategy_book_store_for(state)
    pool_id = cash_pool_id_for_ledger(state, ledger)
    ledgers = store.ledgers_for_cash_pool(pool_id)
    if ledgers:
        return ledgers
    return {_ledger_identity_from_any(ledger)}


def _ledger_identity_from_any(ledger: str | Ledger | object) -> Ledger:
    value = getattr(ledger, "ledger", ledger)
    # LedgerState/Order routing already carries the canonical Ledger object.
    # Avoid re-entering ledger_identity (and its isinstance/hash path) for
    # every cash/fee/margin lookup; string declarations still normalize once.
    return value if isinstance(value, Ledger) else ledger_identity(cast(str | Ledger, value))


def _cash_pool_mapping_from_payload(payload: Mapping[str, Any]) -> Mapping[str, str]:
    raw = payload.get("cash_pools", payload.get("cash_pool_id_by_ledger", {}))
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        raise ValueError("StrategyBook cash_pools must map ledger_id to cash_pool_id")
    return {str(ledger_id): str(pool_id) for ledger_id, pool_id in raw.items()}


def _cash_pool_config_mapping_from_payload(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    raw = payload.get("cash_pool_configs", {})
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        raise ValueError("StrategyBook cash_pool_configs must map cash_pool_id to config mapping")
    return raw


def _cash_pool_config_from_payload(raw: Any) -> CashPoolConfig:
    if isinstance(raw, CashPoolConfig):
        return raw
    if not isinstance(raw, Mapping):
        raise ValueError("StrategyBook cash_pool_configs entries must be mappings")
    return CashPoolConfig(
        initial_capital_major=_optional_float(raw.get("initial_capital_major")),
        base_currency=_optional_str(raw.get("base_currency")),
        currency_conversion_fee_rate=_optional_float(raw.get("currency_conversion_fee_rate")),
        target_margin_utilization=_optional_float(raw.get("target_margin_utilization")),
        max_margin_utilization=_optional_float(raw.get("max_margin_utilization")),
        margin_utilization_tolerance=_optional_float(raw.get("margin_utilization_tolerance")),
    )


def _optional_str(value: object) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _optional_float(value: object) -> float | None:
    if value in (None, ""):
        return None
    return float(value)  # type: ignore[arg-type]
