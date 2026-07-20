"""Single-request JSON entrypoint executed inside a framework environment."""

from __future__ import annotations

from contextlib import redirect_stdout
from importlib.metadata import version
import json
import sys

from .contracts import WorkerRequest, WorkerResponse
from .operations import (
    HEALTH,
    RUN_STRATEGY_INTENTS,
    RUN_TARGET_WEIGHTS,
    canonical_operation,
    operation_keys_for_health,
    operation_manifest,
    runner_name_for_operation,
)


PACKAGES = {
    "backtrader": "backtrader",
    "qlib": "pyqlib",
    "zipline": "zipline-reloaded",
    "rqalpha": "rqalpha",
}


def execute(request: WorkerRequest, progress=None) -> dict:
    if request.engine not in PACKAGES:
        raise ValueError(f"unknown worker engine: {request.engine}")
    operation = canonical_operation(request.operation)
    if operation == HEALTH:
        return {
            "framework_version": version(PACKAGES[request.engine]),
            "operations": operation_keys_for_health(),
            "operation_manifest": operation_manifest(),
            "process_isolation": "conda-subprocess",
        }
    runner_name = runner_name_for_operation(operation)
    if operation == RUN_TARGET_WEIGHTS:
        if request.engine == "backtrader":
            from .runners.backtrader import run_target_weights
        elif request.engine == "qlib":
            from .runners.qlib import run_target_weights
        elif request.engine == "zipline":
            from .runners.zipline import run_target_weights
        else:
            raise NotImplementedError("RQAlpha target-weight runner is not implemented")
        return run_target_weights(request.payload)
    if operation == RUN_STRATEGY_INTENTS:
        if request.engine == "backtrader":
            from .runners.backtrader import run_strategy_intents
        elif request.engine == "qlib":
            from .runners.qlib import run_strategy_intents
        elif request.engine == "zipline":
            from .runners.zipline import run_strategy_intents
        else:
            raise NotImplementedError("RQAlpha strategy-intent runner is not implemented")
        return run_strategy_intents(request.payload, progress=progress)
    raise ValueError(
        f"operation {request.operation!r} ({runner_name}) is not implemented for {request.engine}"
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
            def _progress(completed, total, timestamp):
                sys.stderr.write("GTHT_PROGRESS " + json.dumps({
                    "completed": completed,
                    "total": total,
                    "event_timestamp": timestamp.isoformat(),
                }, separators=(",", ":")) + "\n")
                sys.stderr.flush()

            result = execute(request, progress=_progress)
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
