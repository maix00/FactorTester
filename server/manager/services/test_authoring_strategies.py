"""Transactional API helpers for configuration-owned strategies."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from server.services import configuration_strategies, research_configurations


def read(
    *, workspace_id: str, owner: str, include_source: bool = False,
) -> dict[str, Any]:
    configuration = research_configurations.load_workspace_configuration(
        workspace_id=workspace_id, owner=owner,
    )
    if configuration is None:
        raise KeyError("workspace configuration not found")
    return {
        "success": True,
        "configuration_id": configuration["configuration_id"],
        "revision": configuration["revision"],
        **configuration_strategies.view(
            configuration["payload"], include_source=include_source,
        ),
    }


def write(
    *,
    workspace_id: str,
    owner: str,
    method: str,
    binding_id: str = "",
    request: dict[str, Any],
    strategy_library=None,
) -> dict[str, Any]:
    configuration = research_configurations.load_workspace_configuration(
        workspace_id=workspace_id, owner=owner,
    )
    if configuration is None:
        raise KeyError("workspace configuration not found")
    try:
        expected = int(request.get("expected_revision"))
    except (TypeError, ValueError) as exc:
        raise ValueError("expected_revision is required") from exc
    payload = deepcopy(configuration["payload"])
    if method == "POST":
        kind = str(request.get("kind") or "inline").strip().lower()
        if kind == "inline":
            result = configuration_strategies.add_inline(
                payload,
                name=str(request.get("name") or ""),
                source_code=str(request.get("source_code") or ""),
                entrypoint=str(request.get("entrypoint") or "Strategy"),
                target_strategy_id=str(request.get("target_strategy_id") or ""),
                requirements=request.get("requirements") or {},
            )
        elif kind == "library":
            result = configuration_strategies.add_library(
                payload,
                strategy_ref=str(request.get("strategy_ref") or ""),
                revision_ref=str(request.get("revision_ref") or ""),
                target_strategy_id=str(request.get("target_strategy_id") or ""),
                source_sha256=str(request.get("source_sha256") or ""),
                library=strategy_library,
                owner=owner,
            )
        else:
            raise ValueError("strategy kind must be inline or library")
    elif method == "PATCH":
        if not binding_id:
            raise ValueError("binding_id is required")
        result = configuration_strategies.update_inline(
            payload, binding_id,
            name=request.get("name"),
            source_code=request.get("source_code"),
            entrypoint=request.get("entrypoint"),
            requirements=request.get("requirements"),
        )
    elif method == "DELETE":
        if not binding_id:
            raise ValueError("binding_id is required")
        result = configuration_strategies.remove_binding(payload, binding_id)
    else:
        raise ValueError("configuration strategy method is not supported")
    updated = research_configurations.update_workspace_configuration(
        workspace_id=workspace_id, owner=owner, expected_revision=expected,
        payload=payload,
    )
    return {
        "success": True,
        "configuration": updated,
        **configuration_strategies.view(
            updated["payload"], include_source=False,
        ),
        "change": configuration_strategies.project_change(result),
    }
