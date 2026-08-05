"""Client boundary for bounded factor-family engine operations."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
from typing import Any

from tools.cli.release.research_reporting.references.factor_identity import (
    _validator_process,
)


def describe_factor_family(
    *, source_file: Path, family: str, blob_hash: str,
) -> dict[str, Any]:
    """Read factor metadata through the external FactorTester engine helper."""
    return _request("describe", {
        "source_file": str(source_file),
        "family": family,
        "blob_hash": blob_hash,
    })


def instantiate_factor_family(
    *,
    source_file: Path,
    family: str,
    blob_hash: str,
    params: dict[str, Any],
) -> dict[str, Any]:
    """Generate one canonical alias through the external engine helper."""
    return _request("instantiate", {
        "source_file": str(source_file),
        "family": family,
        "blob_hash": blob_hash,
        "params": params,
    })


def _request(operation: str, request: dict[str, Any]) -> dict[str, Any]:
    command, cwd, environment = _validator_process()
    result = subprocess.run(
        command,
        cwd=cwd,
        env=environment,
        input=json.dumps({
            "operation": operation,
            "request": request,
        }, ensure_ascii=False),
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        detail = result.stderr.strip() or result.stdout.strip() or "no output"
        raise ValueError(
            f"factor engine helper returned invalid output: {detail}"
        ) from error
    if (
        result.returncode
        or not isinstance(payload, dict)
        or payload.get("error")
        or not isinstance(payload.get("result"), dict)
    ):
        raise ValueError(str(payload.get("error") or "factor engine helper failed"))
    return payload["result"]
