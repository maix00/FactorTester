"""Offline validation for ephemeral Research Step contracts."""

from __future__ import annotations

import hashlib
import re
from typing import Any

import orjson


SHA256 = re.compile(r"^[0-9a-f]{64}$")
IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,255}$")
ANALYSES = {
    "backtest", "ic", "factor_evaluation", "factor_type_analysis",
}
ACTION_STATUSES = {
    "unreleased", "released", "running", "evidence_ready",
    "admitted", "audited", "failed", "blocked",
}
PREPARE_FIELDS = {
    "schema_version", "operation", "inspect_context_ref", "binding", "cas",
    "action", "configuration_requests", "execution_ready",
    "authority_refresh_required", "capability_gaps", "contract_hash",
}
CONFIG_FIELDS = {
    "configuration_id", "configuration_revision",
    "configuration_fingerprint", "analyses", "trial_role", "comparison_id",
}
ACTION_FIELDS = {
    "action_id", "status", "stage_id", "input_hash", "execution_mode",
    "expected_evidence_kind", "run_spec_hashes", "comparison_ids",
    "comparison_roles", "obligation_refs",
}
BINDING_FIELDS = {
    "profile_ref", "work_package_id", "workspace_id",
    "instance_id", "branch_id",
}


def validate_prepare_contract(value: dict[str, Any]) -> dict[str, Any]:
    """Validate structure and integrity, never server authority or freshness."""
    if not isinstance(value, dict) or set(value) != PREPARE_FIELDS:
        raise ValueError("research step prepare contract fields are invalid")
    if value.get("schema_version") != 1:
        raise ValueError("prepare contract schema_version must be 1")
    if value.get("operation") != "research.step.prepare":
        raise ValueError("prepare contract operation is invalid")
    context_ref(value.get("inspect_context_ref"))
    _binding(value.get("binding"))
    _cas(value.get("cas"))
    action = _action(value.get("action"))
    configurations = value.get("configuration_requests")
    if not isinstance(configurations, list) or not configurations:
        raise ValueError("configuration_requests must be non-empty")
    normalized = [normalize_configuration(item) for item in configurations]
    identities = [
        (item["configuration_id"], item["configuration_revision"])
        for item in normalized
    ]
    if len(identities) != len(set(identities)):
        raise ValueError("configuration identities must be unique")
    if any(
        item["comparison_id"] not in action["comparison_ids"]
        for item in normalized
    ):
        raise ValueError("configuration comparison_id is not current")
    if any(
        item["trial_role"] not in action["comparison_roles"][
            item["comparison_id"]
        ]
        for item in normalized
    ):
        raise ValueError("configuration trial_role is not declared")
    if value.get("execution_ready") is not False:
        raise ValueError("batch-1 prepare contract cannot be executable")
    if value.get("authority_refresh_required") is not True:
        raise ValueError("prepare contract must require authority refresh")
    _capability_gaps(value.get("capability_gaps"))
    supplied = str(value.get("contract_hash") or "")
    if supplied != contract_hash(value):
        raise ValueError("prepare contract_hash mismatch")
    return {
        "valid": True,
        "contract_hash": supplied,
        "configuration_count": len(normalized),
        "execution_ready": False,
        "authority_refresh_required": True,
    }


def normalize_configuration(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != CONFIG_FIELDS:
        raise ValueError("configuration request fields are invalid")
    revision = value.get("configuration_revision")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        raise ValueError("configuration_revision must be positive")
    analyses = value.get("analyses")
    if (
        not isinstance(analyses, list) or not analyses
        or not all(isinstance(item, str) and item in ANALYSES for item in analyses)
        or len(analyses) != len(set(analyses))
    ):
        raise ValueError("analyses are invalid")
    return {
        "configuration_id": identifier(
            value.get("configuration_id"), "configuration_id",
        ),
        "configuration_revision": revision,
        "configuration_fingerprint": sha256(
            value.get("configuration_fingerprint"),
            "configuration_fingerprint",
        ),
        "analyses": list(analyses),
        "trial_role": identifier(value.get("trial_role"), "trial_role"),
        "comparison_id": identifier(
            value.get("comparison_id"), "comparison_id",
        ),
    }


def identifier(value: Any, field: str) -> str:
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise ValueError(f"{field} is invalid")
    return value


def sha256(value: Any, field: str) -> str:
    if not isinstance(value, str) or not SHA256.fullmatch(value):
        raise ValueError(f"{field} must be sha256")
    return value


def context_ref(value: Any) -> str:
    if (
        not isinstance(value, str) or not value.startswith("sha256:")
        or not SHA256.fullmatch(value[7:])
    ):
        raise ValueError("context_ref must be sha256 reference")
    return value


def contract_hash(value: dict[str, Any]) -> str:
    body = {
        key: item for key, item in value.items()
        if key != "contract_hash"
    }
    return "sha256:" + hashlib.sha256(
        orjson.dumps(body, option=orjson.OPT_SORT_KEYS)
    ).hexdigest()


def _binding(value: Any) -> None:
    if not isinstance(value, dict) or set(value) != BINDING_FIELDS:
        raise ValueError("prepare binding fields are invalid")
    for field, item in value.items():
        identifier(item, f"binding.{field}")


def _cas(value: Any) -> None:
    if not isinstance(value, dict) or set(value) != {
        "latest_trace_id", "checkpoint_hash",
    }:
        raise ValueError("prepare CAS fields are invalid")
    identifier(value["latest_trace_id"], "cas.latest_trace_id")
    sha256(value["checkpoint_hash"], "cas.checkpoint_hash")


def _action(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != ACTION_FIELDS:
        raise ValueError("prepare action fields are invalid")
    for field in ("action_id", "status", "stage_id"):
        identifier(value[field], f"action.{field}")
    if value["status"] not in ACTION_STATUSES:
        raise ValueError("prepare action status is invalid")
    sha256(value["input_hash"], "action.input_hash")
    if value["execution_mode"] != "job":
        raise ValueError("RunSpec preparation requires a job Evidence Action")
    if value["expected_evidence_kind"] != "job_attempt":
        raise ValueError("job Evidence Action must expect job_attempt")
    for field in ("run_spec_hashes", "comparison_ids", "obligation_refs"):
        items = value[field]
        if not isinstance(items, list) or len(items) != len(set(items)):
            raise ValueError(f"action.{field} must be a unique array")
        validator = sha256 if field == "run_spec_hashes" else identifier
        for item in items:
            validator(item, f"action.{field}")
    if not value["comparison_ids"]:
        raise ValueError("job Evidence Action requires a comparison")
    roles = value["comparison_roles"]
    if (
        not isinstance(roles, dict)
        or set(roles) != set(value["comparison_ids"])
    ):
        raise ValueError("action comparison_roles are invalid")
    for comparison_id, items in roles.items():
        identifier(comparison_id, "action.comparison_roles")
        if (
            not isinstance(items, list) or not items
            or len(items) != len(set(items))
        ):
            raise ValueError("comparison roles must be a unique array")
        for item in items:
            identifier(item, "comparison role")
    return value


def _capability_gaps(value: Any) -> None:
    expected = [{
        "capability_id": "research-run.immutable-configuration-snapshot",
        "reason": (
            "stable immutable configuration snapshot preview is unavailable"
        ),
    }]
    if value != expected:
        raise ValueError("prepare capability_gaps are invalid")
