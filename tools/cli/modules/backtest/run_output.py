"""Terminal renderer for backtest SSE progress."""

from __future__ import annotations

import shutil
import sys
from typing import Any

import click


EVENT_PHASE = "event_replay"


class BacktestRunRenderer:
    """Render the web backtest progress protocol for terminal users."""

    def __init__(self, *, verbose: bool = False, live: bool = False) -> None:
        self.verbose = verbose
        self.live = live
        self._manifest_printed = False
        self._current_phase = ""
        self._last_percent: float | None = None
        self._overall_progress = 0.0
        self._phase_order: list[str] = []
        self._phase_labels: dict[str, str] = {}
        self._phase_flows: dict[str, list[dict[str, Any]]] = {}
        self._phase_progress: dict[str, float] = {}
        self._last_phase_percent: dict[str, float] = {}
        self._progress_lines: dict[str, str] = {}
        self._last_log_progress_bucket: dict[str, int] = {}
        self._latest_chart_lines: list[str] = []
        self._status_height = 0
        self._done = False

    def handle(self, event_name: str, data: Any) -> None:
        if self._done and event_name not in {"complete", "done"}:
            return
        if event_name == "activity_manifest":
            self._print_manifest(data)
            return
        if event_name == "runtime_info":
            self._print_runtime_info(data)
            return
        if event_name == "result":
            self._print_result(data)
            return
        if event_name == "activity":
            self._print_activity(data)
            return
        if event_name in {"signal_progress", "progress"}:
            self._print_progress(data)
            return
        if event_name in {"complete", "done"}:
            if self._done:
                return
            self._done = True
            self._echo("回测完成")
            return
        if self.verbose:
            self._echo(f"[{event_name}] {data}")

    def _print_result(self, data: Any) -> None:
        if not isinstance(data, dict):
            if data:
                self._echo(f"[result] {data}")
            return
        groups = data.get("groups")
        if not isinstance(groups, list) or not groups:
            return
        series = _result_series(groups)
        if series:
            chart_lines = ["净值曲线:", *_multi_series_chart(series)]
            self._latest_chart_lines = chart_lines
            if self.live:
                self._print_live_chart(chart_lines)
            else:
                for line in chart_lines:
                    self._echo(line)
        self._echo("结果摘要:")
        for name, curve, is_ls in series:
            final_value = curve[-1]
            spark = _sparkline(curve)
            suffix = " · LS" if is_ls else ""
            self._echo(f"  {name}{suffix}: final={final_value:.2f} points={len(curve)} {spark}")

    def _print_manifest(self, data: Any) -> None:
        if self._manifest_printed:
            return
        phases = _extract_phases(data)
        if not phases:
            return
        self._echo("流程图:")
        for phase in phases:
            key = str(phase.get("key") or phase.get("phase") or "")
            label = str(phase.get("label") or key)
            flows = _sorted_flows(phase.get("flows"))
            if key:
                self._phase_order.append(key)
                self._phase_labels[key] = label
                self._phase_flows[key] = flows
                self._phase_progress.setdefault(key, 0.0)
            if key == EVENT_PHASE:
                self._echo(f"  {label}:")
                for branch_label, branch_flows in _event_branches(flows):
                    names = [_flow_label(flow) for flow in branch_flows]
                    self._echo(f"    {branch_label}: " + (" -> ".join(names) if names else "（空）"))
            else:
                names = [_flow_label(flow) for flow in flows]
                self._echo(f"  {label}: " + (" -> ".join(names) if names else "（空）"))
        self._print_phase_bars(force=True)
        self._manifest_printed = True

    def _print_runtime_info(self, data: Any) -> None:
        if isinstance(data, dict):
            row_type = data.get("type") or data.get("status") or "运行信息"
            detail = data.get("detail") or data.get("message") or data
            self._echo(f"[运行信息] {row_type}: {detail}")
        elif data:
            self._echo(f"[运行信息] {data}")

    def _print_activity(self, data: Any) -> None:
        if not isinstance(data, dict):
            if data:
                self._echo(f"[activity] {data}")
            return
        phase = str(data.get("phase") or "")
        if phase == EVENT_PHASE and not self.verbose and not _is_tty():
            return
        if phase and phase != self._current_phase:
            self._current_phase = phase
            phase_label = data.get("phase_label") or phase
            self._echo(f"阶段: {phase_label}")
        flow_position = self._advance_activity_phase(data)
        timestamp = str(data.get("timestamp") or "").strip()
        label = str(data.get("message") or data.get("flow_label") or data.get("flow_name") or data.get("label") or "").strip()
        if timestamp or label:
            prefix = f"{timestamp} " if timestamp else ""
            if flow_position and phase != EVENT_PHASE:
                self._echo(f"当前: {prefix}{flow_position} {label}".rstrip())
            else:
                self._echo(f"当前: {prefix}{label}".rstrip())
        if self.verbose:
            flow_key = data.get("flow_key") or ""
            self._echo(f"[activity] phase={phase} flow={flow_key}")

    def _print_progress(self, data: Any) -> None:
        if not isinstance(data, dict):
            if self.verbose and data:
                self._echo(f"[progress] {data}")
            return
        percent = _progress_percent(data)
        if percent is None:
            if self.verbose:
                self._echo(f"[progress] {data}")
            return
        if self._last_percent is not None and abs(percent - self._last_percent) < 0.01 and not self.verbose:
            return
        self._last_percent = percent
        phase = str(data.get("phase") or self._current_phase or EVENT_PHASE)
        if phase == "done" and percent >= 100:
            self._overall_progress = 100.0
            for key in self._phase_order:
                self._phase_progress[key] = 100.0
            self._print_total_progress()
            self._print_phase_bars()
            if self.verbose:
                self._echo(f"[progress] phase={phase} percent={percent:.2f}")
            return
        has_completed_total = "completed" in data and "total" in data
        if has_completed_total and phase == EVENT_PHASE:
            self._phase_progress[phase] = percent
            self._overall_progress = max(self._overall_progress, min(90.0, 10.0 + percent * 0.8))
        else:
            self._overall_progress = max(self._overall_progress, percent)
            if phase == EVENT_PHASE:
                event_percent = (percent - 10.0) / 80.0 * 100.0
                self._phase_progress[phase] = max(self._phase_progress.get(phase, 0.0), max(0.0, min(100.0, event_percent)))
        self._print_total_progress()
        self._print_phase_bars()
        if self.verbose:
            self._echo(f"[progress] phase={phase} percent={percent:.2f}")

    def _advance_activity_phase(self, data: dict[str, Any]) -> str:
        phase = str(data.get("phase") or "")
        if not phase or phase == EVENT_PHASE:
            return ""
        flow_key = str(data.get("flow_key") or "")
        flows = self._phase_flows.get(phase) or []
        if not flows:
            self._phase_progress[phase] = max(self._phase_progress.get(phase, 0.0), 100.0)
            self._print_phase_bars()
            return ""
        for index, flow in enumerate(flows, start=1):
            if str(flow.get("flow_key") or "") == flow_key:
                self._phase_progress[phase] = max(self._phase_progress.get(phase, 0.0), index / len(flows) * 100.0)
                self._print_phase_bars()
                return f"{index}/{len(flows)}"
        return ""

    def _print_total_progress(self) -> None:
        percent = self._overall_percent()
        self._update_progress_line("total", f"总进度: {_bar(percent)} {percent:5.1f}%")

    def _print_phase_bars(self, *, force: bool = False) -> None:
        for key in self._phase_order or sorted(self._phase_progress):
            percent = self._phase_progress.get(key, 0.0)
            last = self._last_phase_percent.get(key)
            if not force and last is not None and abs(percent - last) < 0.01 and not self.verbose:
                continue
            self._last_phase_percent[key] = percent
            label = self._phase_labels.get(key, key)
            self._update_progress_line(key, f"  {label}: {_bar(percent, width=16)} {percent:5.1f}%")

    def _overall_percent(self) -> float:
        return max(0.0, min(100.0, self._overall_progress))

    def _print_live_chart(self, lines: list[str]) -> None:
        if _is_tty():
            self._latest_chart_lines = lines
            self._render_status_region()
            return
        # Non-TTY logs and tests must remain readable and append-only.
        self._echo("[live] 刷新净值曲线")
        for line in lines:
            self._echo(line)

    def _update_progress_line(self, key: str, line: str) -> None:
        if not _is_tty():
            if not self.verbose and not self._should_log_progress(key):
                return
            click.echo(line)
            return
        self._progress_lines[key] = line
        self._render_status_region()

    def _should_log_progress(self, key: str) -> bool:
        percent = self._phase_progress.get(key, self._overall_percent() if key == "total" else 0.0)
        if key != "total" and key != EVENT_PHASE:
            return True
        bucket = int(percent // 5)
        previous = self._last_log_progress_bucket.get(key)
        if previous == bucket:
            return False
        self._last_log_progress_bucket[key] = bucket
        return True

    def _echo(self, message: str) -> None:
        if _is_tty() and self._status_height:
            self._clear_status_region(for_redraw=False)
            click.echo(message)
            self._render_status_region()
            return
        click.echo(message)

    def _status_lines(self) -> list[str]:
        lines: list[str] = []
        if "total" in self._progress_lines:
            lines.append(self._progress_lines["total"])
        for key in self._phase_order:
            if key in self._progress_lines:
                lines.append(self._progress_lines[key])
        for key, line in self._progress_lines.items():
            if key != "total" and key not in self._phase_order:
                lines.append(line)
        if self.live and self._latest_chart_lines:
            if lines:
                lines.append("")
            lines.extend(self._latest_chart_lines)
        return lines

    def _render_status_region(self) -> None:
        if not _is_tty():
            return
        self._clear_status_region(for_redraw=True)
        lines = self._status_lines()
        width = _terminal_width()
        for line in lines:
            click.echo("\x1b[2K" + line[:width])
        self._status_height = len(lines)

    def _clear_status_region(self, *, for_redraw: bool) -> None:
        if not self._status_height:
            return
        height = self._status_height
        click.echo(f"\x1b[{self._status_height}F", nl=False)
        for _ in range(height):
            click.echo("\x1b[2K")
        if for_redraw:
            click.echo(f"\x1b[{height}F", nl=False)
        self._status_height = 0


def _extract_phases(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, dict):
        phases = data.get("phases")
    else:
        phases = data
    if not isinstance(phases, list):
        return []
    return [phase for phase in phases if isinstance(phase, dict)]


def _sorted_flows(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    flows = [flow for flow in value if isinstance(flow, dict)]
    return sorted(flows, key=lambda flow: float(flow.get("display_order") or 0))


def _flow_label(flow: dict[str, Any]) -> str:
    return str(flow.get("flow_label") or flow.get("flow_name") or flow.get("flow_key") or "")


def _event_branches(flows: list[dict[str, Any]]) -> list[tuple[str, list[dict[str, Any]]]]:
    signal: list[dict[str, Any]] = []
    notice: list[dict[str, Any]] = []
    order: list[dict[str, Any]] = []
    for flow in flows:
        kind = str(flow.get("event_kind") or "").upper()
        if kind == "ORDER":
            order.append(flow)
        elif kind == "ORDER_NOTICE":
            notice.append(flow)
        else:
            signal.append(flow)
    return [("信号产单", signal), ("通知产单", notice), ("订单处理", order)]


def _progress_percent(data: dict[str, Any]) -> float | None:
    value = data.get("percent")
    if value is not None:
        try:
            return max(0.0, min(100.0, float(value)))
        except (TypeError, ValueError):
            return None
    try:
        completed = float(data.get("completed") or 0)
        total = float(data.get("total") or 0)
    except (TypeError, ValueError):
        return None
    if total <= 0:
        return None
    return max(0.0, min(100.0, completed / total * 100.0))


def _bar(percent: float, *, width: int = 24) -> str:
    filled = int(round(width * percent / 100.0))
    filled = max(0, min(width, filled))
    return "[" + "#" * filled + "-" * (width - filled) + "]"


def _numeric_series(value: Any) -> list[float]:
    if not isinstance(value, list):
        return []
    series: list[float] = []
    for item in value:
        try:
            series.append(float(item))
        except (TypeError, ValueError):
            continue
    return series


def _result_series(groups: list[Any]) -> list[tuple[str, list[float], bool]]:
    series: list[tuple[str, list[float], bool]] = []
    for index, group in enumerate(groups, start=1):
        if not isinstance(group, dict):
            continue
        name = str(group.get("name") or group.get("key") or group.get("group_id") or f"strategy-{index}")
        curve = _numeric_series(group.get("total_equity"))
        if curve:
            series.append((name, curve, bool(group.get("is_ls"))))
    return series


def _multi_series_chart(series: list[tuple[str, list[float], bool]], *, width: int = 48, height: int = 10) -> list[str]:
    if not series:
        return []
    symbols = ["●", "◆", "▲", "■", "◇", "○", "△", "□", "×", "+"]
    colors = ["cyan", "magenta", "green", "yellow", "blue", "red", "bright_cyan", "bright_magenta", "bright_green", "bright_yellow"]
    sampled = [(name, _downsample(curve, width), is_ls) for name, curve, is_ls in series if curve]
    values = [value for _, curve, _ in sampled for value in curve]
    if not values:
        return []
    lo = min(values)
    hi = max(values)
    if hi <= lo:
        hi = lo + 1.0
    grid: list[list[tuple[str, str] | None]] = [[None for _ in range(width)] for _ in range(height)]
    for series_index, (_name, curve, _is_ls) in enumerate(sampled):
        symbol = symbols[series_index % len(symbols)]
        color = colors[series_index % len(colors)]
        for col, value in enumerate(curve[:width]):
            row = int(round((hi - value) / (hi - lo) * (height - 1)))
            row = max(0, min(height - 1, row))
            grid[row][col] = ("*", "white") if grid[row][col] is not None else (symbol, color)
    lines: list[str] = []
    for row_index, row in enumerate(grid):
        if row_index == 0:
            label = f"{hi:>12.2f} ┤"
        elif row_index == height - 1:
            label = f"{lo:>12.2f} ┤"
        else:
            label = " " * 12 + " │"
        body = "".join(_colored(cell) if cell is not None else " " for cell in row)
        lines.append(label + body)
    lines.append(" " * 13 + "└" + "─" * width)
    legend_parts = []
    for index, (name, _curve, is_ls) in enumerate(sampled):
        symbol = symbols[index % len(symbols)]
        color = colors[index % len(colors)]
        suffix = " LS" if is_ls else ""
        legend_parts.append(f"{_colored((symbol, color))} {name}{suffix}")
    lines.append("图例: " + "  ".join(legend_parts))
    return lines


def _colored(cell: tuple[str, str]) -> str:
    symbol, color = cell
    return click.style(symbol, fg=color)


def _is_tty() -> bool:
    return bool(getattr(sys.stdout, "isatty", lambda: False)())


def _terminal_width() -> int:
    return max(40, shutil.get_terminal_size(fallback=(120, 24)).columns)


def _sparkline(values: list[float], *, width: int = 32) -> str:
    if not values:
        return ""
    if len(values) > width:
        values = _downsample(values, width)
    blocks = "▁▂▃▄▅▆▇█"
    lo = min(values)
    hi = max(values)
    if hi <= lo:
        return blocks[0] * len(values)
    scale = (len(blocks) - 1) / (hi - lo)
    return "".join(blocks[int(round((value - lo) * scale))] for value in values)


def _downsample(values: list[float], width: int) -> list[float]:
    if width <= 0 or len(values) <= width:
        return values
    if width == 1:
        return [values[-1]]
    sampled: list[float] = []
    last = len(values) - 1
    for index in range(width):
        source_index = round(index * last / (width - 1))
        sampled.append(values[source_index])
    return sampled
