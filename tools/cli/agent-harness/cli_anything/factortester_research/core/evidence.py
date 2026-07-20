"""Bounded, factual, local-only research evidence envelopes."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
from typing import Any


_INTERPRETATION_FIELDS = {
    "adjudication",
    "claim_evidence_delta",
    "conclusion",
    "decision",
    "decision_warrant",
    "obligation_delta",
}
_IDENTITY_HASH_FIELDS = frozenset({
    "contract_hash",
    "methodology_hash",
    "run_spec_hash",
    "trial_plan_hash",
})
_CONTRACT_EVIDENCE_KINDS = frozenset({
    "hypothesis_semantics",
    "data_availability",
    "data_contract",
    "factor_semantics",
})
_RUN_EVIDENCE_KINDS = frozenset({
    "trial_diagnostics",
    "authoritative_backtest",
    "statistical_robustness",
    "job_attempt",
})


def assert_no_legacy_evidence_payload(value: Any) -> None:
    """Reject a legacy envelope anywhere in an Agent command payload."""
    if isinstance(value, dict):
        if _looks_like_legacy_envelope(value):
            raise ValueError("legacy evidence is unavailable to Agents")
        for item in value.values():
            assert_no_legacy_evidence_payload(item)
    elif isinstance(value, list):
        for item in value:
            assert_no_legacy_evidence_payload(item)


def validate_evidence_envelope(envelope: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(envelope, dict):
        raise ValueError("evidence envelope must be an object")
    if int(envelope.get("schema_version") or 0) == 1:
        raise ValueError("legacy evidence is unavailable to Agents")
    if int(envelope.get("schema_version") or 0) != 2:
        raise ValueError("unsupported evidence envelope schema_version")
    forbidden = sorted(_find_fields(envelope, _INTERPRETATION_FIELDS))
    if forbidden:
        raise ValueError(
            "factual evidence must not contain decision fields: "
            + ", ".join(forbidden)
        )
    if not isinstance(envelope.get("envelope_id"), str):
        raise ValueError("evidence envelope requires envelope_id")
    evidence_kind = envelope.get("evidence_kind")
    if not isinstance(evidence_kind, str):
        raise ValueError("evidence envelope requires evidence_kind")
    source_refs = envelope.get("source_refs")
    if not isinstance(source_refs, list) or not source_refs or not all(
        isinstance(item, str) and item.strip() for item in source_refs
    ):
        raise ValueError("evidence source_refs must be a non-empty array")
    identity_refs = envelope.get("identity_refs")
    if not isinstance(identity_refs, dict):
        raise ValueError("evidence identity_refs must be an object")
    _validate_identity_refs(
        evidence_kind=evidence_kind,
        identity_refs=identity_refs,
    )
    command = envelope.get("command")
    if command is not None:
        if not isinstance(command, dict):
            raise ValueError("evidence command must be an object")
        argv = command.get("argv")
        if not isinstance(argv, list) or not all(
            isinstance(item, str) for item in argv
        ):
            raise ValueError(
                "evidence command argv must be an array of strings"
            )
        returncode = command.get("returncode")
        if not isinstance(returncode, int) or isinstance(returncode, bool):
            raise ValueError(
                "evidence command returncode must be an integer"
            )
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
    for field in ("limitations", "conflicts"):
        value = envelope.get(field)
        if not isinstance(value, list) or not all(
            isinstance(item, str) and item.strip() for item in value
        ):
            raise ValueError(f"evidence {field} must be a text array")
    value = deepcopy(envelope)
    declared_hash = str(value.pop("envelope_hash", "") or "")
    computed_hash = _evidence_hash(value)
    if declared_hash and declared_hash != computed_hash:
        raise ValueError("envelope_hash mismatch")
    value["envelope_hash"] = computed_hash
    return value


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
        "schema_version": 2,
        "envelope_id": envelope_id,
        "evidence_kind": "control_command",
        "source_refs": [f"local-command:{envelope_id}"],
        "identity_refs": {},
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
        "limitations": [],
        "conflicts": [],
    }
    return validate_evidence_envelope(envelope)


def _validate_identity_refs(
    *,
    evidence_kind: str,
    identity_refs: dict[str, Any],
) -> None:
    unsupported = sorted(set(identity_refs) - _IDENTITY_HASH_FIELDS)
    if unsupported:
        raise ValueError(
            "evidence identity_refs contains unsupported fields: "
            + ", ".join(unsupported)
        )
    for field, value in identity_refs.items():
        if (
            not isinstance(value, str)
            or len(value.removeprefix("sha256:")) != 64
            or any(
                character not in "0123456789abcdef"
                for character in value.removeprefix("sha256:")
            )
        ):
            raise ValueError(f"evidence identity_refs.{field} must be sha256")
    if evidence_kind == "control_command":
        required: tuple[str, ...] = ()
    elif evidence_kind in _CONTRACT_EVIDENCE_KINDS:
        required = ("contract_hash", "methodology_hash")
    elif evidence_kind in _RUN_EVIDENCE_KINDS:
        required = (
            "contract_hash",
            "methodology_hash",
            "trial_plan_hash",
            "run_spec_hash",
        )
    else:
        raise ValueError(f"unsupported evidence_kind: {evidence_kind}")
    for field in required:
        if field not in identity_refs:
            raise ValueError(
                f"{evidence_kind} evidence requires identity_refs.{field}"
            )


def _find_fields(value: Any, forbidden: set[str]) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key) in forbidden:
                found.add(str(key))
            found.update(_find_fields(item, forbidden))
    elif isinstance(value, list):
        for item in value:
            found.update(_find_fields(item, forbidden))
    return found


def _evidence_hash(value: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def _looks_like_legacy_envelope(value: dict[str, Any]) -> bool:
    return (
        value.get("schema_version") == 1
        and isinstance(value.get("envelope_id"), str)
    )
