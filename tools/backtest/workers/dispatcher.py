"""Launch one isolated conda process per framework request."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import threading
import time
from collections.abc import Callable

from .contracts import WorkerRequest, WorkerResponse
from ..cancellation import BacktestCancelled


REPO_ROOT = Path(__file__).resolve().parents[3]


class WorkerExecutionError(RuntimeError):
    pass


class EngineWorkerDispatcher:
    def __init__(self, environments: dict[str, str] | None = None) -> None:
        self.environments = environments or {
            "backtrader": "GTHT-backtrader",
            "qlib": "GTHT-qlib",
            "zipline": "GTHT-zipline",
        }

    def dispatch(
        self,
        request: WorkerRequest,
        *,
        timeout_seconds: float = 120.0,
        progress: Callable[[dict], None] | None = None,
        cancel_event: threading.Event | None = None,
    ) -> WorkerResponse:
        try:
            environment = self.environments[request.engine]
        except KeyError as exc:
            raise WorkerExecutionError(f"no worker registered for {request.engine}") from exc
        command = [
            "conda", "run", "--no-capture-output", "-n", environment,
            "python", "-m", "tools.backtest.workers.entrypoint",
        ]
        try:
            completed = (
                self._run_streaming(
                    command,
                    json.dumps(request.to_dict()),
                    timeout_seconds,
                    progress,
                    cancel_event,
                )
                if progress is not None or cancel_event is not None
                else subprocess.run(
                    command,
                    cwd=REPO_ROOT,
                    input=json.dumps(request.to_dict()),
                    capture_output=True,
                    text=True,
                    timeout=timeout_seconds,
                    check=False,
                )
            )
        except subprocess.TimeoutExpired as exc:
            raise WorkerExecutionError(
                f"{request.engine} worker timed out after {timeout_seconds:g}s"
            ) from exc
        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip()
            raise WorkerExecutionError(
                f"{request.engine} worker exited with {completed.returncode}: {detail}"
            )
        try:
            response = WorkerResponse.from_dict(json.loads(completed.stdout))
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            raise WorkerExecutionError(
                f"{request.engine} worker returned an invalid response"
            ) from exc
        if response.request_id != request.request_id or response.engine != request.engine:
            raise WorkerExecutionError("worker response identity does not match request")
        if not response.success:
            raise WorkerExecutionError(response.error or "worker failed without an error")
        return response

    @staticmethod
    def _run_streaming(command, request_json, timeout_seconds, progress, cancel_event):
        process = subprocess.Popen(
            command,
            cwd=REPO_ROOT,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        stdout_parts: list[str] = []
        stderr_parts: list[str] = []

        def _read_stdout() -> None:
            assert process.stdout is not None
            stdout_parts.append(process.stdout.read())

        def _read_stderr() -> None:
            assert process.stderr is not None
            for line in process.stderr:
                if line.startswith("GTHT_PROGRESS "):
                    try:
                        if progress is not None:
                            progress(json.loads(line[len("GTHT_PROGRESS "):]))
                    except (json.JSONDecodeError, TypeError, ValueError):
                        stderr_parts.append(line)
                else:
                    stderr_parts.append(line)

        stdout_thread = threading.Thread(target=_read_stdout, daemon=True)
        stderr_thread = threading.Thread(target=_read_stderr, daemon=True)
        stdout_thread.start()
        stderr_thread.start()
        assert process.stdin is not None
        process.stdin.write(request_json)
        process.stdin.close()
        deadline = time.monotonic() + timeout_seconds
        while process.poll() is None:
            if cancel_event is not None and cancel_event.is_set():
                process.terminate()
                try:
                    process.wait(timeout=3.0)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                stdout_thread.join(timeout=1.0)
                stderr_thread.join(timeout=1.0)
                raise BacktestCancelled()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                process.kill()
                process.wait()
                raise subprocess.TimeoutExpired(command, timeout_seconds)
            try:
                process.wait(timeout=min(0.1, remaining))
            except subprocess.TimeoutExpired:
                continue
        returncode = int(process.returncode or 0)
        stdout_thread.join()
        stderr_thread.join()
        return subprocess.CompletedProcess(
            command,
            returncode,
            "".join(stdout_parts),
            "".join(stderr_parts),
        )
