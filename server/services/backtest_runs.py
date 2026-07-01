"""Page-scoped registry for cancellable backtest runs."""

from __future__ import annotations

from dataclasses import dataclass
import threading


@dataclass(frozen=True, slots=True)
class ActiveBacktestRun:
    run_token: str
    page_uuid: str
    owner: str
    cancelled: threading.Event


_lock = threading.Lock()
_runs: dict[str, ActiveBacktestRun] = {}


def register(run_token: str, page_uuid: str, owner: str) -> ActiveBacktestRun:
    run_token = str(run_token).strip()
    page_uuid = str(page_uuid).strip()
    owner = str(owner).strip()
    if not run_token or not page_uuid or not owner:
        raise ValueError("回测运行必须包含 run_token、page_uuid 和 owner")
    run = ActiveBacktestRun(run_token, page_uuid, owner, threading.Event())
    with _lock:
        if run_token in _runs:
            raise ValueError(f"run_token 已在运行: {run_token}")
        _runs[run_token] = run
    return run


def cancel(run_token: str, page_uuid: str, owner: str) -> bool:
    with _lock:
        run = _runs.get(str(run_token))
        if run is None:
            return False
        if run.page_uuid != str(page_uuid) or run.owner != str(owner):
            raise PermissionError("无权取消其他页面或用户的回测")
        run.cancelled.set()
        return True


def finish(run_token: str) -> None:
    with _lock:
        _runs.pop(str(run_token), None)


def cancel_page(page_uuid: str) -> int:
    with _lock:
        matches = [run for run in _runs.values() if run.page_uuid == str(page_uuid)]
        for run in matches:
            run.cancelled.set()
        return len(matches)


def active_count(page_uuid: str | None = None) -> int:
    with _lock:
        if page_uuid is None:
            return len(_runs)
        return sum(run.page_uuid == str(page_uuid) for run in _runs.values())
