"""Canonical scalar and collection normalization for IC authoring."""

from __future__ import annotations

from typing import Any


def required_texts(values: Any, field_name: str) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise ValueError(f"{field_name} must be a list")
    result = tuple(sorted({str(item or "").strip() for item in values}))
    if not result or "" in result:
        raise ValueError(f"{field_name} requires non-empty values")
    return result


def entry_delays(values: Any) -> tuple[int, ...]:
    if not isinstance(values, (list, tuple)):
        raise ValueError("entry_delay_bars must be a list")
    result: set[int] = set()
    for value in values:
        if isinstance(value, bool):
            raise ValueError("entry_delay_bars requires non-negative integers")
        delay = int(value)
        if delay < 0 or delay != value:
            raise ValueError("entry_delay_bars requires non-negative integers")
        result.add(delay)
    if not result:
        raise ValueError("entry_delay_bars requires at least one value")
    return tuple(sorted(result))


__all__ = ["entry_delays", "required_texts"]
