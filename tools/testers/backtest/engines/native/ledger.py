"""Ledger identity and LedgerState primitives."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from tools.data.types.base import UniqueNameObject

if TYPE_CHECKING:
    from tools.testers.backtest.engines.native.fields import FieldRef
    from tools.testers.backtest.engines.native.strategy import Strategy


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


def ledger_identity(value: str | Ledger) -> Ledger:
    if isinstance(value, Ledger):
        return value
    return Ledger(name=str(value))
