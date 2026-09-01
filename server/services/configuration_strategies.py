"""Inline Strategy bindings owned by one ResearchConfiguration."""

from __future__ import annotations

from copy import deepcopy
from typing import Any
from uuid import uuid4

from server.services.strategy_library.model import inspect_source, normalize_entrypoint


def _normalize_target(value: Any) -> str:
    target = str(value or "").strip()
    if not target:
        raise ValueError("each strategy binding requires target_strategy_id")
    if len(target) > 256 or any(ord(character) < 32 or ord(character) == 127 for character in target):
        raise ValueError("target_strategy_id must be a bounded opaque string")
    return target


def _sections(payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    shared = payload.setdefault("shared", {})
    analyses = payload.setdefault("analyses", {})
    if not isinstance(shared, dict) or not isinstance(analyses, dict):
        raise ValueError("configuration requires object shared and analyses sections")
    temporary = shared.setdefault("temporary_objects", {})
    backtest = analyses.setdefault("backtest", {})
    if not isinstance(temporary, dict) or not isinstance(backtest, dict):
        raise ValueError("strategy configuration sections must be objects")
    strategies = temporary.setdefault("strategies", [])
    bindings = backtest.setdefault("strategy_bindings", [])
    if not isinstance(strategies, list) or not all(isinstance(item, dict) for item in strategies):
        raise ValueError("shared.temporary_objects.strategies must be an array of objects")
    if not isinstance(bindings, list) or not all(isinstance(item, dict) for item in bindings):
        raise ValueError("analyses.backtest.strategy_bindings must be an array of objects")
    return temporary, backtest


def validate(payload: dict[str, Any]) -> None:
    """Validate only the optional strategy extension of a configuration."""
    temporary, backtest = _sections(deepcopy(payload))
    strategies = temporary.get("strategies") or []
    by_ref: dict[str, dict[str, Any]] = {}
    for item in strategies:
        temp_ref = str(item.get("temp_ref") or "").strip()
        if not temp_ref or temp_ref in by_ref:
            raise ValueError("each temporary strategy requires a unique temp_ref")
        source = str(item.get("source_code") or "")
        entrypoint = normalize_entrypoint(item.get("entrypoint"))
        inspection = inspect_source(source, entrypoint)
        name = " ".join(str(item.get("name") or "").split())
        if not name:
            raise ValueError(f"temporary strategy name is required: {temp_ref}")
        requirements = item.get("requirements") or {}
        if not isinstance(requirements, dict):
            raise ValueError(f"temporary strategy requirements must be an object: {temp_ref}")
        recorded_hash = str(item.get("source_sha256") or "").strip()
        if recorded_hash and recorded_hash != inspection["source_sha256"]:
            raise ValueError(f"temporary strategy source hash mismatch: {temp_ref}")
        by_ref[temp_ref] = item
    seen_bindings: set[str] = set()
    seen_targets: set[str] = set()
    for binding in backtest.get("strategy_bindings") or []:
        binding_id = str(binding.get("binding_id") or "").strip()
        target = _normalize_target(binding.get("target_strategy_id"))
        source = binding.get("source")
        if not binding_id or binding_id in seen_bindings:
            raise ValueError("each strategy binding requires a unique binding_id")
        if not target:
            raise ValueError("each strategy binding requires target_strategy_id")
        if target in seen_targets:
            raise ValueError(f"strategy target has more than one binding: {target}")
        if not isinstance(source, dict) or source.get("kind") not in {"inline", "library"}:
            raise ValueError("strategy binding source kind must be inline or library")
        if source.get("kind") == "inline":
            if str(source.get("temp_ref") or "") not in by_ref:
                raise ValueError(f"strategy binding references unknown temporary strategy: {source.get('temp_ref')}")
        elif not str(source.get("strategy_ref") or "").strip() or not str(source.get("revision_ref") or "").strip():
            raise ValueError("library strategy binding requires strategy_ref and revision_ref")
        seen_bindings.add(binding_id)
        seen_targets.add(target)


def view(payload: dict[str, Any]) -> dict[str, Any]:
    temporary, backtest = _sections(deepcopy(payload))
    return {
        "strategies": temporary.get("strategies") or [],
        "bindings": backtest.get("strategy_bindings") or [],
    }


def _new_ref(prefix: str) -> str:
    return f"{prefix}:{uuid4().hex}"


def add_inline(
    payload: dict[str, Any],
    *,
    name: str,
    source_code: str,
    entrypoint: str = "Strategy",
    target_strategy_id: str,
    requirements: dict[str, Any] | None = None,
) -> dict[str, Any]:
    temporary, backtest = _sections(payload)
    name = " ".join(str(name or "").split())
    target = _normalize_target(target_strategy_id)
    if not name or not target:
        raise ValueError("inline strategy name and target_strategy_id are required")
    if any(str(item.get("target_strategy_id") or "") == target
           for item in backtest["strategy_bindings"]):
        raise ValueError(f"strategy target already has a binding: {target}")
    entrypoint = normalize_entrypoint(entrypoint)
    inspection = inspect_source(source_code, entrypoint)
    if requirements is not None and not isinstance(requirements, dict):
        raise ValueError("strategy requirements must be an object")
    strategies = temporary["strategies"]
    existing = next((item for item in strategies if (
        str(item.get("source_sha256") or "") == inspection["source_sha256"]
        and str(item.get("entrypoint") or "Strategy") == entrypoint
    )), None)
    if existing is None:
        existing = {
            "temp_ref": _new_ref("temporary-strategy"),
            "name": name,
            "entrypoint": entrypoint,
            "source_code": str(source_code),
            "source_sha256": inspection["source_sha256"],
            "hooks": inspection["hooks"],
            "requirements": deepcopy(requirements or {}),
        }
        strategies.append(existing)
    binding = {
        "binding_id": _new_ref("strategy-binding"),
        "target_strategy_id": target,
        "source": {"kind": "inline", "temp_ref": existing["temp_ref"]},
    }
    backtest["strategy_bindings"].append(binding)
    return {"strategy": deepcopy(existing), "binding": deepcopy(binding)}


def add_library(
    payload: dict[str, Any],
    *,
    strategy_ref: str,
    revision_ref: str,
    target_strategy_id: str,
    source_sha256: str = "",
) -> dict[str, Any]:
    _temporary, backtest = _sections(payload)
    strategy_ref = str(strategy_ref or "").strip()
    revision_ref = str(revision_ref or "").strip()
    target = _normalize_target(target_strategy_id)
    if not strategy_ref or not revision_ref or not target:
        raise ValueError("library strategy_ref, revision_ref, and target_strategy_id are required")
    if any(str(item.get("target_strategy_id") or "") == target
           for item in backtest["strategy_bindings"]):
        raise ValueError(f"strategy target already has a binding: {target}")
    binding = {
        "binding_id": _new_ref("strategy-binding"),
        "target_strategy_id": target,
        "source": {
            "kind": "library", "strategy_ref": strategy_ref,
            "revision_ref": revision_ref,
            **({"source_sha256": str(source_sha256)} if source_sha256 else {}),
        },
    }
    backtest["strategy_bindings"].append(binding)
    return {"binding": deepcopy(binding)}


def remove_binding(payload: dict[str, Any], binding_id: str) -> dict[str, Any]:
    temporary, backtest = _sections(payload)
    binding_id = str(binding_id or "").strip()
    bindings = backtest["strategy_bindings"]
    selected = next((item for item in bindings if item.get("binding_id") == binding_id), None)
    if selected is None:
        raise KeyError("strategy binding not found")
    bindings[:] = [item for item in bindings if item.get("binding_id") != binding_id]
    source = selected.get("source") or {}
    removed = None
    if source.get("kind") == "inline":
        temp_ref = source.get("temp_ref")
        still_used = any(
            (item.get("source") or {}).get("temp_ref") == temp_ref
            for item in bindings
        )
        if not still_used:
            removed = next((item for item in temporary["strategies"] if item.get("temp_ref") == temp_ref), None)
            temporary["strategies"][:] = [item for item in temporary["strategies"] if item.get("temp_ref") != temp_ref]
    return {"binding": deepcopy(selected), "removed_strategy": deepcopy(removed)}


def update_inline(
    payload: dict[str, Any],
    binding_id: str,
    *,
    name: str | None = None,
    source_code: str | None = None,
    entrypoint: str | None = None,
    requirements: dict[str, Any] | None = None,
) -> dict[str, Any]:
    temporary, backtest = _sections(payload)
    binding = next((item for item in backtest["strategy_bindings"] if item.get("binding_id") == binding_id), None)
    if binding is None or (binding.get("source") or {}).get("kind") != "inline":
        raise KeyError("inline strategy binding not found")
    temp_ref = str(binding["source"].get("temp_ref") or "")
    strategy = next((item for item in temporary["strategies"] if item.get("temp_ref") == temp_ref), None)
    if strategy is None:
        raise KeyError("temporary strategy not found")
    next_name = " ".join(str(name if name is not None else strategy.get("name") or "").split())
    if not next_name:
        raise ValueError("inline strategy name is required")
    next_entrypoint = normalize_entrypoint(entrypoint if entrypoint is not None else strategy.get("entrypoint"))
    next_source = str(source_code if source_code is not None else strategy.get("source_code") or "")
    inspection = inspect_source(next_source, next_entrypoint)
    strategy.update({
        "name": next_name,
        "entrypoint": next_entrypoint,
        "source_code": next_source,
        "source_sha256": inspection["source_sha256"],
        "hooks": inspection["hooks"],
    })
    if requirements is not None:
        if not isinstance(requirements, dict):
            raise ValueError("strategy requirements must be an object")
        strategy["requirements"] = deepcopy(requirements)
    return {"strategy": deepcopy(strategy), "binding": deepcopy(binding)}
