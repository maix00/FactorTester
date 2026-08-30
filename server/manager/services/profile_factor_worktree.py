"""Bind a server-hosted Profile replica to the user's factor repository."""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from server.services.factor_workspace import sync_factor_workspace
from tools.cli.release.factor_worktree import (
    CanonicalFactorRepoStore,
    ensure_factor_worktree_binding,
)
from tools.cli.release.local_profile import LocalProfileStore, new_local_profile

_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.RLock()


def _principal_lock(principal: str) -> threading.RLock:
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(principal, threading.RLock())


def ensure_server_profile_factor_worktree(
    principal: str,
    profile_id: str,
    workspace_root: Path,
    client_root: Path,
    *,
    canonical_root: Path | None = None,
    synchronize: Callable[[str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Create one persistent Profile branch/worktree in the user's factor repo.

    The database factor library materializes the ``download`` branch. Every
    Profile receives an isolated ``agent/<profile>`` worktree over the same Git
    object store. Accepted Profile commits merge into ``upload``; the existing
    upload hook synchronizes that branch back into the database factor library.
    """
    owner = str(principal or "").strip()
    identifier = str(profile_id or "").strip()
    workspace = Path(workspace_root).expanduser().resolve()
    local_root = Path(client_root).expanduser().resolve()
    if not owner or not identifier:
        raise ValueError("principal and profile_id are required")

    with _principal_lock(owner):
        store = LocalProfileStore(local_root)
        try:
            profile = store.load(identifier)
        except ValueError:
            profile = new_local_profile(
                profile_id=identifier,
                display_name=identifier,
                workspace_root=workspace,
                principal_ref=owner,
            )
            store.save(profile)
        else:
            binding = profile.get("session_binding") or {}
            if str(binding.get("principal_ref") or "") != owner:
                raise ValueError("Profile factor worktree principal does not match")
            if Path(str(profile.get("workspace_root") or "")).resolve() != workspace:
                raise ValueError("Profile factor worktree workspace does not match")

        current = store.load(identifier).get("factor_workspace_binding") or {}
        if current:
            return ensure_factor_worktree_binding(local_root, identifier)

        source = canonical_root
        if source is None:
            sync = synchronize or (
                lambda value: sync_factor_workspace(value, branch_mode="force")
            )
            result = sync(owner)
            source = Path(str(result.get("workspace_root") or ""))
        canonical = Path(source).expanduser().resolve()
        CanonicalFactorRepoStore(local_root).register(
            canonical,
            owner_ref=owner,
        )

        return ensure_factor_worktree_binding(
            local_root,
            identifier,
            branch=f"agent/{identifier}",
            worktree_path=workspace / "factor-worktree",
            source_sync_enabled=False,
        )
