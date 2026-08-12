"""Typed commands returned by user-facing native Strategy hooks.

Commands describe a request; the strategy hook adapter and owning Flows apply
them.  They never contain a reference to the scheduler, ledger, or broker.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from .orders.enums import OrderSide


class StrategyCommandKind(str, Enum):
    SUBMIT = "submit_order"
    CANCEL = "cancel_order"
    REPLACE = "replace_order"
    CLOSE = "close_position"


@dataclass(frozen=True)
class SubmitOrderCommand:
    product: Any
    quantity: float
    side: OrderSide | str = OrderSide.BUY
    reason: str = "submit_order"

    @property
    def kind(self) -> StrategyCommandKind:
        return StrategyCommandKind.SUBMIT

    def __post_init__(self) -> None:
        if float(self.quantity) <= 0:
            raise ValueError("submit_order quantity must be positive")
        object.__setattr__(self, "side", OrderSide(self.side))


@dataclass(frozen=True)
class CancelOrderCommand:
    order_id: str
    reason: str = "cancel_order"

    @property
    def kind(self) -> StrategyCommandKind:
        return StrategyCommandKind.CANCEL


@dataclass(frozen=True)
class ReplaceOrderCommand:
    order_id: str
    quantity: float
    reason: str = "replace_order"

    @property
    def kind(self) -> StrategyCommandKind:
        return StrategyCommandKind.REPLACE

    def __post_init__(self) -> None:
        if float(self.quantity) <= 0:
            raise ValueError("replace_order quantity must be positive")


@dataclass(frozen=True)
class ClosePositionCommand:
    product: Any
    quantity: float | None = None
    reason: str = "close_position"

    @property
    def kind(self) -> StrategyCommandKind:
        return StrategyCommandKind.CLOSE

    def __post_init__(self) -> None:
        if self.quantity is not None and float(self.quantity) <= 0:
            raise ValueError("close_position quantity must be positive")


StrategyCommand = (
    SubmitOrderCommand
    | CancelOrderCommand
    | ReplaceOrderCommand
    | ClosePositionCommand
)


def command_payload(command: StrategyCommand) -> dict[str, Any]:
    """Encode a command for a causal SIGNAL event."""

    if isinstance(command, SubmitOrderCommand):
        return {
            "kind": "strategy_runtime_command",
            "command_kind": command.kind.value,
            "product": command.product,
            "quantity": float(command.quantity),
            "side": command.side.value,
            "reason": command.reason,
        }
    if isinstance(command, CancelOrderCommand):
        return {
            "kind": "strategy_runtime_command",
            "command_kind": command.kind.value,
            "order_id": command.order_id,
            "reason": command.reason,
        }
    if isinstance(command, ReplaceOrderCommand):
        return {
            "kind": "strategy_runtime_command",
            "command_kind": command.kind.value,
            "order_id": command.order_id,
            "quantity": float(command.quantity),
            "reason": command.reason,
        }
    return {
        "kind": "strategy_runtime_command",
        "command_kind": command.kind.value,
        "product": command.product,
        "quantity": None if command.quantity is None else float(command.quantity),
        "reason": command.reason,
    }


def command_from_payload(payload: dict[str, Any]) -> StrategyCommand:
    kind = StrategyCommandKind(payload.get("command_kind"))
    if kind is StrategyCommandKind.SUBMIT:
        return SubmitOrderCommand(
            product=payload.get("product"), quantity=payload.get("quantity", 0),
            side=payload.get("side", OrderSide.BUY.value), reason=str(payload.get("reason") or kind.value),
        )
    if kind is StrategyCommandKind.CANCEL:
        return CancelOrderCommand(str(payload.get("order_id") or ""), str(payload.get("reason") or kind.value))
    if kind is StrategyCommandKind.REPLACE:
        return ReplaceOrderCommand(
            str(payload.get("order_id") or ""), payload.get("quantity", 0),
            str(payload.get("reason") or kind.value),
        )
    return ClosePositionCommand(
        product=payload.get("product"), quantity=payload.get("quantity"),
        reason=str(payload.get("reason") or kind.value),
    )
