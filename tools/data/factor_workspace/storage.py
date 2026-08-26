"""Local filesystem and sqlite helpers for factor workspace sources."""

from __future__ import annotations

import os
from pathlib import Path

from scripts.data_dir import DATA_DIR
from tools.data.sqlite.factor_source_settings import load_factor_source_root
from tools.data.sqlite.factor_source_store import (
    canonical_factor_source_code,
    normalize_factor_source_code,
)
from tools.data.sqlite.factor_source_store import (
    delete_factor_source as delete_factor_source_row,
)
from tools.data.sqlite.factor_source_store import (
    load_factor_source as load_factor_source_row,
)
from tools.data.sqlite.factor_source_store import (
    rename_factor_source as rename_factor_source_row,
)
from tools.data.sqlite.factor_source_store import (
    upsert_factor_source as upsert_factor_source_row,
)

WORKSPACE_ROOTS_DIR = os.path.join(DATA_DIR, "users")


def default_factor_source_root(username: str) -> str:
    """Return the portable canonical factor-library path for one principal."""
    return os.path.join(
        WORKSPACE_ROOTS_DIR,
        username,
        "personal-workspace",
        "factor-library",
    )


def is_profile_factor_worktree_root(path: str | os.PathLike[str] | None) -> bool:
    """Return whether *path* is an Agent-owned Profile worktree.

    Profile worktrees are intentionally separate from the user canonical factor
    workspace.  They may be used as a transient Run source, but they are never
    a valid target for the upload/download repository synchronizer.
    """
    try:
        parts = tuple(Path(os.path.abspath(os.fspath(path or ""))).parts)
    except (TypeError, ValueError, OSError):
        return False
    for index, part in enumerate(parts[:-2]):
        if part == "profiles" and parts[index + 2] == "factor-worktree":
            return True
    return False


def assert_canonical_factor_workspace_root(path: str | os.PathLike[str]) -> str:
    """Validate and return a canonical workspace root for source sync.

    Keeping this check at the storage boundary prevents Web, CLI, and native
    clients from accidentally treating a Profile worktree as canonical merely
    because its filesystem path was configured in the server settings.
    """
    root = os.path.abspath(os.path.expanduser(os.fspath(path)))
    if is_profile_factor_worktree_root(root):
        raise PermissionError(
            "Profile factor-worktree 只能用于 Agent 草稿或单次任务源码，"
            "不能作为 canonical 因子库的 upload/download 同步目录"
        )
    return root


def _normalize_root(path: str | None) -> str | None:
    root = str(path or "").strip()
    if not root:
        return None
    return os.path.abspath(os.path.expanduser(root))


def factor_source_root(username: str) -> str:
    configured_root = configured_factor_source_root(username)
    if configured_root:
        return configured_root
    directory = default_factor_source_root(username)
    os.makedirs(directory, exist_ok=True)
    return directory


def configured_factor_source_root(username: str) -> str | None:
    """Return an explicitly configured workspace without creating anything."""
    try:
        return _normalize_root(load_factor_source_root(username))
    except Exception:
        return None


def existing_factor_workspace_root(username: str) -> str | None:
    """Return a workspace that may be safely mirrored by a Web save.

    Web CRUD is backed by the SQLite source registry.  It may mirror files only
    when the user explicitly configured a workspace or an older generated
    workspace has a matching ownership manifest.  The fallback directory is
    deliberately not created here.
    """
    configured = configured_factor_source_root(username)
    if configured:
        return configured
    fallback = default_factor_source_root(username)
    manifest_path = os.path.join(fallback, ".factor_workspace", "manifest.json")
    if not os.path.isfile(manifest_path):
        return None
    try:
        import json

        with open(manifest_path, "r", encoding="utf-8") as file:
            manifest = json.load(file)
    except (OSError, ValueError, TypeError):
        return None
    if isinstance(manifest, dict) and str(manifest.get("username") or "") == username:
        return fallback
    return None


def custom_factor_dir(username: str) -> str:
    directory = os.path.join(factor_source_root(username), "custom_factors")
    os.makedirs(directory, exist_ok=True)
    return directory


def factor_path(username: str, factor_id: str) -> str:
    return os.path.join(custom_factor_dir(username), f"{factor_id}.py")


def load_factor_source(username: str, factor_id: str) -> str | None:
    return load_factor_source_row("custom", username, factor_id)


def save_factor_source(
    username: str,
    factor_id: str,
    source_code: str,
    *,
    chinese_name: str | None = None,
    description: str | None = None,
    category: str | None = None,
) -> None:
    source_code = normalize_factor_source_code(source_code)
    upsert_factor_source_row(
        "custom", username, factor_id, factor_id, source_code,
        chinese_name=chinese_name,
        description=description,
        category=category,
    )
    root = existing_factor_workspace_root(username)
    if root:
        path = os.path.join(root, "custom_factors", f"{factor_id}.py")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as file:
            file.write(canonical_factor_source_code(source_code))


def save_public_factor_source(
    factor_id: str,
    source_code: str,
    *,
    chinese_name: str | None = None,
    description: str | None = None,
    category: str | None = None,
) -> None:
    source_code = normalize_factor_source_code(source_code)
    upsert_factor_source_row(
        "public", "", factor_id, factor_id, source_code,
        chinese_name=chinese_name,
        description=description,
        category=category,
    )


def rename_factor_source(username: str, old_factor_id: str, new_factor_id: str) -> bool:
    source_exists = load_factor_source_row("custom", username, old_factor_id) is not None
    rename_factor_source_row("custom", username, old_factor_id, new_factor_id, new_factor_id)
    root = existing_factor_workspace_root(username)
    existed = False
    if root:
        custom_dir = os.path.join(root, "custom_factors")
        old_path = os.path.join(custom_dir, f"{old_factor_id}.py")
        new_path = os.path.join(custom_dir, f"{new_factor_id}.py")
        existed = os.path.exists(old_path)
        if existed:
            os.rename(old_path, new_path)

        old_json = os.path.join(custom_dir, f"{old_factor_id}.json")
        if os.path.exists(old_json):
            os.rename(old_json, os.path.join(custom_dir, f"{new_factor_id}.json"))

        pycache = os.path.join(custom_dir, "__pycache__")
        if os.path.isdir(pycache):
            import shutil

            shutil.rmtree(pycache, ignore_errors=True)

    return source_exists or existed


def delete_factor_source(username: str, factor_id: str) -> bool:
    source_exists = load_factor_source_row("custom", username, factor_id) is not None
    delete_factor_source_row("custom", username, factor_id)
    existed = False
    root = existing_factor_workspace_root(username)
    if root:
        custom_dir = os.path.join(root, "custom_factors")
        path = os.path.join(custom_dir, f"{factor_id}.py")
        if os.path.exists(path):
            os.remove(path)
            existed = True
        old_path = os.path.join(custom_dir, f"{factor_id}.json")
        if os.path.exists(old_path):
            os.remove(old_path)
            existed = True
    return source_exists or existed


def load_public_factor_source(factor_id: str) -> str | None:
    """Load a public factor only from the authoritative SQLite registry.

    The legacy repository-level ``Factors/`` directory was only a compatibility
    mirror.  Public source synchronization now operates through
    ``factor_family_sources`` exclusively; a missing local file can never
    shadow or mutate the registry.
    """
    return load_factor_source_row("public", "", factor_id)
