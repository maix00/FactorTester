"""Bounded, local-only research evidence envelopes."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
from typing import Any


_DECISIONS = {
    "continue",
    "capability_gap",
    "factor_improvement",
    "candidate",
    "watchlist",
    "reject",
}


def validate_evidence_envelope(envelope: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(envelope, dict):
        raise ValueError("evidence envelope must be an object")
    if int(envelope.get("schema_version") or 0) != 1:
        raise ValueError("unsupported evidence envelope schema_version")
    command = envelope.get("command")
    if not isinstance(command, dict):
        raise ValueError("evidence envelope requires command")
    argv = command.get("argv")
    if not isinstance(argv, list) or not all(
        isinstance(item, str) for item in argv
    ):
        raise ValueError("evidence command argv must be an array of strings")
    returncode = command.get("returncode")
    if not isinstance(returncode, int) or isinstance(returncode, bool):
        raise ValueError("evidence command returncode must be an integer")
    for field in ("stdout_ref", "stderr_ref"):
        if not isinstance(command.get(field), str):
            raise ValueError(f"evidence command {field} must be a string")
    for field in ("metric_refs", "artifact_refs"):
        value = envelope.get(field)
        if not isinstance(value, list) or not all(
            isinstance(item, str) and item.strip() for item in value
        ):
            raise ValueError(f"evidence {field} must be an array of references")
    hypotheses_tested = envelope.get("hypotheses_tested")
    if (
        not isinstance(hypotheses_tested, int)
        or isinstance(hypotheses_tested, bool)
        or hypotheses_tested < 0
    ):
        raise ValueError("hypotheses_tested must be non-negative")
    stop_condition = envelope.get("stop_condition")
    if stop_condition is not None and not isinstance(stop_condition, str):
        raise ValueError("stop_condition must be a string or null")
    if envelope.get("decision") not in _DECISIONS:
        raise ValueError("invalid evidence decision")
    return deepcopy(envelope)


def persist_command_evidence(
    *,
    session_path: str,
    envelope_id: str,
    argv: list[str],
    returncode: int,
    stdout: str,
    stderr: str,
    hypotheses_tested: int,
    stop_condition: str | None,
    decision: str,
) -> dict[str, Any]:
    """Persist stdout/stderr locally and return a bounded auditable envelope."""
    session_file = Path(session_path)
    artifact_dir = session_file.parent / f"{session_file.name}.artifacts"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    refs: dict[str, str] = {}
    artifact_refs: list[str] = []
    for stream, text in (("stdout", stdout), ("stderr", stderr)):
        if not text:
            refs[stream] = ""
            continue
        digest = hashlib.sha256(text.encode()).hexdigest()
        path = artifact_dir / f"{envelope_id}.{stream}.{digest[:12]}.txt"
        path.write_text(text, encoding="utf-8")
        refs[stream] = f"local-artifact:{path}:{digest}"
        artifact_refs.append(refs[stream])
    envelope = {
        "schema_version": 1,
        "envelope_id": envelope_id,
        "command": {
            "argv": list(argv),
            "returncode": int(returncode),
            "stdout_ref": refs["stdout"],
            "stderr_ref": refs["stderr"],
        },
        "metric_refs": [],
        "artifact_refs": artifact_refs,
        "hypotheses_tested": hypotheses_tested,
        "stop_condition": stop_condition,
        "decision": decision,
    }
    value = validate_evidence_envelope(envelope)
    value["envelope_hash"] = hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    return value
