"""Runtime configuration helpers for backtest execution."""

from __future__ import annotations

from typing import Any
import uuid


RENDERER_EVENT_NAMES = {
    "activity_manifest",
    "runtime_info",
    "progress",
    "activity",
    "signal_progress",
    "result",
    "complete",
    "done",
}


def equity_curve_live_enabled(store) -> bool:
    curve_mode = store.effective("equity_curve_mode")
    if curve_mode is not None:
        return str(curve_mode).strip().lower() == "live"
    return truthy(store.effective("equity_compute_live"))


def configure_step_mode_payload(run_payload: dict[str, Any], *, step_mode: bool) -> str:
    if step_mode:
        run_token = uuid.uuid4().hex
        run_payload["run_token"] = run_token
        run_payload["step_mode"] = True
        return run_token
    return str(run_payload.get("run_token") or "")


def stream_error_message(data: Any) -> str:
    message = data.get("error") if isinstance(data, dict) else data
    traceback_text = str(data.get("traceback") or "").strip() if isinstance(data, dict) else ""
    if traceback_text:
        message = f"{message}\n{traceback_text}"
    return str(message)


def is_renderer_event(event_name: str) -> bool:
    return event_name in RENDERER_EVENT_NAMES


def truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"true", "1", "yes", "y", "on", "live"}
