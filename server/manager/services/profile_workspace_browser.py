"""Safe listing and 7997 object identities for server Profile workspaces."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from server.manager.services.agent_workspace import (
    server_profile_workspace,
)
from server.manager.storage.profile_runtime_store import ProfileRuntimeStore

PROFILE_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
HIDDEN_NAMES = frozenset({".codex", ".git", ".env"})
SECRET_SUFFIXES = frozenset(
    {
        ".db",
        ".sqlite",
        ".sqlite3",
        ".key",
        ".pem",
        ".token",
        ".secret",
    }
)


class ProfileWorkspaceError(ValueError):
    """A Profile workspace is unavailable or the requested path is unsafe."""


def workspace_object_id(profile_id: str, relative_path: str) -> str:
    profile = _profile_id(profile_id)
    relative = _relative_parts(relative_path)
    if not relative:
        raise ProfileWorkspaceError("a workspace file path is required")
    return f"{profile}/{'/'.join(relative)}"


def parse_workspace_object_id(object_id: str) -> tuple[str, str]:
    raw = str(object_id or "").strip()
    profile, separator, relative = raw.partition("/")
    if not separator:
        raise ProfileWorkspaceError("workspace object identity is invalid")
    parts = _relative_parts(relative)
    if not parts:
        raise ProfileWorkspaceError("workspace object identity is invalid")
    return _profile_id(profile), "/".join(parts)


class ProfileWorkspaceBrowser:
    """Expose only the non-secret, regular-file part of one Profile root."""

    def __init__(
        self,
        *,
        data_root: str | Path,
        runtime_store: ProfileRuntimeStore,
        server_id: str,
    ) -> None:
        self.data_root = Path(data_root).expanduser().resolve()
        self.runtime_store = runtime_store
        self.server_id = str(server_id or "").strip()

    def _root(self, principal: str, profile_id: str) -> Path:
        runtime = self.runtime_store.runtime(principal, profile_id)
        if runtime is None or str(runtime.get("runtime_kind") or "") != "server":
            raise ProfileWorkspaceError("Profile is not bound to a server runtime")
        if str(runtime.get("executor_id") or "") != self.server_id:
            raise ProfileWorkspaceError("Profile belongs to another server")
        root = server_profile_workspace(self.data_root, principal, profile_id)
        if not root.is_dir():
            raise ProfileWorkspaceError("Profile workspace has not been created")
        return root

    @staticmethod
    def _safe_path(root: Path, relative_path: str, *, allow_root: bool = True) -> Path:
        parts = _relative_parts(relative_path)
        if not parts and not allow_root:
            raise ProfileWorkspaceError("a workspace file path is required")
        candidate = root.joinpath(*parts)
        resolved = candidate.resolve()
        if resolved != root and root not in resolved.parents:
            raise ProfileWorkspaceError("workspace path escapes the Profile root")
        current = root
        for part in parts:
            current = current / part
            if current.is_symlink():
                raise ProfileWorkspaceError("workspace symlinks are not downloadable")
        return resolved

    def list(
        self, principal: str, profile_id: str, relative_path: str = ""
    ) -> dict[str, Any]:
        root = self._root(principal, profile_id)
        directory = self._safe_path(root, relative_path)
        if not directory.is_dir():
            raise ProfileWorkspaceError("workspace path is not a directory")
        current = "/".join(_relative_parts(relative_path))
        entries = []
        for child in sorted(
            directory.iterdir(),
            key=lambda item: (not item.is_dir(), item.name.casefold()),
        ):
            if _is_hidden_or_sensitive(child.name):
                continue
            if child.is_symlink() or not (child.is_dir() or child.is_file()):
                continue
            child_path = f"{current}/{child.name}" if current else child.name
            entries.append(
                {
                    "name": child.name,
                    "path": child_path,
                    "kind": "directory" if child.is_dir() else "file",
                    "size_bytes": child.stat().st_size if child.is_file() else 0,
                    "downloadable": child.is_file(),
                }
            )
        return {
            "profile_id": _profile_id(profile_id),
            "path": current,
            "entries": entries,
        }

    def file_metadata(
        self, principal: str, profile_id: str, relative_path: str
    ) -> dict[str, Any]:
        root = self._root(principal, profile_id)
        path = self._safe_path(root, relative_path, allow_root=False)
        if (
            not path.is_file()
            or path.is_symlink()
            or _is_hidden_or_sensitive(path.name)
        ):
            raise ProfileWorkspaceError("workspace file is unavailable")
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        relative = "/".join(_relative_parts(relative_path))
        return {
            "object_id": workspace_object_id(profile_id, relative),
            "filename": path.name,
            "content_type": "application/octet-stream",
            "size_bytes": path.stat().st_size,
            "sha256": digest.hexdigest(),
            "path": relative,
            "storage_server_id": self.server_id,
        }

    def delete_file(
        self, principal: str, profile_id: str, relative_path: str
    ) -> dict[str, Any]:
        root = self._root(principal, profile_id)
        path = self._safe_path(root, relative_path, allow_root=False)
        if (
            not path.is_file()
            or path.is_symlink()
            or _is_hidden_or_sensitive(path.name)
        ):
            raise ProfileWorkspaceError("workspace file is unavailable")
        relative = "/".join(_relative_parts(relative_path))
        path.unlink()
        return {
            "profile_id": _profile_id(profile_id),
            "path": relative,
            "deleted": True,
        }

    def write_file(
        self,
        principal: str,
        profile_id: str,
        relative_path: str,
        data: bytes,
        *,
        filename: str = "",
    ) -> dict[str, Any]:
        """Atomically persist an uploaded file inside the Profile workspace.

        The target is the optional ``relative_path`` directory joined with the
        (sanitized) ``filename``.  Uploads are bounded, filtered against hidden
        /sensitive names, and written via a temp file + ``os.replace`` so a
        concurrent reader never sees a partial file.  Path escape and symlink
        guards are the same as for delete/download.
        """
        import os
        import tempfile

        root = self._root(principal, profile_id)
        directory = self._safe_path(root, relative_path)
        # Older workspaces predate uploads/. Create only this managed directory.
        if _relative_parts(relative_path) == ("uploads",):
            directory.mkdir(exist_ok=True)
        if not directory.is_dir():
            raise ProfileWorkspaceError("workspace path is not a directory")
        safe_name = _safe_filename(filename)
        if not safe_name:
            raise ProfileWorkspaceError("workspace filename is invalid")
        if _is_hidden_or_sensitive(safe_name):
            raise ProfileWorkspaceError("workspace filename is not allowed")
        size = len(data or b"")
        if size > 64 * 1024 * 1024:
            raise ProfileWorkspaceError("workspace upload is invalid")
        target = directory / safe_name
        if target.is_symlink():
            raise ProfileWorkspaceError("workspace upload target is invalid")
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temp = tempfile.mkstemp(
            prefix=f".{safe_name}.upload.", dir=str(directory),
        )
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data or b"")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, target)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)
        current = "/".join(_relative_parts(relative_path))
        child_path = f"{current}/{safe_name}" if current else safe_name
        return {
            "profile_id": _profile_id(profile_id),
            "path": child_path,
            "name": safe_name,
            "kind": "file",
            "size_bytes": size,
            "saved": True,
        }





def _safe_filename(value: object) -> str:
    """Return a safe single-path-component filename, or '' when invalid."""
    name = str(value or "").strip()
    if not name or name in {".", ".."} or "/" in name or "\\" in name:
        return ""
    if name.startswith("."):
        return ""
    if "\x00" in name or len(name.encode("utf-8")) > 255:
        return ""
    return name


def _profile_id(value: object) -> str:
    result = str(value or "").strip()
    if not PROFILE_ID_PATTERN.fullmatch(result):
        raise ProfileWorkspaceError("Profile identifier is invalid")
    return result


def _relative_parts(value: object) -> tuple[str, ...]:
    raw = str(value or "").replace("\\", "/").strip("/")
    if not raw:
        return ()
    if "\x00" in raw:
        raise ProfileWorkspaceError("workspace path is invalid")
    parts = tuple(part for part in raw.split("/") if part and part != ".")
    if any(part == ".." or _is_hidden_or_sensitive(part) for part in parts):
        raise ProfileWorkspaceError("workspace path is not downloadable")
    return parts


def _is_hidden_or_sensitive(name: str) -> bool:
    value = str(name or "")
    return (
        not value
        or value.startswith(".")
        or value in HIDDEN_NAMES
        or value.casefold().endswith(tuple(SECRET_SUFFIXES))
    )


__all__ = [
    "ProfileWorkspaceBrowser",
    "ProfileWorkspaceError",
    "parse_workspace_object_id",
    "workspace_object_id",
]
