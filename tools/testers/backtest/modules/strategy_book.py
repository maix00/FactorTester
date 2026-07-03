"""StrategyBookModule — strategy registration and position-book routing.

StrategyBook owns the routing decision from a strategy/order to a ledger_id.
The actual cash, ProductPosition objects and lots deque live in Ledgers keyed
by that ledger_id.

(Renamed from BrokerModule/NativeBroker — "broker" is reserved for
CounterParty, the fee/margin/liquidity commercial-terms concept; this module
is purely about which strategies exist and which ledger each one's orders
land in, see ADR-032.)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, ClassVar, Literal, cast

from .base import ExecutableModule, FieldDefinition, FieldRef
from .engine import engine_mode_for

if TYPE_CHECKING:
    from tools.testers.backtest.engines.native.ledger import StrategyConfig


LedgerMode = Literal["private", "shared"]


class StrategyBookModule(ExecutableModule):
    key: ClassVar[str] = "strategy_book"
    label: ClassVar[str] = "策略簿"
    order: ClassVar[int] = 155

    ledger_mode: ClassVar[FieldRef[LedgerMode]] = FieldRef("ledger_mode")
    ledger_id: ClassVar[FieldRef[str | None]] = FieldRef("ledger_id")

    fields: ClassVar[dict[str, FieldDefinition]] = {
        "ledger_mode": FieldDefinition(
            public=True,
            label="账本模式",
            default="private",
            control_template="select",
            tab="strategy_book",
            options=(("private", "私有账本"), ("shared", "共享账本")),
            editable_when={"engine_mode": ("custom",)},
            default_when={"engine_mode": {"basic": "private", "auto": "private", "exact": "private"}},
            chip_template="账本模式: {value}",
            tab_label="策略簿",
            tab_order=155,
            help_text=(
                "private 为每个策略使用私有账本；shared 允许通过 ledger_id "
                "把一个或多个策略路由到同一个账本。"
            ),
        ),
        "ledger_id": FieldDefinition(
            public=True,
            label="账本",
            default=None,
            control_template="text",
            tab="strategy_book",
            visible_when={"ledger_mode": ("shared",)},
            editable_when={"engine_mode": ("custom",), "ledger_mode": ("shared",)},
            chip_template="账本: {value}",
            tab_label="策略簿",
            tab_order=155,
            help_text=(
                "shared 模式下的账本 id。相同 id 会共享同一个现金、ProductPosition 和 lots deque；"
                "不同 id 彼此隔离。private 模式会忽略该字段并使用策略私有账本 id。"
            ),
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


class NativeStrategyBook:
    """The default (and currently only) strategy-book implementation.

    Owns the strategy/order -> ledger_id routing decision. `ledger_mode=
    "shared"` is a configuration branch of this same class (shared ledger
    via an explicit ledger_id string), not a separate class. Fee/margin/
    liquidity commercial terms are CounterParty's concern (ADR-032), not
    this module's -- this class never grows fee_model/buying_power_model-
    style factories.
    """

    def resolve_ledger_mode(self, strategy_config: "StrategyConfig") -> LedgerMode:
        engine_mode = engine_mode_for(strategy_config)
        if engine_mode == "custom":
            value = str(strategy_config.get(StrategyBookModule.ledger_mode, "private") or "private")
            if value not in {"private", "shared"}:
                raise ValueError(f"unsupported ledger mode: {value}")
            return cast(LedgerMode, value)
        return "private"

    def ledger_id_for(
        self,
        strategy: object,
        strategy_config: "StrategyConfig",
        order: object | None = None,
    ) -> str:
        order_ledger_id = getattr(order, "fields", {}).get("ledger_id") if order is not None else None
        if order_ledger_id not in (None, ""):
            return str(order_ledger_id)
        if self.resolve_ledger_mode(strategy_config) == "shared":
            raw = strategy_config.get(StrategyBookModule.ledger_id)
            if raw in (None, ""):
                raise ValueError("shared ledger_mode requires ledger_id")
            return str(raw)
        return f"private:{getattr(strategy, 'alias', strategy)}"

    def assign_ledger_id_for_strategy(
        self,
        state: object,
        strategy: object,
        strategy_config: "StrategyConfig",
        order: object | None = None,
    ) -> str:
        ledger_id = self.ledger_id_for(strategy, strategy_config, order)
        store = strategy_book_store_for(state)
        store.ledger_ids_by_strategy.setdefault(strategy, set()).add(ledger_id)
        store.default_ledger_id_by_strategy.setdefault(strategy, ledger_id)
        return ledger_id


_NATIVE_STRATEGY_BOOK = NativeStrategyBook()


def strategy_book_for(state: object) -> NativeStrategyBook:
    """The run's strategy book. One shared NativeStrategyBook instance for
    now -- it is stateless (all runtime state lives in StrategyBookStore on
    the run state), so per-run construction buys nothing yet. When strategy
    book selection becomes per-strategy/per-run, this is the single lookup
    point to extend."""
    return _NATIVE_STRATEGY_BOOK


# ── thin delegates (existing call sites keep working unchanged) ──────


def resolve_ledger_mode(strategy_config: "StrategyConfig") -> LedgerMode:
    return _NATIVE_STRATEGY_BOOK.resolve_ledger_mode(strategy_config)


def ledger_id_for(strategy: object, strategy_config: "StrategyConfig", order: object | None = None) -> str:
    return _NATIVE_STRATEGY_BOOK.ledger_id_for(strategy, strategy_config, order)


def assign_ledger_id_for_strategy(
    state: object,
    strategy: object,
    strategy_config: "StrategyConfig",
    order: object | None = None,
) -> str:
    return _NATIVE_STRATEGY_BOOK.assign_ledger_id_for_strategy(state, strategy, strategy_config, order)
