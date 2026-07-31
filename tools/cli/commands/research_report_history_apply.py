"""Apply a validated Graph-history placement plan to one local report."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from tools.cli.release.research_reporting.authoring.tree_descriptor import (
    report_tree_descriptor,
    section_refs_from_snapshot,
)
from tools.cli.release.research_reporting.authoring.tree_model import (
    MAX_BATCH_OPERATIONS,
    apply_batch,
    load_snapshot,
)
from tools.cli.release.research_reporting.authoring.tree_system_mutations import (
    convert_system_section_to_special,
    move_system_component,
)
from tools.cli.release.research_reporting.git import commit_work_package

from .research_graph_local_report import persist_report_descriptor
from .research_graph_report_sync import synchronize_report_container
from .research_report_history_reparent import reparent_checkpoint_items
from .research_report_history_obligations import (
    obligation_change_operations,
)
from .research_report_history_obligation_parents import obligation_parents
from .research_report_history_requirement_sections import (
    migrate_requirement_sections,
)
from .research_report_history_cleanup import cleanup_legacy_chapters


def apply_history(
    local,
    *,
    branch_id: str,
    contexts: list[dict[str, Any]],
    component_hints: dict[str, str],
    component_parent_hints: dict[str, str],
    component_special_hints: dict[str, str],
    component_requirement_hints: dict[str, dict[str, str]],
    report_component_hints: dict[str, str],
    requirement_titles: dict[str, str] | None = None,
) -> dict[str, Any]:
    try:
        before_ids = _component_ids(local, branch_id)
    except (OSError, ValueError):
        before_ids = set()
    component_containers = _component_containers(
        contexts,
        report_component_hints=report_component_hints,
    )
    parents = {}
    parent_by_container = {}
    last_context_by_container = {
        _container_key(context["container"]): context
        for context in contexts
    }
    for context in contexts:
        container_key = _container_key(context["container"])
        if container_key not in parent_by_container:
            # One capability episode can occur in several immutable timeline
            # rows.  Synchronize its final projection once; replaying each
            # intermediate status would only churn authoring generations while
            # leaving the final report tree unchanged.
            sync = synchronize_report_container(
                local,
                container=last_context_by_container[container_key][
                    "container"
                ],
                component_hints=component_hints,
                commit=False,
            )
            parent_by_container[container_key] = str(sync["component_id"])
        if context["side"] == "target":
            parents[context["step_ref"]] = parent_by_container[container_key]
    authoritative_parents = {
        component_id: parent_by_container[container_key]
        for component_id, container_key in component_containers.items()
    }
    system_owned_components = {
        *parent_by_container.values(),
        *authoritative_parents,
    }
    ignored_parent_hints = sorted(
        set(component_parent_hints) & system_owned_components
    )
    manual_parent_hints = {
        component_id: parent_id
        for component_id, parent_id in component_parent_hints.items()
        if component_id not in system_owned_components
    }
    historical_parents = {
        **manual_parent_hints,
        **authoritative_parents,
    }
    placement = reparent_checkpoint_items(
        package_root=local.package_root, branch_id=branch_id,
        parent_by_checkpoint=parents,
        parent_by_component=historical_parents,
    )
    interim = load_snapshot(
        package_root=local.package_root, branch_id=branch_id,
    )
    obligation_parent_map, obligation_parent_fallbacks = obligation_parents(
        contexts=contexts,
        fallback_by_step=parents,
        snapshot=interim,
    )
    bindings_by_component: dict[str, list[dict[str, Any]]] = {}
    for binding in interim["bindings"]:
        value = deepcopy(binding)
        component_id = str(value.pop("component_id"))
        bindings_by_component.setdefault(component_id, []).append(value)
    obligation_ops, obligation_episodes = obligation_change_operations(
        contexts,
        parent_by_step=obligation_parent_map,
        components={
            str(item["component_id"]): {
                **deepcopy(item),
                "bindings": bindings_by_component.get(
                    str(item["component_id"]), [],
                ),
            }
            for item in interim["components"]
        },
    )
    for offset in range(0, len(obligation_ops), MAX_BATCH_OPERATIONS):
        apply_batch(
            package_root=local.package_root,
            branch_id=branch_id,
            operations=obligation_ops[
                offset:offset + MAX_BATCH_OPERATIONS
            ],
            include_snapshot=False,
        )
    requirement_sections = migrate_requirement_sections(
        package_root=local.package_root,
        branch_id=branch_id,
        contexts=contexts,
        requirement_titles=requirement_titles,
        component_requirement_hints=component_requirement_hints,
    )
    canonical_component_ids = {
        component_id
        for container_key, component_id in parent_by_container.items()
        if container_key[0] == "chapter"
    }
    canonical_component_ids.update(_bound_anchor_chapters(
        interim,
        anchor_nodes={
            str(context["container"]["anchor_node"])
            for context in contexts
        },
    ))
    cleanup = cleanup_legacy_chapters(
        package_root=local.package_root,
        branch_id=branch_id,
        canonical_component_ids=canonical_component_ids,
    )
    if cleanup["unresolved_legacy_chapters"]:
        raise ValueError(
            "legacy report chapters still contain unmapped content: "
            + ", ".join(cleanup["unresolved_legacy_chapters"])
        )
    manual = _apply_component_hints(
        local.package_root,
        branch_id=branch_id,
        parent_hints=manual_parent_hints,
        special_hints=component_special_hints,
    )
    git = commit_work_package(
        local.package_root,
        message="Reconcile Graph report history",
    )
    snapshot = load_snapshot(
        package_root=local.package_root, branch_id=branch_id,
    )
    persist_report_descriptor(local, report_tree_descriptor(
        package_root=local.package_root,
        work_package_id=local.record["record_id"],
        branch_id=branch_id, head=snapshot["head"],
        section_refs=section_refs_from_snapshot(snapshot),
    ))
    return {
        "mode": "applied",
        "created_container_count": len(
            _ids(snapshot["components"]) - before_ids
        ),
        "moved_item_count": len(placement["moved"]),
        "obligation_change_episode_count": obligation_episodes,
        "obligation_change_operation_count": len(obligation_ops),
        "obligation_parent_fallbacks": obligation_parent_fallbacks,
        "requirement_section_migration": requirement_sections,
        "legacy_cleanup": cleanup,
        "manual_component_migration": manual,
        "ignored_system_parent_hints": ignored_parent_hints,
        "placement": placement, "git": git,
    }


def _component_ids(local, branch_id: str) -> set[str]:
    return _ids(load_snapshot(
        package_root=local.package_root, branch_id=branch_id,
    )["components"])


def _ids(components: list[dict[str, Any]]) -> set[str]:
    return {str(item["component_id"]) for item in components}


def _bound_anchor_chapters(
    snapshot: dict[str, Any],
    *,
    anchor_nodes: set[str],
) -> set[str]:
    """Preserve inherited node chapters during detour-only continuations."""
    components = {
        str(item["component_id"]): item
        for item in snapshot["components"]
    }
    result = set()
    for binding in snapshot["bindings"]:
        target_ref = str(binding.get("target_ref") or "")
        data = binding.get("data") or {}
        component_id = str(binding.get("component_id") or "")
        component = components.get(component_id) or {}
        if (
            binding.get("kind") == "graph_reference"
            and data.get("role") == "report_chapter"
            and target_ref.startswith("node:")
            and target_ref.removeprefix("node:") in anchor_nodes
            and component.get("kind") == "chapter"
            and component.get("parent_id") is None
        ):
            result.add(component_id)
    return result


def _component_containers(
    contexts: list[dict[str, Any]],
    *,
    report_component_hints: dict[str, str],
) -> dict[str, tuple[str, ...]]:
    targets: dict[str, tuple[str, ...]] = {}
    for context in contexts:
        if context["side"] != "target":
            continue
        key = _container_key(context["container"])
        for historical_id in context["report_component_ids"]:
            component_id = report_component_hints.get(
                historical_id, historical_id,
            )
            previous = targets.setdefault(component_id, key)
            if previous != key:
                raise ValueError(
                    "historical report component maps to multiple containers: "
                    f"report:{component_id}"
                )
    return targets


def _container_key(container: dict[str, Any]) -> tuple[str, ...]:
    kind = str(container["kind"])
    anchor = str(container["anchor_node"])
    if kind == "chapter":
        return kind, anchor
    return kind, anchor, str(container["detour"]["episode_id"])


def _apply_component_hints(
    package_root,
    *,
    branch_id: str,
    parent_hints: dict[str, str],
    special_hints: dict[str, str],
) -> dict[str, list[str]]:
    moved: list[str] = []
    converted: list[str] = []
    snapshot = load_snapshot(
        package_root=package_root, branch_id=branch_id,
    )
    components = {
        item["component_id"]: item for item in snapshot["components"]
    }
    for component_id, parent_id in parent_hints.items():
        component = components.get(component_id)
        if component is None or parent_id not in components:
            raise ValueError(
                "manual report placement references an absent component: "
                f"{component_id} -> {parent_id}"
            )
        if component["parent_id"] == parent_id:
            continue
        move_system_component(
            package_root=package_root,
            branch_id=branch_id,
            component_id=component_id,
            parent_id=parent_id,
        )
        component["parent_id"] = parent_id
        moved.append(component_id)
    for component_id, display_kind in special_hints.items():
        component = components.get(component_id)
        if component is None:
            raise ValueError(
                "manual special conversion references an absent component: "
                + component_id
            )
        if (
            component["kind"] == "special"
            and component["display_kind"] == display_kind
        ):
            continue
        convert_system_section_to_special(
            package_root=package_root,
            branch_id=branch_id,
            component_id=component_id,
            display_kind=display_kind,
        )
        component["kind"] = "special"
        component["display_kind"] = display_kind
        converted.append(component_id)
    return {"moved": moved, "converted": converted}
