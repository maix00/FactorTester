"""Small JSON-lines client for the local research-job daemon."""

from __future__ import annotations

import socket
from pathlib import Path
from typing import Any

import orjson

from .paths import normalized_socket_path


class DaemonUnavailable(RuntimeError):
    pass


class JobDaemonClient:
    def __init__(self, socket_path: str | Path, *, timeout: float = 2.0) -> None:
        self.socket_path = str(normalized_socket_path(socket_path))
        self.timeout = max(0.05, float(timeout))

    def request(self, action: str, **payload: Any) -> dict[str, Any]:
        request = orjson.dumps({"action": str(action), **payload}) + b"\n"
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                sock.settimeout(self.timeout)
                sock.connect(self.socket_path)
                sock.sendall(request)
                chunks = bytearray()
                while True:
                    chunk = sock.recv(65536)
                    if not chunk:
                        break
                    chunks.extend(chunk)
                    if b"\n" in chunk:
                        break
        except (FileNotFoundError, ConnectionError, OSError, socket.timeout) as exc:
            raise DaemonUnavailable(f"research job daemon unavailable: {exc}") from exc
        line = bytes(chunks).partition(b"\n")[0]
        if not line:
            raise DaemonUnavailable("research job daemon returned no response")
        response = orjson.loads(line)
        if not isinstance(response, dict):
            raise DaemonUnavailable("research job daemon returned an invalid response")
        if not response.get("success", False):
            raise RuntimeError(str(response.get("error") or "daemon request failed"))
        return response

    def health(self) -> dict[str, Any]:
        return self.request("health")

    def drain(self) -> dict[str, Any]:
        return self.request("drain")

    def resume(self) -> dict[str, Any]:
        return self.request("resume")

    def wake(self) -> None:
        self.request("wake")

    def cancel(self, job_id: str) -> None:
        self.request("cancel", job_id=str(job_id))

    def continue_step(self, job_id: str, command: dict[str, Any]) -> bool:
        return bool(self.request(
            "continue_step", job_id=str(job_id), command=dict(command)
        ).get("continued"))

    def events(self, job_id: str, *, after: int, timeout: float = 15.0) -> dict[str, Any]:
        return self.request(
            "events",
            job_id=str(job_id),
            after=max(0, int(after)),
            timeout=max(0.0, float(timeout)),
        )["snapshot"]
