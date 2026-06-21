"""Launch one isolated conda process per framework request."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

from .contracts import WorkerRequest, WorkerResponse


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
            completed = subprocess.run(
                command,
                cwd=REPO_ROOT,
                input=json.dumps(request.to_dict()),
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
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
