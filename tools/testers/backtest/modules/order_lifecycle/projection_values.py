"""JSON-safe enum and timestamp conversion."""

from __future__ import annotations


def enum_values(values: dict) -> dict:
    return timestamp_values({
        key: getattr(value, "value", value)
        for key, value in values.items()
    })


def timestamp_values(values: dict) -> dict:
    return {
        key: timestamp_text(value) if key in {
            "timestamp", "submitted_at", "market_timestamp",
        } else value
        for key, value in values.items()
    }


def timestamp_text(value) -> str | None:
    return value.isoformat() if hasattr(value, "isoformat") else (
        None if value is None else str(value)
    )
