"""Publication-quality static SVG rendering for report time series."""

from __future__ import annotations

import io
import math
from typing import Any

from matplotlib import dates as mdates, rc_context
from matplotlib.backends.backend_svg import FigureCanvasSVG
from matplotlib.figure import Figure

from server.jobs.report_outputs.plot_format import (
    PERCENT_METRICS,
    PLOT_RC,
    date_values,
    format_value,
    passive_svg,
    value_formatter,
)


def render_series_svg(
    title: str,
    series: list[dict[str, Any]],
    *,
    value_kind: str = "number",
    currency: str = "",
    reference_value: float | None = None,
    reference_label: str = "",
) -> bytes:
    with rc_context(PLOT_RC):
        return _render_series_svg(
            title, series, value_kind=value_kind, currency=currency,
            reference_value=reference_value, reference_label=reference_label,
        )


def render_metrics_svg(title: str, series: list[dict[str, Any]]) -> bytes:
    metrics = list(dict.fromkeys(
        str(item.get("metric") or "") for item in series if item.get("metric")
    ))
    if not metrics:
        return b""
    with rc_context(PLOT_RC):
        figure = Figure(
            figsize=(10.4, max(3.0, len(metrics) * 2.35)),
            dpi=100,
            layout="constrained",
        )
        canvas = FigureCanvasSVG(figure)
        axes = figure.subplots(len(metrics), 1, squeeze=False).ravel()
        figure.suptitle(title, x=0.01, ha="left", fontsize=16, fontweight="semibold")
        for axis, metric in zip(axes, metrics):
            items = [item for item in series if item.get("metric") == metric]
            _draw_metric_axis(axis, metric, items)
        output = io.BytesIO()
        canvas.print_svg(output, metadata={"Date": None})
        return passive_svg(output.getvalue())


def render_holding_half_life_svg(
    title: str,
    rows: list[dict[str, Any]],
) -> bytes:
    """Plot oriented forward-horizon IC and its fitted holding decay.

    The x-axis is the actual forward-horizon duration in hours.  Each panel is
    one factor/entry-delay pair.  A panel is still useful when the fit is not
    estimable: points and an explicit status are shown, with no invented
    curve.  This renderer is called only for the explicit on-demand output.
    """

    if not rows:
        return b""
    with rc_context(PLOT_RC):
        figure = Figure(
            figsize=(10.4, max(3.2, len(rows) * 3.0)),
            dpi=100,
            layout="constrained",
        )
        canvas = FigureCanvasSVG(figure)
        axes = figure.subplots(len(rows), 1, squeeze=False).ravel()
        figure.suptitle(title, x=0.01, ha="left", fontsize=16, fontweight="semibold")
        for axis, row in zip(axes, rows):
            points = [item for item in row.get("points") or () if isinstance(item, dict)]
            x_values = [float(item["horizon_seconds"]) / 3600.0 for item in points]
            y_values = [float(item["oriented_mean_ic"]) for item in points]
            if x_values and y_values:
                axis.scatter(x_values, y_values, color="#2563eb", s=26, zorder=3)
                for x_value, y_value, item in zip(x_values, y_values, points):
                    axis.annotate(
                        str(item.get("horizon") or ""),
                        (x_value, y_value),
                        xytext=(4, 4), textcoords="offset points", fontsize=7,
                        color="#4b5563",
                    )
                baseline = y_values[0]
                axis.axhline(
                    baseline / 2.0, color="#94a3b8", linestyle="--",
                    linewidth=0.9, label="基准 IC 的一半",
                )
            slope = row.get("exponential_log_decay_slope_per_second")
            intercept = row.get("exponential_log_decay_intercept")
            if x_values and slope is not None and intercept is not None:
                slope_value = float(slope)
                intercept_value = float(intercept)
                if slope_value < 0:
                    x_min, x_max = min(x_values), max(x_values)
                    grid = [x_min + (x_max - x_min) * index / 100.0 for index in range(101)]
                    direction = float(row.get("expected_direction") or 1)
                    curve = [direction * math.exp(intercept_value + slope_value * value * 3600.0) for value in grid]
                    axis.plot(grid, curve, color="#dc2626", linewidth=1.35, label="指数衰减拟合")
            factor_alias = str(row.get("factor_alias") or "")
            delay = row.get("entry_delay_bars")
            status = str(row.get("exponential_status") or "not_estimable")
            half_life = row.get("exponential_half_life_seconds")
            status_text = f"指数拟合: {status}"
            if half_life is not None:
                status_text += f"；半衰期={float(half_life) / 3600.0:g}h"
            crossing = row.get("crossing_half_life_seconds")
            if crossing is not None:
                status_text += f"；网格交叉={float(crossing) / 3600.0:g}h"
            axis.set_title(f"{factor_alias} · entry_delay={delay} · {status_text}", loc="left", fontsize=10, fontweight="semibold", pad=8)
            axis.set_xlabel("forward holding horizon (hours)")
            axis.set_ylabel("expected-sign × mean IC")
            axis.set_facecolor("#ffffff")
            axis.grid(axis="y", color="#e5e7eb", linewidth=0.8)
            axis.spines[["top", "right", "left"]].set_visible(False)
            axis.tick_params(axis="both", colors="#4b5563", labelsize=8)
            axis.margins(x=0.05, y=0.15)
            if axis.get_legend_handles_labels()[0]:
                axis.legend(loc="best", frameon=False, fontsize=7)
        output = io.BytesIO()
        canvas.print_svg(output, metadata={"Date": None})
        return passive_svg(output.getvalue())


def _draw_metric_axis(axis: Any, metric: str, items: list[dict[str, Any]]) -> None:
    label = str(items[0].get("metric_label") or metric) if items else metric
    axis.set_title(label, loc="left", fontsize=11, fontweight="semibold", pad=8)
    axis.set_facecolor("#ffffff")
    axis.grid(axis="y", color="#e5e7eb", linewidth=0.8)
    axis.spines[["top", "right", "left"]].set_visible(False)
    axis.tick_params(axis="both", colors="#4b5563", labelsize=8)
    uses_dates = False
    for item in items[:6]:
        values = [float(value) for value in item.get("values") or ()]
        timestamps = list(item.get("timestamps") or ())[:len(values)]
        dates = date_values(timestamps)
        x_values: list[Any] = dates if dates is not None else list(range(len(values)))
        uses_dates = uses_dates or dates is not None
        axis.plot(x_values, values, linewidth=1.35, label=str(item.get("label") or "")[:120])
    if uses_dates:
        locator = mdates.AutoDateLocator(minticks=3, maxticks=6)
        axis.xaxis.set_major_locator(locator)
        axis.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))
    axis.yaxis.set_major_formatter(
        value_formatter("percent" if metric in PERCENT_METRICS else "number", "")
    )
    axis.margins(x=0.01, y=0.12)
    if len(items) > 1:
        axis.legend(loc="best", frameon=False, fontsize=7)


def _render_series_svg(
    title: str,
    series: list[dict[str, Any]],
    *,
    value_kind: str,
    currency: str,
    reference_value: float | None,
    reference_label: str,
) -> bytes:
    values = [float(value) for item in series for value in item["values"]]
    if not values:
        return b""
    figure = Figure(figsize=(10.4, 5.2), dpi=100, layout="constrained")
    canvas = FigureCanvasSVG(figure)
    axis = figure.subplots()
    axis.set_title(title, loc="left", fontsize=16, fontweight="semibold", pad=14)
    axis.set_facecolor("#ffffff")
    figure.patch.set_facecolor("#ffffff")
    axis.grid(axis="y", color="#e5e7eb", linewidth=0.8)
    axis.spines[["top", "right", "left"]].set_visible(False)
    axis.tick_params(axis="both", colors="#4b5563", labelsize=9)

    uses_dates = False
    for item in series[:6]:
        item_values = [float(value) for value in item.get("values") or ()]
        timestamps = list(item.get("timestamps") or ())
        dates = date_values(timestamps[:len(item_values)])
        x_values: list[Any]
        if dates is not None and len(dates) == len(item_values):
            x_values = dates
            uses_dates = True
        else:
            x_values = list(range(len(item_values)))
        axis.plot(
            x_values, item_values, linewidth=1.55,
            label=str(item.get("label") or "")[:120],
        )

    if uses_dates:
        locator = mdates.AutoDateLocator(minticks=4, maxticks=7)
        axis.xaxis.set_major_locator(locator)
        axis.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))
    axis.yaxis.set_major_formatter(value_formatter(value_kind, currency))
    if value_kind == "number" and min(values) < 0 < max(values):
        axis.axhline(0.0, color="#9ca3af", linewidth=0.9, linestyle="--")
    if reference_value is not None and min(values) <= reference_value <= max(values):
        axis.axhline(reference_value, color="#6b7280", linewidth=1.0, linestyle="--")
        label = reference_label or "参考值"
        axis.annotate(
            f"{label} {format_value(reference_value, value_kind, currency)}",
            xy=(1.0, reference_value), xycoords=("axes fraction", "data"),
            xytext=(-4, 5), textcoords="offset points", ha="right",
            color="#4b5563", fontsize=9,
        )
    axis.margins(x=0.01, y=0.08)
    if len(series) > 1:
        axis.legend(
            loc="upper center", bbox_to_anchor=(0.5, -0.15), ncol=2,
            frameon=False, fontsize=8, handlelength=2.4,
        )
    output = io.BytesIO()
    canvas.print_svg(output, metadata={"Date": None})
    return passive_svg(output.getvalue())
