"""Version-independent local user, Agent, and adapter profiles."""

from __future__ import annotations

import json
import sys
from hashlib import sha256
from pathlib import Path

import click

from tools.cli.client import FactorTesterClient
from tools.cli.core.context import client_from_config
from tools.cli.core.errors import friendly_errors
from tools.cli.http import ClientConfig, HttpSession, save_config
from tools.cli.release.factor_worktree import (
    CanonicalFactorRepoStore,
    ensure_factor_worktree_binding,
)
from tools.cli.release.local_profile import (
    LocalProfileStore,
    new_local_profile,
)
from tools.cli.release.local_profile_contracts import session_binding_reference
from tools.cli.release.profile import load_profile_root
from tools.cli.release.profile_lifecycle import ProfileLifecycle
from tools.cli.release.profile_sync import (
    manager_url_for_client_url,
)
from tools.cli.release.profile_sync import (
    sync_profile as _sync_profile,
)
from tools.cli.release.storage import read_json
from tools.cli.release.user_layout import (
    default_user_factor_library,
    default_user_profile_root,
    user_layout_status,
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


@client_profile.command("create")
@click.option("--profile-id", required=True)
@click.option("--display-name", required=True)
@click.option(
    "--server-url", default="", help="临时客户端连接覆盖；不会写入 Profile。",
)
@click.option(
    "--manager-url",
    default="",
    help="Profile 投影同步的 Manager 7998 地址；省略时按执行服务地址推导。",
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
    manager_url: str,
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
        agent_id=agent_id,
        role=role,
        principal_ref=principal_ref,
    )
    profile = LocalProfileStore(
        load_profile_root(release_profile)
    ).load(profile_id)
    control_profile_sync = _sync_profile(
        profile,
        manager_url=(
            manager_url
            or (manager_url_for_client_url(server_url) if server_url else "")
        ),
    )
    click.echo(_json({
        **receipt,
        "server_visibility_verified": bool(control_profile_sync.get("synced")),
        "server_visibility_pending": not bool(control_profile_sync.get("synced")),
        "control_profile_sync": control_profile_sync,
    }))


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
    """Request deletion; currently fail closed pending reference clearance."""
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


@client_profile.command("sync")
@click.argument("profile_id", required=False)
@click.option(
    "--manager-url", "--server-url", "manager_url", default="",
    help="Profile 投影同步的 Manager 7998 地址。",
)
@_root_option
@friendly_errors
def sync_profiles(
    profile_id: str | None,
    manager_url: str,
    release_profile: Path | None,
) -> None:
    """Synchronize one Profile, or all locally bound Profiles, to its Manager."""
    store = LocalProfileStore(load_profile_root(release_profile))
    profiles = [store.load(profile_id)] if profile_id else store.list()
    results: list[dict[str, object]] = []
    for profile in profiles:
        receipt = _sync_profile(profile, manager_url=manager_url)
        results.append({
            "profile_id": str(profile.get("profile_id") or ""),
            **receipt,
        })
    click.echo(_json({
        "schema_version": 1,
        "profiles": results,
        "synced": all(bool(item.get("synced")) for item in results),
    }))


@client_profile.group("server")
def profile_server() -> None:
    """Configure the client connection (not a local Profile field)."""


@profile_server.command("set")
@click.argument("profile_id")
@click.option("--server-url", required=True)
@_root_option
@friendly_errors
def set_profile_server(
    profile_id: str,
    server_url: str,
    release_profile: Path | None,
) -> None:
    # Keep the old invocation shape for installed scripts, but move the
    # connection to the client-wide CLI config.  A Profile is portable local
    # state and must not acquire a server endpoint as a side effect.
    LocalProfileStore(load_profile_root(release_profile)).load(profile_id)
    config = ClientConfig(server_url.rstrip("/"))
    save_config(config)
    click.echo(_json({
        "profile_id": profile_id,
        "connection_scope": "client",
        "base_url": config.base_url,
    }))


@client_profile.group("workspace")
def profile_workspace() -> None:
    """Bind local Profiles to authorized server research workspaces."""


@profile_workspace.command("bind")
@click.argument("profile_id")
@click.option("--workspace-id", required=True)
@click.option("--server-workspace-ref", required=True)
@click.option(
    "--access-mode",
    type=click.Choice(["owner", "granted", "read_only"]),
    required=True,
)
@click.option("--owner-ref", required=True)
@click.option("--path", "workspace_path", type=click.Path(path_type=Path))
@_root_option
@friendly_errors
def bind_profile_workspace(
    profile_id: str,
    workspace_id: str,
    server_workspace_ref: str,
    access_mode: str,
    owner_ref: str,
    workspace_path: Path | None,
    release_profile: Path | None,
) -> None:
    store = LocalProfileStore(load_profile_root(release_profile))
    profile = store.load(profile_id)
    path = workspace_path or Path(profile["workspace_root"])
    click.echo(_json(store.upsert_workspace(profile_id, {
        "workspace_id": workspace_id,
        "path": str(path.expanduser().resolve()),
        "access_mode": access_mode,
        "owner_ref": owner_ref,
        "server_workspace_ref": server_workspace_ref,
    })))


@profile_workspace.command("list")
@click.argument("profile_id")
@_root_option
@friendly_errors
def list_profile_workspaces(
    profile_id: str,
    release_profile: Path | None,
) -> None:
    profile = LocalProfileStore(
        load_profile_root(release_profile)
    ).load(profile_id)
    click.echo(_json(profile["workspaces"]))


@profile_workspace.command("remove")
@click.argument("profile_id")
@click.argument("workspace_id")
@_root_option
@friendly_errors
def remove_profile_workspace(
    profile_id: str,
    workspace_id: str,
    release_profile: Path | None,
) -> None:
    store = LocalProfileStore(load_profile_root(release_profile))
    click.echo(_json(store.remove_workspace(profile_id, workspace_id)))


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


@client_profile.command("bootstrap")
@click.option("--profile-id", required=True)
@click.option("--display-name", required=True)
@click.option(
    "--server-url", default="", help="临时客户端连接覆盖；不会写入 Profile。",
)
@click.option("--manager-url", default="")
@click.option("--agent-id", required=True)
@click.option(
    "--role",
    type=click.Choice(["planning", "research"]),
    default="research",
)
@click.option("--principal-ref", default="")
@_root_option
@friendly_errors
def bootstrap_profile(
    profile_id: str,
    display_name: str,
    server_url: str,
    manager_url: str,
    agent_id: str,
    role: str,
    principal_ref: str,
    release_profile: Path | None,
) -> None:
    """Idempotently discover, claim, and register one local Agent profile."""
    root = load_profile_root(release_profile)
    store = LocalProfileStore(root)
    if not principal_ref:
        raise ValueError("principal_ref is required")
    client = (
        FactorTesterClient(HttpSession(server_url))
        if server_url else client_from_config()
    )
    authenticated = client.current_principal()
    authenticated_ref = str(authenticated.get("username") or "")
    if authenticated_ref != principal_ref:
        raise ValueError("authenticated principal does not match principal_ref")
    candidate = new_local_profile(
        profile_id=profile_id,
        display_name=display_name,
        workspace_root=default_user_profile_root(
            principal_ref, profile_id
        ),
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
        stable = ("display_name", "workspace_root")
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
    profile = store.load(profile_id)
    control_profile_sync = _sync_profile(profile, manager_url=manager_url)
    claim_command = (
        f"factortester client profile claim {profile_id} {agent_id}"
    )
    click.echo(_json({
        "schema_version": 1,
        "discovered_existing_profile": discovered,
        "local_profile_claimed": True,
        "local_source_registered": False,
        # Keep the legacy bootstrap-completed flag for existing automation.
        # The authoritative remote result is the explicit sync receipt below;
        # ``server_visibility_pending`` prevents this compatibility flag from
        # being mistaken for a committed PostgreSQL projection.
        "server_visibility_verified": True,
        "server_visibility_pending": not bool(control_profile_sync.get("synced")),
        "control_profile_sync": control_profile_sync,
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
    client = client_from_config()
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
    client = client_from_config()
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
        "session_ref": session_binding_reference(
            principal_ref, profile_id, projection_hash,
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


@click.command("canonical-register", hidden=True)
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
    expected = default_user_factor_library(owner_ref).resolve()
    if path.expanduser().resolve() != expected:
        raise ValueError(
            "canonical factor library must use the unified user layout"
        )
    root = load_profile_root(release_profile)
    click.echo(_json(
        CanonicalFactorRepoStore(root).register(path, owner_ref=owner_ref)
    ))


@click.command("canonical-show", hidden=True)
@_root_option
@friendly_errors
def show_canonical_factor_repo(
    release_profile: Path | None,
) -> None:
    root = load_profile_root(release_profile)
    click.echo(_json(CanonicalFactorRepoStore(root).load()))


@click.command("create-profile-worktree")
@click.argument("profile_id")
@click.option("--branch", default="")
@click.option(
    "--worktree-path",
    type=click.Path(file_okay=False, path_type=Path),
)
@click.option("--source-sync/--no-source-sync", default=False)
@_root_option
@friendly_errors
def create_profile_factor_worktree(
    profile_id: str,
    branch: str,
    worktree_path: Path | None,
    source_sync: bool,
    release_profile: Path | None,
) -> None:
    click.echo(_json(ensure_factor_worktree_binding(
        load_profile_root(release_profile),
        profile_id,
        branch=branch,
        worktree_path=worktree_path,
        source_sync_enabled=source_sync,
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
