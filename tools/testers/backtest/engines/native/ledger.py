"""Ledger identity and LedgerState primitives."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from tools.data.types.base import UniqueNameObject
from tools.testers.backtest.engines.native.guarded_dict import GuardedDict

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
        self.fields = GuardedDict(fields or {}, label=f"LedgerState[{self.ledger.name}].fields")
        self._flow_contract_audit: tuple[Any, object] | None = None

    @property
    def ledger_id(self) -> str:
        return self.ledger.name

    def get(self, ref: "FieldRef", default: Any = None) -> Any:
        return self.fields.get(ref, default)

    def set(self, ref: "FieldRef", value: Any) -> None:
        audit = getattr(self, "_flow_contract_audit", None)
        if audit is not None:
            ctx, token = audit
            ctx.record_external_contract_write(ref, token)
        with self.fields.unguarded_write():
            self.fields[ref] = value

    def set_guarded_writes_enabled(self, enabled: bool) -> None:
        self.fields.set_guarded_writes_enabled(enabled)

    def enter_flow_contract_audit(self, ctx: Any, token: object) -> tuple[Any, object] | None:
        previous = getattr(self, "_flow_contract_audit", None)
        self._flow_contract_audit = (ctx, token)
        return previous

    def restore_flow_contract_audit(self, previous: tuple[Any, object] | None) -> None:
        self._flow_contract_audit = previous


def ledger_identity(value: str | Ledger) -> Ledger:
    if isinstance(value, Ledger):
        return value
    return Ledger(name=str(value))
