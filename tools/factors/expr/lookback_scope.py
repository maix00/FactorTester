"""Declarative boundaries for bar-search expressions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .core import FactorExpr
from .leaf import ConstExpr, _to_expr


class LookbackScope:
    """Value object describing where a bar search may look."""

    kind: str

    def resolve(self, *args: Any, **kwargs: Any) -> LookbackScope:
        return self

    def structural_key(self) -> tuple[Any, ...]:
        return (type(self).__name__, self.kind)


@dataclass(frozen=True)
class BarCountScope(LookbackScope):
    count: FactorExpr
    kind: str = "bars"

    def resolve(self, *args: Any, **kwargs: Any) -> BarCountScope:
        return BarCountScope(self.count.resolve(*args, **kwargs))

    def resolved_count(self) -> int:
        if not isinstance(self.count, ConstExpr):
            raise TypeError("bar-search scope must resolve to a constant bar count")
        value = int(self.count.value)
        if value <= 0 or value != self.count.value:
            raise ValueError("bar-search scope requires a positive integer bar count")
        return value

    def structural_key(self) -> tuple[Any, ...]:
        return (type(self).__name__, self.kind, self.count._structural_key())


@dataclass(frozen=True)
class SessionScope(LookbackScope):
    gap: str = "3h"
    kind: str = "session"

    def structural_key(self) -> tuple[Any, ...]:
        return (type(self).__name__, self.kind, self.gap)


@dataclass(frozen=True)
class TradingDayScope(LookbackScope):
    kind: str = "trading_day"


def bars(count: Any) -> BarCountScope:
    return BarCountScope(_to_expr(count))


def session(*, gap: str = "3h") -> SessionScope:
    return SessionScope(gap=gap)


def trading_day() -> TradingDayScope:
    return TradingDayScope()

