"""Version-independent local user, Agent, and adapter profiles."""

from __future__ import annotations

import json
from hashlib import sha256
import sys
from pathlib import Path
import click

from tools.cli.core.errors import friendly_errors
from tools.cli.release.local_profile import (
    LocalProfileStore,
    new_local_profile,
)
from tools.cli.release.profile import load_profile_root
from tools.cli.release.profile_lifecycle import ProfileLifecycle
from tools.cli.release.personal_workspace_migration import (
    apply_personal_workspace_migration,
    personal_workspace_status,
    plan_personal_workspace_migration,
    rollback_personal_workspace_migration,
    verify_personal_workspace_migration,
)
from tools.cli.release.legacy_workspace_cleanup import (
    plan_legacy_workspace_cleanup,
    purge_legacy_workspaces,
)
from tools.cli.release.user_layout_migration import (
    apply_user_layout_migration,
    default_user_profile_root,
    plan_user_layout_migration,
    rollback_user_layout_migration,
    user_layout_status,
    verify_user_layout_migration,
)
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
from tools.cli.release.factor_worktree import (
    CanonicalFactorRepoStore,
    apply_factor_worktree_binding,
    plan_factor_worktree_binding,
    repair_factor_worktree_binding,
    rollback_factor_worktree_binding,
    verify_factor_worktree_binding,
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


@client_profile.command("import-ui-session")
@click.option("--server-url", required=True)
@click.option("--principal-ref", required=True)
@friendly_errors
def import_ui_session(server_url: str, principal_ref: str) -> None:
    """Import the native UI cookie bridge from JSON on stdin."""
    value = json.load(sys.stdin)
    if not isinstance(value, dict) or set(value) != {"cookies"}:
        raise ValueError("UI session bridge payload is invalid")
    cookies = value["cookies"]
    if not isinstance(cookies, list):
        raise ValueError("UI session cookies must be an array")
    session = HttpSession(server_url)
    session.import_cookies(cookies)
    principal = FactorTesterClient(session).current_principal()
    observed = str(principal.get("username") or "")
    if observed != principal_ref:
        session.clear_cookies()
        raise ValueError("imported UI principal does not match")
    click.echo(_json({
        "schema_version": 1,
        "principal_ref": observed,
        "verified": True,
    }))


@client_profile.command("clear-ui-session")
@click.option("--server-url", required=True)
@friendly_errors
def clear_ui_session(server_url: str) -> None:
    session = HttpSession(server_url)
    session.clear_cookies()
    click.echo(_json({"schema_version": 1, "cleared": True}))


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
    candidate = new_local_profile(
        profile_id=profile_id,
        display_name=display_name,
        server_url=server_url,
        workspace_root=workspace_root
        or default_profile_workspace_root(profile_id),
    )
    try:
        profile = store.load(profile_id)
    except ValueError:
        profile = store.save(candidate)
    else:
        stable = ("display_name", "server", "workspace_root")
        if any(profile[key] != candidate[key] for key in stable):
            raise ValueError(
                "existing profile configuration differs; use an explicit "
                "profile update"
            )
    store.ensure_workspace_root(profile_id)
    click.echo(_json(profile))


@client_profile.command("create")
@click.option("--profile-id", required=True)
@click.option("--display-name", required=True)
@click.option("--server-url", required=True)
@click.option(
    "--workspace-root",
    type=click.Path(file_okay=False, path_type=Path),
)
@click.option("--agent-id", default="")
@click.option(
    "--role",
    type=click.Choice(["planning", "research"]),
    default="research",
)
@click.option("--principal-ref", default="")
@_root_option
@friendly_errors
def create_profile(
    profile_id: str,
    display_name: str,
    server_url: str,
    workspace_root: Path | None,
    agent_id: str,
    role: str,
    principal_ref: str,
    release_profile: Path | None,
) -> None:
    """Create one provider-neutral local Profile and optional Agent."""
    receipt = ProfileLifecycle(
        load_profile_root(release_profile)
    ).create(
        profile_id=profile_id,
        display_name=display_name,
        server_url=server_url,
        workspace_root=workspace_root,
        agent_id=agent_id,
        role=role,
        principal_ref=principal_ref,
    )
    click.echo(_json(receipt))


@client_profile.command("deactivate")
@click.argument("profile_id")
@_root_option
@friendly_errors
def deactivate_profile(
    profile_id: str,
    release_profile: Path | None,
) -> None:
    click.echo(_json(ProfileLifecycle(
        load_profile_root(release_profile)
    ).deactivate(profile_id)))


@client_profile.command("delete")
@click.argument("profile_id")
@_root_option
@friendly_errors
def delete_profile(
    profile_id: str,
    release_profile: Path | None,
) -> None:
    """Unbind a clean worktree and delete local Profile metadata."""
    click.echo(_json(ProfileLifecycle(
        load_profile_root(release_profile)
    ).delete(profile_id)))


@client_profile.command("purge")
@click.argument("profile_id")
@_root_option
@friendly_errors
def purge_profile(
    profile_id: str,
    release_profile: Path | None,
) -> None:
    """Remove an empty deleted Profile workspace and tombstone."""
    click.echo(_json(ProfileLifecycle(
        load_profile_root(release_profile)
    ).purge(profile_id)))


@client_profile.command("list")
@_root_option
@friendly_errors
def list_profiles(release_profile: Path | None) -> None:
    click.echo(_json(
        LocalProfileStore(load_profile_root(release_profile)).list()
    ))


@client_profile.group("user-layout")
def profile_user_layout() -> None:
    """Manage one principal-scoped ownership tree."""


@profile_user_layout.command("show")
@click.option("--principal", "principal_ref", required=True)
@_root_option
@friendly_errors
def show_user_layout(
    principal_ref: str,
    release_profile: Path | None,
) -> None:
    click.echo(_json(user_layout_status(
        load_profile_root(release_profile), principal_ref
    )))


@profile_user_layout.group("migration")
def user_layout_migration() -> None:
    """Move canonical and Profile roots as one recoverable transaction."""


@user_layout_migration.command("plan")
@click.option("--principal", "principal_ref", required=True)
@click.option(
    "--output",
    required=True,
    type=click.Path(dir_okay=False, path_type=Path),
)
@_root_option
@friendly_errors
def plan_user_layout(
    principal_ref: str,
    output: Path,
    release_profile: Path | None,
) -> None:
    plan = plan_user_layout_migration(
        load_profile_root(release_profile), principal_ref
    )
    write_json(output, plan)
    click.echo(_json(plan))


@user_layout_migration.command("apply")
@click.argument(
    "plan_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@_root_option
@friendly_errors
def apply_user_layout(
    plan_path: Path,
    release_profile: Path | None,
) -> None:
    plan = read_json(plan_path)
    if not isinstance(plan, dict):
        raise ValueError("principal user layout migration plan is invalid")
    click.echo(_json(apply_user_layout_migration(
        load_profile_root(release_profile), plan
    )))


@user_layout_migration.command("verify")
@click.argument("migration_id")
@_root_option
@friendly_errors
def verify_user_layout(
    migration_id: str,
    release_profile: Path | None,
) -> None:
    click.echo(_json(verify_user_layout_migration(
        load_profile_root(release_profile), migration_id
    )))


@user_layout_migration.command("rollback")
@click.argument("migration_id")
@_root_option
@friendly_errors
def rollback_user_layout(
    migration_id: str,
    release_profile: Path | None,
) -> None:
    click.echo(_json(rollback_user_layout_migration(
        load_profile_root(release_profile), migration_id
    )))


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
    candidate = new_local_profile(
        profile_id=profile_id,
        display_name=display_name,
        server_url=server_url,
        workspace_root=workspace_root
        or default_user_profile_root(principal_ref, profile_id),
        principal_ref=principal_ref,
    )
    try:
        existing = store.load(profile_id)
    except ValueError:
        existing = None
    if existing is not None:
        binding = existing.get("session_binding") or {}
        if (
            binding
            and binding.get("principal_ref") != principal_ref
        ):
            raise ValueError(
                "profile is bound to another principal; rebind or create a new profile"
            )
        stable = ("display_name", "server", "workspace_root")
        if any(existing[key] != candidate[key] for key in stable):
            raise ValueError(
                "existing profile configuration differs; use an explicit "
                "profile update"
            )
    discovered = True
    if existing is None:
        discovered = False
        store.save(candidate)
    store.bind_session(profile_id, principal_ref=principal_ref)
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
    claim = store.claim_agent(profile_id, agent_id)
    claim_command = (
        f"factortester client profile claim {profile_id} {agent_id}"
    )
    click.echo(_json({
        "schema_version": 1,
        "discovered_existing_profile": discovered,
        "local_profile_claimed": True,
        "local_source_registered": False,
        "server_visibility_verified": True,
        "ready": False,
        "can_start_inspection_and_planning": True,
        "claim_command": claim_command,
        "claim_receipt": claim,
        "profile": profile,
        "agent_prompt": (
            f"Use profile={profile_id} agent={agent_id}; run "
            f"`{claim_command}` to deterministically resume inspection "
            "and planning. Bind an approved research scope before execution."
        ),
    }))


@client_profile.command("claim")
@click.argument("profile_id")
@click.argument("agent_id")
@_root_option
@friendly_errors
def claim_profile_agent(
    profile_id: str,
    agent_id: str,
    release_profile: Path | None,
) -> None:
    """Resume one pre-registered Agent identity from a compact prompt."""
    receipt = LocalProfileStore(
        load_profile_root(release_profile)
    ).claim_agent(profile_id, agent_id)
    click.echo(_json(receipt))


@client_profile.group("initialization")
def profile_initialization() -> None:
    """Discover and bind authorized factor-library provenance."""


@profile_initialization.command("list")
@click.argument("profile_id")
@_root_option
@friendly_errors
def list_profile_initialization_sources(
    profile_id: str,
    release_profile: Path | None,
) -> None:
    store = LocalProfileStore(load_profile_root(release_profile))
    profile = store.load(profile_id)
    binding = profile.get("session_binding") or {}
    principal_ref = str(binding.get("principal_ref") or "")
    client = FactorTesterClient(HttpSession(profile["server"]["base_url"]))
    authenticated = client.current_principal()
    if str(authenticated.get("username") or "") != principal_ref:
        raise ValueError("authenticated principal does not match profile")
    click.echo(_json(client.factor_library_sources()))


@profile_initialization.command("bind")
@click.argument("profile_id")
@click.option("--owner-ref", required=True)
@click.option(
    "--mode",
    type=click.Choice(["reference", "snapshot"]),
    default="reference",
)
@click.option("--snapshot-ref", default="")
@_root_option
@friendly_errors
def bind_profile_initialization_source(
    profile_id: str,
    owner_ref: str,
    mode: str,
    snapshot_ref: str,
    release_profile: Path | None,
) -> None:
    root = load_profile_root(release_profile)
    store = LocalProfileStore(root)
    profile = store.load(profile_id)
    binding = profile.get("session_binding") or {}
    principal_ref = str(binding.get("principal_ref") or "")
    client = FactorTesterClient(HttpSession(profile["server"]["base_url"]))
    authenticated = client.current_principal()
    if str(authenticated.get("username") or "") != principal_ref:
        raise ValueError("authenticated principal does not match profile")
    sources = client.factor_library_sources()
    granted = {
        str(item.get("owner_ref") or "")
        for item in sources.get("sources", [])
    }
    if owner_ref not in granted:
        raise ValueError("factor-library owner is not in authorized grants")
    projection = client.factor_library_source_projection(owner_ref)
    body = projection.get("projection") or {}
    if body.get("principal") != principal_ref:
        raise ValueError("factor-library projection principal mismatch")
    if body.get("owner_ref") != owner_ref:
        raise ValueError("factor-library projection owner mismatch")
    serialized = json.dumps(body, ensure_ascii=False).lower()
    if any(item in serialized for item in ("source_code", "math_expr", ".py")):
        raise ValueError("factor-library projection contains source material")
    projection_hash = str(projection.get("projection_hash") or "")
    if not projection_hash:
        raise ValueError("factor-library projection hash is missing")
    click.echo(_json(store.upsert_initialization_source(profile_id, {
        "source_id": (
            "factor-library-"
            + sha256(owner_ref.encode()).hexdigest()[:12]
        ),
        "kind": "server_factor_library",
        "owner_ref": owner_ref,
        "mode": mode,
        "source_ref": f"factortester://factor-library/{owner_ref}",
        "snapshot_ref": snapshot_ref,
        "principal_ref": principal_ref,
        "session_ref": (
            f"session-binding://{principal_ref}/{profile_id}/"
            f"{projection_hash}"
        ),
        "projection_hash": projection_hash,
        "source_materialized": False,
    })))


@client_profile.group("history")
def profile_history() -> None:
    """Manage compact local research/report references."""


@profile_history.command("list")
@click.argument("profile_id")
@_root_option
@friendly_errors
def list_profile_history(
    profile_id: str,
    release_profile: Path | None,
) -> None:
    profile = LocalProfileStore(
        load_profile_root(release_profile)
    ).load(profile_id)
    click.echo(_json(profile["research_records"]))


@profile_history.command("upsert")
@click.argument("profile_id")
@click.option(
    "--record",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@_root_option
@friendly_errors
def upsert_profile_history(
    profile_id: str,
    record: Path,
    release_profile: Path | None,
) -> None:
    value = read_json(record)
    if not isinstance(value, dict):
        raise ValueError("research record must be an object")
    click.echo(_json(LocalProfileStore(
        load_profile_root(release_profile)
    ).upsert_research_record(profile_id, value)))


@client_profile.group("workspace")
def profile_workspace() -> None:
    """Plan and audit visible local factor workspaces."""


@client_profile.group("personal-workspace")
def profile_personal_workspace() -> None:
    """Manage the canonical personal factor workspace."""


@profile_personal_workspace.command("show")
@click.option("--principal", "principal_ref", required=True)
@_root_option
@friendly_errors
def show_personal_workspace(
    principal_ref: str,
    release_profile: Path | None,
) -> None:
    click.echo(_json(personal_workspace_status(
        load_profile_root(release_profile), principal_ref
    )))


@profile_personal_workspace.group("migration")
def personal_workspace_migration() -> None:
    """Relocate a canonical personal factor Git workspace safely."""


@profile_personal_workspace.group("cleanup")
def personal_workspace_cleanup() -> None:
    """Audit legacy workspaces before any gated cleanup."""


@personal_workspace_cleanup.command("plan")
@click.option(
    "--workspace",
    "workspaces",
    multiple=True,
    required=True,
    type=click.Path(exists=True, file_okay=False, path_type=Path),
)
@click.option(
    "--output",
    required=True,
    type=click.Path(dir_okay=False, path_type=Path),
)
@_root_option
@friendly_errors
def plan_legacy_personal_workspace_cleanup(
    workspaces: tuple[Path, ...],
    output: Path,
    release_profile: Path | None,
) -> None:
    plan = plan_legacy_workspace_cleanup(
        load_profile_root(release_profile), list(workspaces)
    )
    write_json(output, plan)
    click.echo(_json(plan))


@personal_workspace_cleanup.command("purge")
@click.argument(
    "plan_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@_root_option
@friendly_errors
def purge_legacy_personal_workspaces(
    plan_path: Path,
    release_profile: Path | None,
) -> None:
    plan = read_json(plan_path)
    if not isinstance(plan, dict):
        raise ValueError("legacy workspace cleanup plan is invalid")
    click.echo(_json(purge_legacy_workspaces(
        load_profile_root(release_profile), plan
    )))


@personal_workspace_migration.command("plan")
@click.option("--principal", "principal_ref", required=True)
@click.option(
    "--target",
    type=click.Path(file_okay=False, path_type=Path),
)
@click.option(
    "--output",
    required=True,
    type=click.Path(dir_okay=False, path_type=Path),
)
@_root_option
@friendly_errors
def plan_personal_workspace(
    principal_ref: str,
    target: Path | None,
    output: Path,
    release_profile: Path | None,
) -> None:
    plan = plan_personal_workspace_migration(
        load_profile_root(release_profile),
        principal_ref,
        target=target,
    )
    write_json(output, plan)
    click.echo(_json(plan))


@personal_workspace_migration.command("apply")
@click.argument(
    "plan_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@_root_option
@friendly_errors
def apply_personal_workspace(
    plan_path: Path,
    release_profile: Path | None,
) -> None:
    plan = read_json(plan_path)
    if not isinstance(plan, dict):
        raise ValueError("personal workspace migration plan is invalid")
    click.echo(_json(apply_personal_workspace_migration(
        load_profile_root(release_profile), plan
    )))


@personal_workspace_migration.command("verify")
@click.argument("migration_id")
@_root_option
@friendly_errors
def verify_personal_workspace(
    migration_id: str,
    release_profile: Path | None,
) -> None:
    click.echo(_json(verify_personal_workspace_migration(
        load_profile_root(release_profile), migration_id
    )))


@personal_workspace_migration.command("rollback")
@click.argument("migration_id")
@_root_option
@friendly_errors
def rollback_personal_workspace(
    migration_id: str,
    release_profile: Path | None,
) -> None:
    click.echo(_json(rollback_personal_workspace_migration(
        load_profile_root(release_profile), migration_id
    )))


@client_profile.group("factor-worktree")
def profile_factor_worktree() -> None:
    """Bind isolated profile worktrees to one canonical factor Git repo."""


@profile_factor_worktree.command("canonical-register")
@click.option(
    "--path",
    required=True,
    type=click.Path(exists=True, file_okay=False, path_type=Path),
)
@click.option("--owner-ref", required=True)
@_root_option
@friendly_errors
def register_canonical_factor_repo(
    path: Path,
    owner_ref: str,
    release_profile: Path | None,
) -> None:
    root = load_profile_root(release_profile)
    click.echo(_json(
        CanonicalFactorRepoStore(root).register(path, owner_ref=owner_ref)
    ))


@profile_factor_worktree.command("canonical-show")
@_root_option
@friendly_errors
def show_canonical_factor_repo(
    release_profile: Path | None,
) -> None:
    root = load_profile_root(release_profile)
    click.echo(_json(CanonicalFactorRepoStore(root).load()))


@profile_factor_worktree.command("plan")
@click.argument("profile_id")
@click.option("--branch", default="")
@click.option(
    "--worktree-path",
    type=click.Path(file_okay=False, path_type=Path),
)
@click.option("--source-sync/--no-source-sync", default=False)
@click.option(
    "--output",
    required=True,
    type=click.Path(dir_okay=False, path_type=Path),
)
@_root_option
@friendly_errors
def plan_profile_factor_worktree(
    profile_id: str,
    branch: str,
    worktree_path: Path | None,
    source_sync: bool,
    output: Path,
    release_profile: Path | None,
) -> None:
    root = load_profile_root(release_profile)
    plan = plan_factor_worktree_binding(
        root,
        profile_id,
        branch=branch,
        worktree_path=worktree_path,
        source_sync_enabled=source_sync,
    )
    write_json(output, plan)
    click.echo(_json(plan))


@profile_factor_worktree.command("apply")
@click.argument(
    "plan_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@_root_option
@friendly_errors
def apply_profile_factor_worktree(
    plan_path: Path,
    release_profile: Path | None,
) -> None:
    plan = read_json(plan_path)
    if not isinstance(plan, dict):
        raise ValueError("factor worktree plan is invalid")
    click.echo(_json(apply_factor_worktree_binding(
        load_profile_root(release_profile), plan
    )))


@profile_factor_worktree.command("verify")
@click.argument("profile_id")
@click.option("--run-pyright", is_flag=True)
@_root_option
@friendly_errors
def verify_profile_factor_worktree(
    profile_id: str,
    run_pyright: bool,
    release_profile: Path | None,
) -> None:
    click.echo(_json(verify_factor_worktree_binding(
        load_profile_root(release_profile),
        profile_id,
        run_pyright=run_pyright,
    )))


@profile_factor_worktree.command("repair")
@click.argument("profile_id")
@_root_option
@friendly_errors
def repair_profile_factor_worktree(
    profile_id: str,
    release_profile: Path | None,
) -> None:
    click.echo(_json(repair_factor_worktree_binding(
        load_profile_root(release_profile), profile_id
    )))


@profile_factor_worktree.command("rollback")
@click.argument("profile_id")
@click.argument("binding_id")
@_root_option
@friendly_errors
def rollback_profile_factor_worktree(
    profile_id: str,
    binding_id: str,
    release_profile: Path | None,
) -> None:
    click.echo(_json(rollback_factor_worktree_binding(
        load_profile_root(release_profile), profile_id, binding_id
    )))


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
