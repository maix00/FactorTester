"""CLI boundary for the external batch FactorFamily alias validator."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
from typing import Any


_VALIDATOR_ENV = "FACTORTESTER_FACTOR_ALIAS_VALIDATOR"


def validate_canonical_factor_identity(
    *,
    source_file: Path,
    identity: str,
    object_kind: str,
    blob_hash: str,
) -> str:
    """Reject new immutable references that use a non-canonical alias."""
    return validate_canonical_factor_identities([{
        "source_file": str(source_file),
        "identity": str(identity),
        "object_kind": object_kind,
        "blob_hash": blob_hash,
    }])[0]


def validate_canonical_factor_identities(
    requests: list[dict[str, Any]],
) -> list[str]:
    """Validate one batch without importing the Factor engine into the client."""
    return [
        str(item["canonical_identity"])
        for item in inspect_canonical_factor_identities(requests)
    ]


def inspect_canonical_factor_identities(
    requests: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return canonical aliases and formula fingerprints in one engine batch."""
    if not requests:
        raise ValueError("factor identity validation batch is empty")
    command, cwd, environment = _validator_process()
    result = subprocess.run(
        command,
        cwd=cwd,
        env=environment,
        input=json.dumps({"requests": requests}, ensure_ascii=False),
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        detail = result.stderr.strip() or result.stdout.strip() or "no output"
        raise ValueError(
            f"factor alias validator returned invalid output: {detail}"
        ) from error
    if not isinstance(payload, dict) or payload.get("error"):
        raise ValueError(
            str(payload.get("error") or "factor alias validator failed")
        )
    rows = payload.get("results")
    if not isinstance(rows, list) or len(rows) != len(requests):
        raise ValueError("factor alias validator returned an incomplete batch")
    identities: list[dict[str, Any]] = []
    for request, row in zip(requests, rows, strict=True):
        if not isinstance(row, dict):
            raise ValueError("factor alias validator returned an invalid result")
        identity = str(request.get("identity") or "")
        expected = str(row.get("canonical_identity") or "")
        if not expected:
            raise ValueError("factor alias validator omitted canonical identity")
        if identity != expected:
            raise ValueError(
                f"Non-canonical factor identity {identity!r}; expected {expected!r}"
            )
        family_fingerprint = str(row.get("family_formula_fingerprint") or "")
        self_fingerprint = str(row.get("self_formula_fingerprint") or "")
        if len(family_fingerprint) != 64:
            raise ValueError("factor alias validator omitted family formula identity")
        if str(request.get("object_kind")) == "factor" and len(self_fingerprint) != 64:
            raise ValueError("factor alias validator omitted self formula identity")
        identities.append({
            "canonical_identity": expected,
            "family_formula_fingerprint": family_fingerprint,
            "self_formula_fingerprint": self_fingerprint,
            "params": dict(row.get("params") or {}),
        })
    if result.returncode:
        raise ValueError("factor alias validator rejected the identity batch")
    return identities


def _validator_process() -> tuple[list[str], Path | None, dict[str, str]]:
    configured = os.environ.get(_VALIDATOR_ENV, "").strip()
    environment = dict(os.environ)
    if configured:
        command = shlex.split(configured)
        if not command:
            raise ValueError(f"{_VALIDATOR_ENV} is empty")
        return command, None, environment

    tools_root = Path(__file__).resolve().parents[4]
    validator = tools_root / "factors" / "alias_validator.py"
    if not validator.is_file():
        raise ValueError(
            "canonical factor alias validation requires the FactorTester engine "
            f"helper; set {_VALIDATOR_ENV} to its command"
        )
    repository = tools_root.parent
    existing = environment.get("PYTHONPATH", "")
    environment["PYTHONPATH"] = (
        str(repository) if not existing
        else os.pathsep.join([str(repository), existing])
    )
    return [sys.executable, str(validator)], repository, environment
