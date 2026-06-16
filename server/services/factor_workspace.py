"""Local factor workspace build and sync helpers."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from server.services.sqlite.factor_source_store import list_factor_sources
from tools.tool_docs import scan_tool_files


def _storage():
    from server.modules.custom_factors import storage as factor_storage
    return factor_storage


def _workspace_root(username: str) -> str:
    return _storage().factor_source_root(username)


def _workspace_public_dir(root: str) -> str:
    return os.path.join(root, 'public_factors')


def _workspace_custom_dir(root: str) -> str:
    return os.path.join(root, 'custom_factors')


def _ensure_workspace_layout(root: str) -> None:
    Path(root).mkdir(parents=True, exist_ok=True)
    Path(_workspace_public_dir(root)).mkdir(parents=True, exist_ok=True)
    Path(_workspace_custom_dir(root)).mkdir(parents=True, exist_ok=True)
    Path(os.path.join(root, '.factor_workspace')).mkdir(parents=True, exist_ok=True)


def _write_text_if_changed(path: str, content: str) -> bool:
    existing = None
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as file:
            existing = file.read()
    if existing == content:
        return False
    Path(os.path.dirname(path)).mkdir(parents=True, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as file:
        file.write(content)
    return True


def _write_json(path: str, payload: dict[str, Any]) -> bool:
    content = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    return _write_text_if_changed(path, content + '\n')


def _remove_missing_files(directory: str, expected_names: set[str]) -> list[str]:
    removed: list[str] = []
    if not os.path.isdir(directory):
        return removed
    for filename in sorted(os.listdir(directory)):
        if not filename.endswith('.py'):
            continue
        if filename in expected_names:
            continue
        path = os.path.join(directory, filename)
        if os.path.isfile(path):
            os.remove(path)
            removed.append(path)
    return removed


def _sync_tools_index(root: str) -> bool:
    tools_dir = os.path.join(os.getcwd(), 'tools')
    tool_files = scan_tool_files(tools_dir, include_symbols=True)
    payload = {
        'workspace_root': root,
        'tools_dir': tools_dir,
        'generated_at': time.time(),
        'files': tool_files,
    }
    return _write_json(os.path.join(root, 'tools_index.json'), payload)


def sync_database_to_workspace(username: str) -> dict[str, Any]:
    root = _workspace_root(username)
    _ensure_workspace_layout(root)

    custom_count = 0
    public_count = 0
    touched_files = []
    expected_custom_files: set[str] = set()
    expected_public_files: set[str] = set()

    for record in list_factor_sources('custom'):
        owner_username = str(record.get('owner_username') or '')
        factor_id = str(record.get('factor_id') or '')
        source_code = str(record.get('source_code') or '')
        if not owner_username or not factor_id or not source_code:
            continue
        if owner_username != username:
            continue
        expected_custom_files.add(f'{factor_id}.py')
        local_path = _storage().factor_path(username, factor_id)
        if _write_text_if_changed(local_path, source_code):
            touched_files.append(local_path)
        custom_count += 1

    for record in list_factor_sources('public'):
        factor_id = str(record.get('factor_id') or '')
        source_code = str(record.get('source_code') or '')
        if not factor_id or not source_code:
            continue
        expected_public_files.add(f'{factor_id}.py')
        local_path = os.path.join(_workspace_public_dir(root), f'{factor_id}.py')
        if _write_text_if_changed(local_path, source_code):
            touched_files.append(local_path)
        public_count += 1

    removed_files = []
    removed_files.extend(_remove_missing_files(_workspace_custom_dir(root), expected_custom_files))
    removed_files.extend(_remove_missing_files(_workspace_public_dir(root), expected_public_files))

    tools_index_changed = _sync_tools_index(root)

    manifest = {
        'workspace_root': root,
        'username': username,
        'custom_factor_dir': _storage().custom_factor_dir(username),
        'public_factor_dir': _workspace_public_dir(root),
        'custom_factor_count': custom_count,
        'public_factor_count': public_count,
        'touched_files': touched_files,
        'removed_files': removed_files,
    }
    manifest_changed = _write_json(os.path.join(root, '.factor_workspace', 'manifest.json'), manifest)

    return {
        'workspace_root': root,
        'custom_factor_count': custom_count,
        'public_factor_count': public_count,
        'touched_files': touched_files,
        'removed_files': removed_files,
        'tools_index_changed': tools_index_changed,
        'manifest_changed': manifest_changed,
    }


def build_factor_workspace(username: str) -> dict[str, Any]:
    return sync_database_to_workspace(username)


def sync_factor_workspace(username: str) -> dict[str, Any]:
    return sync_database_to_workspace(username)


def sync_workspace_to_database(username: str) -> dict[str, Any]:
    root = _workspace_root(username)
    _ensure_workspace_layout(root)

    custom_dir = _storage().custom_factor_dir(username)
    updated_custom = 0
    updated_public = 0

    if os.path.isdir(custom_dir):
        for filename in sorted(os.listdir(custom_dir)):
            if not filename.endswith('.py'):
                continue
            factor_id = filename[:-3]
            source = _storage().load_factor_source(username, factor_id)
            file_path = os.path.join(custom_dir, filename)
            with open(file_path, 'r', encoding='utf-8') as file:
                source_code = file.read()
            if source != source_code:
                _storage().save_factor_source(username, factor_id, source_code)
                updated_custom += 1

    public_dir = _workspace_public_dir(root)
    if os.path.isdir(public_dir):
        for filename in sorted(os.listdir(public_dir)):
            if not filename.endswith('.py'):
                continue
            factor_id = filename[:-3]
            file_path = os.path.join(public_dir, filename)
            with open(file_path, 'r', encoding='utf-8') as file:
                source_code = file.read()
            if _storage().load_public_factor_source(factor_id) != source_code:
                _storage().save_public_factor_source(factor_id, source_code)
                updated_public += 1

    return {
        'workspace_root': root,
        'updated_custom_count': updated_custom,
        'updated_public_count': updated_public,
    }


def push_factor_workspace(username: str, allow_public_write: bool = False) -> dict[str, Any]:
    root = _workspace_root(username)
    _ensure_workspace_layout(root)

    public_dir = _workspace_public_dir(root)
    changed_public_files: list[str] = []
    if os.path.isdir(public_dir):
        for filename in sorted(os.listdir(public_dir)):
            if not filename.endswith('.py'):
                continue
            factor_id = filename[:-3]
            file_path = os.path.join(public_dir, filename)
            with open(file_path, 'r', encoding='utf-8') as file:
                source_code = file.read()
            if _storage().load_public_factor_source(factor_id) != source_code:
                changed_public_files.append(file_path)

    if changed_public_files and not allow_public_write:
        rel = [os.path.relpath(path, root) for path in changed_public_files]
        raise PermissionError(f'只有超级管理员可以同步公共因子到数据库：{rel}')

    return sync_workspace_to_database(username)
