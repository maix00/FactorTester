"""One-time source migration for explicitly reviewed report components."""

from __future__ import annotations

import json
import hashlib
from pathlib import Path

import click

from tools.cli.release.profile import load_profile_root
from tools.cli.release.research_reporting.authoring import (
    commit_branch_authoring,
)
from tools.cli.release.research_reporting.authoring.export import (
    export_branch_report,
)
from tools.cli.release.research_reporting.maintenance.component_semantics import (
    migrate_component_semantics,
    prepare_component_semantics,
)

from .research_report_common import output, read_json, scope_options
from .research_report_scope import resolve_branch_report_scope


@click.command("migrate-component-semantics")
@scope_options
@click.option(
    "--plan-file", required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option("--dry-run", is_flag=True)
@click.option("--json", "as_json", is_flag=True)
def migrate_component_semantics_command(
    profile_id: str, work_package_id: str, branch_id: str,
    release_profile: Path | None, plan_file: Path, dry_run: bool, as_json: bool,
) -> None:
    """Apply a complete component review directly to the report source tree."""
    scope = resolve_branch_report_scope(
        client_root=load_profile_root(release_profile), profile_id=profile_id,
        work_package_id=work_package_id, branch_id=branch_id,
    )
    plan = read_json(plan_file)
    if not isinstance(plan, dict):
        raise click.ClickException("--plan-file must contain a JSON object")
    migration_id = str(plan.get("migration_id") or "")
    if (
        not migration_id
        or migration_id != Path(migration_id).name
        or "/" in migration_id
        or "\\" in migration_id
    ):
        raise click.ClickException("migration_id must be a safe file name")
    if dry_run:
        result = prepare_component_semantics(
            package_root=scope.package_root, branch_id=branch_id,
            scope=scope, plan=plan,
        )
        result.pop("operations")
        result["dry_run"] = True
        output(result, as_json)
        return
    migration_root = scope.package_root / "migrations"
    migration_root.mkdir(parents=True, exist_ok=True)
    plan_path = migration_root / f"{migration_id}.plan.json"
    receipt = migration_root / f"{migration_id}.receipt.json"
    encoded_plan = (
        json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode()
    if plan_path.exists() and plan_path.read_bytes() != encoded_plan:
        raise click.ClickException(
            f"migration plan already exists with different content: {plan_path}"
        )
    if receipt.exists():
        raise click.ClickException(
            f"migration receipt already exists: {receipt}"
        )
    plan_path.write_bytes(encoded_plan)
    result = migrate_component_semantics(
        package_root=scope.package_root, branch_id=branch_id,
        scope=scope, plan=plan,
    )
    result["plan"] = str(plan_path)
    result["plan_sha256"] = hashlib.sha256(encoded_plan).hexdigest()
    receipt.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    exported = export_branch_report(
        package_root=scope.package_root, work_package_id=work_package_id,
        branch_id=branch_id, commit=False,
    )
    result["receipt"] = str(receipt)
    result["export"] = {
        "path": str(exported["path"]),
        "changed": exported["changed"],
        "content_hash": exported["content_hash"],
    }
    result["git"] = commit_branch_authoring(
        scope.package_root, message="Migrate report component semantics",
    )
    output(result, as_json)
