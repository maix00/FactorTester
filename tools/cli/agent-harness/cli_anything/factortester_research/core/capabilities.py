"""Capability-contract validation and deterministic graph binding."""

from __future__ import annotations

from copy import deepcopy
import hashlib
from importlib.resources import files
import json
import os
from pathlib import Path
import re
from typing import Any


_IMPLEMENTATION_KINDS = {"cli", "server", "skill", "library", "guidance"}
_APPROVAL_STATUSES = {
    "approved",
    "quarantined",
    "unavailable",
    "rejected",
    "superseded",
}
_EXECUTION_MODES = {"real_backend", "guidance_only", "external_service"}
_RESOLUTION_CACHE: dict[str, dict[str, Any]] = {}
_UNKNOWN = object()
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def load_builtin_capability_registry() -> dict[str, Any]:
    """Load the packaged, reviewable capability catalog."""
    resources = (
        files("cli_anything.factortester_research")
        .joinpath("resources")
    )
    registry = json.loads(
        resources.joinpath("capabilities.v1.json").read_text(encoding="utf-8")
    )
    registry["provider_lock"] = json.loads(
        resources.joinpath("provider-locks.v1.json").read_text(encoding="utf-8")
    )
    return validate_capability_registry(
        registry
    )


def validate_capability_registry(registry: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(registry, dict):
        raise ValueError("capability registry must be an object")
    if int(registry.get("schema_version") or 0) != 1:
        raise ValueError("unsupported capability registry schema_version")
    capabilities = registry.get("capabilities")
    if not isinstance(capabilities, list) or not all(
        isinstance(item, dict) for item in capabilities
    ):
        raise ValueError("capabilities must be an array of objects")
    ids = [str(item.get("capability_id") or "").strip() for item in capabilities]
    if any(not item for item in ids):
        raise ValueError("every capability requires capability_id")
    if len(set(ids)) != len(ids):
        raise ValueError("capability ids must be unique")
    provider_lock = registry.get("provider_lock")
    if provider_lock is not None:
        if not isinstance(provider_lock, dict):
            raise ValueError("provider_lock must be an object")
        if int(provider_lock.get("schema_version") or 0) != 1:
            raise ValueError("unsupported provider_lock schema_version")
        providers = provider_lock.get("providers")
        implementations = provider_lock.get("implementations")
        if not isinstance(providers, dict):
            raise ValueError("provider_lock.providers must be an object")
        if not isinstance(implementations, dict):
            raise ValueError(
                "provider_lock.implementations must be an object"
            )
        for implementation_id, source in implementations.items():
            if not isinstance(source, dict):
                raise ValueError(
                    f"provider source lock must be an object: {implementation_id}"
                )
            sha256 = str(source.get("sha256") or "")
            if not _SHA256_PATTERN.fullmatch(sha256):
                raise ValueError(
                    f"provider source lock requires sha256: {implementation_id}"
                )
    for capability in capabilities:
        capability_id = str(capability["capability_id"])
        if not str(capability.get("industry_semantics") or "").strip():
            raise ValueError(
                f"capability requires industry_semantics: {capability_id}"
            )
        for key in ("when_to_use", "preconditions", "prohibitions"):
            value = capability.get(key)
            if not isinstance(value, list) or not all(
                isinstance(item, str) and item.strip() for item in value
            ):
                raise ValueError(
                    f"{key} must contain non-empty strings: {capability_id}"
                )
        implementations = capability.get("implementations")
        if not isinstance(implementations, list) or not all(
            isinstance(item, dict) for item in implementations
        ):
            raise ValueError(
                f"implementations must be an array: {capability_id}"
            )
        implementation_ids = [
            str(item.get("implementation_id") or "").strip()
            for item in implementations
        ]
        if any(not item for item in implementation_ids):
            raise ValueError(
                f"every implementation requires implementation_id: "
                f"{capability_id}"
            )
        if len(set(implementation_ids)) != len(implementation_ids):
            raise ValueError(
                f"implementation ids must be unique within {capability_id}"
            )
        for implementation in implementations:
            implementation_id = str(implementation["implementation_id"])
            if str(implementation.get("kind") or "") not in _IMPLEMENTATION_KINDS:
                raise ValueError(f"invalid implementation kind: {implementation_id}")
            if (
                str(implementation.get("approval_status") or "")
                not in _APPROVAL_STATUSES
            ):
                raise ValueError(
                    f"invalid implementation approval_status: "
                    f"{implementation_id}"
                )
            if (
                str(implementation.get("execution_mode") or "")
                not in _EXECUTION_MODES
            ):
                raise ValueError(
                    f"invalid implementation execution_mode: "
                    f"{implementation_id}"
                )
            requires_approval = implementation.get(
                "requires_execution_approval",
                False,
            )
            if not isinstance(requires_approval, bool):
                raise ValueError(
                    "requires_execution_approval must be boolean: "
                    f"{implementation_id}"
                )
            product_scopes = implementation.get("product_scopes")
            if not isinstance(product_scopes, list) or not all(
                isinstance(item, str) and item.strip() for item in product_scopes
            ):
                raise ValueError(
                    f"implementation product_scopes must be non-empty strings: "
                    f"{implementation_id}"
                )
            approved_source_sha256 = implementation.get(
                "approved_source_sha256"
            )
            if approved_source_sha256 is not None and not (
                isinstance(approved_source_sha256, str)
                and _SHA256_PATTERN.fullmatch(approved_source_sha256)
            ):
                raise ValueError(
                    f"invalid approved_source_sha256: {implementation_id}"
                )
    return deepcopy(registry)


def _canonical_hash(value: Any) -> str:
    raw = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(raw).hexdigest()


def _semantic_facts(facts: dict[str, Any]) -> dict[str, Any]:
    """Remove runtime identity that must not alter deterministic semantics."""
    value = deepcopy(facts)
    runtime = value.get("runtime")
    if isinstance(runtime, dict):
        for key in ("model_id", "model_provider", "codex_version"):
            runtime.pop(key, None)
        if not runtime:
            value.pop("runtime", None)
    return value


def _source_lock(
    catalog: dict[str, Any],
    implementation: dict[str, Any],
) -> dict[str, Any] | None:
    inline_hash = implementation.get("approved_source_sha256")
    if inline_hash:
        return {
            "source_path": implementation.get("source_path"),
            "sha256": inline_hash,
        }
    provider_lock = catalog.get("provider_lock") or {}
    value = (provider_lock.get("implementations") or {}).get(
        str(implementation.get("implementation_id") or "")
    )
    return value if isinstance(value, dict) else None


def _resolve_source_path(
    catalog: dict[str, Any],
    implementation: dict[str, Any],
    source_lock: dict[str, Any],
) -> Path | None:
    source_path = str(
        source_lock.get("source_path")
        or implementation.get("source_path")
        or ""
    ).strip()
    if not source_path:
        return None
    path = Path(source_path).expanduser()
    if path.is_absolute():
        return path
    provider_id = str(implementation.get("provider") or "")
    provider = (
        (catalog.get("provider_lock") or {}).get("providers") or {}
    ).get(provider_id) or {}
    root_env = str(
        source_lock.get("root_env")
        or provider.get("root_env")
        or ""
    ).strip()
    root_value = os.environ.get(root_env) if root_env else None
    root = (
        root_value
        or source_lock.get("root_hint")
        or provider.get("root_hint")
    )
    if not root:
        return None
    return Path(str(root)).expanduser() / path


def _implementation_source_state(
    catalog: dict[str, Any],
    implementation: dict[str, Any],
) -> dict[str, Any]:
    """Probe only a selected candidate; never load the Skill body into context."""
    source_path = implementation.get("source_path")
    source_lock = _source_lock(catalog, implementation)
    if not source_path and source_lock is None:
        return {"status": "internal"}
    implementation_id = str(implementation.get("implementation_id") or "")
    if source_lock is None:
        return {
            "status": "unapproved",
            "implementation_id": implementation_id,
        }
    path = _resolve_source_path(catalog, implementation, source_lock)
    if path is None or not path.is_file():
        return {
            "status": "unavailable",
            "implementation_id": implementation_id,
            "expected_sha256": str(source_lock["sha256"]),
        }
    observed = hashlib.sha256(path.read_bytes()).hexdigest()
    expected = str(source_lock["sha256"])
    return {
        "status": "verified" if observed == expected else "mismatch",
        "implementation_id": implementation_id,
        "expected_sha256": expected,
        "observed_sha256": observed,
    }


def _candidate_source_states(
    *,
    capability_ids: list[str],
    contracts: dict[str, dict[str, Any]],
    catalog: dict[str, Any],
    product_group: str,
) -> dict[str, dict[str, Any]]:
    states: dict[str, dict[str, Any]] = {}
    for capability_id in sorted(set(capability_ids)):
        contract = contracts.get(capability_id) or {}
        for implementation in contract.get("implementations") or []:
            if implementation.get("approval_status") != "approved":
                continue
            scopes = implementation.get("product_scopes") or []
            if product_group not in scopes and "all" not in scopes:
                continue
            implementation_id = str(implementation["implementation_id"])
            states[implementation_id] = _implementation_source_state(
                catalog,
                implementation,
            )
    return states


def capability_descriptor(contract: dict[str, Any]) -> dict[str, str]:
    description = str(contract.get("industry_semantics") or "").strip()
    return {
        "capability_description": description,
        "descriptor_hash": _canonical_hash({
            "capability_id": str(contract.get("capability_id") or ""),
            "industry_semantics": description,
            "when_to_use": contract.get("when_to_use") or [],
            "preconditions": contract.get("preconditions") or [],
            "prohibitions": contract.get("prohibitions") or [],
        }),
    }


def _fact_value(facts: dict[str, Any], field: str) -> Any:
    value: Any = facts
    for part in field.split("."):
        if not isinstance(value, dict) or part not in value:
            return _UNKNOWN
        value = value[part]
    return value


def evaluate_capability_predicate(
    predicate: dict[str, Any],
    facts: dict[str, Any],
) -> bool | None:
    """Evaluate a bounded predicate; None means semantic judgment is needed."""
    if not isinstance(predicate, dict):
        raise ValueError("capability predicate must be an object")
    if "any" in predicate:
        values = [
            evaluate_capability_predicate(item, facts)
            for item in predicate["any"]
        ]
        if any(value is True for value in values):
            return True
        if all(value is False for value in values):
            return False
        return None
    if "all" in predicate:
        values = [
            evaluate_capability_predicate(item, facts)
            for item in predicate["all"]
        ]
        if any(value is False for value in values):
            return False
        if all(value is True for value in values):
            return True
        return None
    field = str(predicate.get("field") or "")
    if not field:
        raise ValueError("leaf predicate requires field")
    value = _fact_value(facts, field)
    if value is _UNKNOWN:
        return None
    if "equals" in predicate:
        return value == predicate["equals"]
    if "in" in predicate:
        choices = predicate["in"]
        if not isinstance(choices, list):
            raise ValueError("predicate in must be an array")
        return value in choices
    if "contains_any" in predicate:
        choices = predicate["contains_any"]
        if not isinstance(choices, list):
            raise ValueError("predicate contains_any must be an array")
        if not isinstance(value, (list, tuple, set)):
            return False
        return any(item in value for item in choices)
    raise ValueError("unsupported capability predicate operator")


def _resolve_capability_ids(
    *,
    capability_ids: list[str],
    contracts: dict[str, dict[str, Any]],
    product_group: str,
    grants: set[str],
    required_by: str,
    source_states: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    bindings: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []
    for capability_id in sorted(set(capability_ids)):
        contract = contracts.get(capability_id)
        if contract is None:
            gaps.append({
                "capability_id": capability_id,
                "reason": "capability_contract_missing",
                "required_by": required_by,
            })
            continue
        descriptor = capability_descriptor(contract)
        product_candidates = sorted(
            (
                implementation
                for implementation in contract["implementations"]
                if implementation["approval_status"] == "approved"
                and (
                    product_group in implementation["product_scopes"]
                    or "all" in implementation["product_scopes"]
                )
            ),
            key=lambda item: str(item["implementation_id"]),
        )
        if not product_candidates:
            gaps.append({
                "capability_id": capability_id,
                **descriptor,
                "reason": "approved_product_implementation_missing",
                "required_by": required_by,
            })
            continue
        verified_candidates = [
            implementation
            for implementation in product_candidates
            if source_states.get(
                str(implementation["implementation_id"]),
                {"status": "internal"},
            )["status"] in {"internal", "verified"}
        ]
        if not verified_candidates:
            source_state = source_states[
                str(product_candidates[0]["implementation_id"])
            ]
            reason_by_status = {
                "mismatch": "provider_fingerprint_mismatch",
                "unavailable": "provider_source_unavailable",
                "unapproved": "provider_source_fingerprint_unapproved",
            }
            gaps.append({
                "capability_id": capability_id,
                **descriptor,
                "reason": reason_by_status[source_state["status"]],
                **{
                    key: source_state[key]
                    for key in (
                        "implementation_id",
                        "expected_sha256",
                        "observed_sha256",
                    )
                    if key in source_state
                },
                "required_by": required_by,
            })
            continue
        candidates = [
            implementation
            for implementation in verified_candidates
            if not implementation.get("requires_execution_approval", False)
            or implementation["implementation_id"] in grants
        ]
        if not candidates:
            gaps.append({
                "capability_id": capability_id,
                **descriptor,
                "reason": "execution_approval_required",
                "candidate_implementation_ids": [
                    item["implementation_id"] for item in verified_candidates
                ],
                "required_by": required_by,
            })
            continue
        implementation = candidates[0]
        source_state = source_states.get(
            str(implementation["implementation_id"]),
            {"status": "internal"},
        )
        bindings.append({
            "capability_id": capability_id,
            **descriptor,
            "implementation_id": implementation["implementation_id"],
            "provider": str(implementation.get("provider") or ""),
            "kind": implementation["kind"],
            "execution_mode": implementation["execution_mode"],
            "execution_approval_granted": (
                implementation["implementation_id"] in grants
            ),
            **({
                "source_fingerprint": source_state["observed_sha256"],
            } if source_state["status"] == "verified" else {}),
            "required_by": required_by,
        })
    return bindings, gaps


def resolve_graph_capabilities(
    graph: dict[str, Any],
    registry: dict[str, Any],
    *,
    product_group: str,
    approved_implementation_ids: set[str] | None = None,
    node_id: str | None = None,
    facts: dict[str, Any] | None = None,
    triggered_capability_ids: set[str] | None = None,
    include_all: bool = False,
) -> dict[str, Any]:
    """Resolve only the current node unless full activation audit is explicit."""
    catalog = validate_capability_registry(registry)
    contracts = {
        str(item["capability_id"]): item
        for item in catalog["capabilities"]
    }
    grants = set(approved_implementation_ids or set())
    nodes = graph.get("nodes") or []
    selected_node_id = node_id or str(graph.get("entry_node") or "")
    if not selected_node_id and nodes:
        selected_node_id = str(nodes[0].get("node_id") or "")
    if include_all:
        selected_nodes = list(nodes)
        resolution_scope = "activation_audit"
    else:
        selected_nodes = [
            node for node in nodes
            if str(node.get("node_id") or "") == selected_node_id
        ]
        if not selected_nodes:
            raise ValueError(f"unknown graph node: {selected_node_id}")
        resolution_scope = "current_node"
    fact_payload = facts or {}
    semantic_fact_payload = _semantic_facts(fact_payload)
    explicit_triggers = set(triggered_capability_ids or set())
    required_ids = [
        capability_id
        for node in selected_nodes
        for capability_id in node.get("required_capabilities") or []
    ]
    edge_ids = [
        capability_id
        for edge in graph.get("edges") or []
        if include_all or str(edge.get("from_node") or "") in {
            selected_node_id,
            "*",
        }
        for capability_id in edge.get("required_capabilities") or []
    ]
    triggered_specs: list[dict[str, Any]] = []
    undetermined_specs: list[dict[str, Any]] = []
    for node in selected_nodes:
        for item in node.get("conditional_capabilities") or []:
            capability_id = str(item["capability_id"])
            outcome = (
                True
                if capability_id in explicit_triggers
                else evaluate_capability_predicate(
                    item.get("predicate") or {},
                    semantic_fact_payload,
                )
            )
            compact = {
                "capability_id": capability_id,
                "node_id": str(node.get("node_id") or ""),
                "explanation": str(item.get("explanation") or item.get("when") or ""),
            }
            if outcome is True:
                triggered_specs.append(compact)
            elif outcome is None:
                undetermined_specs.append(compact)
    all_selected_ids = (
        required_ids
        + edge_ids
        + [item["capability_id"] for item in triggered_specs]
    )
    source_states = _candidate_source_states(
        capability_ids=all_selected_ids,
        contracts=contracts,
        catalog=catalog,
        product_group=product_group,
    )
    semantic_cache_key = _canonical_hash({
        "graph": graph,
        "catalog": catalog,
        "product_group": product_group,
        "grants": sorted(grants),
        "selected_node_id": selected_node_id,
        "facts": semantic_fact_payload,
        "explicit_triggers": sorted(explicit_triggers),
        "include_all": include_all,
        "source_states": source_states,
    })
    cache_key = semantic_cache_key
    cached = _RESOLUTION_CACHE.get(cache_key)
    if cached is not None:
        result = deepcopy(cached)
        result["cache"]["hit"] = True
        return result
    bindings, gaps = _resolve_capability_ids(
        capability_ids=required_ids + edge_ids,
        contracts=contracts,
        product_group=product_group,
        grants=grants,
        required_by=(
            "all_graph_nodes" if include_all else selected_node_id
        ),
        source_states=source_states,
    )
    conditional_bindings, conditional_gaps = _resolve_capability_ids(
        capability_ids=[
            item["capability_id"] for item in triggered_specs
        ],
        contracts=contracts,
        product_group=product_group,
        grants=grants,
        required_by=selected_node_id,
        source_states=source_states,
    )
    result = {
        "catalog_id": str(catalog.get("catalog_id") or ""),
        "catalog_hash": _canonical_hash(catalog),
        "provider_conformance_hash": _canonical_hash(source_states),
        "product_group": product_group,
        "scope": resolution_scope,
        "node_id": selected_node_id,
        "bindings": bindings,
        "gaps": gaps,
        "triggered_conditional_bindings": conditional_bindings,
        "triggered_conditional_gaps": conditional_gaps,
        "undetermined_conditions": undetermined_specs,
        "requires_agent_judgment": bool(undetermined_specs),
        "semantic_cache_key": semantic_cache_key,
        "cache": {
            "key": cache_key,
            "hit": False,
            "scope": "process",
        },
    }
    _RESOLUTION_CACHE[cache_key] = deepcopy(result)
    return result
