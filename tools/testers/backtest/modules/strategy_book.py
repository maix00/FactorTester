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
from typing import TYPE_CHECKING, Any, ClassVar, Literal

from .base import ExecutableModule, FieldDefinition, FieldRef
from tools.testers.backtest.engines.native.ledger import Ledger, ledger_identity

if TYPE_CHECKING:
    from tools.testers.backtest.engines.native.ledger import StrategyConfig


StrategyBookMode = Literal["per_strategy_one_ledger"]


class StrategyBookModule(ExecutableModule):
    key: ClassVar[str] = "strategy_book"
    label: ClassVar[str] = "策略簿"
    order: ClassVar[int] = 155

    strategy_book_mode: ClassVar[FieldRef[StrategyBookMode]] = FieldRef("strategy_book_mode")
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


@dataclass
class StrategyBookStore:
    ledgers_by_strategy: dict[object, set[Ledger]] = field(default_factory=dict)
    _default_ledger_by_strategy: dict[object, Ledger] = field(default_factory=dict)
    order_ledger_router: Callable[[object, object], str | Ledger] | None = None
    available_cash_resolver: Callable[[object, object, float, str], float] | None = None
    merge_trade_decisions: Callable[[object, object], object] = lambda decisions, ctx: decisions
    apply_hierarchy_constraints: Callable[[object, object], object] = lambda decision, ctx: decision

    def register_strategy_ledgers(
        self,
        strategy: object,
        ledger_ids: Sequence[str],
        *,
        default_ledger_id: str,
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
        self._default_ledger_by_strategy[strategy] = default

    def ledgers_for_strategy(self, state: object, strategy: object) -> set[Ledger]:
        return self.ledgers_by_strategy.get(strategy, {ledger_identity(f"private:{_strategy_alias(strategy)}")})

    def default_ledger_for_strategy(self, state: object, strategy: object) -> Ledger:
        return self._default_ledger_by_strategy.get(strategy, ledger_identity(f"private:{_strategy_alias(strategy)}"))

    def ledger_for_order(self, state: object, order: object) -> Ledger:
        strategy = getattr(order, "strategy")
        if self.order_ledger_router is not None:
            ledger = ledger_identity(str(self.order_ledger_router(state, order)))
        else:
            order_ledger_id = getattr(order, "fields", {}).get("ledger_id")
            ledger = (
                ledger_identity(str(order_ledger_id))
                if order_ledger_id not in (None, "")
                else self.default_ledger_for_strategy(state, strategy)
            )
        allowed = self.ledgers_for_strategy(state, strategy)
        if ledger not in allowed:
            raise ValueError(
                f"strategy {_strategy_alias(strategy)!r} cannot route order to undeclared ledger_id {ledger.name!r}"
            )
        return ledger


def strategy_book_store_for(state: object) -> StrategyBookStore:
    store = getattr(state, "strategy_book_store", None)
    if store is None:
        store = StrategyBookStore()
        setattr(state, "strategy_book_store", store)
    return store


def materialize_strategy_book_store(state: object, strategy_book: object, strategies: Mapping[str, object]) -> StrategyBookStore:
    book = strategy_book if hasattr(strategy_book, "ledger_ids_for_strategy") else StrategyBookSimple()
    store = strategy_book_store_for(state)
    store.order_ledger_router = getattr(strategy_book, "order_ledger_router", None)
    store.available_cash_resolver = getattr(strategy_book, "available_cash_resolver", None)
    store.merge_trade_decisions = getattr(book, "merge_trade_decisions", store.merge_trade_decisions)
    store.apply_hierarchy_constraints = getattr(book, "apply_hierarchy_constraints", store.apply_hierarchy_constraints)
    for alias, strategy in strategies.items():
        ledger_ids = tuple(str(value) for value in _book_ledger_ids_for_alias(book, alias))
        if not ledger_ids:
            ledger_ids = (f"private:{alias}",)
        default = str(_book_default_ledger_id_for_alias(book, alias, ledger_ids[0]))
        store.register_strategy_ledgers(strategy, ledger_ids, default_ledger_id=default)
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

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "StrategyBook":
        if "strategies" not in payload:
            return cls.from_mapping(payload)
        strategies = payload.get("strategies", {})
        if not isinstance(strategies, Mapping):
            raise ValueError("StrategyBook.from_dict requires a mapping at 'strategies'")
        ledger_ids_by_alias: dict[str, tuple[str, ...]] = {}
        default_by_alias: dict[str, str] = {}
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
        store.register_strategy_ledgers(strategy, (default,), default_ledger_id=default)
    if order is None:
        return store.default_ledger_for_strategy(state, strategy)
    return store.ledger_for_order(state, order)


def _strategy_alias(strategy: object) -> str:
    return str(getattr(strategy, "alias", strategy))


def available_cash_for_ledger(state: object, ledger_state: object, cash_major: float, *, reason: str) -> float:
    store = strategy_book_store_for(state)
    if store.available_cash_resolver is not None:
        return max(0.0, float(store.available_cash_resolver(state, ledger_state, cash_major, reason)))
    ledger_config = state.ledger_config_for(ledger_state)  # type: ignore[attr-defined]
    ratio = max(0.0, min(1.0, float(getattr(ledger_config, "cash_reserve_ratio", None) or 0.0)))
    fixed = max(0.0, float(getattr(ledger_config, "cash_reserve_major", None) or 0.0))
    reserve = cash_major * ratio + fixed
    return max(0.0, cash_major - reserve)
