"""Shared formatting helpers for passive report SVGs."""

from __future__ import annotations

from datetime import datetime, timezone
import math
import re
from typing import Any

from matplotlib.ticker import FuncFormatter, PercentFormatter


PLOT_RC = {
    "font.family": "sans-serif",
    # Debian's fonts-noto-cjk registers the shared CJK faces under language
    # suffixes, and the release image ends up with the JP faces only, so the
    # JP/TC/KR names must be listed too or every Chinese chart title falls back
    # to DejaVu Sans and renders as tofu boxes.
    "font.sans-serif": [
        "Noto Sans CJK SC", "Noto Sans CJK TC", "Noto Sans CJK JP",
        "Noto Sans CJK KR",
        "PingFang SC", "Microsoft YaHei",
        "Arial Unicode MS", "DejaVu Sans",
    ],
    "svg.fonttype": "none",
    "svg.hashsalt": "factortester-report-v1",
}

PERCENT_METRICS = {
    "annual_return", "max_drawdown", "drawdown", "rolling_volatility_60",
}


def passive_svg(value: bytes) -> bytes:
    """Strip XML/DTD metadata so native clients can load passive SVG safely."""
    text = value.decode("utf-8")
    start = text.find("<svg")
    if start < 0:
        return b""
    text = text[start:]
    text = re.sub(r"\s*<metadata>.*?</metadata>\s*", "\n", text, flags=re.DOTALL)
    return text.encode("utf-8")


def date_values(values: list[Any]) -> list[datetime] | None:
    if not values:
        return None
    parsed = [_datetime(value) for value in values]
    return None if any(value is None for value in parsed) else parsed  # type: ignore[return-value]


def value_formatter(kind: str, currency: str) -> FuncFormatter | PercentFormatter:
    if kind == "percent":
        return PercentFormatter(xmax=1.0, decimals=1)
    return FuncFormatter(lambda value, _position: format_value(value, kind, currency))


def format_value(value: float, kind: str, currency: str) -> str:
    if kind == "currency":
        prefix = (currency or "CNY").upper()
        magnitude = abs(value)
        if magnitude >= 1_000_000_000:
            return f"{prefix} {value / 1_000_000_000:.2f}B"
        if magnitude >= 1_000_000:
            return f"{prefix} {value / 1_000_000:.2f}M"
        if magnitude >= 1_000:
            return f"{prefix} {value / 1_000:.1f}K"
        return f"{prefix} {value:,.2f}"
    if kind == "percent":
        return f"{value * 100:.2f}%"
    if not math.isfinite(value):
        return ""
    return f"{value:.4g}"


def _datetime(value: Any) -> datetime | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        number = float(value)
        if abs(number) < 100_000_000:
            return None
        if abs(number) > 20_000_000_000:
            number /= 1_000.0
        try:
            return datetime.fromtimestamp(number, timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=parsed.tzinfo or timezone.utc)
