"""Server-side replica of the client Profile workspace layout.

The layout mirrors the client-side FactorTester contract.  This module only
resolves the server root and creates the Profile's persistent workspace replica;
it never treats that replica as the user's canonical factor library.
"""

from __future__ import annotations

import os
from pathlib import Path

from tools.cli.release.local_profile_contracts import (
    validate_local_identifier,
    validate_principal_identifier,
)


WORKSPACE_DIRECTORIES = (
    "factor-worktree",
    "strategy-worktree",
    "research",
    "reports",
    "manifests",
)


def profile_workspace_relative_path(principal: str, profile_id: str) -> str:
    """Return the portable relative path shared by client and server."""
    owner = validate_principal_identifier(principal, "principal")
    profile = validate_local_identifier(profile_id, "profile_id")
    return f"users/{owner}/profiles/{profile}"


def server_profile_workspace(
    data_root: str | Path,
    principal: str,
    profile_id: str,
) -> Path:
    root = Path(data_root).expanduser().resolve()
    relative = profile_workspace_relative_path(principal, profile_id)
    return root / relative


def ensure_server_profile_workspace(
    data_root: str | Path,
    principal: str,
    profile_id: str,
) -> Path:
    """Create the Profile workspace replica with owner-only permissions."""
    root = server_profile_workspace(data_root, principal, profile_id)
    root.mkdir(parents=True, exist_ok=True)
    for directory in WORKSPACE_DIRECTORIES:
        (root / directory).mkdir(exist_ok=True)
    for path in [root, *[root / directory for directory in WORKSPACE_DIRECTORIES]]:
        try:
            os.chmod(path, 0o700)
        except OSError:
            pass
    return root
