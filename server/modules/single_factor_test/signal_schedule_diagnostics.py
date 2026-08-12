"""Compact, read-only evidence about a factor's emitted signal schedule."""

from __future__ import annotations

import hashlib
import json
from typing import Any

import pandas as pd

from tools.data.types import finest_index


def policy_for_factor(factor: Any) -> dict[str, Any]:
    """Project the bound factor-family scheduling policy into JSON values."""

    family = getattr(factor, "family", None)
    signal_frequency = getattr(factor, "signal_freq", None)
    if signal_frequency is None:
        signal_frequency = getattr(getattr(factor, "freq", None), "name", None)
    elif hasattr(signal_frequency, "name"):
        signal_frequency = signal_frequency.name
    gap = getattr(family, "end_session_gap", None)
    return {
        "signal_frequency": str(signal_frequency) if signal_frequency is not None else None,
        "basepoint": _json_policy_value(getattr(family, "basepoint", None)),
        "daily_basepoint": _json_policy_value(
            getattr(family, "daily_basepoint", None)
        ),
        "end_session_skip": getattr(family, "end_session_skip", None),
        "end_session_gap": str(gap) if gap is not None else None,
    }


def summarize_signal_schedule(
    raw: pd.Series,
    scheduled: pd.Series,
    *,
    policy: dict[str, Any],
    max_gap_samples: int = 3,
) -> dict[str, Any]:
    """Describe schedule identity without returning the underlying observations.

    This is deliberately evidence about the already-computed batch result.  It
    does not claim that incremental/live evaluation emits an equivalent stream.
    """

    raw = raw.dropna()
    scheduled = scheduled.dropna()
    raw_index = _datetime_index(raw)
    scheduled_index = _datetime_index(scheduled)
    gap_threshold = _duration_seconds(policy.get("end_session_gap"))

    return {
        "policy": dict(policy),
        "raw_observation_count": int(len(raw)),
        "scheduled_observation_count": int(len(scheduled)),
        "scheduled_timestamp_hash": _hash_json(
            [_timestamp_text(value) for value in scheduled_index]
        ),
        "scheduled_value_hash": _hash_json(
            [_stable_scalar(value) for value in scheduled.to_numpy()]
        ),
        "first_scheduled_timestamp": (
            _timestamp_text(scheduled_index[0]) if len(scheduled_index) else None
        ),
        "last_scheduled_timestamp": (
            _timestamp_text(scheduled_index[-1]) if len(scheduled_index) else None
        ),
        "boundary_basis": "elapsed_gap_only",
        "trading_day_mapping_status": "not_bound",
        "incremental_equivalence_status": "not_evaluated",
        "session_gap_samples": _gap_samples(
            raw_index,
            minimum_gap_seconds=gap_threshold,
            limit=max_gap_samples,
        ),
    }


def _datetime_index(series: pd.Series) -> pd.DatetimeIndex:
    index = finest_index(series.index) if isinstance(series.index, pd.MultiIndex) else series.index
    return pd.DatetimeIndex(index)


def _gap_samples(
    index: pd.DatetimeIndex,
    *,
    minimum_gap_seconds: float | None,
    limit: int,
) -> list[dict[str, Any]]:
    if minimum_gap_seconds is None or limit <= 0:
        return []
    samples: list[dict[str, Any]] = []
    for previous, current in zip(index[:-1], index[1:]):
        gap_seconds = float((current - previous).total_seconds())
        if gap_seconds <= minimum_gap_seconds:
            continue
        samples.append({
            "previous_timestamp": _timestamp_text(previous),
            "next_timestamp": _timestamp_text(current),
            "gap_seconds": gap_seconds,
        })
        if len(samples) >= limit:
            break
    return samples


def _duration_seconds(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(pd.Timedelta(value).total_seconds())
    except (TypeError, ValueError):
        return None


def _timestamp_text(value: Any) -> str:
    return pd.Timestamp(value).isoformat()


def _stable_scalar(value: Any) -> Any:
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float):
        return value.hex()
    if isinstance(value, (str, int, bool)) or value is None:
        return value
    return str(value)


def _hash_json(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _json_policy_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if callable(value):
        return getattr(value, "__qualname__", getattr(value, "__name__", str(value)))
    return str(value)
