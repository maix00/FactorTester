"""Unix-socket server owned by the dedicated research scheduler process."""

from __future__ import annotations

import os
import socketserver
from pathlib import Path
from typing import Any

import orjson

from server.jobs.scheduling import ResearchJobScheduler

from .paths import normalized_socket_path


class _Handler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        raw = self.rfile.readline(4 * 1024 * 1024)
        try:
            request = orjson.loads(raw)
            response = self.server.dispatch(request)  # type: ignore[attr-defined]
            payload = {"success": True, **response}
        except Exception as exc:
            payload = {"success": False, "error": str(exc)}
        self.wfile.write(orjson.dumps(payload) + b"\n")


class _UnixServer(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True

    def __init__(self, socket_path: str, scheduler: ResearchJobScheduler) -> None:
        self.scheduler = scheduler
        super().__init__(socket_path, _Handler)

    def dispatch(self, request: dict[str, Any]) -> dict[str, Any]:
        action = str(request.get("action") or "")
        if action == "health":
            return {
                "deployment_id": self.scheduler.deployment_id,
                "planner_workers": self.scheduler.planners.worker_snapshot(),
                "execution_workers": self.scheduler.executors.worker_snapshot(),
            }
        if action == "wake":
            self.scheduler.tick()
            return {}
        if action == "cancel":
            job_id = str(request.get("job_id") or "")
            notified = self.scheduler.planners.request_cancel(job_id)
            notified = self.scheduler.executors.request_cancel(job_id) or notified
            return {"notified": notified}
        if action == "events":
            job_id = str(request.get("job_id") or "")
            if not job_id:
                raise ValueError("job_id is required")
            return {
                "snapshot": self.scheduler.broker.wait(
                    job_id,
                    after=max(0, int(request.get("after") or 0)),
                    timeout=min(30.0, max(0.0, float(request.get("timeout") or 0.0))),
                )
            }
        raise ValueError(f"unsupported daemon action: {action}")


class JobDaemonServer:
    def __init__(self, *, socket_path: str | Path, scheduler: ResearchJobScheduler) -> None:
        self.socket_path = normalized_socket_path(socket_path)
        self.socket_path.parent.mkdir(parents=True, exist_ok=True)
        if self.socket_path.exists():
            self.socket_path.unlink()
        self.scheduler = scheduler
        self.server = _UnixServer(str(self.socket_path), scheduler)

    def serve_forever(self) -> None:
        self.scheduler.start()
        try:
            self.server.serve_forever(poll_interval=0.2)
        finally:
            self.close()

    def close(self) -> None:
        self.server.server_close()
        self.scheduler.stop()
        try:
            os.unlink(self.socket_path)
        except FileNotFoundError:
            pass
