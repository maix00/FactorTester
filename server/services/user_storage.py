"""
用户文件系统存储助手。

目录结构：
  ../data/
    users/
      <username>/                    ← user_data_dir() 返回
        params_templates/            ← 参数模板 JSON
          <FactorFamily>.json
        <kind>_templates.json        ← 其他类型的模板
      _archived/                     ← archive_user_dir() 归档目标
        <username>__<timestamp>/

核心函数：
  user_data_dir(username)            用户根目录（自动创建）
  user_template_path(...)            模板文件路径（按 kind / scope_key / ff_alias 分路径）
  load_user_templates / save_user_templates   JSON 格式读写
  archive_user_dir(username)         带时间戳归档（用于注销用户）
"""

from __future__ import annotations

import json
import os
import shutil
import time


import os as _os
_DATA_DIR = _os.environ.get('FT_DATA_DIR', _os.path.join(_os.path.dirname(__file__), '..', '..', '..', 'data'))
USERS_DIR = _os.path.join(_DATA_DIR, 'users')


def user_data_dir(username: str) -> str:
    directory = os.path.join(USERS_DIR, username)
    os.makedirs(directory, exist_ok=True)
    return directory


def user_template_path(
    username: str,
    kind: str,
    ff_alias: str | None = None,
    scope_key: str | None = None,
) -> str:
    """Return the JSON path for a user's template collection.

    `scope_key` is the storage-level isolation key. Different modules may choose
    different meanings for it, e.g. a single-factor-test FactorFamily alias or a
    factor-library user_id. Keep this helper business-agnostic.
    """
    directory = user_data_dir(username)
    if scope_key:
        directory = os.path.join(directory, f'{kind}_templates')
        os.makedirs(directory, exist_ok=True)
        if ff_alias:
            # 两级：{kind}_templates/{scope_key}/{ff_alias}.json
            directory = os.path.join(directory, scope_key)
            os.makedirs(directory, exist_ok=True)
            return os.path.join(directory, f'{ff_alias}.json')
        return os.path.join(directory, f'{scope_key}.json')
    if kind == 'params' and ff_alias:
        directory = os.path.join(directory, 'params_templates')
        os.makedirs(directory, exist_ok=True)
        return os.path.join(directory, f'{ff_alias}.json')
    return os.path.join(directory, f'{kind}_templates.json')


def load_user_templates(
    username: str,
    kind: str,
    ff_alias: str | None = None,
    scope_key: str | None = None,
) -> list:
    path = user_template_path(username, kind, ff_alias, scope_key=scope_key)
    try:
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as file:
                data = json.load(file)
            if isinstance(data, dict) and isinstance(data.get('templates'), list):
                return data['templates']
    except Exception:
        pass
    return []


def save_user_templates(
    username: str,
    kind: str,
    templates: list,
    ff_alias: str | None = None,
    scope_key: str | None = None,
) -> None:
    path = user_template_path(username, kind, ff_alias, scope_key=scope_key)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    # Use new format with metadata wrapper
    wrapper_ff_alias = ff_alias or (scope_key if scope_key else 'unknown')
    data = {
        'ff_alias': wrapper_ff_alias,
        'templates': templates,
    }
    with open(path, 'w', encoding='utf-8') as file:
        json.dump(data, file, ensure_ascii=False, indent=2)


_last_template_ts = 0

def new_template_id() -> str:
    """Return a unique, monotonically-increasing millisecond-precision id."""
    global _last_template_ts
    ts = int(time.time() * 1000)
    if ts <= _last_template_ts:
        ts = _last_template_ts + 1
    _last_template_ts = ts
    return str(ts)


def migrate_templates_on_rename(old_name: str, new_name: str) -> int:
    """Rename templates after a FactorFamily is renamed.

    Scans ALL user directories and:
    1. Renames global_templates/{old_name}.json → {new_name}.json
    2. Renames params_templates/{old_name}.json → {new_name}.json
    3. In any global_templates/*.json, updates ff_alias fields
       referencing old_name → new_name

    Returns number of files touched.
    """
    touched = 0
    if not os.path.isdir(USERS_DIR):
        return touched

    for username in os.listdir(USERS_DIR):
        if username.startswith('_') or username.startswith('.'):
            continue
        user_dir = os.path.join(USERS_DIR, username)
        if not os.path.isdir(user_dir):
            continue

        # 1. Rename global_templates (scope_key-based)
        global_dir = os.path.join(user_dir, 'global_templates')
        if os.path.isdir(global_dir):
            old_path = os.path.join(global_dir, f'{old_name}.json')
            new_path = os.path.join(global_dir, f'{new_name}.json')
            if os.path.isfile(old_path) and not os.path.exists(new_path):
                shutil.move(old_path, new_path)
                touched += 1

        # 2. Rename params_templates (ff_alias-based)
        params_dir = os.path.join(user_dir, 'params_templates')
        if os.path.isdir(params_dir):
            old_path = os.path.join(params_dir, f'{old_name}.json')
            new_path = os.path.join(params_dir, f'{new_name}.json')
            if os.path.isfile(old_path) and not os.path.exists(new_path):
                shutil.move(old_path, new_path)
                touched += 1

        # 3. Update ff_alias inside all global_templates JSON files
        if os.path.isdir(global_dir):
            for fname in os.listdir(global_dir):
                if not fname.endswith('.json'):
                    continue
                fpath = os.path.join(global_dir, fname)
                try:
                    with open(fpath, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    if not isinstance(data, list):
                        continue
                    changed = False
                    for tmpl in data:
                        if isinstance(tmpl, dict) and tmpl.get('ff_alias') == old_name:
                            tmpl['ff_alias'] = new_name
                            changed = True
                    if changed:
                        with open(fpath, 'w', encoding='utf-8') as f:
                            json.dump(data, f, ensure_ascii=False, indent=2)
                        touched += 1
                except Exception:
                    continue

    return touched


def archive_user_dir(username: str) -> str | None:
    """Move a user's storage directory into archive with timestamp suffix.

    Returns archived directory path when moved, else None when source doesn't exist.
    """
    src = os.path.join(USERS_DIR, username)
    if not os.path.isdir(src):
        return None
    archive_root = os.path.join(USERS_DIR, '_archived')
    os.makedirs(archive_root, exist_ok=True)
    timestamp = time.strftime('%Y%m%d_%H%M%S')
    dst = os.path.join(archive_root, f'{username}__{timestamp}')
    suffix = 1
    while os.path.exists(dst):
        suffix += 1
        dst = os.path.join(archive_root, f'{username}__{timestamp}_{suffix}')
    shutil.move(src, dst)
    return dst
