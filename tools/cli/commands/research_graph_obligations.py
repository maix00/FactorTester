"""Branch-local obligation ledger commands for research agents."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
from typing import Any

import click

from tools.cli.client import FactorTesterClient
from tools.cli.http import HttpSession
from tools.cli.release.local_profile import LocalProfileStore
from tools.cli.release.profile import load_profile_root
from tools.cli.release.research_obligations import (
    append_event,
    apply_obligation_deltas,
    branch_identity,
    canonicalize_ledger,
    initialize_ledger,
    ledger_hash,
    ledger_from_history,
    ledger_path,
    load_ledger,
    obligations as packet_obligations,
    project_requirement_coverage,
    requirement_union,
    requirements as packet_requirements,
    write_ledger,
)
from tools.cli.release.research_obligations.reporting import (
    edge_coverage_operation,
    edge_selection_operation,
    obligation_change_operations,
)
from tools.cli.release.research_reporting.authoring.submission_begin import (
    begin_submission,
)
from tools.cli.release.research_reporting.authoring.tree_model import (
    apply_batch,
)
from tools.cli.release.research_reporting.authoring.tree_store import (
    load_head,
)
from tools.cli.release.research_reporting.authoring.tree_paths import (
    report_tree_paths,
)

from .research_graph_local_report import resolve_local_graph_report
from .research_graph_report_policy import report_container
from .research_graph_chapter_reconciliation import (
    reconcile_current_container,
)
from .research_report_scope import (
    load_current_authoring,
    resolve_branch_report_scope,
)
from .research_report_submission_finalize import finalize_report_command
from .research_report_submission_preflight import checked_component_preflight
from .research_report_history_timeline import (
    load_history,
    obligation_history_contexts,
)
from tools.cli.release.research_reporting.git import commit_work_package


def register_obligation_commands(parent: click.Group) -> None:
    obligation = click.Group(
        "obligation",
        help="登记、检查并提交当前研究分支的义务变化",
    )
    parent.add_command(obligation)

    @obligation.command("status")
    @_scope_options
    def status(
        instance_id: str,
        branch_id: str,
        profile_id: str,
        agent_id: str,
        release_profile: Path | None,
    ) -> None:
        """读取或从当前服务器投影初始化单文件义务账本。"""
        scope, packet = _scope(
            instance_id, branch_id, profile_id, agent_id, release_profile,
        )
        ledger = _load_or_initialize(scope, packet)
        click.echo(_json({
            "ledger_file": str(ledger_path(scope.package_root, branch_id)),
            "generation": ledger["generation"],
            "branch": ledger["branch"],
            "current_projection": ledger["current_projection"],
        }))
    _register_change_command(obligation)
    _register_history_migration_command(obligation)


def record_edge_selection(
    *,
    instance_id: str,
    branch_id: str,
    edge_id: str,
    profile_id: str,
    agent_id: str,
    release_profile: Path | None,
    reason_markdown: str,
    submission_sequence: int | None = None,
) -> dict[str, Any]:
    scope, packet = _scope(
        instance_id, branch_id, profile_id, agent_id, release_profile,
    )
    client_root = load_profile_root(release_profile)
    profile = LocalProfileStore(client_root).load(profile_id)
    client = FactorTesterClient(HttpSession(profile["server"]["base_url"]))
    edge_packet = client.get_research_graph_edge_info(
        instance_id, branch_id, edge_id,
    )
    ledger = _load_or_initialize(scope, packet)
    selected_edge = {
        "edge_id": edge_id,
        "target_node": str(
            (edge_packet.get("edge") or {}).get("to_node") or ""
        ),
        "state_ref": str(edge_packet.get("state_ref") or ""),
        "transition_contract": deepcopy(edge_packet.get("edge") or {}),
        "required_requirement_ids": [
            str(item["requirement_id"])
            for item in (
                (edge_packet.get("edge") or {}).get(
                    "obligation_requirements",
                )
                or []
            )
        ],
    }
    latest_edge_event = next((
        item for item in reversed(ledger["history"])
        if item.get("event_type") == "edge_selected"
    ), None)
    if (
        ledger["current_projection"]["selected_edge"] == selected_edge
        and (latest_edge_event or {}).get("reason_markdown") == reason_markdown
    ):
        return {
            "selected_edge_id": edge_id,
            "state_changed": False,
            "server_state_changed": False,
            "ledger_generation": ledger["generation"],
            "coverage": ledger["current_projection"]["requirement_coverage"],
            "edge": edge_packet.get("edge") or {},
            "report_requirements": edge_packet.get("report_requirements") or [],
            "next_actions": edge_packet.get("next_actions") or [],
        }
    event_id = _event_id(
        ledger["current_projection"]["projection_hash"],
        {
            "selected_edge": selected_edge,
            "reason_markdown": reason_markdown,
        },
    )
    changed_refs = _latest_changed_refs(ledger)
    requirements = requirement_union(packet, edge_packet)
    node_requirement_ids = {
        str(item["requirement_id"])
        for item in packet_requirements(packet)
    }
    coverage = project_requirement_coverage(
        requirements=requirements,
        obligations=ledger["current_projection"]["obligations"],
        changed_obligation_refs=changed_refs,
        edge_required_ids=set(selected_edge["required_requirement_ids"]),
        node_required_ids=node_requirement_ids,
    )
    next_ledger = deepcopy(ledger)
    next_ledger["current_projection"]["selected_edge"] = selected_edge
    next_ledger["current_projection"]["requirement_coverage"] = coverage
    next_ledger = append_event(
        next_ledger,
        event_type="edge_selected",
        event_id=event_id,
        payload={
            **selected_edge,
            "reason_markdown": reason_markdown,
            "coverage_snapshot": coverage,
            "updated_requirement_table_id": (
                _latest_requirement_table_id(ledger)
            ),
            "report_components": {},
        },
    )
    chapter = reconcile_current_container(
        scope, container=report_container(packet),
    )
    event = next_ledger["history"][-1]
    path_operation, path_component_id = edge_selection_operation(
        event=event,
        parent_id=str(chapter["component_id"]),
    )
    bindings, diagnostics = checked_component_preflight(
        scope=_report_scope(scope),
        component_id=path_component_id,
        kind="special",
        title=str(path_operation["title"]),
        body=str(path_operation["body"]),
        content=path_operation["content"],
        display_kind="path_selection",
    )
    if diagnostics:
        first = diagnostics[0]
        raise click.ClickException(
            "edge selection rich text failed report preflight: "
            f"{first['field']} {first['line']}:{first['column']} "
            f"{first['message']}; rule: {first['rule']}; "
            f"example: {first['example']}"
        )
    path_operation["bindings"] = bindings
    event["report_components"] = {
        "path_selection_id": path_component_id,
        "requirement_table_id": _latest_requirement_table_id(ledger),
    }
    next_ledger = canonicalize_ledger(next_ledger)
    obligation_event = _latest_obligation_event(ledger)
    if obligation_event is None:
        raise click.ClickException(
            "edge selection requires a prior obligation change report"
        )
    table_id = _latest_requirement_table_id(ledger)
    if not table_id:
        raise click.ClickException(
            "latest obligation change has no requirement coverage table"
        )
    coverage_operation, expected_table_id = edge_coverage_operation(
        event_id=str(obligation_event["event_id"]),
        parent_id=str(
            (obligation_event.get("report_components") or {})["special_id"]
        ),
        coverage=coverage,
        replace=True,
    )
    if table_id != expected_table_id:
        raise click.ClickException(
            "latest obligation requirement table identity is invalid"
        )
    operations = [path_operation, coverage_operation]
    sidecar = {
        "path": "obligations.json",
        "base_generation": ledger["generation"],
        "next_generation": next_ledger["generation"],
        "next_hash": ledger_hash(next_ledger),
        "next_value": next_ledger,
    }
    submission = begin_submission(
        package_root=scope.package_root,
        branch_id=branch_id,
        requested_sequence=submission_sequence,
        logical_identity={
            "kind": "edge_selected",
            "event_id": event_id,
            "path_selection_id": path_component_id,
            "requirement_table_id": table_id,
        },
        payload={"operations": operations, "ledger_hash": sidecar["next_hash"]},
        sidecars=[sidecar],
    )
    write_ledger(scope.package_root, branch_id, next_ledger)
    apply_batch(
        package_root=scope.package_root,
        branch_id=branch_id,
        operations=operations,
        include_snapshot=False,
        submission=submission,
    )
    report_scope = _report_scope(scope)
    authoring = load_current_authoring(report_scope)
    finalized = finalize_report_command(
        scope=report_scope,
        submission=submission,
        descriptor=authoring["descriptor"],
        message="Select research Graph edge",
        as_json=True,
    )
    return {
        "selected_edge_id": edge_id,
        "state_changed": True,
        "server_state_changed": False,
        "ledger_generation": next_ledger["generation"],
        "coverage": coverage,
        "path_selection_id": path_component_id,
        "updated_requirement_table_id": table_id,
        "git": finalized["git"],
        "edge": edge_packet.get("edge") or {},
        "report_requirements": edge_packet.get("report_requirements") or [],
        "next_actions": edge_packet.get("next_actions") or [],
    }

def _register_change_command(obligation: click.Group) -> None:
    @obligation.command("change")
    @_scope_options
    @click.option(
        "--change-file",
        required=True,
        type=click.Path(exists=True, dir_okay=False, path_type=Path),
        help="义务变化、Research Cycle 提交和预期账本 hash",
    )
    @click.option(
        "--submission-sequence",
        type=click.IntRange(min=1),
        default=None,
        help="修正或恢复被拦截提交时复用的报告提交序号",
    )
    def change(
        instance_id: str,
        branch_id: str,
        profile_id: str,
        agent_id: str,
        release_profile: Path | None,
        change_file: Path,
        submission_sequence: int | None,
    ) -> None:
        """原子登记义务变化、解释、三张报告表与 Work Package Git 提交。"""
        scope, packet = _scope(
            instance_id, branch_id, profile_id, agent_id, release_profile,
        )
        payload = _read_change(change_file)
        ledger = _load_or_initialize(scope, packet)
        expected = str(payload["expected_projection_hash"])
        event_id = _event_id(expected, payload)
        existing = next((
            item for item in ledger["history"]
            if item["event_id"] == event_id
        ), None)
        if existing is None:
            if ledger["current_projection"]["projection_hash"] != expected:
                raise click.ClickException(
                    "obligation ledger projection is stale; run "
                    "research-graph obligation status and rebuild the change"
                )
            obligations, changed = apply_obligation_deltas(
                ledger["current_projection"]["obligations"],
                payload["obligation_delta"],
            )
            requirements = packet_requirements(packet)
            selected = ledger["current_projection"]["selected_edge"]
            coverage = project_requirement_coverage(
                requirements=requirements,
                obligations=obligations,
                changed_obligation_refs=changed,
                edge_required_ids=_edge_requirement_ids(selected),
            )
            chapter = reconcile_current_container(
                scope, container=report_container(packet),
            )
            paths = report_tree_paths(scope.package_root, branch_id)
            report_sequence = load_head(paths)["generation"] + 1
            next_ledger = deepcopy(ledger)
            next_ledger["current_projection"]["obligations"] = obligations
            next_ledger["current_projection"]["requirement_coverage"] = coverage
            next_ledger = append_event(
                next_ledger,
                event_type="obligation_change",
                event_id=event_id,
                payload={
                    "agent_id": scope.agent_id,
                    "node_id": ledger["branch"]["current_node"],
                    "report_submission_sequence": report_sequence,
                    "reason_markdown": payload["reason_markdown"],
                    "obligation_delta": payload["obligation_delta"],
                    "research_cycle": payload["research_cycle"],
                    "obligation_presentations": payload[
                        "obligation_presentations"
                    ],
                    "obligations_snapshot": obligations,
                    "coverage_snapshot": coverage,
                    "report_components": {},
                },
            )
            event = next_ledger["history"][-1]
            operations, component_ids = obligation_change_operations(
                event=event,
                parent_id=str(chapter["component_id"]),
            )
            event["report_components"] = component_ids
            ledger = canonicalize_ledger(next_ledger)
        else:
            ledger = load_ledger(scope.package_root, branch_id)
            event = existing
            chapter = reconcile_current_container(
                scope, container=report_container(packet),
            )
            operations, component_ids = obligation_change_operations(
                event=event,
                parent_id=str(chapter["component_id"]),
            )
            if event.get("report_components") != component_ids:
                raise click.ClickException(
                    "obligation event report component identity is invalid"
                )
        special = operations[0]
        bindings, diagnostics = checked_component_preflight(
            scope=_report_scope(scope),
            component_id=str(special["component_id"]),
            kind="special",
            title=str(special["title"]),
            body=str(special["body"]),
            content=special["content"],
            display_kind="obligation_changes",
        )
        if diagnostics:
            first = diagnostics[0]
            raise click.ClickException(
                "obligation explanation failed report preflight: "
                f"{first['field']} {first['line']}:{first['column']} "
                f"{first['message']}; rule: {first['rule']}; "
                f"example: {first['example']}"
            )
        special["bindings"] = bindings
        sidecar = {
            "path": "obligations.json",
            "base_generation": ledger["generation"] - 1,
            "next_generation": ledger["generation"],
            "next_hash": ledger_hash(ledger),
            "next_value": ledger,
        }
        submission = begin_submission(
            package_root=scope.package_root,
            branch_id=branch_id,
            requested_sequence=submission_sequence,
            logical_identity={
                "kind": "obligation_change",
                "event_id": event_id,
                "component_ids": component_ids,
            },
            payload={
                "operations": operations,
                "ledger_hash": sidecar["next_hash"],
            },
            sidecars=[sidecar],
        )
        path = ledger_path(scope.package_root, branch_id)
        persisted = (
            load_ledger(scope.package_root, branch_id)
            if path.exists() else None
        )
        if persisted is None or ledger_hash(persisted) != sidecar["next_hash"]:
            write_ledger(scope.package_root, branch_id, ledger)
        if submission.phase not in {"published", "finalized"}:
            apply_batch(
                package_root=scope.package_root,
                branch_id=branch_id,
                operations=operations,
                include_snapshot=False,
                submission=submission,
            )
        authoring = (
            None if submission.phase == "finalized"
            else load_current_authoring(_report_scope(scope))
        )
        finalized = finalize_report_command(
            scope=_report_scope(scope),
            submission=submission,
            descriptor=authoring["descriptor"] if authoring else {},
            message="Record obligation change",
            as_json=True,
        )
        click.echo(_json({
            "status": "recorded",
            "event_id": event_id,
            "ledger_generation": ledger["generation"],
            "ledger_projection_hash": ledger["current_projection"][
                "projection_hash"
            ],
            "report_submission_sequence": submission.sequence,
            "report_components": component_ids,
            "git": finalized["git"],
            "next_action": {
                "command": (
                    "factortester research-graph edge choose "
                    f"{instance_id} {branch_id} <edge-id> "
                    f"--profile-id {profile_id} --agent-id {agent_id} "
                    "--reason-file <portable-markdown>"
                ),
                "instruction": (
                    "用富文本说明选择理由；选择后覆盖表会标记该 "
                    "Edge 要求的义务类别"
                ),
            },
        }))


def _register_history_migration_command(obligation: click.Group) -> None:
    @obligation.command("migrate-history")
    @_scope_options
    @click.option(
        "--apply",
        "apply_migration",
        is_flag=True,
        help="写入单文件义务账本并提交 Work Package Git",
    )
    def migrate_history(
        instance_id: str,
        branch_id: str,
        profile_id: str,
        agent_id: str,
        release_profile: Path | None,
        apply_migration: bool,
    ) -> None:
        """从服务端已接受历史一次性重建当前分支义务账本。"""
        scope, packet = _scope(
            instance_id, branch_id, profile_id, agent_id, release_profile,
        )
        path = ledger_path(scope.package_root, branch_id)
        if path.exists():
            raise click.ClickException(
                "branch obligation ledger already exists; migration is "
                "one-time and never overwrites it"
            )
        client_root = load_profile_root(release_profile)
        profile = LocalProfileStore(client_root).load(profile_id)
        client = FactorTesterClient(HttpSession(
            profile["server"]["base_url"],
        ))
        items = _load_logical_obligation_history(
            client, scope=scope, branch_id=branch_id,
        )
        contexts = obligation_history_contexts(items)
        ledger = ledger_from_history(
            branch_ref=f"graph-branch:{instance_id}:{branch_id}",
            packet=packet,
            contexts=contexts,
        )
        result = {
            "status": "preview" if not apply_migration else "migrated",
            "state_changed": bool(apply_migration),
            "ledger_file": str(path),
            "history_transition_count": len(items),
            "obligation_event_count": len(ledger["history"]),
            "ledger_generation": ledger["generation"],
            "projection_hash": ledger["current_projection"][
                "projection_hash"
            ],
        }
        if apply_migration:
            write_ledger(scope.package_root, branch_id, ledger)
            result["git"] = commit_work_package(
                scope.package_root,
                message="Migrate branch obligation ledger from server history",
            )
        click.echo(_json(result))


def _load_logical_obligation_history(
    client: FactorTesterClient,
    *,
    scope: Any,
    branch_id: str,
) -> list[dict[str, Any]]:
    """Include inherited branch history, not only its latest incarnation."""
    return load_history(
        client,
        work_package_ref=f"work-package:{scope.record['record_id']}",
        branch_id=branch_id,
    )


def _scope_options(function):
    options = [
        click.argument("instance_id"),
        click.argument("branch_id"),
        click.option("--profile-id", required=True),
        click.option("--agent-id", required=True),
        click.option(
            "--release-profile",
            type=click.Path(exists=True, dir_okay=False, path_type=Path),
        ),
    ]
    for option in reversed(options):
        function = option(function)
    return function


def _scope(
    instance_id: str,
    branch_id: str,
    profile_id: str,
    agent_id: str,
    release_profile: Path | None,
):
    client_root = load_profile_root(release_profile)
    try:
        scope = resolve_local_graph_report(
            client_root=client_root,
            profile_id=profile_id,
            agent_id=agent_id,
            instance_id=instance_id,
            branch_id=branch_id,
        )
        profile = LocalProfileStore(client_root).load(profile_id)
        client = FactorTesterClient(HttpSession(profile["server"]["base_url"]))
        packet = client.get_research_graph_node_info(instance_id, branch_id)
    except (OSError, RuntimeError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    return scope, packet


def _load_or_initialize(scope, packet: dict[str, Any]) -> dict[str, Any]:
    path = ledger_path(scope.package_root, scope.branch_id)
    if path.exists():
        ledger = load_ledger(scope.package_root, scope.branch_id)
        _validate_fresh(ledger, packet, scope)
        return ledger
    obligations = packet_obligations(packet)
    identity = branch_identity(
        instance_id=scope.instance_id,
        branch_id=scope.branch_id,
        packet=packet,
    )
    ledger = initialize_ledger(
        branch_ref=identity["branch_ref"],
        graph_ref=identity["graph_ref"],
        current_node=identity["current_node"],
        context_ref=identity["context_ref"],
        checkpoint_ref=identity["checkpoint_ref"],
        obligations=obligations,
    )
    ledger["current_projection"]["requirement_coverage"] = (
        project_requirement_coverage(
            requirements=packet_requirements(packet),
            obligations=obligations,
        )
    )
    return ledger


def _validate_fresh(ledger, packet, scope) -> None:
    expected = branch_identity(
        instance_id=scope.instance_id,
        branch_id=scope.branch_id,
        packet=packet,
    )
    if ledger["branch"] != expected:
        raise click.ClickException(
            "obligation ledger branch/context/checkpoint is stale; reconcile "
            "the accepted transition before making another obligation change"
        )


def _edge_requirement_ids(selected: Any) -> set[str]:
    if not isinstance(selected, dict):
        return set()
    return {
        str(item) for item in selected.get("required_requirement_ids") or []
        if isinstance(item, str) and item
    }


def _latest_obligation_event(ledger: dict[str, Any]) -> dict[str, Any] | None:
    return next((
        item for item in reversed(ledger["history"])
        if item["event_type"] == "obligation_change"
    ), None)


def _latest_requirement_table_id(ledger: dict[str, Any]) -> str:
    event = _latest_obligation_event(ledger) or {}
    return str(
        (event.get("report_components") or {}).get(
            "requirement_table_id",
        ) or ""
    )


def _latest_changed_refs(ledger: dict[str, Any]) -> set[str]:
    event = _latest_obligation_event(ledger) or {}
    return {
        f"obligation:{item['obligation_id']}"
        for item in event.get("obligation_delta") or []
        if isinstance(item, dict) and item.get("obligation_id")
    }


def _read_change(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise click.ClickException("change file is not valid JSON") from exc
    required = {
        "expected_projection_hash", "research_cycle", "obligation_delta",
        "obligation_presentations", "reason_markdown",
    }
    if not isinstance(value, dict) or set(value) != required:
        raise click.ClickException(
            "change file fields must be expected_projection_hash, "
            "research_cycle, obligation_delta, obligation_presentations, "
            "reason_markdown"
        )
    if (
        not isinstance(value["research_cycle"], dict)
        or not isinstance(value["obligation_delta"], list)
        or not isinstance(value["obligation_presentations"], dict)
        or not isinstance(value["reason_markdown"], str)
        or not value["reason_markdown"].strip()
    ):
        raise click.ClickException("change file field types are invalid")
    return value


def _event_id(expected: str, payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        {"expected": expected, "payload": payload},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()[:32]


def _report_scope(scope):
    return resolve_branch_report_scope(
        client_root=scope.client_root,
        profile_id=scope.profile_id,
        work_package_id=scope.record["record_id"],
        branch_id=scope.branch_id,
    )


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)
