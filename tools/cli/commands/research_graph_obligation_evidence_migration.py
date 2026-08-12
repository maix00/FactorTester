"""One-time fragment-Evidence upgrade for branch obligation reports."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

import click

from tools.cli.release.research_obligations import (
    ledger_hash,
    ledger_path,
    load_ledger,
    migrate_ledger_evidence_v2,
    write_ledger,
)
from tools.cli.release.research_reporting.authoring.submission_begin import (
    begin_submission,
)
from tools.cli.release.research_reporting.authoring.tree_model import (
    apply_batch,
)
from tools.cli.release.research_reporting.git import commit_work_package
from tools.cli.release.research_reporting.generation import work_package_lock

from .research_report_scope import load_current_authoring
from .research_report_submission_finalize import finalize_report_command


def register_evidence_migration_command(
    group: click.Group,
    *,
    scope_options: Callable,
    scope_resolver: Callable,
    report_scope_resolver: Callable,
) -> None:
    @group.command("migrate-evidence-v2")
    @scope_options
    @click.option(
        "--apply",
        "apply_migration",
        is_flag=True,
        help="原子更新账本、历史义务表和 Work Package Git",
    )
    def migrate_evidence_v2(
        instance_id: str,
        branch_id: str,
        profile_id: str,
        agent_id: str,
        release_profile: Path | None,
        apply_migration: bool,
    ) -> None:
        """把历史义务报告升级为 fragment-bound EvidenceUse 结构。"""
        scope, _packet = scope_resolver(
            instance_id, branch_id, profile_id, agent_id, release_profile,
        )
        if apply_migration:
            with work_package_lock(scope.package_root):
                result = _migrate(
                    scope=scope,
                    branch_id=branch_id,
                    report_scope_resolver=report_scope_resolver,
                    apply_migration=True,
                )
        else:
            result = _migrate(
                scope=scope,
                branch_id=branch_id,
                report_scope_resolver=report_scope_resolver,
                apply_migration=False,
            )
        click.echo(_json(result))


def _migrate(
    *,
    scope: Any,
    branch_id: str,
    report_scope_resolver: Callable,
    apply_migration: bool,
) -> dict[str, Any]:
    path = ledger_path(scope.package_root, branch_id)
    raw = _read_raw(path)
    schema_version = raw.get("schema_version")
    if schema_version == 2:
        return {
            "status": "already_migrated",
            "state_changed": False,
            "ledger_file": str(path),
            "from_schema_version": 2,
            "to_schema_version": 2,
            "history_event_count": len(raw.get("history") or []),
            "report_replacement_count": 0,
            "legacy_evidence_disposition": "unverifiable_fragment",
            "next_ledger_hash": ledger_hash(raw),
        }
    if schema_version != 1:
        raise click.ClickException(
            "evidence migration accepts only obligation ledger schema v1 or v2"
        )
    current = load_ledger(scope.package_root, branch_id)
    migrated, operations = migrate_ledger_evidence_v2(current)
    result = {
        "status": "preview" if not apply_migration else "migrated",
        "state_changed": bool(apply_migration),
        "ledger_file": str(path),
        "from_schema_version": 1,
        "to_schema_version": 2,
        "history_event_count": len(current["history"]),
        "report_replacement_count": len(operations),
        "legacy_evidence_disposition": "unverifiable_fragment",
        "next_ledger_hash": ledger_hash(migrated),
    }
    if not apply_migration:
        return result
    sidecar = {
        "path": "obligations.json",
        "base_generation": current["generation"],
        "next_generation": migrated["generation"],
        "next_hash": ledger_hash(migrated),
        "next_value": migrated,
    }
    if operations:
        submission = begin_submission(
            package_root=scope.package_root,
            branch_id=branch_id,
            requested_sequence=None,
            logical_identity={
                "kind": "obligation_evidence_v2_migration",
                "from_ledger_hash": ledger_hash(current),
                "to_ledger_hash": sidecar["next_hash"],
            },
            payload={
                "operations": operations,
                "ledger_hash": sidecar["next_hash"],
            },
            sidecars=[sidecar],
        )
        write_ledger(scope.package_root, branch_id, migrated)
        apply_batch(
            package_root=scope.package_root,
            branch_id=branch_id,
            operations=operations,
            include_snapshot=False,
            submission=submission,
        )
        report_scope = report_scope_resolver(scope)
        authoring = load_current_authoring(report_scope)
        finalized = finalize_report_command(
            scope=report_scope,
            submission=submission,
            descriptor=authoring["descriptor"],
            message="Migrate obligation reports to fragment EvidenceUse",
            as_json=True,
        )
        result["git"] = finalized["git"]
    else:
        write_ledger(scope.package_root, branch_id, migrated)
        result["git"] = commit_work_package(
            scope.package_root,
            message="Migrate obligation ledger to fragment EvidenceUse",
        )
    return result


def _read_raw(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise click.ClickException(
            f"cannot read historical obligation ledger: {path}"
        ) from exc
    if not isinstance(value, dict):
        raise click.ClickException("historical obligation ledger is invalid")
    return value


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)
