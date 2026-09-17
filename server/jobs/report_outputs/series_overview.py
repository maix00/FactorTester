"""Render the factor-series result area as PNG panels with a real time axis.

One figure per time window: the traded product's K线, every factor layer the
run computed, 成交量 and (when present) 持仓量.  PNG keeps the mounted report
assets small, and a real time axis is readable where a bar index is not.
"""

from __future__ import annotations

import math
from typing import Any

import pandas as pd

PALETTE = {
    "price_up": "#18a572", "price_down": "#e14d5b",
    "volume": "#8aa4c8", "interest": "#d97706",
    "layer": "#1f6feb", "signal": "#d1564b",
}


def _axis_time(value: Any) -> pd.Timestamp | None:
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        number = float(value)
        if abs(number) > 1e11:
            number /= 1000.0
        try:
            return pd.Timestamp(number, unit="s", tz="UTC").tz_convert("Asia/Shanghai")
        except (ValueError, OSError):
            return None
    try:
        stamp = pd.Timestamp(str(value))
    except (ValueError, TypeError):
        return None
    return stamp.tz_convert("Asia/Shanghai") if stamp.tz else stamp.tz_localize("UTC").tz_convert("Asia/Shanghai")


def _market_frame(bars: list[dict[str, Any]]) -> pd.DataFrame:
    rows = []
    for bar in bars:
        stamp = _axis_time(bar.get("time") or bar.get("timestamp"))
        if stamp is None:
            continue
        rows.append({
            "time": stamp,
            "open": _float(bar.get("open")), "high": _float(bar.get("high")),
            "low": _float(bar.get("low")), "close": _float(bar.get("close")),
            "volume": _float(bar.get("volume")) or 0.0,
            "open_interest": _float(bar.get("open_interest")),
        })
    frame = pd.DataFrame(rows)
    return frame.dropna(subset=["time"]).sort_values("time") if not frame.empty else frame


def _layer_frame(item: dict[str, Any]) -> pd.DataFrame:
    dates = item.get("dates") or []
    values = item.get("values") or []
    rows = []
    for index, value in enumerate(values):
        stamp = _axis_time(dates[index]) if index < len(dates) else None
        if stamp is None or not isinstance(value, (int, float)) or isinstance(value, bool):
            continue
        rows.append({"time": stamp, "value": float(value)})
    frame = pd.DataFrame(rows)
    return frame.dropna().sort_values("time") if not frame.empty else frame


def _float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _downsample(frame: pd.DataFrame, maximum: int) -> pd.DataFrame:
    if frame.empty or len(frame) <= maximum:
        return frame
    step = max(1, math.ceil(len(frame) / maximum))
    return frame.iloc[::step]


def _intraday_slice(frame: pd.DataFrame, days: int = 3) -> pd.DataFrame:
    if frame.empty:
        return frame
    sessions = sorted({stamp.date() for stamp in frame["time"]})
    if len(sessions) <= days:
        return frame
    keep = set(sessions[-days:])
    return frame[frame["time"].dt.date.isin(keep)]


def _hourly(frame: pd.DataFrame, value: str) -> pd.DataFrame:
    """Resample to one hour while keeping every column the panels need."""
    if frame.empty:
        return frame
    indexed = frame.set_index("time")
    if value == "value":
        aggregated = indexed["value"].resample("1h").last()
        return aggregated.dropna().reset_index()
    keep = [column for column in indexed.columns if column != "volume"]
    aggregated = indexed[keep].resample("1h").last()
    if "volume" in indexed.columns:
        aggregated["volume"] = indexed["volume"].resample("1h").sum()
    return aggregated.dropna(how="all").reset_index()


def available_windows(payload: dict[str, Any]) -> list[str]:
    """Which windows make sense for this result: full always, intraday/hourly only intraday."""
    frames = [
        _layer_frame(item) for item in (payload.get("series") or [])
        if isinstance(item, dict)
    ]
    frames = [frame for frame in frames if not frame.empty]
    markets = [
        _market_frame([bar for bar in (item.get("bars") or []) if isinstance(bar, dict)])
        for item in (payload.get("market") or []) if isinstance(item, dict)
    ]
    frames.extend(frame for frame in markets if not frame.empty)
    if not frames:
        return []
    windows = ["full"]
    intraday = False
    for frame in frames:
        sessions = {stamp.date() for stamp in frame["time"]}
        if len(sessions) > 3 and len(frame) > len(sessions) * 1.5:
            intraday = True
            break
    if intraday:
        windows.extend(["intraday", "hourly"])
    return windows


def overview_panels(
    payload: dict[str, Any], *, window: str, maximum_points: int = 2000,
) -> list[tuple[str, str, pd.DataFrame]]:
    """Return ``(kind, title, frame)`` for every panel the WINDOW draws, in order.

    The renderer and its tests share this one source of truth, so a test can
    assert exactly the panel titles a reader sees.
    """
    markets = [
        item for item in (payload.get("market") or [])
        if isinstance(item, dict) and item.get("bars")
    ]
    market = markets[0] if markets else {}
    # The payload carries the whole range thinned plus the native-resolution tail;
    # the intraday window is the only one that wants the fine bars.
    key = "recent_bars" if window == "intraday" and market.get("recent_bars") else "bars"
    price = _market_frame([bar for bar in (market.get(key) or []) if isinstance(bar, dict)])
    layers = []
    for item in payload.get("series") or []:
        if not isinstance(item, dict):
            continue
        frame = _layer_frame(item)
        if frame.empty:
            continue
        layers.append((str(item.get("layer") or "因子值"), frame))

    if window == "intraday":
        price = _intraday_slice(price)
        layers = [(name, _intraday_slice(frame)) for name, frame in layers]
        if price.empty and market.get("bars"):
            price = _intraday_slice(_market_frame(market["bars"]))
    elif window == "hourly":
        price = _hourly(price, "close") if not price.empty else price
        layers = [(name, _hourly(frame, "value")) for name, frame in layers]
    else:
        price = _downsample(price, maximum_points)
        layers = [(name, _downsample(frame, maximum_points)) for name, frame in layers]

    panels: list[tuple[str, str, pd.DataFrame]] = []
    if not price.empty:
        panels.append(("price", f"{market.get('product') or 'product'} K线（{market.get('freq') or ''}）", price))
    for name, frame in layers:
        if not frame.empty:
            panels.append(("layer", f"因子层 · {name}", frame))
    if not price.empty:
        if "volume" in price.columns:
            panels.append(("volume", "成交量", price))
        if "open_interest" in price.columns and price["open_interest"].notna().any():
            panels.append(("interest", "持仓量", price))
    return panels


def panel_titles(payload: dict[str, Any], *, window: str) -> list[str]:
    return [title for _kind, title, _frame in overview_panels(payload, window=window)]


def render_overview_png(payload: dict[str, Any], *, window: str, maximum_points: int = 2000) -> bytes:
    """Return one PNG panel stack for the requested window ('full'/'intraday'/'hourly')."""
    panels = overview_panels(payload, window=window, maximum_points=maximum_points)
    if not panels:
        return b""
    markets = [
        item for item in (payload.get("market") or [])
        if isinstance(item, dict) and item.get("bars")
    ]
    market = markets[0] if markets else {}

    import matplotlib
    matplotlib.use("Agg")
    from io import BytesIO

    from matplotlib import pyplot as plt
    from matplotlib import rc_context

    from .plot_format import PLOT_RC

    height = 1.6 + 1.5 * len(panels)
    with rc_context(PLOT_RC):
        figure, axes = plt.subplots(len(panels), 1, figsize=(10.0, height), squeeze=False)
        for row, (kind, title, frame) in enumerate(panels):
            axis = axes[row][0]
            if kind == "price":
                _candles(axis, frame)
            elif kind == "layer":
                axis.plot(frame["time"], frame["value"], linewidth=0.6, color=PALETTE["layer"])
            elif kind == "volume":
                axis.bar(frame["time"], frame["volume"], width=_bar_width(frame),
                         color=PALETTE["volume"])
            elif kind == "interest":
                axis.plot(frame["time"], frame["open_interest"], linewidth=0.7,
                          color=PALETTE["interest"])
            axis.set_title(title, fontsize=9)
            _axis(axis, frame["time"], window)
        label = {"full": "全时段", "intraday": "最近交易日日内", "hourly": "小时级"}.get(window, window)
        figure.suptitle(
            f"{market.get('product') or ''} 因子值序列与行情 · {label}".strip(), fontsize=11,
        )
        figure.tight_layout(rect=(0, 0, 1, 0.985))
        buffer = BytesIO()
        figure.savefig(buffer, format="png", dpi=110)
        plt.close(figure)
    return buffer.getvalue()


def _candles(axis, price: pd.DataFrame) -> None:
    width = _bar_width(price)
    rising = price["close"] >= price["open"]
    axis.vlines(price["time"], price["low"], price["high"], linewidth=0.4,
                color=[PALETTE["price_up"] if up else PALETTE["price_down"] for up in rising])
    axis.bar(price["time"], (price["close"] - price["open"]).abs().clip(lower=1e-9),
             bottom=price[["open", "close"]].min(axis=1), width=width,
             color=[PALETTE["price_up"] if up else PALETTE["price_down"] for up in rising],
             linewidth=0)


def _bar_width(price: pd.DataFrame) -> float:
    if len(price) < 2:
        return 0.0005
    span = (price["time"].iloc[-1] - price["time"].iloc[0]).total_seconds()
    return max(1e-6, span / max(1, len(price)) / 86400.0 * 0.8)


def _axis(axis, times, window: str) -> None:
    axis.grid(alpha=0.25)
    axis.tick_params(labelsize=7)
    if window == "intraday" and len(times) > 1:
        axis.xaxis.set_major_formatter(_hour_formatter())


def _hour_formatter():
    from matplotlib.dates import DateFormatter
    return DateFormatter("%H:%M")
