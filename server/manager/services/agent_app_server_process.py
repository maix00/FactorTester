"""Thread-safe JSONL process bridge for one Codex app-server instance."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any, Callable, Mapping


class AgentAppServerProcessError(RuntimeError):
    """The app-server process cannot accept or complete a request."""


class AgentAppServerProcess:
    """Own a single app-server subprocess and its JSON-RPC event stream."""

    def __init__(
        self,
        *,
        command: list[str],
        cwd: str | Path,
        environment: Mapping[str, str],
        event_limit: int = 500,
        event_observer: Callable[[Mapping[str, Any]], None] | None = None,
    ) -> None:
        if not command:
            raise AgentAppServerProcessError("app-server command is required")
        self.command = [str(item) for item in command]
        self.cwd = str(Path(cwd).expanduser().resolve())
        self.environment = {str(key): str(value) for key, value in environment.items()}
        self.event_limit = max(20, int(event_limit))
        self.event_observer = event_observer
        self._process: subprocess.Popen[bytes] | None = None
        self._reader: threading.Thread | None = None
        self._stderr_reader: threading.Thread | None = None
        self._write_lock = threading.Lock()
        self._condition = threading.Condition()
        self._responses: dict[int, dict[str, Any]] = {}
        self._events: deque[dict[str, Any]] = deque(maxlen=self.event_limit)
        self._stderr: deque[str] = deque(maxlen=40)
        self._next_id = 1
        self._sequence = 0

    @property
    def process(self) -> subprocess.Popen[bytes] | None:
        return self._process

    def is_running(self) -> bool:
        process = self._process
        return process is not None and process.poll() is None

    def start(self) -> None:
        if self.is_running():
            return
        try:
            process = subprocess.Popen(
                self.command,
                cwd=self.cwd,
                env=self.environment,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
            )
        except OSError as exc:
            raise AgentAppServerProcessError("could not start app-server") from exc
        self._process = process
        self._reader = threading.Thread(
            target=self._read_stdout,
            name="factor-manager-agent-app-server",
            daemon=True,
        )
        self._stderr_reader = threading.Thread(
            target=self._read_stderr,
            name="factor-manager-agent-app-server-stderr",
            daemon=True,
        )
        self._reader.start()
        self._stderr_reader.start()

    def _append_event(self, payload: dict[str, Any]) -> None:
        with self._condition:
            self._sequence += 1
            self._events.append({
                "sequence": self._sequence,
                "payload": payload,
            })
            self._condition.notify_all()
        if self.event_observer is not None:
            try:
                self.event_observer(payload)
            except Exception:
                # Runtime telemetry must never interrupt the JSONL reader.
                pass

    def _read_stdout(self) -> None:
        process = self._process
        stream = process.stdout if process is not None else None
        if stream is None:
            return
        while True:
            line = stream.readline()
            if not line:
                break
            try:
                payload = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            if not isinstance(payload, dict):
                continue
            identifier = payload.get("id")
            if isinstance(identifier, int) and (
                "result" in payload or "error" in payload
            ):
                with self._condition:
                    self._responses[identifier] = payload
                    self._condition.notify_all()
            else:
                self._append_event(payload)
        returncode = process.poll() if process is not None else None
        self._append_event({
            "type": "app_server_exit",
            "returncode": returncode,
        })

    def _read_stderr(self) -> None:
        process = self._process
        stream = process.stderr if process is not None else None
        if stream is None:
            return
        for line in iter(stream.readline, b""):
            try:
                value = line.decode("utf-8", errors="replace").rstrip()
            except AttributeError:
                value = str(line).rstrip()
            if value:
                with self._condition:
                    self._stderr.append(value)

    def _send(self, payload: Mapping[str, Any]) -> None:
        process = self._process
        if process is None or process.stdin is None or not self.is_running():
            raise AgentAppServerProcessError("app-server is not running")
        raw = (json.dumps(dict(payload), ensure_ascii=False) + "\n").encode("utf-8")
        try:
            with self._write_lock:
                process.stdin.write(raw)
                process.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise AgentAppServerProcessError("app-server input is unavailable") from exc

    def notify(self, method: str, params: Mapping[str, Any] | None = None) -> None:
        self._send({
            "jsonrpc": "2.0",
            "method": str(method),
            "params": dict(params or {}),
        })

    def request(
        self,
        method: str,
        params: Mapping[str, Any] | None = None,
        *,
        timeout: float = 20.0,
    ) -> dict[str, Any]:
        with self._condition:
            identifier = self._next_id
            self._next_id += 1
        return self.request_with_id(
            identifier,
            method,
            params,
            timeout=timeout,
        )

    def request_with_id(
        self,
        identifier: int,
        method: str,
        params: Mapping[str, Any] | None = None,
        *,
        timeout: float = 20.0,
    ) -> dict[str, Any]:
        with self._condition:
            if int(identifier) >= self._next_id:
                self._next_id = int(identifier) + 1
        self._send({
            "jsonrpc": "2.0",
            "id": int(identifier),
            "method": str(method),
            "params": dict(params or {}),
        })
        deadline = time.monotonic() + max(0.1, float(timeout))
        with self._condition:
            while identifier not in self._responses:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise AgentAppServerProcessError(
                        f"app-server request timed out: {method}"
                    )
                self._condition.wait(timeout=remaining)
        return self._take_response(identifier)

    def _take_response(self, identifier: int) -> dict[str, Any]:
        with self._condition:
            response = self._responses.pop(identifier, None)
        if response is None:
            raise AgentAppServerProcessError("app-server response disappeared")
        return response

    def events(self, after: int = 0) -> list[dict[str, Any]]:
        with self._condition:
            return [
                dict(item)
                for item in self._events
                if int(item["sequence"]) > int(after)
            ]

    def wait_for_events(self, after: int = 0, timeout: float = 20.0) -> list[dict[str, Any]]:
        deadline = time.monotonic() + max(0.1, float(timeout))
        with self._condition:
            while not any(
                int(item["sequence"]) > int(after) for item in self._events
            ):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._condition.wait(timeout=remaining)
            return [
                dict(item)
                for item in self._events
                if int(item["sequence"]) > int(after)
            ]

    def status(self) -> dict[str, Any]:
        process = self._process
        with self._condition:
            stderr_tail = list(self._stderr)[-10:]
            sequence = self._sequence
        return {
            "running": self.is_running(),
            "pid": process.pid if process is not None else None,
            "returncode": process.poll() if process is not None else None,
            "event_sequence": sequence,
            "stderr_tail": stderr_tail,
        }

    def stop(self, *, timeout: float = 5.0) -> None:
        process = self._process
        if process is None:
            return
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=max(0.1, float(timeout)))
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=max(0.1, float(timeout)))
            except ProcessLookupError:
                pass
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is not None:
                try:
                    stream.close()
                except OSError:
                    pass
        with self._condition:
            self._condition.notify_all()
        self._process = None
