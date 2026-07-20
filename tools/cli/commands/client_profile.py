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
    default_profile_workspace_root,
    plan_workspace_migration,
    rollback_workspace_migration,
    verify_workspace_migration,
)


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
