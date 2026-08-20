"""Merge Provider model discovery with Codex conversation capabilities."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from server.manager.services.agent_app_server_errors import AgentAppServerError


def build_model_catalog(
    health: Mapping[str, object],
    runtime_models: Sequence[Mapping[str, object]],
) -> dict[str, Any]:
    """Return only models available from the bound Provider account."""
    runtime_by_id = {
        str(item.get("id") or item.get("model") or "").strip(): item
        for item in runtime_models
        if str(item.get("id") or item.get("model") or "").strip()
    }
    models = []
    for model_id in health.get("available_models") or []:
        identifier = str(model_id or "").strip()
        if not identifier:
            continue
        runtime = runtime_by_id.get(identifier, {})
        efforts = [
            {
                "id": str(item.get("reasoningEffort") or ""),
                "description": str(item.get("description") or ""),
            }
            for item in (runtime.get("supportedReasoningEfforts") or [])
            if isinstance(item, Mapping) and item.get("reasoningEffort")
        ]
        tiers = [
            {
                "id": str(item.get("id") or ""),
                "name": str(item.get("name") or item.get("id") or ""),
                "description": str(item.get("description") or ""),
            }
            for item in (runtime.get("serviceTiers") or [])
            if isinstance(item, Mapping) and item.get("id")
        ]
        models.append({
            "id": identifier,
            "display_name": str(runtime.get("displayName") or identifier),
            "description": str(runtime.get("description") or ""),
            "reasoning_efforts": efforts,
            "service_tiers": tiers,
            "default_reasoning_effort": str(
                runtime.get("defaultReasoningEffort") or ""
            ),
            "default_service_tier": str(runtime.get("defaultServiceTier") or ""),
            "capabilities_known": bool(runtime),
        })
    return {
        "models": models,
        "latency_ms": int(health.get("latency_ms") or 0),
        "truncated": bool(health.get("available_models_truncated")),
    }


def validate_model_settings(
    catalog: Mapping[str, object],
    *,
    model_id: str,
    reasoning_effort: str,
    service_tier: str,
) -> tuple[str, str, str]:
    """Validate one conversation selection against current capabilities."""
    model = str(model_id or "").strip()
    models = {
        str(item.get("id") or ""): item
        for item in (catalog.get("models") or [])
        if isinstance(item, Mapping)
    }
    if model not in models:
        raise AgentAppServerError("selected model is unavailable")
    metadata = models[model]
    effort = str(reasoning_effort or "").strip()
    allowed_efforts = {
        str(item.get("id") or "")
        for item in (metadata.get("reasoning_efforts") or [])
        if isinstance(item, Mapping)
    }
    if effort and effort not in allowed_efforts:
        raise AgentAppServerError("selected reasoning effort is unavailable")
    tier = str(service_tier or "").strip()
    allowed_tiers = {
        str(item.get("id") or "")
        for item in (metadata.get("service_tiers") or [])
        if isinstance(item, Mapping)
    }
    if tier and tier not in allowed_tiers:
        raise AgentAppServerError("selected service tier is unavailable")
    return model, effort, tier


__all__ = ["build_model_catalog", "validate_model_settings"]
