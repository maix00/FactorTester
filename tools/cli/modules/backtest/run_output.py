"""Terminal renderer for backtest SSE progress."""

from __future__ import annotations

from typing import Any

import click


EVENT_PHASE = "event_replay"


class BacktestRunRenderer:
    """Render the web backtest progress protocol for terminal users."""

    def __init__(self, *, verbose: bool = False) -> None:
        self.verbose = verbose
        self._manifest_printed = False
        self._current_phase = ""
        self._last_percent: float | None = None
        self._phase_order: list[str] = []
        self._phase_labels: dict[str, str] = {}
        self._phase_flows: dict[str, list[dict[str, Any]]] = {}
        self._phase_progress: dict[str, float] = {}
        self._last_phase_percent: dict[str, float] = {}
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
        if event_name == "activity":
            self._print_activity(data)
            return
        if event_name in {"signal_progress", "progress"}:
            self._print_progress(data)
            return
        if event_name in {"complete", "done"}:
            self._done = True
            click.echo("回测完成")
            return
        if self.verbose:
            click.echo(f"[{event_name}] {data}")

    def _print_manifest(self, data: Any) -> None:
        if self._manifest_printed:
            return
        phases = _extract_phases(data)
        if not phases:
            return
        click.echo("流程图:")
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
                click.echo(f"  {label}:")
                for branch_label, branch_flows in _event_branches(flows):
                    names = [_flow_label(flow) for flow in branch_flows]
                    click.echo(f"    {branch_label}: " + (" -> ".join(names) if names else "（空）"))
            else:
                names = [_flow_label(flow) for flow in flows]
                click.echo(f"  {label}: " + (" -> ".join(names) if names else "（空）"))
        self._print_phase_bars(force=True)
        self._manifest_printed = True

    def _print_runtime_info(self, data: Any) -> None:
        if isinstance(data, dict):
            row_type = data.get("type") or data.get("status") or "运行信息"
            detail = data.get("detail") or data.get("message") or data
            click.echo(f"[运行信息] {row_type}: {detail}")
        elif data:
            click.echo(f"[运行信息] {data}")

    def _print_activity(self, data: Any) -> None:
        if not isinstance(data, dict):
            if data:
                click.echo(f"[activity] {data}")
            return
        phase = str(data.get("phase") or "")
        if phase and phase != self._current_phase:
            self._current_phase = phase
            phase_label = data.get("phase_label") or phase
            click.echo(f"阶段: {phase_label}")
        flow_position = self._advance_activity_phase(data)
        timestamp = str(data.get("timestamp") or "").strip()
        label = str(data.get("message") or data.get("flow_label") or data.get("flow_name") or data.get("label") or "").strip()
        if timestamp or label:
            prefix = f"{timestamp} " if timestamp else ""
            if flow_position and phase != EVENT_PHASE:
                click.echo(f"当前: {prefix}{flow_position} {label}".rstrip())
            else:
                click.echo(f"当前: {prefix}{label}".rstrip())
        if self.verbose:
            flow_key = data.get("flow_key") or ""
            click.echo(f"[activity] phase={phase} flow={flow_key}")

    def _print_progress(self, data: Any) -> None:
        if not isinstance(data, dict):
            if self.verbose and data:
                click.echo(f"[progress] {data}")
            return
        percent = _progress_percent(data)
        if percent is None:
            if self.verbose:
                click.echo(f"[progress] {data}")
            return
        if self._last_percent is not None and abs(percent - self._last_percent) < 0.01 and not self.verbose:
            return
        self._last_percent = percent
        phase = str(data.get("phase") or self._current_phase or EVENT_PHASE)
        if phase:
            self._phase_progress[phase] = percent
        self._print_total_progress()
        self._print_phase_bars()
        if self.verbose:
            click.echo(f"[progress] phase={phase} percent={percent:.2f}")

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
        click.echo(f"总进度: {_bar(percent)} {percent:5.1f}%")

    def _print_phase_bars(self, *, force: bool = False) -> None:
        for key in self._phase_order or sorted(self._phase_progress):
            percent = self._phase_progress.get(key, 0.0)
            last = self._last_phase_percent.get(key)
            if not force and last is not None and abs(percent - last) < 0.01 and not self.verbose:
                continue
            self._last_phase_percent[key] = percent
            label = self._phase_labels.get(key, key)
            click.echo(f"  {label}: {_bar(percent, width=16)} {percent:5.1f}%")

    def _overall_percent(self) -> float:
        if not self._phase_order:
            return self._last_percent or 0.0
        total = sum(self._phase_progress.get(key, 0.0) for key in self._phase_order)
        return max(0.0, min(100.0, total / len(self._phase_order)))


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
