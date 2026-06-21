"""Single-request JSON entrypoint executed inside a framework environment."""

from __future__ import annotations

from contextlib import redirect_stdout
from importlib.metadata import version
import json
import sys

from .contracts import WorkerRequest, WorkerResponse


PACKAGES = {
    "backtrader": "backtrader",
    "qlib": "pyqlib",
    "zipline": "zipline-reloaded",
}


def execute(request: WorkerRequest) -> dict:
    if request.engine not in PACKAGES:
        raise ValueError(f"unknown worker engine: {request.engine}")
    if request.operation == "health":
        operations = ["health", "run_target_weights", "run_group_strategy"]
        return {
            "framework_version": version(PACKAGES[request.engine]),
            "operations": operations,
            "process_isolation": "conda-subprocess",
        }
    if request.operation == "run_target_weights":
        if request.engine == "backtrader":
            from .runners.backtrader import run_target_weights
        elif request.engine == "qlib":
            from .runners.qlib import run_target_weights
        else:
            from .runners.zipline import run_target_weights
        return run_target_weights(request.payload)
    if request.operation == "run_group_strategy":
        if request.engine == "backtrader":
            from .runners.backtrader import run_group_strategy
        elif request.engine == "qlib":
            from .runners.qlib import run_group_strategy
        else:
            from .runners.zipline import run_group_strategy
        return run_group_strategy(request.payload)
    raise ValueError(
        f"operation {request.operation!r} is not implemented for {request.engine}"
    )


def main() -> int:
    raw = sys.stdin.read()
    request_id = "invalid"
    engine = "invalid"
    try:
        request = WorkerRequest.from_dict(json.loads(raw))
        request_id = request.request_id
        engine = request.engine
        # Frameworks may print during execution; stdout is reserved for protocol JSON.
        with redirect_stdout(sys.stderr):
            result = execute(request)
        response = WorkerResponse(request_id, engine, True, result)
    except Exception as exc:
        response = WorkerResponse(
            request_id,
            engine,
            False,
            error=f"{type(exc).__name__}: {exc}",
        )
    sys.stdout.write(json.dumps(response.to_dict(), separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
