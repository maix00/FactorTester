"""BrokerModule — broker selection and position-book routing.

Broker owns the routing decision from a strategy/order to a ledger_id.
The actual cash, ProductPosition objects and lots deque live in Ledgers keyed
by that ledger_id.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, ClassVar, Literal, cast

from .base import ExecutableModule, FieldDefinition, FieldRef
from .engine import engine_mode_for

if TYPE_CHECKING:
    from tools.testers.backtest.engines.native.ledger import StrategyConfig


BrokerModel = Literal["native_broker", "custom_broker"]


class BrokerModule(ExecutableModule):
    key: ClassVar[str] = "broker"
    label: ClassVar[str] = "经纪账户"
    order: ClassVar[int] = 155

    broker_model: ClassVar[FieldRef[BrokerModel]] = FieldRef("broker_model")
    ledger_id: ClassVar[FieldRef[str | None]] = FieldRef("ledger_id")

    fields: ClassVar[dict[str, FieldDefinition]] = {
        "broker_model": FieldDefinition(
            public=True,
            label="经纪模式",
            default="native_broker",
            control_template="select",
            tab="broker",
            options=(("native_broker", "NativeBroker"), ("custom_broker", "CustomBroker")),
            editable_when={"engine_mode": ("custom",)},
            default_when={"engine_mode": {"basic": "native_broker", "auto": "native_broker", "exact": "native_broker"}},
            chip_template="经纪模式: {value}",
            tab_label="经纪账户",
            tab_order=155,
            help_text=(
                "native_broker 为每个策略使用私有账本；custom_broker 允许通过 ledger_id "
                "把一个或多个策略路由到同一个账本。"
            ),
        ),
        "ledger_id": FieldDefinition(
            public=True,
            label="账本",
            default=None,
            control_template="text",
            tab="broker",
            visible_when={"broker_model": ("custom_broker",)},
            editable_when={"engine_mode": ("custom",), "broker_model": ("custom_broker",)},
            chip_template="账本: {value}",
            tab_label="经纪账户",
            tab_order=155,
            help_text=(
                "custom_broker 下的账本 id。相同 id 会共享同一个现金、ProductPosition 和 lots deque；"
                "不同 id 彼此隔离。native_broker 会忽略该字段并使用策略私有账本 id。"
            ),
        ),
    }


@dataclass
class BrokerStore:
    ledger_ids_by_strategy: dict[object, set[str]] = field(default_factory=dict)
    default_ledger_id_by_strategy: dict[object, str] = field(default_factory=dict)


def broker_store_for(state: object) -> BrokerStore:
    store = getattr(state, "broker_store", None)
    if store is None:
        store = BrokerStore()
        setattr(state, "broker_store", store)
    return store


def resolve_broker_model(strategy_config: "StrategyConfig") -> BrokerModel:
    engine_mode = engine_mode_for(strategy_config)
    if engine_mode == "custom":
        value = str(strategy_config.get(BrokerModule.broker_model, "native_broker") or "native_broker")
        if value not in {"native_broker", "custom_broker"}:
            raise ValueError(f"unsupported broker model: {value}")
        return cast(BrokerModel, value)
    return "native_broker"


def ledger_id_for(strategy: object, strategy_config: "StrategyConfig", order: object | None = None) -> str:
    order_ledger_id = getattr(order, "fields", {}).get("ledger_id") if order is not None else None
    if order_ledger_id not in (None, ""):
        return str(order_ledger_id)
    if resolve_broker_model(strategy_config) == "custom_broker":
        raw = strategy_config.get(BrokerModule.ledger_id)
        if raw in (None, ""):
            raise ValueError("CustomBroker requires ledger_id")
        return str(raw)
    return f"native_broker:{getattr(strategy, 'alias', strategy)}"


def assign_ledger_id_for_strategy(
    state: object,
    strategy: object,
    strategy_config: "StrategyConfig",
    order: object | None = None,
) -> str:
    ledger_id = ledger_id_for(strategy, strategy_config, order)
    store = broker_store_for(state)
    store.ledger_ids_by_strategy.setdefault(strategy, set()).add(ledger_id)
    store.default_ledger_id_by_strategy.setdefault(strategy, ledger_id)
    return ledger_id
