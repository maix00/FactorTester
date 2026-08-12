"""Orthogonal market-data dimensions shared by availability providers."""

from __future__ import annotations

from typing import Any

from tools.data.types import DataFreq


SAMPLING_MODES = frozenset({"bar", "event", "snapshot"})
DATA_KINDS = frozenset({"ohlcv_bar", "trade", "quote", "order_book"})
MARKET_DEPTHS = frozenset({"not_applicable", "l1", "l2", "full_depth"})
DELIVERY_MODES = frozenset({
    "historical_snapshot",
    "live_stream",
    "delayed_stream",
})


def availability_dimensions(
    *,
    sampling_mode: str,
    frequency: Any | None,
    data_kind: str,
    market_depth: str,
    delivery_mode: str,
) -> dict[str, str | None]:
    """Validate and serialize independent sampling, time, content and delivery."""
    _require_member("sampling_mode", sampling_mode, SAMPLING_MODES)
    _require_member("data_kind", data_kind, DATA_KINDS)
    _require_member("market_depth", market_depth, MARKET_DEPTHS)
    _require_member("delivery_mode", delivery_mode, DELIVERY_MODES)

    normalized_frequency = (
        None if frequency is None else DataFreq(frequency).name
    )
    if sampling_mode == "bar" and normalized_frequency is None:
        raise ValueError("bar availability requires a temporal frequency")
    if data_kind == "ohlcv_bar" and (
        sampling_mode != "bar" or market_depth != "not_applicable"
    ):
        raise ValueError(
            "ohlcv_bar availability requires bar sampling and no market depth"
        )
    if data_kind == "order_book" and market_depth == "not_applicable":
        raise ValueError("order_book availability requires a market depth")

    return {
        "sampling_mode": sampling_mode,
        "frequency": normalized_frequency,
        "data_kind": data_kind,
        "market_depth": market_depth,
        "delivery_mode": delivery_mode,
    }


def _require_member(name: str, value: str, allowed: frozenset[str]) -> None:
    if value not in allowed:
        raise ValueError(f"invalid availability {name}: {value}")
