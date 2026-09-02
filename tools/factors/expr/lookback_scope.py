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

    def to_latex(self, subst: dict | None = None) -> str:
        return f"\\operatorname{{Scope{self.kind.title()}}}"


@dataclass(frozen=True)
class BarCountScope(LookbackScope):
    count: FactorExpr
    kind: str = "bars"

    def resolve(self, *args: Any, **kwargs: Any) -> BarCountScope:
        return BarCountScope(self.count.resolve(*args, **kwargs))

    def resolved_count(
        self,
        *,
        ctx: Any | None = None,
        source_freq: Any | None = None,
        products: Any = (),
    ) -> int:
        if not isinstance(self.count, ConstExpr):
            raise TypeError("bar-search scope must resolve to a constant bar count")
        value = self.count.value
        if isinstance(value, bool):
            raise ValueError("bar-search scope requires a positive bar count or duration")
        if isinstance(value, int):
            count = value
        else:
            frequency = source_freq if ctx is None else ctx.freq
            scope_products = products if ctx is None else ctx.products
            if frequency is None:
                raise ValueError("duration bar-search scope requires a source frequency")
            from .rolling import _resolve_windows
            common, count, _ = _resolve_windows(value, frequency, scope_products)
            if not common:
                raise ValueError(
                    "bar-search duration must resolve to one common bar count "
                    "for all selected products"
                )
        if count <= 0:
            raise ValueError("bar-search scope requires a positive bar count or duration")
        return int(count)

    def resolve_for_streaming(self, source_freq: Any, products: Any) -> BarCountScope:
        return BarCountScope(ConstExpr(self.resolved_count(
            source_freq=source_freq,
            products=products,
        )))

    def structural_key(self) -> tuple[Any, ...]:
        return (type(self).__name__, self.kind, self.count._structural_key())

    def to_latex(self, subst: dict | None = None) -> str:
        return (
            "\\operatorname{ScopeBars}"
            f"\\left({self.count._to_latex(subst)}\\right)"
        )


@dataclass(frozen=True)
class SessionScope(LookbackScope):
    gap: str = "3h"
    kind: str = "session"

    def structural_key(self) -> tuple[Any, ...]:
        return (type(self).__name__, self.kind, self.gap)

    def to_latex(self, subst: dict | None = None) -> str:
        return (
            "\\operatorname{ScopeSession}"
            f"\\left(\\mathrm{{{self.gap}}}\\right)"
        )


@dataclass(frozen=True)
class TradingDayScope(LookbackScope):
    kind: str = "trading_day"

    def to_latex(self, subst: dict | None = None) -> str:
        return "\\operatorname{ScopeTradingDay}"


def scope_bars(count: Any) -> BarCountScope:
    return BarCountScope(_to_expr(count))


def scope_session(*, gap: str = "3h") -> SessionScope:
    return SessionScope(gap=gap)


def scope_trading_day() -> TradingDayScope:
    return TradingDayScope()
