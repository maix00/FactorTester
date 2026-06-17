"""Database/workspace synchronization for factor sources."""

from __future__ import annotations

import os
from typing import Any

from tools.data.sqlite.factor_source_store import list_factor_sources

from .git import _apply_workspace_git_branch, _ensure_git_workspace
from . import storage as factor_workspace_storage
from .construct import (
    _clear_workspace_generated,
    _ensure_workspace_layout,
    _remove_missing_files,
    _sync_tools_index,
    _sync_tools_sdk,
    _sync_vscode_settings,
    _workspace_custom_dir,
    _workspace_public_dir,
    _workspace_root,
    _write_json,
    _write_text_if_changed,
)


def sync_database_to_workspace(username: str, branch_mode: str = "auto", clear_existing: bool = False) -> dict[str, Any]:
    root = _workspace_root(username)
    _ensure_workspace_layout(root)
    git_info = _ensure_git_workspace(root, username)
    selected_branch = _apply_workspace_git_branch(root, username, branch_mode)

    cleared_files: list[str] = []
    if clear_existing:
        cleared_files = _clear_workspace_generated(root)

    custom_count = 0
    public_count = 0
    touched_files: list[str] = []
    expected_custom_files: set[str] = set()
    expected_public_files: set[str] = set()

    for record in list_factor_sources("custom"):
        owner_username = str(record.get("owner_username") or "")
        factor_id = str(record.get("factor_id") or "")
        source_code = str(record.get("source_code") or "")
        if not owner_username or not factor_id or not source_code:
            continue
        if owner_username != username:
            continue
        expected_custom_files.add(f"{factor_id}.py")
        local_path = factor_workspace_storage.factor_path(username, factor_id)
        if _write_text_if_changed(local_path, source_code):
            touched_files.append(local_path)
        custom_count += 1

    for record in list_factor_sources("public"):
        factor_id = str(record.get("factor_id") or "")
        source_code = str(record.get("source_code") or "")
        if not factor_id or not source_code:
            continue
        expected_public_files.add(f"{factor_id}.py")
        local_path = os.path.join(_workspace_public_dir(root), f"{factor_id}.py")
        if _write_text_if_changed(local_path, source_code):
            touched_files.append(local_path)
        public_count += 1

    removed_files: list[str] = []
    removed_files.extend(_remove_missing_files(_workspace_custom_dir(root), expected_custom_files))
    removed_files.extend(_remove_missing_files(_workspace_public_dir(root), expected_public_files))

    tools_index_changed = _sync_tools_index(root)
    tools_sdk_changed = _sync_tools_sdk(root)
    vscode_settings_changed = _sync_vscode_settings(root)

    manifest = {
        "workspace_root": root,
        "username": username,
        "custom_factor_dir": factor_workspace_storage.custom_factor_dir(username),
        "public_factor_dir": _workspace_public_dir(root),
        "git": git_info,
        "git_selected_branch": selected_branch,
        "cleared_files": cleared_files,
        "custom_factor_count": custom_count,
        "public_factor_count": public_count,
        "touched_files": touched_files,
        "removed_files": removed_files,
    }
    manifest_changed = _write_json(os.path.join(root, ".factor_workspace", "manifest.json"), manifest)

    return {
        "workspace_root": root,
        "custom_factor_count": custom_count,
        "public_factor_count": public_count,
        "git": git_info,
        "git_selected_branch": selected_branch,
        "cleared_files": cleared_files,
        "touched_files": touched_files,
        "removed_files": removed_files,
        "tools_index_changed": tools_index_changed,
        "tools_sdk_changed": tools_sdk_changed,
        "vscode_settings_changed": vscode_settings_changed,
        "manifest_changed": manifest_changed,
    }


def sync_factor_workspace(username: str, branch_mode: str = "force") -> dict[str, Any]:
    return sync_database_to_workspace(username, branch_mode=branch_mode)


def sync_workspace_to_database(username: str, branch_mode: str = "auto") -> dict[str, Any]:
    root = _workspace_root(username)
    _ensure_workspace_layout(root)
    _ensure_git_workspace(root, username)
    selected_branch = _apply_workspace_git_branch(root, username, branch_mode)

    custom_dir = _workspace_custom_dir(root)
    updated_custom = 0
    updated_public = 0

    if os.path.isdir(custom_dir):
        for filename in sorted(os.listdir(custom_dir)):
            if not filename.endswith(".py"):
                continue
            factor_id = filename[:-3]
            source = factor_workspace_storage.load_factor_source(username, factor_id)
            file_path = os.path.join(custom_dir, filename)
            with open(file_path, "r", encoding="utf-8") as file:
                source_code = file.read()
            if source != source_code:
                factor_workspace_storage.save_factor_source(username, factor_id, source_code)
                updated_custom += 1

    public_dir = _workspace_public_dir(root)
    if os.path.isdir(public_dir):
        for filename in sorted(os.listdir(public_dir)):
            if not filename.endswith(".py"):
                continue
            factor_id = filename[:-3]
            file_path = os.path.join(public_dir, filename)
            with open(file_path, "r", encoding="utf-8") as file:
                source_code = file.read()
            if factor_workspace_storage.load_public_factor_source(factor_id) != source_code:
                factor_workspace_storage.save_public_factor_source(factor_id, source_code)
                updated_public += 1

    return {
        "workspace_root": root,
        "git_selected_branch": selected_branch,
        "updated_custom_count": updated_custom,
        "updated_public_count": updated_public,
    }


def push_factor_workspace(username: str, allow_public_write: bool = False, branch_mode: str = "auto") -> dict[str, Any]:
    root = _workspace_root(username)
    _ensure_workspace_layout(root)
    _ensure_git_workspace(root, username)
    selected_branch = _apply_workspace_git_branch(root, username, branch_mode)

    public_dir = _workspace_public_dir(root)
    changed_public_files: list[str] = []
    if os.path.isdir(public_dir):
        for filename in sorted(os.listdir(public_dir)):
            if not filename.endswith(".py"):
                continue
            factor_id = filename[:-3]
            file_path = os.path.join(public_dir, filename)
            with open(file_path, "r", encoding="utf-8") as file:
                source_code = file.read()
            if factor_workspace_storage.load_public_factor_source(factor_id) != source_code:
                changed_public_files.append(file_path)

    if changed_public_files and not allow_public_write:
        rel = [os.path.relpath(path, root) for path in changed_public_files]
        raise PermissionError(f"只有超级管理员可以同步公共因子到数据库：{rel}")

    result = sync_workspace_to_database(username, branch_mode=branch_mode)
    result["git_selected_branch"] = selected_branch or result.get("git_selected_branch", "")
    return result
