"""Apply a validated Graph-history placement plan to one local report."""

from __future__ import annotations

from typing import Any

from tools.cli.release.research_reporting.authoring.tree_descriptor import (
    report_tree_descriptor,
    section_refs_from_snapshot,
)
from tools.cli.release.research_reporting.authoring.tree_model import load_snapshot
from tools.cli.release.research_reporting.git import commit_work_package

from .research_graph_local_report import persist_report_descriptor
from .research_graph_report_sync import synchronize_report_container
from .research_report_history_reparent import reparent_checkpoint_items


def apply_history(
    local,
    *,
    branch_id: str,
    contexts: list[dict[str, Any]],
    component_hints: dict[str, str],
) -> dict[str, Any]:
    try:
        before_ids = _component_ids(local, branch_id)
    except (OSError, ValueError):
        before_ids = set()
    component_containers = _component_containers(contexts)
    parents = {}
    parent_by_container = {}
    for context in contexts:
        sync = synchronize_report_container(
            local, container=context["container"],
            component_hints=component_hints, commit=False,
        )
        parent_by_container[_container_key(context["container"])] = str(
            sync["component_id"]
        )
        if context["side"] == "target":
            parents[context["step_ref"]] = str(sync["component_id"])
    placement = reparent_checkpoint_items(
        package_root=local.package_root, branch_id=branch_id,
        parent_by_checkpoint=parents,
        parent_by_component={
            component_id: parent_by_container[container_key]
            for component_id, container_key in component_containers.items()
        },
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
        "placement": placement, "git": git,
    }


def _component_ids(local, branch_id: str) -> set[str]:
    return _ids(load_snapshot(
        package_root=local.package_root, branch_id=branch_id,
    )["components"])


def _ids(components: list[dict[str, Any]]) -> set[str]:
    return {str(item["component_id"]) for item in components}


def _component_containers(
    contexts: list[dict[str, Any]],
) -> dict[str, tuple[str, ...]]:
    targets: dict[str, tuple[str, ...]] = {}
    for context in contexts:
        if context["side"] != "target":
            continue
        key = _container_key(context["container"])
        for component_id in context["report_component_ids"]:
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
