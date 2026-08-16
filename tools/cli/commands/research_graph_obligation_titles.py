"""One-time obligation and requirement title migration command."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

import click

from tools.cli.release.research_obligations import (
    ledger_hash,
    ledger_path,
    load_ledger,
    migrate_ledger_titles,
    report_title_operations,
    write_ledger,
)
from tools.cli.release.research_reporting.authoring.submission_begin import (
    begin_submission,
)
from tools.cli.release.research_reporting.authoring.tree_model import (
    apply_batch,
)
from tools.cli.release.research_reporting.authoring.tree_projection import (
    load_snapshot,
)
from tools.cli.release.research_reporting.authoring.inline_links import (
    validate_typed_target,
)
from tools.cli.release.research_reporting.git import commit_work_package

from .research_report_scope import load_current_authoring
from .research_report_submission_finalize import finalize_report_command


def register_title_migration_command(
    obligation: click.Group,
    *,
    scope_resolver: Callable[..., tuple[Any, dict[str, Any]]],
    report_scope_resolver: Callable[[Any], Any],
) -> None:
    @obligation.command("migrate-titles")
    @click.option("--instance-id", required=True)
    @click.option("--branch-id", required=True)
    @click.option("--profile-id", required=True)
    @click.option("--agent-id", required=True)
    @click.option(
        "--release-profile",
        type=click.Path(exists=True, dir_okay=False, path_type=Path),
    )
    @click.option(
        "--title-file",
        required=True,
        type=click.Path(exists=True, dir_okay=False, path_type=Path),
    )
    def migrate_titles(
        instance_id: str,
        branch_id: str,
        profile_id: str,
        agent_id: str,
        release_profile: Path | None,
        title_file: Path,
    ) -> None:
        """一次性迁移账本与报告源中的短中文标题。"""
        titles = _load_titles(title_file)
        scope, _packet = scope_resolver(
            instance_id, branch_id, profile_id, agent_id, release_profile,
        )
        has_ledger = ledger_path(scope.package_root, branch_id).is_file()
        ledger = (
            load_ledger(scope.package_root, branch_id)
            if has_ledger else None
        )
        migrated = (
            migrate_ledger_titles(
                ledger,
                obligation_titles=titles["obligations"],
                requirement_titles=titles["requirements"],
            )
            if ledger is not None else None
        )
        snapshot = load_snapshot(
            package_root=scope.package_root, branch_id=branch_id,
        )
        operations = report_title_operations(
            snapshot,
            obligation_titles=titles["obligations"],
            requirement_titles=titles["requirements"],
            reference_rewrites=titles["reference_rewrites"],
        )
        if not operations and migrated == ledger:
            click.echo(json.dumps({
                "changed": False,
                "ledger_generation": (
                    ledger["generation"] if ledger is not None else None
                ),
                "report_generation": snapshot["head"]["generation"],
            }, ensure_ascii=False))
            return
        ledger_changed = (
            ledger is not None
            and migrated is not None
            and migrated != ledger
        )
        if not operations:
            assert migrated is not None
            write_ledger(scope.package_root, branch_id, migrated)
            git = commit_work_package(
                scope.package_root,
                message="Migrate obligation Chinese titles",
            )
            click.echo(json.dumps({
                "changed": True,
                "component_count": 0,
                "ledger_generation": migrated["generation"],
                "report_generation": snapshot["head"]["generation"],
                "git": git,
            }, ensure_ascii=False))
            return
        sidecars = []
        if ledger_changed:
            sidecars.append({
                "path": "obligations.json",
                "base_generation": ledger["generation"],
                "next_generation": migrated["generation"],
                "next_hash": ledger_hash(migrated),
                "next_value": migrated,
            })
        submission = begin_submission(
            package_root=scope.package_root,
            branch_id=branch_id,
            requested_sequence=None,
            logical_identity={
                "kind": "obligation_title_migration",
                "ledger_generation": (
                    ledger["generation"] if ledger is not None else None
                ),
            },
            payload={
                "operations": operations,
                "ledger_hash": (
                    ledger_hash(migrated) if migrated is not None else None
                ),
            },
            sidecars=sidecars,
        )
        if ledger_changed:
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
            message="Migrate obligation Chinese titles",
            as_json=True,
        )
        click.echo(json.dumps({
            "changed": True,
            "component_count": len(operations),
            "ledger_generation": (
                migrated["generation"] if migrated is not None else None
            ),
            "report_generation": authoring["head"]["generation"],
            "git": finalized["git"],
        }, ensure_ascii=False))


def _load_titles(path: Path) -> dict[str, dict[str, str]]:
    from cli_anything.factortester_research.core.successor_graph.requirement_titles import (
        REQUIREMENT_TITLE_MAP_ZH,
    )

    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise click.ClickException("title file is not valid JSON") from exc
    if (
        not isinstance(value, dict)
        or set(value) - {
            "obligations", "requirements", "reference_rewrites",
        }
        or "obligations" not in value
    ):
        raise click.ClickException(
            "title file must contain obligations and may contain requirements"
        )
    value.setdefault("requirements", REQUIREMENT_TITLE_MAP_ZH)
    value.setdefault("reference_rewrites", {})
    result = {}
    for field in ("obligations", "requirements"):
        items = value[field]
        if not isinstance(items, dict) or not items:
            raise click.ClickException(f"{field} titles must be an object")
        normalized = {
            str(key): str(title).strip() for key, title in items.items()
        }
        if any(
            not key or not title or "\n" in title or len(title) > 32
            for key, title in normalized.items()
        ):
            raise click.ClickException(
                f"{field} titles must be one-line titles up to 32 characters"
            )
        result[field] = normalized
    rewrites = value["reference_rewrites"]
    if not isinstance(rewrites, dict):
        raise click.ClickException("reference_rewrites must be an object")
    normalized_rewrites = {}
    for source, rewrite in rewrites.items():
        if (
            not isinstance(source, str)
            or "|" not in source
            or not isinstance(rewrite, dict)
            or set(rewrite) != {"kind", "target_ref", "title_zh"}
        ):
            raise click.ClickException(
                "reference_rewrites entries are invalid"
            )
        kind = str(rewrite["kind"])
        title = str(rewrite["title_zh"]).strip()
        title_limit = 128 if kind in {"factor", "factor_set"} else 32
        if not title or "\n" in title or len(title) > title_limit:
            raise click.ClickException(
                "reference rewrite title_zh must be short"
            )
        try:
            validate_typed_target(
                kind=kind,
                target_ref=str(rewrite["target_ref"]),
                field="reference_rewrites",
            )
        except ValueError as exc:
            raise click.ClickException(str(exc)) from exc
        normalized_rewrites[source] = {
            "kind": kind,
            "target_ref": str(rewrite["target_ref"]),
            "title_zh": title,
        }
    result["reference_rewrites"] = normalized_rewrites
    return result
