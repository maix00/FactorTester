"""Public historical trading-rule protocols; no platform or provider imports."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class TradingFieldValue(Protocol):
    """Fields consumed from one source-owned historical lookup result."""

    value: Any
    approximated: bool
    provider: str
    source_key: str
    effective_trading_day: Any
    effective_timestamp: Any


@runtime_checkable
class TradingFieldProvider(Protocol):
    """Minimal source-owned historical-field lookup contract."""

    def resolve_at(self, *args: Any, **kwargs: Any) -> Any: ...


__all__ = ["TradingFieldProvider", "TradingFieldValue"]
