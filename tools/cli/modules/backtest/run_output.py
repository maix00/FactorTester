"""Terminal renderer for backtest SSE progress."""

from __future__ import annotations

import contextlib
import io
import shutil
import sys
import time
from typing import Any

import click

from tools.cli.table import display_width, pad_display, truncate_display


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
        self._activity_line = ""
        self._mode_line = ""
        self._last_mode_line = ""
        self._latest_chart_lines: list[str] = []
        self._status_height = 0
        self._done = False
        self._last_event_activity_log_at: float | None = None
        self._event_activity_log_interval = 2.0
        self._activity_typewriter_delay = 0.006
        self.last_result: dict[str, Any] = {}
        self._runtime_info_seen: set[tuple[str, str]] = set()

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
        self.last_result = dict(data)
        groups = data.get("groups")
        if not isinstance(groups, list) or not groups:
            return
        series = _result_series(groups)
        if series:
            chart_lines = ["净值曲线:", *_multi_series_chart(series, width=_chart_body_width())]
            self._latest_chart_lines = chart_lines
            if self.live:
                self._print_live_chart(chart_lines)
            else:
                for line in chart_lines:
                    self._echo(line)
        self._echo("结果摘要:")
        summary_rows = [
            (f"{name} · LS" if is_ls else name, curve[0], curve[-1], len(curve))
            for name, curve, is_ls in series
        ]
        name_width = max((display_width(row[0]) for row in summary_rows), default=0)
        final_width = max((len(f"{row[2]:.2f}") for row in summary_rows), default=0)
        return_width = max((display_width(_return_text(row[1], row[2])) for row in summary_rows), default=0)
        points_width = max((len(str(row[3])) for row in summary_rows), default=0)
        self._echo(
            f"  {pad_display('策略', name_width)}  "
            f"{'最终权益':>{final_width}}  "
            f"{pad_display('收益率', return_width, align='right')}  "
            f"{'点数':>{points_width}}"
        )
        for display_name, start_value, final_value, point_count in summary_rows:
            self._echo(
                f"  {pad_display(display_name, name_width)}  "
                f"{final_value:>{final_width}.2f}  "
                f"{pad_display(_return_text(start_value, final_value), return_width, align='right')}  "
                f"{point_count:>{points_width}}"
            )

    def _print_manifest(self, data: Any) -> None:
        if self._manifest_printed:
            return
        phases = _extract_phases(data)
        if not phases:
            return
        for phase in phases:
            key = str(phase.get("key") or phase.get("phase") or "")
            label = str(phase.get("label") or key)
            flows = _sorted_flows(phase.get("flows"))
            if key:
                self._phase_order.append(key)
                self._phase_labels[key] = label
                self._phase_flows[key] = flows
                self._phase_progress.setdefault(key, 0.0)
        self._print_phase_bars(force=True)
        self._manifest_printed = True

    def _print_runtime_info(self, data: Any) -> None:
        if isinstance(data, dict):
            code = str(data.get("code") or "")
            aggregation_key = str(data.get("aggregation_key") or "")
            if not aggregation_key:
                row = data.get("row")
                if isinstance(row, dict):
                    aggregation_key = str(row.get("aggregation_key") or "")
                    code = code or str(row.get("code") or "")
            if code and aggregation_key:
                dedupe_key = (code, aggregation_key)
                if dedupe_key in self._runtime_info_seen:
                    return
                self._runtime_info_seen.add(dedupe_key)
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
        should_log_activity = True
        if phase == EVENT_PHASE:
            should_log_activity = self._should_log_event_activity()
        if phase and phase != self._current_phase:
            self._current_phase = phase
            phase_label = data.get("phase_label") or phase
            self._echo(f"阶段: {phase_label}")
        flow_position = self._advance_activity_phase(data)
        timestamp = str(data.get("timestamp") or "").strip()
        label = str(data.get("message") or data.get("flow_label") or data.get("flow_name") or data.get("label") or "").strip()
        if timestamp or label:
            prefix = f"{timestamp} " if timestamp else ""
            phase_label = str(data.get("phase_label") or self._phase_labels.get(phase, phase) or "").strip()
            phase_prefix = f"{phase_label} · " if phase_label else ""
            activity_text = ""
            if flow_position and phase != EVENT_PHASE:
                activity_text = f"当前: {phase_prefix}{prefix}{flow_position} {label}".rstrip()
            else:
                activity_text = f"当前: {phase_prefix}{prefix}{label}".rstrip()
            if self.verbose and data.get("flow_key"):
                activity_text = f"{activity_text} · {data.get('flow_key')}"
            if should_log_activity:
                self._update_activity_line(activity_text)
        mode_line = _format_mode_info(data.get("mode_info"))
        if mode_line and mode_line != self._last_mode_line:
            self._last_mode_line = mode_line
            self._update_mode_line(mode_line, log_when_not_tty=should_log_activity)
        if self.verbose:
            flow_key = data.get("flow_key") or ""
            if not _is_tty() and should_log_activity:
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
        if self._last_percent is not None and abs(percent - self._last_percent) < 0.01:
            return
        self._last_percent = percent
        phase = str(data.get("phase") or self._current_phase or EVENT_PHASE)
        if phase == "done" and percent >= 100:
            self._overall_progress = 100.0
            for key in self._phase_order:
                self._phase_progress[key] = 100.0
            self._print_total_progress()
            self._print_phase_bars()
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
            if not force and last is not None and abs(percent - last) < 0.01:
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
            if not self._should_log_progress(key):
                return
            click.echo(line)
            return
        self._progress_lines[key] = line
        self._render_status_region()

    def _update_activity_line(self, line: str) -> None:
        if not _is_tty():
            self._echo(line)
            return
        previous = self._activity_line
        if previous and line.startswith(previous):
            self._type_activity_line(line, start=len(previous))
            return
        if len(line) <= 24:
            self._activity_line = line
            self._render_status_region()
            return
        self._activity_line = ""
        for index in range(1, len(line) + 1):
            self._activity_line = line[:index]
            self._render_status_region()
            time.sleep(self._activity_typewriter_delay)

    def _type_activity_line(self, line: str, *, start: int) -> None:
        for index in range(start + 1, len(line) + 1):
            self._activity_line = line[:index]
            self._render_status_region()
            time.sleep(self._activity_typewriter_delay)
        self._activity_line = line
        self._render_status_region()

    def _update_mode_line(self, line: str, *, log_when_not_tty: bool) -> None:
        if not _is_tty():
            if log_when_not_tty:
                self._echo(line)
            return
        self._mode_line = line
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

    def _should_log_event_activity(self) -> bool:
        now = time.monotonic()
        if self._last_event_activity_log_at is None:
            self._last_event_activity_log_at = now
            return True
        if now - self._last_event_activity_log_at < self._event_activity_log_interval:
            return False
        self._last_event_activity_log_at = now
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
        if self._activity_line:
            lines.append(self._activity_line)
        if self._mode_line:
            lines.append(self._mode_line)
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
            _write_tty_line("\x1b[2K" + line[:width])
            sys.stdout.write("\n")
        sys.stdout.flush()
        self._status_height = len(lines)

    def _clear_status_region(self, *, for_redraw: bool) -> None:
        if not self._status_height:
            return
        height = self._status_height
        sys.stdout.write(f"\x1b[{height}F")
        for index in range(height):
            sys.stdout.write("\r\x1b[2K")
            if index < height - 1:
                sys.stdout.write("\x1b[1B")
        if height > 1:
            sys.stdout.write(f"\x1b[{height - 1}F")
        sys.stdout.write("\r")
        sys.stdout.flush()
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


def _multi_series_chart(
    series: list[tuple[str, list[float], bool]],
    *,
    width: int = 48,
    height: int = 18,
    title: str = "净值曲线",
    ylabel: str = "权益",
) -> list[str]:
    if not series:
        return []
    plotext_lines = _plotext_chart(series, width=width, height=height, title=title, ylabel=ylabel)
    if plotext_lines:
        return plotext_lines
    symbols = list("123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ")
    rows = [(f"{name} LS" if is_ls else name, curve[-1], curve) for name, curve, is_ls in series if curve]
    if not rows:
        return []
    max_name_width = 24
    name_width = min(max_name_width, max(display_width(row[0]) for row in rows))
    final_width = max(len(f"{row[1]:.2f}") for row in rows)
    spark_width = max(12, min(width, _terminal_width() - name_width - final_width - 16))
    lines = ["图例: 每行一条策略曲线，避免终端字符重叠"]
    for index, (name, final_value, curve) in enumerate(rows):
        symbol = symbols[index % len(symbols)]
        display_name = _truncate(name, name_width)
        spark = _sparkline(curve, width=spark_width)
        lines.append(f"  {symbol} {pad_display(display_name, name_width)}  {spark}  末值 {final_value:>{final_width}.2f}")
    return lines


def _plotext_chart(series: list[tuple[str, list[float], bool]], *, width: int, height: int, title: str, ylabel: str) -> list[str]:
    try:
        import plotext as plt  # type: ignore[import-not-found, import-untyped]
    except Exception:
        return []
    buffer = io.StringIO()
    try:
        plt.clear_figure()
        plt.plotsize(width, height)
        plt.title(title)
        plt.xlabel("样本点")
        plt.ylabel(ylabel)
        for name, curve, is_ls in series:
            label = f"{name} LS" if is_ls else name
            plt.plot(list(range(len(curve))), curve, label=label)
        with contextlib.redirect_stdout(buffer):
            plt.show()
        lines = [line.rstrip() for line in buffer.getvalue().splitlines() if line.strip()]
        return lines
    except Exception:
        return []
    finally:
        with contextlib.suppress(Exception):
            plt.clear_figure()


def _return_text(start_value: float, final_value: float) -> str:
    if start_value == 0:
        return "n/a"
    return f"{(final_value / start_value - 1.0) * 100:.2f}%"


def _format_mode_info(value: Any) -> str:
    if not isinstance(value, dict) or not value:
        return ""
    items: list[str] = []
    for key in sorted(value):
        raw = value.get(key)
        if raw in (None, ""):
            continue
        text = str(raw)
        if len(text) > 24:
            text = text[:21] + "..."
        items.append(f"{key}={text}")
    if not items:
        return ""
    width = max(24, _terminal_width() - 8)
    return truncate_display("模式: " + " · ".join(items), width)


def _is_tty() -> bool:
    return bool(getattr(sys.stdout, "isatty", lambda: False)())


def _terminal_width() -> int:
    return max(40, shutil.get_terminal_size(fallback=(120, 24)).columns)


def _chart_body_width() -> int:
    return max(24, min(80, _terminal_width() - 16))


def _truncate(value: str, width: int) -> str:
    return truncate_display(value, width)


def _write_tty_line(text: str) -> None:
    sys.stdout.write(text)


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
