"""Compact Agent instructions derived from one continuation preview."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


def with_agent_plan(preview: dict[str, Any]) -> dict[str, Any]:
    """Attach ordering guidance without changing the server authorization body."""
    value = deepcopy(preview)
    descriptor = value.get("descriptor") or {}
    preflight = descriptor.get("requirement_preflight") or {}
    detour = descriptor.get("capability_detour") or {}
    current_node = str(descriptor.get("target_node") or "")
    resume_node = str(detour.get("resume_node") or "")
    immediate = _text_ids(preflight.get("assessment_required_ids"))
    value["agent_plan"] = {
        "schema_version": 1,
        "sequence": [
            {
                "order": 1,
                "action": "assess_current_node_reentry",
                "node_id": current_node,
                "requirement_ids": immediate,
                "required": bool(immediate),
            },
            {
                "order": 2,
                "action": "complete_existing_capability_detour",
                "required": bool(resume_node),
                "resume_node": resume_node,
            },
            {
                "order": 3,
                "action": "resume_original_node",
                "required": bool(resume_node),
                "node_id": resume_node,
            },
            {
                "order": 4,
                "action": "assess_node_local_upgrade_requirements",
                "scope": "when_each_owning_node_is_entered",
            },
        ],
        "capability_detour_policy": {
            "episode": "retain_existing",
            "nested_detour": "forbidden",
            "new_detour": "only_after_existing_episode_is_closed",
        },
        "next_packet_command": (
            "factortester research graphs node info "
            "<target-instance-id> <target-branch-id>"
        ),
    }
    return value


def _text_ids(value: Any) -> list[str]:
    return sorted({str(item) for item in value or [] if str(item)})
