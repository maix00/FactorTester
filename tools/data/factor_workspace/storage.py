"""Local filesystem and sqlite helpers for factor workspace sources."""

from __future__ import annotations

import os
from pathlib import Path
from tools.data.sqlite.factor_source_store import normalize_factor_source_code
from tools.data.sqlite.factor_source_settings import load_factor_source_root
from tools.data.sqlite.factor_source_store import (
    delete_factor_source as delete_factor_source_row,
    load_factor_source as load_factor_source_row,
    rename_factor_source as rename_factor_source_row,
    upsert_factor_source as upsert_factor_source_row,
)

from scripts.data_dir import DATA_DIR

WORKSPACE_ROOTS_DIR = os.path.join(DATA_DIR, "factor_workspaces")


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
    try:
        configured_root = _normalize_root(load_factor_source_root(username))
        if configured_root:
            return configured_root
    except Exception:
        pass
    directory = os.path.join(WORKSPACE_ROOTS_DIR, username)
    os.makedirs(directory, exist_ok=True)
    return directory


def custom_factor_dir(username: str) -> str:
    directory = os.path.join(factor_source_root(username), "custom_factors")
    os.makedirs(directory, exist_ok=True)
    return directory


def factor_path(username: str, factor_id: str) -> str:
    return os.path.join(custom_factor_dir(username), f"{factor_id}.py")


def load_factor_source(username: str, factor_id: str) -> str | None:
    return load_factor_source_row("custom", username, factor_id)


def save_factor_source(username: str, factor_id: str, source_code: str) -> None:
    source_code = normalize_factor_source_code(source_code)
    upsert_factor_source_row("custom", username, factor_id, factor_id, source_code)
    path = factor_path(username, factor_id)
    with open(path, "w", encoding="utf-8") as file:
        file.write(source_code)


def public_factor_path(factor_id: str) -> str:
    return os.path.join(os.getcwd(), "Factors", f"{factor_id}.py")


def save_public_factor_source(factor_id: str, source_code: str) -> None:
    source_code = normalize_factor_source_code(source_code)
    upsert_factor_source_row("public", "", factor_id, factor_id, source_code)
    path = public_factor_path(factor_id)
    with open(path, "w", encoding="utf-8") as file:
        file.write(source_code)


def rename_factor_source(username: str, old_factor_id: str, new_factor_id: str) -> bool:
    source_exists = load_factor_source_row("custom", username, old_factor_id) is not None
    rename_factor_source_row("custom", username, old_factor_id, new_factor_id, new_factor_id)
    old_path = factor_path(username, old_factor_id)
    existed = os.path.exists(old_path)
    new_path = factor_path(username, new_factor_id)
    if existed:
        os.rename(old_path, new_path)

    old_json = os.path.join(custom_factor_dir(username), f"{old_factor_id}.json")
    if os.path.exists(old_json):
        new_json = os.path.join(custom_factor_dir(username), f"{new_factor_id}.json")
        os.rename(old_json, new_json)

    pycache = os.path.join(custom_factor_dir(username), "__pycache__")
    if os.path.isdir(pycache):
        import shutil

        shutil.rmtree(pycache, ignore_errors=True)

    return source_exists or existed


def delete_factor_source(username: str, factor_id: str) -> bool:
    source_exists = load_factor_source_row("custom", username, factor_id) is not None
    delete_factor_source_row("custom", username, factor_id)
    path = factor_path(username, factor_id)
    existed = False
    if os.path.exists(path):
        os.remove(path)
        existed = True
    old_path = os.path.join(custom_factor_dir(username), f"{factor_id}.json")
    if os.path.exists(old_path):
        os.remove(old_path)
        existed = True
    return source_exists or existed


def load_public_factor_source(factor_id: str) -> str | None:
    path = public_factor_path(factor_id)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as file:
            source = normalize_factor_source_code(file.read())
        if source:
            stored = load_factor_source_row("public", "", factor_id)
            if stored != source:
                upsert_factor_source_row("public", "", factor_id, factor_id, source)
            return source
    return load_factor_source_row("public", "", factor_id)
