"""One-time, server-authoritative Graph report hierarchy reconciliation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import click

from tools.cli.core.context import client_from_config
from tools.cli.release.profile import load_profile_root

from .research_graph_local_report import (
    resolve_local_graph_report,
)
from .research_graph_report_policy import report_container
from .research_report_common import output, scope_options
from .research_report_history_apply import apply_history
from .research_report_history_map import load_history_map
from .research_report_history_obligations import (
    obligation_change_operations,
)
from .research_report_history_timeline import history_contexts, load_history
from .research_report_scope import resolve_branch_report_scope


@click.command("reconcile-graph-history")
@scope_options
@click.option(
    "--component-map-file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option("--apply", "apply_changes", is_flag=True)
@click.option("--json", "as_json", is_flag=True)
def reconcile_graph_history(
    profile_id: str,
    work_package_id: str,
    branch_id: str,
    release_profile: Path | None,
    component_map_file: Path | None,
    apply_changes: bool,
    as_json: bool,
) -> None:
    """Plan or apply missing Graph chapters and checkpoint-item placement."""
    try:
        result = _reconcile(
            profile_id=profile_id, work_package_id=work_package_id,
            branch_id=branch_id, release_profile=release_profile,
            component_map_file=component_map_file, apply_changes=apply_changes,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    output(result, as_json)


def _reconcile(
    *,
    profile_id: str, work_package_id: str, branch_id: str,
    release_profile: Path | None, component_map_file: Path | None,
    apply_changes: bool,
    client: Any | None = None,
) -> dict[str, Any]:
    client_root = load_profile_root(release_profile)
    branch = resolve_branch_report_scope(
        client_root=client_root, profile_id=profile_id,
        work_package_id=work_package_id, branch_id=branch_id,
    )
    instance_id = _graph_instance(branch.branch_ref, branch_id)
    local = resolve_local_graph_report(
        client_root=client_root, profile_id=profile_id,
        agent_id=str(branch.record["agent_id"]),
        instance_id=instance_id, branch_id=branch_id,
    )
    remote = client or client_from_config()
    items = load_history(
        remote,
        work_package_ref=str(local.record["graph_instance_ref"]),
        branch_id=branch_id,
    )
    contexts = history_contexts(items)
    current_packet: dict[str, Any] | None = None
    if not contexts:
        current_packet = remote.get_research_graph_node_info(
            instance_id, branch_id,
        )
        contexts = [{
            "step_ref": "", "side": "current",
            "packet": current_packet,
            "report_component_ids": [],
        }]
    normalized = [
        {
            **context,
            "container": (
                context["container"]
                if "container" in context
                else report_container(context["packet"])
            ),
        }
        for context in contexts
    ]
    episode_ids = {
        context["container"]["detour"]["episode_id"]
        for context in normalized
        if "detour" in context["container"]
    }
    mapping = load_history_map(
        component_map_file, episode_ids=episode_ids,
    )
    plan = _plan(normalized, episode_ids, apply_changes)
    if not apply_changes:
        return plan
    historical_ids = _historical_requirement_ids(normalized)
    required_ids = historical_ids
    existing_titles = _context_requirement_titles(normalized)
    missing_title_ids = required_ids - set(existing_titles)
    if missing_title_ids and current_packet is None:
        current_packet = remote.get_research_graph_node_info(
            instance_id, branch_id,
        )
    requirement_titles = {
        **existing_titles,
        **_migration_requirement_titles(
            remote,
            packet=current_packet or {},
            required_ids=missing_title_ids,
        ),
    }
    normalized = _with_requirement_presentations(
        normalized, requirement_titles=requirement_titles,
    )
    _preflight_obligation_history(normalized)
    return {**plan, **apply_history(
        local, branch_id=branch_id, contexts=normalized,
        component_hints=mapping["episode_components"],
        component_parent_hints=mapping["component_parents"],
        component_special_hints=mapping["component_special_kinds"],
    )}


def _preflight_obligation_history(
    contexts: list[dict[str, Any]],
) -> None:
    """Reject invalid historical obligations before source-tree mutations."""
    obligation_change_operations(
        contexts,
        parent_by_step={
            str(context["step_ref"]): "history-preflight-parent"
            for context in contexts
            if (
                context.get("side") == "target"
                and context.get("obligation_changes")
            )
        },
        components={},
    )


def _plan(contexts, episode_ids: set[str], apply_changes: bool) -> dict[str, Any]:
    chapters = list(dict.fromkeys(
        item["container"]["anchor_node"] for item in contexts
    ))
    return {
        "schema_version": 1,
        "mode": "applied" if apply_changes else "plan",
        "context_count": len(contexts),
        "chapter_nodes": chapters,
        "capability_episode_refs": sorted(episode_ids),
        "report_component_count": len({
            component_id
            for context in contexts
            for component_id in context["report_component_ids"]
        }),
        "obligation_change_episode_count": sum(
            bool(context.get("obligation_changes"))
            for context in contexts
            if context.get("side") == "target"
        ),
        "obligation_change_count": sum(
            len(context.get("obligation_changes") or [])
            for context in contexts
            if context.get("side") == "target"
        ),
    }


def _graph_instance(branch_ref: str, branch_id: str) -> str:
    parts = branch_ref.split(":")
    if len(parts) != 3 or parts[0] != "graph-branch" or parts[2] != branch_id:
        raise ValueError("historical reconciliation requires a Graph branch")
    return parts[1]


def _migration_requirement_titles(
    client: Any,
    *,
    packet: dict[str, Any],
    required_ids: set[str],
) -> dict[str, str]:
    if not required_ids:
        return {}
    graph_ref = str(packet.get("graph") or "")
    marker = graph_ref.rfind("@v")
    if marker <= 0 or not graph_ref[marker + 2:].isdigit():
        raise ValueError(
            "current research branch has no exact Graph version"
        )
    graph_id = graph_ref[:marker]
    version = int(graph_ref[marker + 2:])
    graph = next((
        item for item in client.list_research_graph_versions(graph_id)
        if int(item.get("version") or 0) == version
    ), None)
    if graph is None:
        raise ValueError(
            f"server has no immutable Graph source for {graph_ref}"
        )
    catalog = graph.get("requirement_catalog") or {}
    titles = {
        str(item.get("requirement_id") or ""): str(
            item.get("title_zh") or ""
        ).strip()
        for item in catalog.get("requirements") or []
        if isinstance(item, dict)
    }
    missing = sorted(
        requirement_id for requirement_id in required_ids
        if not titles.get(requirement_id)
    )
    if missing:
        raise ValueError(
            "immutable Graph requirement catalog has no title_zh: "
            + ", ".join(missing)
        )
    return {
        requirement_id: titles[requirement_id]
        for requirement_id in sorted(required_ids)
    }


def _historical_requirement_ids(
    contexts: list[dict[str, Any]],
) -> set[str]:
    return {
        str(requirement_id).removeprefix("requirement:")
        for context in contexts
        for change in context.get("obligation_changes") or []
        for requirement_id in [
            *(change.get("from_requirement_refs") or []),
            *(change.get("to_requirement_refs") or []),
        ]
        if str(requirement_id)
    }


def _context_requirement_titles(
    contexts: list[dict[str, Any]],
) -> dict[str, str]:
    return {
        str(item.get("requirement_id") or "").removeprefix(
            "requirement:"
        ): str(item.get("title_zh") or "").strip()
        for context in contexts
        for item in context.get("requirement_presentations") or []
        if (
            isinstance(item, dict)
            and str(item.get("requirement_id") or "")
            and str(item.get("title_zh") or "").strip()
        )
    }


def _with_requirement_presentations(
    contexts: list[dict[str, Any]],
    *,
    requirement_titles: dict[str, str],
) -> list[dict[str, Any]]:
    if not requirement_titles:
        return contexts
    values = []
    for context in contexts:
        existing = {
            str(item.get("requirement_id") or "").removeprefix(
                "requirement:"
            ): item
            for item in context.get("requirement_presentations") or []
            if isinstance(item, dict)
        }
        needed = {
            str(requirement_id).removeprefix("requirement:")
            for change in context.get("obligation_changes") or []
            for requirement_id in [
                *(change.get("from_requirement_refs") or []),
                *(change.get("to_requirement_refs") or []),
            ]
            if str(requirement_id)
        }
        presentations = [dict(item) for item in existing.values()]
        presentations.extend({
            "requirement_id": requirement_id,
            "title_zh": requirement_titles[requirement_id],
        } for requirement_id in sorted(needed - set(existing)))
        values.append({
            **context,
            "requirement_presentations": presentations,
        })
    return values
