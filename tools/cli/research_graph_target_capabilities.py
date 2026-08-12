"""Prepare a server-safe capability binding for one selected target node."""

from __future__ import annotations

from typing import Any

from cli_anything.factortester_research.core.capability_registry import (
    load_builtin_capability_registry,
)
from cli_anything.factortester_research.core.capability_resolution import (
    resolve_graph_capabilities,
)
from tools.cli.capability_projection import server_capability_resolution


_GUIDANCE = {
    "research-obligation.discover": {
        "mode": "discover",
        "skill_ref": "research-obligation-cycle",
        "instruction_zh": (
            "进入目标节点后立即登记可能改变研究决策的新义务"
        ),
        "discovery_sources": [
            "self_discovery",
            "grill",
            "external_audit",
        ],
        "category_policy": (
            "match_existing_category_or_register_explicitly_unclassified"
        ),
    },
}


def prepare_target_capabilities(
    target: dict[str, Any],
    *,
    product_group: str,
    resolution_output: str = "",
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Resolve exact server descriptors through the packaged local registry."""
    node_id = str(target.get("node_id") or "")
    required = [
        dict(item)
        for item in target.get("required") or []
        if isinstance(item, dict)
    ]
    capability_ids = [
        str(item.get("capability_id") or "") for item in required
    ]
    plan = {
        "node_id": node_id,
        "required_capability_ids": capability_ids,
        "resolution_required": bool(
            target.get("resolution_required") or required
        ),
        "resolution_output": resolution_output if required else "",
        "agent_guidance": [
            {
                "capability_id": capability_id,
                **_GUIDANCE[capability_id],
            }
            for capability_id in capability_ids
            if capability_id in _GUIDANCE
        ],
        "advance_option": (
            "--target-capability-resolution-file "
            + resolution_output
            if required and resolution_output else "automatic"
            if required else ""
        ),
    }
    if not required:
        return plan, None
    if not node_id:
        raise ValueError("target capability contract requires node_id")
    registry = load_builtin_capability_registry()
    local = resolve_graph_capabilities(
        {
            "entry_node": node_id,
            "nodes": [{
                "node_id": node_id,
                "required_capabilities": capability_ids,
                "conditional_capabilities": [],
            }],
            "edges": [],
        },
        registry,
        product_group=product_group,
        node_id=node_id,
    )
    if local.get("gaps"):
        reasons = ", ".join(
            f"{item.get('capability_id')}:{item.get('reason')}"
            for item in local["gaps"]
        )
        raise ValueError(
            "target capability resolution has local gaps: " + reasons
        )
    expected = {
        str(item.get("capability_id") or ""): item
        for item in required
    }
    for binding in local.get("bindings") or []:
        capability_id = str(binding.get("capability_id") or "")
        descriptor = expected.get(capability_id) or {}
        if any((
            binding.get("capability_description")
            != descriptor.get("capability_description"),
            binding.get("descriptor_hash")
            != descriptor.get("descriptor_hash"),
        )):
            raise ValueError(
                "target capability descriptor differs from local registry: "
                + capability_id
            )
    return plan, server_capability_resolution(local)
