"""Resolve safe server Profile workspace files for the 7997 origin."""

from __future__ import annotations

from pathlib import Path

from server.manager.services.agent_workspace import server_profile_workspace
from server.manager.services.profile_workspace_browser import (
    ProfileWorkspaceError,
    parse_workspace_object_id,
)


class ProfileWorkspaceOriginAdapter:
    def __init__(self, *, data_root: str | Path) -> None:
        self.data_root = Path(data_root).expanduser().resolve()

    def __call__(self, transfer) -> Path:
        profile_id, relative = parse_workspace_object_id(
            str(transfer.object_id or ""),
        )
        root = server_profile_workspace(
            self.data_root,
            str(transfer.principal or ""),
            profile_id,
        )
        candidate = root / relative
        current = root
        for part in relative.split("/"):
            current = current / part
            if current.is_symlink():
                raise ProfileWorkspaceError("workspace symlinks are not downloadable")
        candidate = candidate.resolve()
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise ProfileWorkspaceError("workspace path escapes the Profile root") from exc
        if not candidate.is_file():
            raise FileNotFoundError("workspace file is unavailable")
        if candidate.stat().st_size != int(transfer.expected_size):
            raise RuntimeError("workspace file size changed after authorization")
        return candidate


__all__ = ["ProfileWorkspaceOriginAdapter"]
