"""StrategyBookModule — strategy registration and ledger routing.

StrategyBook owns the routing decision from a strategy/order to a ledger_id.
The actual cash, ProductPosition objects and lots deque live in Ledgers keyed
by that ledger_id.

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

if TYPE_CHECKING:
    from tools.testers.backtest.engines.native.ledger import StrategyConfig


StrategyBookMode = Literal["per_strategy_one_ledger"]


class StrategyBookModule(ExecutableModule):
    key: ClassVar[str] = "strategy_book"
    label: ClassVar[str] = "策略簿"
    order: ClassVar[int] = 155

    strategy_book_mode: ClassVar[FieldRef[StrategyBookMode]] = FieldRef("strategy_book_mode")

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
    }


@dataclass
class StrategyBookStore:
    ledger_ids_by_strategy: dict[object, set[str]] = field(default_factory=dict)
    default_ledger_id_by_strategy: dict[object, str] = field(default_factory=dict)


def strategy_book_store_for(state: object) -> StrategyBookStore:
    store = getattr(state, "strategy_book_store", None)
    if store is None:
        store = StrategyBookStore()
        setattr(state, "strategy_book_store", store)
    return store


@dataclass(frozen=True)
class LedgerSpec:
    initial_capital_major: float | None = None
    base_currency: str | None = None
    counterparty_profile: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StrategyBook:
    """Declarative strategy-to-ledger topology.

    The default object is intentionally tiny: it maps strategies to ledger_id
    strings. LedgerModule still creates the Ledger objects; CounterParty
    still owns commercial terms. Subclasses can override the routing and
    future decision-merging hooks without becoming a backtest runner.
    """

    strategy_ledger_ids_by_alias: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    default_ledger_id_by_alias: Mapping[str, str] = field(default_factory=dict)
    ledger_specs: Mapping[str, LedgerSpec] = field(default_factory=dict)

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
            ledger_specs=_parse_ledger_specs(payload.get("ledgers", {})),
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
            ledger_specs={ledger_id: LedgerSpec() for ledger_id in set(resolved.values())},
        )

    def ledger_ids_for_strategy(self, strategy: object) -> tuple[str, ...]:
        alias = _strategy_alias(strategy)
        ledger_ids = self.strategy_ledger_ids_by_alias.get(alias)
        if ledger_ids:
            return ledger_ids
        return (self.default_ledger_id_for_strategy(strategy),)

    def default_ledger_id_for_strategy(self, strategy: object) -> str:
        alias = _strategy_alias(strategy)
        return self.default_ledger_id_by_alias.get(alias, f"private:{alias}")

    def ledger_id_for_order(
        self,
        strategy: object,
        strategy_config: "StrategyConfig",
        order: object | None = None,
    ) -> str:
        order_ledger_id = getattr(order, "fields", {}).get("ledger_id") if order is not None else None
        if order_ledger_id not in (None, ""):
            ledger_id = str(order_ledger_id)
            if ledger_id not in self.ledger_ids_for_strategy(strategy):
                raise ValueError(
                    f"strategy {_strategy_alias(strategy)!r} cannot route order to undeclared ledger_id {ledger_id!r}"
                )
            return ledger_id
        return self.default_ledger_id_for_strategy(strategy)

    def assign_ledger_id_for_strategy(
        self,
        state: object,
        strategy: object,
        strategy_config: "StrategyConfig",
        order: object | None = None,
    ) -> str:
        ledger_id = self.ledger_id_for_order(strategy, strategy_config, order)
        store = strategy_book_store_for(state)
        store.ledger_ids_by_strategy.setdefault(strategy, set()).update(self.ledger_ids_for_strategy(strategy))
        store.default_ledger_id_by_strategy.setdefault(strategy, self.default_ledger_id_for_strategy(strategy))
        return ledger_id

    def provision_ledgers(self, state: object) -> None:
        for strategy, strategy_config in getattr(state, "strategy_configs", {}).items():
            self.assign_ledger_id_for_strategy(state, strategy, strategy_config)

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

    def ledger_id_for_order(
        self,
        strategy: object,
        strategy_config: "StrategyConfig",
        order: object | None = None,
    ) -> str:
        self.resolve_strategy_book_mode(strategy_config)
        order_ledger_id = getattr(order, "fields", {}).get("ledger_id") if order is not None else None
        if order_ledger_id not in (None, ""):
            return str(order_ledger_id)
        return f"private:{getattr(strategy, 'alias', strategy)}"

    def default_ledger_id_for_strategy(self, strategy: object) -> str:
        return f"private:{_strategy_alias(strategy)}"

    def ledger_ids_for_strategy(self, strategy: object) -> tuple[str, ...]:
        return (self.default_ledger_id_for_strategy(strategy),)


_STRATEGY_BOOK_SIMPLE = StrategyBookSimple()


def strategy_book_for(state: object) -> StrategyBook:
    book = getattr(state, "strategy_book", None)
    if book is not None:
        return book
    return _STRATEGY_BOOK_SIMPLE


def resolve_strategy_book_mode(strategy_config: "StrategyConfig") -> StrategyBookMode:
    return _STRATEGY_BOOK_SIMPLE.resolve_strategy_book_mode(strategy_config)


def ledger_id_for(strategy: object, strategy_config: "StrategyConfig", order: object | None = None) -> str:
    return _STRATEGY_BOOK_SIMPLE.ledger_id_for_order(strategy, strategy_config, order)


def assign_ledger_id_for_strategy(
    state: object,
    strategy: object,
    strategy_config: "StrategyConfig",
    order: object | None = None,
) -> str:
    return strategy_book_for(state).assign_ledger_id_for_strategy(state, strategy, strategy_config, order)


def _parse_ledger_specs(raw_ledgers: object) -> dict[str, LedgerSpec]:
    if raw_ledgers is None:
        return {}
    if not isinstance(raw_ledgers, Mapping):
        raise ValueError("StrategyBook.from_dict requires a mapping at 'ledgers'")
    result: dict[str, LedgerSpec] = {}
    for ledger_id, raw_spec in raw_ledgers.items():
        if raw_spec is None:
            result[str(ledger_id)] = LedgerSpec()
            continue
        if not isinstance(raw_spec, Mapping):
            raise ValueError(f"ledger spec for {ledger_id!r} must be a mapping")
        known = {"initial_capital_major", "base_currency", "counterparty_profile"}
        result[str(ledger_id)] = LedgerSpec(
            initial_capital_major=(
                float(raw_spec["initial_capital_major"])
                if raw_spec.get("initial_capital_major") is not None else None
            ),
            base_currency=(
                str(raw_spec["base_currency"])
                if raw_spec.get("base_currency") is not None else None
            ),
            counterparty_profile=(
                str(raw_spec["counterparty_profile"])
                if raw_spec.get("counterparty_profile") is not None else None
            ),
            metadata={str(key): value for key, value in raw_spec.items() if key not in known},
        )
    return result


def _strategy_alias(strategy: object) -> str:
    return str(getattr(strategy, "alias", strategy))
