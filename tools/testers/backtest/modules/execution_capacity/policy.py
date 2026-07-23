"""Resolve matching and bar-capacity policy without silent fallback."""

from __future__ import annotations

from typing import Any


def effective_matching_model(config: Any, matching_ref: Any, liquidity_ref: Any) -> str:
    matching = str(config.get(matching_ref, "auto") or "auto")
    liquidity = str(config.get(liquidity_ref, "infinite") or "infinite")
    if matching == "auto":
        return "bar_volume_limited" if liquidity == "volume_participation" else "next_bar_full_fill"
    if matching == "next_bar_full_fill" and liquidity != "infinite":
        raise ValueError(
            "matching_model='next_bar_full_fill' conflicts with "
            "liquidity_mode='volume_participation'; use matching_model='auto' "
            "or 'bar_volume_limited'"
        )
    if matching == "bar_volume_limited" and liquidity != "volume_participation":
        raise ValueError(
            "matching_model='bar_volume_limited' requires "
            "liquidity_mode='volume_participation'"
        )
    if matching not in {"next_bar_full_fill", "bar_volume_limited"}:
        raise ValueError(f"unknown matching_model: {matching!r}")
    return matching
