"""Serialization helpers for order lifecycle audit."""

from __future__ import annotations

from typing import Any

import pandas as pd


def timestamp_key(value: Any) -> str:
    return "" if value is None else pd.Timestamp(value).isoformat()


def float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
