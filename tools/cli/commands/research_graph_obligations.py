"""Branch-local obligation ledger commands for research agents."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import click

from tools.cli.client import FactorTesterClient
from tools.cli.core.context import client_from_config
from tools.cli.release.local_profile import LocalProfileStore
from tools.cli.release.profile import load_profile_root
from tools.cli.release.research_obligations import (
    append_event,
    apply_evidence_use_deltas,
    apply_obligation_deltas,
    branch_identity,
    canonicalize_ledger,
    initialize_ledger,
    ledger_from_history,
    ledger_hash,
    ledger_path,
    load_ledger,
    prepare_obligation_split,
    project_requirement_coverage,
    requirement_title_overrides,
    requirement_union,
    validate_evidence_use_object,
    write_ledger,
)
from tools.cli.release.research_obligations import (
    obligations as packet_obligations,
)
from tools.cli.release.research_obligations import (
    requirements as packet_requirements,
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
from tools.cli.release.research_reporting.authoring.tree_paths import (
    report_tree_paths,
)
from tools.cli.release.research_reporting.authoring.tree_store import (
    load_head,
)
from tools.cli.release.research_reporting.git import commit_work_package

from .research_graph_chapter_reconciliation import (
    reconcile_current_container,
)
from .research_graph_cycle_contract import (
    validate_research_cycle_envelope,
)
from .research_graph_local_report import resolve_local_graph_report
from .research_graph_obligation_context import refresh_context_metadata
from .research_graph_obligation_definition_migration import (
    register_definition_migration_command,
)
from .research_graph_obligation_evidence_migration import (
    register_evidence_migration_command,
)
from .research_graph_obligation_titles import (
    register_title_migration_command,
)
from .research_graph_report_policy import report_container
from .research_report_history_timeline import (
    load_history,
    obligation_history_contexts,
)
from .research_report_scope import (
    load_current_authoring,
    resolve_branch_report_scope,
)
from .research_report_submission_finalize import finalize_report_command
from .research_report_submission_preflight import checked_component_preflight


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
            "change_contract": {
                "research_cycle_envelope_schema_version": 1,
                "parent_trace_ref": ledger["branch"]["checkpoint_ref"],
                "event_schema_rule": (
                    "proposal and decision objects keep their own "
                    "schema_version inside the v1 envelope"
                ),
            },
        }))
    _register_change_command(obligation)
    _register_split_command(obligation)
    _register_history_migration_command(obligation)
    register_evidence_migration_command(
        obligation,
        scope_options=_scope_options,
        scope_resolver=_scope,
        report_scope_resolver=_report_scope,
    )
    register_title_migration_command(
        obligation,
        scope_resolver=_scope,
        report_scope_resolver=_report_scope,
    )
    register_definition_migration_command(
        obligation,
        scope_resolver=_scope,
    )


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
    LocalProfileStore(client_root).load(profile_id)
    client = client_from_config()
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
        evidence_uses=ledger["current_projection"]["evidence_uses"],
        edge_required_ids=set(selected_edge["required_requirement_ids"]),
        node_required_ids=node_requirement_ids,
        title_overrides=requirement_title_overrides(ledger),
        enforce_evidence=True,
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
            "evidence_uses_snapshot": deepcopy(
                ledger["current_projection"]["evidence_uses"]
            ),
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
        coverage=coverage,
        obligations=ledger["current_projection"]["obligations"],
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
        result = _record_change_payload(
            scope=scope,
            packet=packet,
            payload=payload,
            instance_id=instance_id,
            branch_id=branch_id,
            profile_id=profile_id,
            agent_id=agent_id,
            release_profile=release_profile,
            submission_sequence=submission_sequence,
        )
        click.echo(_json(result))


def _register_split_command(obligation: click.Group) -> None:
    @obligation.command("split")
    @_scope_options
    @click.option(
        "--split-file",
        required=True,
        type=click.Path(exists=True, dir_okay=False, path_type=Path),
        help="父义务、子义务、显式 EvidenceUse 与解释",
    )
    @click.option(
        "--submission-sequence",
        type=click.IntRange(min=1),
        default=None,
        help="修正或恢复被拦截提交时复用的报告提交序号",
    )
    def split(
        instance_id: str,
        branch_id: str,
        profile_id: str,
        agent_id: str,
        release_profile: Path | None,
        split_file: Path,
        submission_sequence: int | None,
    ) -> None:
        """拆分宽泛义务；子义务不会隐式继承父义务的 Evidence。"""
        scope, packet = _scope(
            instance_id, branch_id, profile_id, agent_id, release_profile,
        )
        split_payload = _read_split(split_file)
        ledger = _load_or_initialize(scope, packet)
        if (
            ledger["current_projection"]["projection_hash"]
            != split_payload["expected_projection_hash"]
        ):
            raise click.ClickException(
                "obligation ledger projection is stale; run "
                "research-graph obligation status and rebuild the split"
            )
        try:
            prepared = prepare_obligation_split(
                obligations=ledger["current_projection"]["obligations"],
                evidence_uses=ledger["current_projection"]["evidence_uses"],
                parent_obligation_id=split_payload[
                    "parent_obligation_id"
                ],
                children=split_payload["children"],
                child_evidence_use_delta=split_payload[
                    "child_evidence_use_delta"
                ],
            )
        except ValueError as exc:
            raise click.ClickException(str(exc)) from exc
        payload = {
            "expected_projection_hash": split_payload[
                "expected_projection_hash"
            ],
            "research_cycle": split_payload["research_cycle"],
            "obligation_delta": prepared["obligation_delta"],
            "evidence_use_delta": prepared["evidence_use_delta"],
            "obligation_presentations": split_payload[
                "obligation_presentations"
            ],
            "reason_markdown": split_payload["reason_markdown"],
        }
        result = _record_change_payload(
            scope=scope,
            packet=packet,
            payload=payload,
            instance_id=instance_id,
            branch_id=branch_id,
            profile_id=profile_id,
            agent_id=agent_id,
            release_profile=release_profile,
            submission_sequence=submission_sequence,
            event_type="obligation_split",
            event_metadata={
                "split_parent_ref": prepared["split_parent_ref"],
                "split_child_refs": prepared["split_child_refs"],
            },
        )
        click.echo(_json(result))


def _record_change_payload(
    *,
    scope: Any,
    packet: dict[str, Any],
    payload: dict[str, Any],
    instance_id: str,
    branch_id: str,
    profile_id: str,
    agent_id: str,
    release_profile: Path | None,
    submission_sequence: int | None,
    event_type: str = "obligation_change",
    event_metadata: dict[str, Any] | None = None,
    report_parent_id: str | None = None,
) -> dict[str, Any]:
    ledger = _load_or_initialize(scope, packet)
    expected = str(payload["expected_projection_hash"])
    identity_payload = {
        **payload,
        "event_type": event_type,
        "event_metadata": event_metadata or {},
    }
    event_id = _event_id(expected, identity_payload)
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
        evidence_use_delta = _prepare_evidence_use_deltas(
            payload["evidence_use_delta"],
            instance_id=instance_id,
            branch_id=branch_id,
            profile_id=profile_id,
            release_profile=release_profile,
        )
        evidence_use_changes = _describe_evidence_use_changes(
            ledger["current_projection"]["evidence_uses"],
            evidence_use_delta,
        )
        evidence_uses, changed_evidence_uses = apply_evidence_use_deltas(
            ledger["current_projection"]["evidence_uses"],
            evidence_use_delta,
            obligations=obligations,
        )
        selected = ledger["current_projection"]["selected_edge"]
        requirements = _requirements_for_selected_edge(packet, selected)
        requirement_titles = _complete_requirement_titles(
            ledger=ledger,
            requirements=requirements,
            obligations=obligations,
            instance_id=instance_id,
            branch_id=branch_id,
            profile_id=profile_id,
            release_profile=release_profile,
        )
        coverage = project_requirement_coverage(
            requirements=requirements,
            obligations=obligations,
            changed_obligation_refs=changed,
            evidence_uses=evidence_uses,
            edge_required_ids=_edge_requirement_ids(selected),
            title_overrides=requirement_titles,
            enforce_evidence=selected is not None,
        )
        chapter = reconcile_current_container(
            scope, container=report_container(packet),
        )
        parent_id = _validated_report_parent(
            scope,
            container_id=str(chapter["component_id"]),
            requested_parent_id=report_parent_id,
        )
        paths = report_tree_paths(scope.package_root, branch_id)
        report_sequence = load_head(paths)["generation"] + 1
        next_ledger = deepcopy(ledger)
        next_ledger["current_projection"]["obligations"] = obligations
        next_ledger["current_projection"]["evidence_uses"] = evidence_uses
        next_ledger["current_projection"]["requirement_coverage"] = coverage
        next_ledger = append_event(
            next_ledger,
            event_type=event_type,
            event_id=event_id,
            payload={
                "agent_id": scope.agent_id,
                "node_id": ledger["branch"]["current_node"],
                "report_submission_sequence": report_sequence,
                "reason_markdown": payload["reason_markdown"],
                "obligation_delta": payload["obligation_delta"],
                "evidence_use_delta": evidence_use_delta,
                "evidence_use_changes": evidence_use_changes,
                "changed_evidence_use_ids": sorted(changed_evidence_uses),
                "research_cycle": payload["research_cycle"],
                "obligation_presentations": payload[
                    "obligation_presentations"
                ],
                "obligations_snapshot": obligations,
                "evidence_uses_snapshot": evidence_uses,
                "coverage_snapshot": coverage,
                "requirement_titles": requirement_titles,
                "report_components": {},
                **(event_metadata or {}),
            },
        )
        event = next_ledger["history"][-1]
        operations, component_ids = obligation_change_operations(
            event=event,
            parent_id=parent_id,
        )
        event["report_components"] = component_ids
        ledger = canonicalize_ledger(next_ledger)
    else:
        ledger = load_ledger(scope.package_root, branch_id)
        event = existing
        chapter = reconcile_current_container(
            scope, container=report_container(packet),
        )
        parent_id = _validated_report_parent(
            scope,
            container_id=str(chapter["component_id"]),
            requested_parent_id=report_parent_id,
        )
        operations, component_ids = obligation_change_operations(
            event=event,
            parent_id=parent_id,
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
    replay_sequence = (
        submission_sequence
        if submission_sequence is not None
        else int(event["report_submission_sequence"])
        if existing is not None
        else None
    )
    submission = begin_submission(
        package_root=scope.package_root,
        branch_id=branch_id,
        requested_sequence=replay_sequence,
        logical_identity={
            "kind": event_type,
            "event_id": event_id,
            "component_ids": component_ids,
        },
        payload={"operations": operations, "ledger_hash": sidecar["next_hash"]},
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
        message=(
            "Split research obligation"
            if event_type == "obligation_split"
            else "Record Evidence lifecycle and obligation changes"
            if event_type == "evidence_lifecycle"
            else "Record obligation change"
        ),
        as_json=True,
    )
    return {
        "status": (
            "split" if event_type == "obligation_split"
            else "evidence_lifecycle_recorded"
            if event_type == "evidence_lifecycle"
            else "recorded"
        ),
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
                "factortester research graphs edge choose "
                f"{instance_id} {branch_id} <edge-id> "
                f"--profile-id {profile_id} --agent-id {agent_id} "
                "--reason-file <portable-markdown>"
            ),
            "instruction": (
                "用富文本说明选择理由；选择后覆盖表会标记该 "
                "Edge 要求的义务类别"
            ),
        },
    }


def record_evidence_lifecycle_report(
    *,
    instance_id: str,
    branch_id: str,
    profile_id: str,
    agent_id: str,
    release_profile: Path | None,
    evidence: dict[str, Any],
    lifecycle_transition: dict[str, Any],
    change_payload: dict[str, Any],
    parent_id: str,
    submission_sequence: int | None,
) -> dict[str, Any]:
    """Remove current EvidenceUse bindings and report the lifecycle ruling."""
    scope, packet = _scope(
        instance_id, branch_id, profile_id, agent_id, release_profile,
    )
    ledger = _load_or_initialize(scope, packet)
    evidence_ref = str(evidence.get("evidence_ref") or "")
    action = str(lifecycle_transition.get("action") or "")
    removals = [
        {"op": "remove", "use_id": str(item["use_id"])}
        for item in ledger["current_projection"]["evidence_uses"]
        if action == "exclude" and item.get("evidence_ref") == evidence_ref
    ]
    payload = {
        "expected_projection_hash": change_payload[
            "expected_projection_hash"
        ],
        "research_cycle": change_payload["research_cycle"],
        "obligation_delta": change_payload["obligation_delta"],
        "evidence_use_delta": removals,
        "obligation_presentations": change_payload[
            "obligation_presentations"
        ],
        "reason_markdown": change_payload["reason_markdown"],
    }
    title_zh = str(
        (evidence.get("envelope") or {}).get("title_zh")
        or (evidence.get("envelope") or {}).get("title")
        or evidence_ref
    )
    result = _record_change_payload(
        scope=scope,
        packet=packet,
        payload=payload,
        instance_id=instance_id,
        branch_id=branch_id,
        profile_id=profile_id,
        agent_id=agent_id,
        release_profile=release_profile,
        submission_sequence=submission_sequence,
        event_type="evidence_lifecycle",
        event_metadata={
            "evidence_lifecycle": {
                "transition_ref": str(
                    lifecycle_transition["transition_ref"]
                ),
                "evidence_ref": evidence_ref,
                "evidence_title_zh": title_zh,
                "action": action,
                "from_status": str(
                    lifecycle_transition["from_status"]
                ),
                "to_status": str(lifecycle_transition["to_status"]),
                "reason_zh": str(lifecycle_transition["reason_zh"]),
                "removed_evidence_use_ids": [
                    str(item["use_id"])
                    for item in ledger["current_projection"][
                        "evidence_uses"
                    ]
                    if (
                        action == "exclude"
                        and item.get("evidence_ref") == evidence_ref
                    )
                ],
            },
        },
        report_parent_id=parent_id,
    )
    result["removed_evidence_use_count"] = len(removals)
    return result


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
        LocalProfileStore(client_root).load(profile_id)
        client = client_from_config()
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
        LocalProfileStore(client_root).load(profile_id)
        client = client_from_config()
        packet = client.get_research_graph_node_info(instance_id, branch_id)
        _hydrate_requirement_titles(
            client=client,
            packet=packet,
            instance_id=instance_id,
            branch_id=branch_id,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    return scope, packet


def _hydrate_requirement_titles(
    *,
    client: FactorTesterClient,
    packet: dict[str, Any],
    instance_id: str,
    branch_id: str,
) -> None:
    """Lazy-load catalog titles omitted from bounded Agent packets."""
    for item in packet.get("entry_requirements") or []:
        if not isinstance(item, dict) or item.get("title_zh"):
            continue
        requirement_id = str(item.get("requirement_id") or "")
        if not requirement_id:
            continue
        detail = client.get_current_graph_requirement(
            instance_id,
            branch_id,
            requirement_id,
        )
        requirement = detail.get("requirement") or detail
        title = str(
            requirement.get("title_zh") if isinstance(requirement, dict)
            else ""
        ).strip()
        if not title:
            raise ValueError(
                f"requirement catalog has no title_zh: {requirement_id}"
            )
        item["title_zh"] = title


def _load_or_initialize(scope, packet: dict[str, Any]) -> dict[str, Any]:
    path = ledger_path(scope.package_root, scope.branch_id)
    if path.exists():
        ledger = load_ledger(scope.package_root, scope.branch_id)
        return _validate_fresh(ledger, packet, scope)
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


def _validate_fresh(ledger, packet, scope) -> dict[str, Any]:
    expected = branch_identity(
        instance_id=scope.instance_id,
        branch_id=scope.branch_id,
        packet=packet,
    )
    try:
        return refresh_context_metadata(
            ledger,
            expected_branch=expected,
        )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc


def _edge_requirement_ids(selected: Any) -> set[str]:
    if not isinstance(selected, dict):
        return set()
    return {
        str(item) for item in selected.get("required_requirement_ids") or []
        if isinstance(item, str) and item
    }


def _requirements_for_selected_edge(
    packet: dict[str, Any],
    selected: Any,
) -> list[dict[str, Any]]:
    """Keep selected-Edge classes addressable while recording obligations."""
    if not isinstance(selected, dict):
        return packet_requirements(packet)
    edge = selected.get("transition_contract")
    if not isinstance(edge, dict):
        raise click.ClickException(
            "selected Edge has no frozen transition contract; choose the "
            "Edge again before recording obligation coverage"
        )
    return requirement_union(packet, {"edge": edge})


def _complete_requirement_titles(
    *,
    ledger: dict[str, Any],
    requirements: list[dict[str, Any]],
    obligations: list[dict[str, Any]],
    instance_id: str,
    branch_id: str,
    profile_id: str,
    release_profile: Path | None,
) -> dict[str, str]:
    """Freeze titles for current and historically retained requirement refs."""
    titles = requirement_title_overrides(ledger)
    required_ids: set[str] = set()
    for requirement in requirements:
        requirement_id = str(
            requirement.get("requirement_id") or ""
        ).removeprefix("requirement:")
        if not requirement_id:
            continue
        required_ids.add(requirement_id)
        title = str(
            requirement.get("title_zh")
            or requirement.get("description_zh")
            or requirement.get("description")
            or ""
        ).strip()
        if title:
            titles[requirement_id] = title
    for obligation in obligations:
        required_ids.update(
            str(reference).removeprefix("requirement:")
            for reference in obligation.get("requirement_refs") or []
            if isinstance(reference, str) and reference
        )
    missing = sorted(required_ids - set(titles))
    if missing:
        client_root = load_profile_root(release_profile)
        LocalProfileStore(client_root).load(profile_id)
        client = client_from_config()
        for requirement_id in missing:
            detail = client.get_current_graph_requirement(
                instance_id, branch_id, requirement_id,
            )
            requirement = detail.get("requirement") or detail
            title = str(
                requirement.get("title_zh")
                if isinstance(requirement, dict) else ""
            ).strip()
            if not title:
                raise click.ClickException(
                    "requirement catalog has no title_zh: "
                    f"{requirement_id}"
                )
            titles[requirement_id] = title
    return {
        requirement_id: titles[requirement_id]
        for requirement_id in sorted(required_ids)
    }


def _latest_obligation_event(ledger: dict[str, Any]) -> dict[str, Any] | None:
    return next((
        item for item in reversed(ledger["history"])
        if item["event_type"] in {
            "obligation_change", "obligation_split", "evidence_lifecycle",
        }
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


def _validated_report_parent(
    scope: Any,
    *,
    container_id: str,
    requested_parent_id: str | None,
) -> str:
    parent_id = str(requested_parent_id or container_id).strip()
    if not parent_id:
        raise click.ClickException("report parent_id is required")
    snapshot = load_current_authoring(_report_scope(scope))
    parents = {
        str(item["component_id"]): (
            str(item["parent_id"])
            if item["parent_id"] is not None else ""
        )
        for item in snapshot["components"]
    }
    current = parent_id
    seen: set[str] = set()
    while current != container_id:
        if current in seen or current not in parents:
            raise click.ClickException(
                "parent_id must stay inside the current research report "
                "container"
            )
        seen.add(current)
        current = parents[current]
    return parent_id


def _read_change(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise click.ClickException("change file is not valid JSON") from exc
    required = {
        "expected_projection_hash", "research_cycle", "obligation_delta",
        "evidence_use_delta", "obligation_presentations", "reason_markdown",
    }
    if not isinstance(value, dict) or set(value) != required:
        raise click.ClickException(
            "change file fields must be expected_projection_hash, "
            "research_cycle, obligation_delta, evidence_use_delta, "
            "obligation_presentations, reason_markdown"
        )
    if (
        not isinstance(value["research_cycle"], dict)
        or not isinstance(value["obligation_delta"], list)
        or not isinstance(value["evidence_use_delta"], list)
        or not isinstance(value["obligation_presentations"], dict)
        or not isinstance(value["reason_markdown"], str)
        or not value["reason_markdown"].strip()
    ):
        raise click.ClickException("change file field types are invalid")
    validate_research_cycle_envelope(value["research_cycle"])
    return value


def _read_split(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise click.ClickException("split file is not valid JSON") from exc
    required = {
        "expected_projection_hash", "parent_obligation_id", "children",
        "child_evidence_use_delta", "research_cycle",
        "obligation_presentations", "reason_markdown",
    }
    if not isinstance(value, dict) or set(value) != required:
        raise click.ClickException(
            "split file fields must be expected_projection_hash, "
            "parent_obligation_id, children, child_evidence_use_delta, "
            "research_cycle, obligation_presentations, reason_markdown"
        )
    if (
        not isinstance(value["expected_projection_hash"], str)
        or not isinstance(value["parent_obligation_id"], str)
        or not isinstance(value["children"], list)
        or not isinstance(value["child_evidence_use_delta"], list)
        or not isinstance(value["research_cycle"], dict)
        or not isinstance(value["obligation_presentations"], dict)
        or not isinstance(value["reason_markdown"], str)
        or not value["reason_markdown"].strip()
    ):
        raise click.ClickException("split file field types are invalid")
    validate_research_cycle_envelope(value["research_cycle"])
    return value


def _prepare_evidence_use_deltas(
    deltas: list[dict[str, Any]],
    *,
    instance_id: str,
    branch_id: str,
    profile_id: str,
    release_profile: Path | None,
) -> list[dict[str, Any]]:
    """Resolve each Evidence object and freeze its Graph admission."""
    client_root = load_profile_root(release_profile)
    LocalProfileStore(client_root).load(profile_id)
    client = client_from_config()
    prepared = deepcopy(deltas)
    validated: list[dict[str, Any]] = []
    for delta in prepared:
        if not isinstance(delta, dict):
            raise click.ClickException(
                "evidence_use_delta must contain objects"
            )
        if delta.get("op") != "add":
            validated.append(delta)
            continue
        use = delta.get("use")
        try:
            evidence_ref = str((use or {}).get("evidence_ref") or "")
            evidence = client.get_research_evidence(evidence_ref)
            normalized = validate_evidence_use_object(use, evidence)
            admission = client.admit_research_evidence_for_graph(
                evidence_ref,
                instance_id=instance_id,
                branch_id=branch_id,
                qualification=normalized["qualification"],
                note=normalized["rationale_zh"],
            )
        except (KeyError, RuntimeError, TypeError, ValueError) as exc:
            raise click.ClickException(
                f"EvidenceUse validation failed: {exc}"
            ) from exc
        if admission.get("qualification") != normalized["qualification"]:
            raise click.ClickException(
                "EvidenceUse admission qualification mismatch"
            )
        validated.append({"op": "add", "use": normalized})
    return validated


def _describe_evidence_use_changes(
    current: list[dict[str, Any]],
    deltas: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Freeze both sides of EvidenceUse changes for report rendering."""
    by_id = {
        str(item.get("use_id") or ""): deepcopy(item)
        for item in current
        if isinstance(item, dict) and item.get("use_id")
    }
    changes = []
    for delta in deltas:
        operation = str(delta.get("op") or "")
        if operation == "add":
            changes.append({"op": "add", "use": deepcopy(delta["use"])})
            continue
        use_id = str(delta.get("use_id") or "")
        use = by_id.get(use_id)
        if operation != "remove" or use is None:
            raise click.ClickException(
                "EvidenceUse removal cannot be described from current ledger"
            )
        changes.append({"op": "remove", "use": use})
    return changes


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
