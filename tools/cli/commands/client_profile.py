"""Version-independent local user, Agent, and adapter profiles."""

from __future__ import annotations

import json
from pathlib import Path
import click

from tools.cli.core.errors import friendly_errors
from tools.cli.release.local_profile import (
    LocalProfileStore,
    new_local_profile,
)
from tools.cli.release.profile import load_profile_root
from tools.cli.release.storage import read_json, write_json
from tools.cli.release.workspace_migration import (
    apply_workspace_migration,
    apply_workspace_repair,
    default_profile_workspace_root,
    plan_workspace_migration,
    plan_workspace_repair,
    rollback_workspace_migration,
    rollback_workspace_repair,
    verify_workspace_migration,
    verify_workspace_repair,
)
from tools.cli.client import FactorTesterClient
from tools.cli.http import HttpSession


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)


def _root_option(function):
    return click.option(
        "--release-profile",
        type=click.Path(exists=True, dir_okay=False, path_type=Path),
    )(function)


@click.group("profile")
def client_profile() -> None:
    """Manage version-independent local profiles."""


@client_profile.command("init")
@click.option("--profile-id", required=True)
@click.option("--display-name", required=True)
@click.option("--server-url", required=True)
@click.option(
    "--workspace-root",
    type=click.Path(file_okay=False, path_type=Path),
)
@_root_option
@friendly_errors
def initialize_profile(
    profile_id: str,
    display_name: str,
    server_url: str,
    workspace_root: Path | None,
    release_profile: Path | None,
) -> None:
    store = LocalProfileStore(load_profile_root(release_profile))
    click.echo(_json(store.save(new_local_profile(
        profile_id=profile_id,
        display_name=display_name,
        server_url=server_url,
        workspace_root=workspace_root
        or default_profile_workspace_root(profile_id),
    ))))


@client_profile.command("list")
@_root_option
@friendly_errors
def list_profiles(release_profile: Path | None) -> None:
    click.echo(_json(
        LocalProfileStore(load_profile_root(release_profile)).list()
    ))


@client_profile.command("bootstrap")
@click.option("--profile-id", required=True)
@click.option("--display-name", required=True)
@click.option("--server-url", required=True)
@click.option("--agent-id", required=True)
@click.option(
    "--role",
    type=click.Choice(["planning", "research"]),
    default="research",
)
@click.option("--principal-ref", default="")
@click.option(
    "--source-mode",
    type=click.Choice(["reference", "snapshot"]),
    default="reference",
)
@click.option("--snapshot-ref", default="")
@click.option(
    "--workspace-root",
    type=click.Path(file_okay=False, path_type=Path),
)
@_root_option
@friendly_errors
def bootstrap_profile(
    profile_id: str,
    display_name: str,
    server_url: str,
    agent_id: str,
    role: str,
    principal_ref: str,
    source_mode: str,
    snapshot_ref: str,
    workspace_root: Path | None,
    release_profile: Path | None,
) -> None:
    """Idempotently discover, claim, and register one local Agent profile."""
    root = load_profile_root(release_profile)
    store = LocalProfileStore(root)
    if not principal_ref:
        raise ValueError("principal_ref is required")
    client = FactorTesterClient(HttpSession(server_url))
    authenticated = client.current_principal()
    authenticated_ref = str(authenticated.get("username") or "")
    if authenticated_ref != principal_ref:
        raise ValueError("authenticated principal does not match principal_ref")
    projection = client.factor_library_source_projection(principal_ref)
    body = projection.get("projection") or {}
    if body.get("principal") != principal_ref:
        raise ValueError("factor-library projection principal mismatch")
    if body.get("owner_ref") != principal_ref:
        raise ValueError("factor-library projection owner mismatch")
    serialized = json.dumps(body, ensure_ascii=False).lower()
    if any(item in serialized for item in ("source_code", "math_expr", ".py")):
        raise ValueError("factor-library projection contains source material")
    projection_hash = str(projection.get("projection_hash") or "")
    if not projection_hash:
        raise ValueError("factor-library projection hash is missing")
    try:
        existing = store.load(profile_id)
    except ValueError:
        existing = None
    if existing is not None:
        bound_principals = {
            str(item.get("principal_ref") or "")
            for item in existing.get("initialization_sources", [])
        }
        if bound_principals and bound_principals != {principal_ref}:
            raise ValueError(
                "profile is bound to another principal; rebind or create a new profile"
            )
    discovered = True
    if existing is None:
        discovered = False
        store.save(new_local_profile(
            profile_id=profile_id,
            display_name=display_name,
            server_url=server_url,
            workspace_root=workspace_root
            or default_profile_workspace_root(profile_id),
        ))
    store.upsert_initialization_source(profile_id, {
        "source_id": "principal-factor-library",
        "kind": "server_factor_library",
        "owner_ref": principal_ref,
        "mode": source_mode,
        "source_ref": f"factortester://factor-library/{principal_ref}",
        "snapshot_ref": snapshot_ref,
        "principal_ref": principal_ref,
        "session_ref": (
            f"session-binding://{principal_ref}/{profile_id}/{projection_hash}"
        ),
        "projection_hash": projection_hash,
        "source_materialized": False,
    })
    scope = (
        {"workspace_id": "all"}
        if role == "planning"
        else {"instance_id": "unbound", "branch_id": "unbound"}
    )
    profile = store.upsert_agent(profile_id, {
        "agent_id": agent_id,
        "role": role,
        "scope": scope,
        "status": "needs_scope",
        "next_action": "Bind a real workspace or research instance and branch.",
    })
    click.echo(_json({
        "schema_version": 1,
        "discovered_existing_profile": discovered,
        "local_profile_claimed": True,
        "local_source_registered": True,
        "server_visibility_verified": True,
        "ready": False,
        "profile": profile,
        "agent_prompt": (
            f"Use FactorTester profile '{profile_id}' as Agent "
            f"'{agent_id}', inspect its initialization provenance, "
            "bind a real research scope, then resume work."
        ),
    }))


@client_profile.group("workspace")
def profile_workspace() -> None:
    """Plan and audit visible local factor workspaces."""


@profile_workspace.command("plan")
@click.argument("profile_id")
@click.option(
    "--workspace",
    "workspace_specs",
    type=(str, click.Path(exists=True, file_okay=False, path_type=Path),
          click.Choice(["owner", "granted", "read_only"]), str),
    multiple=True,
    required=True,
    metavar="ID SOURCE ACCESS_MODE SERVER_REF",
)
@click.option(
    "--target-root",
    type=click.Path(file_okay=False, path_type=Path),
)
@click.option(
    "--output",
    required=True,
    type=click.Path(dir_okay=False, path_type=Path),
)
@friendly_errors
def plan_profile_workspace(
    profile_id: str,
    workspace_specs: tuple[tuple[str, Path, str, str], ...],
    target_root: Path | None,
    output: Path,
) -> None:
    plan = plan_workspace_migration(
        profile_id,
        target_root or default_profile_workspace_root(profile_id),
        [
            {
                "workspace_id": workspace_id,
                "source": str(source),
                "access_mode": access_mode,
                "server_workspace_ref": server_ref,
            }
            for workspace_id, source, access_mode, server_ref
            in workspace_specs
        ],
    )
    write_json(output, plan)
    click.echo(_json(plan))


@profile_workspace.command("apply")
@click.argument(
    "plan_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@_root_option
@friendly_errors
def apply_profile_workspace(
    plan_path: Path,
    release_profile: Path | None,
) -> None:
    plan = read_json(plan_path)
    if not isinstance(plan, dict):
        raise ValueError("workspace migration plan is invalid")
    root = load_profile_root(release_profile)
    click.echo(_json(apply_workspace_migration(root, plan)))


@profile_workspace.command("verify")
@click.argument("profile_id")
@_root_option
@friendly_errors
def verify_profile_workspace(
    profile_id: str,
    release_profile: Path | None,
) -> None:
    root = load_profile_root(release_profile)
    click.echo(_json(verify_workspace_migration(root, profile_id)))


@profile_workspace.command("rollback")
@click.argument("profile_id")
@click.argument("migration_id")
@_root_option
@friendly_errors
def rollback_profile_workspace(
    profile_id: str,
    migration_id: str,
    release_profile: Path | None,
) -> None:
    root = load_profile_root(release_profile)
    click.echo(_json(rollback_workspace_migration(
        root, profile_id, migration_id
    )))


@profile_workspace.command("repair-plan")
@click.argument("profile_id")
@click.argument("workspace_id")
@click.option(
    "--output",
    required=True,
    type=click.Path(dir_okay=False, path_type=Path),
)
@_root_option
@friendly_errors
def plan_profile_workspace_repair(
    profile_id: str,
    workspace_id: str,
    output: Path,
    release_profile: Path | None,
) -> None:
    """Preview repair of an already materialized legacy workspace."""
    plan = plan_workspace_repair(
        load_profile_root(release_profile), profile_id, workspace_id
    )
    write_json(output, plan)
    click.echo(_json(plan))


@profile_workspace.command("repair-apply")
@click.argument(
    "plan_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@_root_option
@friendly_errors
def apply_profile_workspace_repair(
    plan_path: Path,
    release_profile: Path | None,
) -> None:
    """Atomically repair a previewed legacy workspace."""
    plan = read_json(plan_path)
    if not isinstance(plan, dict):
        raise ValueError("workspace repair plan is invalid")
    click.echo(_json(apply_workspace_repair(
        load_profile_root(release_profile), plan
    )))


@profile_workspace.command("repair-verify")
@click.argument("profile_id")
@click.argument("repair_id")
@_root_option
@friendly_errors
def verify_profile_workspace_repair(
    profile_id: str,
    repair_id: str,
    release_profile: Path | None,
) -> None:
    click.echo(_json(verify_workspace_repair(
        load_profile_root(release_profile), profile_id, repair_id
    )))


@profile_workspace.command("repair-rollback")
@click.argument("profile_id")
@click.argument("repair_id")
@_root_option
@friendly_errors
def rollback_profile_workspace_repair(
    profile_id: str,
    repair_id: str,
    release_profile: Path | None,
) -> None:
    click.echo(_json(rollback_workspace_repair(
        load_profile_root(release_profile), profile_id, repair_id
    )))


@client_profile.group("agent")
def profile_agent() -> None:
    """Configure provider-neutral local Agent identities."""


@profile_agent.command("set")
@click.argument("profile_id")
@click.option("--agent-id", required=True)
@click.option(
    "--role",
    type=click.Choice(["planning", "research"]),
    required=True,
)
@click.option("--workspace-id", default="")
@click.option("--instance-id", default="")
@click.option("--branch-id", default="")
@_root_option
@friendly_errors
def set_profile_agent(
    profile_id: str,
    agent_id: str,
    role: str,
    workspace_id: str,
    instance_id: str,
    branch_id: str,
    release_profile: Path | None,
) -> None:
    scope = (
        {"workspace_id": workspace_id}
        if role == "planning"
        else {"instance_id": instance_id, "branch_id": branch_id}
    )
    store = LocalProfileStore(load_profile_root(release_profile))
    click.echo(_json(store.upsert_agent(profile_id, {
        "agent_id": agent_id,
        "role": role,
        "scope": scope,
    })))


@client_profile.group("adapter")
def profile_adapter() -> None:
    """Configure local adapter references without storing secrets."""


@profile_adapter.command("set")
@click.argument("profile_id")
@click.option("--adapter-id", required=True)
@click.option("--enabled/--disabled", default=True)
@click.option("--credential-ref", default="")
@click.option("--configuration-ref", default="")
@_root_option
@friendly_errors
def set_profile_adapter(
    profile_id: str,
    adapter_id: str,
    enabled: bool,
    credential_ref: str,
    configuration_ref: str,
    release_profile: Path | None,
) -> None:
    store = LocalProfileStore(load_profile_root(release_profile))
    click.echo(_json(store.upsert_adapter(profile_id, {
        "adapter_id": adapter_id,
        "enabled": enabled,
        "credential_ref": credential_ref,
        "configuration_ref": configuration_ref,
    })))
