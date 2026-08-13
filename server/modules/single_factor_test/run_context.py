"""Portable, Manager-authored context for federated research Runs.

The browser submits a workspace reference to its current Manager.  A remote
execution service cannot resolve that reference because workspace authoring is
owned by the origin Manager's local store.  This module carries the already
frozen request across the authenticated Manager boundary without copying or
synchronising the workspace database.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
from typing import Any

import orjson

from server.services import research_configurations, research_runs


MANAGER_RUN_CONTEXT_KEY = "_manager_run_context"
MANAGER_RUN_CONTEXT_SCHEMA_VERSION = 1


class RunRequestError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int = 400,
        details: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.details = details or {}


def create_manager_run_context(
    prepared: dict[str, Any],
    *,
    owner: str,
) -> dict[str, Any]:
    """Create a JSON-safe immutable envelope for one prepared Run request."""
    owner = str(owner or "").strip()
    if not owner:
        raise RunRequestError("manager run context owner is required")
    run_spec = prepared.get("run_spec")
    if not isinstance(run_spec, dict):
        raise RunRequestError("manager run context requires a RunSpec")
    context = {
        "schema_version": MANAGER_RUN_CONTEXT_SCHEMA_VERSION,
        "owner": owner,
        "run_spec_hash": research_runs.hash_run_spec(run_spec),
        "prepared": deepcopy(prepared),
    }
    try:
        # Fail at the origin rather than discovering a non-portable value only
        # after route selection or federation transport encoding.
        orjson.dumps(context, option=orjson.OPT_SORT_KEYS)
    except (TypeError, ValueError) as exc:
        raise RunRequestError("manager run context is not JSON serializable") from exc
    return context


def load_manager_run_context(
    value: object,
    *,
    owner: str,
) -> dict[str, Any]:
    """Validate and return a prepared request received from a trusted Manager."""
    if not isinstance(value, dict):
        raise RunRequestError(
            "manager run context must be an object",
            details={"code": "invalid_manager_run_context"},
        )
    if int(value.get("schema_version") or 0) != MANAGER_RUN_CONTEXT_SCHEMA_VERSION:
        raise RunRequestError(
            "unsupported manager run context schema",
            details={"code": "invalid_manager_run_context"},
        )
    if str(value.get("owner") or "").strip() != str(owner or "").strip():
        raise RunRequestError(
            "manager run context owner does not match the authenticated user",
            status_code=403,
            details={"code": "manager_run_context_owner_mismatch"},
        )
    prepared = value.get("prepared")
    if not isinstance(prepared, dict):
        raise RunRequestError(
            "manager run context is missing its prepared request",
            details={"code": "invalid_manager_run_context"},
        )
    run_spec = prepared.get("run_spec")
    if not isinstance(run_spec, dict):
        raise RunRequestError(
            "manager run context is missing its RunSpec",
            details={"code": "invalid_manager_run_context"},
        )
    expected_hash = str(value.get("run_spec_hash") or "").strip()
    if expected_hash != research_runs.hash_run_spec(run_spec):
        raise RunRequestError(
            "manager run context RunSpec hash does not match",
            details={"code": "invalid_manager_run_context"},
        )

    workspace_id = str(prepared.get("workspace_id") or "").strip()
    analyses = prepared.get("analyses")
    configuration = prepared.get("configuration")
    frozen = prepared.get("frozen_configuration")
    if (
        not workspace_id
        or not isinstance(analyses, list)
        or not analyses
        or not isinstance(configuration, dict)
        or not isinstance(frozen, dict)
    ):
        raise RunRequestError(
            "manager run context is incomplete",
            details={"code": "invalid_manager_run_context"},
        )
    if workspace_id != str(run_spec.get("workspace_id") or "").strip():
        raise RunRequestError(
            "manager run context workspace does not match its RunSpec",
            details={"code": "invalid_manager_run_context"},
        )
    normalized_analyses = [str(item).strip() for item in analyses]
    if normalized_analyses != list(run_spec.get("analyses") or []):
        raise RunRequestError(
            "manager run context analyses do not match its RunSpec",
            details={"code": "invalid_manager_run_context"},
        )

    try:
        configuration_id = str(configuration["configuration_id"])
        revision = int(configuration["revision"])
        fingerprint = str(configuration["fingerprint"])
        payload = research_configurations.validate_payload(
            configuration["payload"]
        )
        frozen_payload = research_configurations.validate_payload(
            frozen["payload"]
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise RunRequestError(
            "manager run context configuration is invalid",
            details={"code": "invalid_manager_run_context"},
        ) from exc
    actual_fingerprint = hashlib.sha256(
        orjson.dumps(payload, option=orjson.OPT_SORT_KEYS)
    ).hexdigest()
    if fingerprint != actual_fingerprint:
        raise RunRequestError(
            "manager run context configuration fingerprint does not match",
            details={"code": "invalid_manager_run_context"},
        )
    if (
        configuration_id != str(run_spec.get("configuration_id") or "")
        or revision != int(run_spec.get("configuration_revision") or 0)
        or fingerprint != str(run_spec.get("configuration_fingerprint") or "")
        or frozen_payload != run_spec.get("configuration")
    ):
        raise RunRequestError(
            "manager run context configuration does not match its RunSpec",
            details={"code": "invalid_manager_run_context"},
        )
    return deepcopy(prepared)


__all__ = [
    "MANAGER_RUN_CONTEXT_KEY",
    "RunRequestError",
    "create_manager_run_context",
    "load_manager_run_context",
]
