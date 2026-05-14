"""Storage for factor-library two-level-scoped parameter configs.

Scope model:
  1st level: user_id (path_template ID → scope_key)
  2nd level: (user_id, scope_key)

Storage layout:
  {user_data}/factor_library_param_configs/{scope_key}/{ff_alias}.json

Migration: old flat files at {user_data}/factor_library_param_configs/{ff_alias}.json
are auto-migrated to scope_key="default" on first access.
"""

import json
import os
import shutil
import time

from server.services.user_storage import user_data_dir

DEFAULT_SCOPE_KEY = 'default'


def _base_config_dir(username: str) -> str:
    d = os.path.join(user_data_dir(username), 'factor_library_param_configs')
    os.makedirs(d, exist_ok=True)
    return d


def param_config_dir(username: str, scope_key: str = DEFAULT_SCOPE_KEY) -> str:
    d = os.path.join(_base_config_dir(username), scope_key)
    os.makedirs(d, exist_ok=True)
    return d


def param_config_path(username: str, scope_key: str, ff_alias: str) -> str:
    return os.path.join(param_config_dir(username, scope_key), f'{ff_alias}.json')


def _old_flat_path(username: str, ff_alias: str) -> str:
    """Path for pre-scope flat storage (migration source)."""
    return os.path.join(_base_config_dir(username), f'{ff_alias}.json')


def _migrate_if_needed(username: str, scope_key: str, ff_alias: str) -> str | None:
    """Auto-migrate from old flat storage to scoped storage.

    Returns the target path if migration happened, None otherwise.
    """
    old_path = _old_flat_path(username, ff_alias)
    new_path = param_config_path(username, scope_key, ff_alias)
    if os.path.isfile(old_path) and not os.path.exists(new_path):
        os.makedirs(os.path.dirname(new_path), exist_ok=True)
        shutil.move(old_path, new_path)
        return new_path
    return None


def _cleanup_empty_scope_dirs(username: str) -> None:
    """Remove empty scope directories after delete."""
    base = _base_config_dir(username)
    if not os.path.isdir(base):
        return
    for entry in os.listdir(base):
        entry_path = os.path.join(base, entry)
        if not os.path.isdir(entry_path):
            continue
        try:
            os.rmdir(entry_path)
        except OSError:
            pass
    # Also clean up orphaned old flat files
    for entry in os.listdir(base):
        if entry.endswith('.json'):
            os.remove(os.path.join(base, entry))


def load_param_config(username: str, ff_alias: str, scope_key: str = DEFAULT_SCOPE_KEY) -> dict | None:
    _migrate_if_needed(username, scope_key, ff_alias)
    path = param_config_path(username, scope_key, ff_alias)
    try:
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if isinstance(data, dict) and isinstance(data.get('params_list'), list):
                return data
    except Exception:
        pass
    return None


def save_param_config(username: str, ff_alias: str, params_list: list, scope_key: str = DEFAULT_SCOPE_KEY) -> dict:
    config = {
        'id': username,
        'scope': 'user_submission',
        'scope_key': scope_key,
        'scope_user_id': username,
        'name': username,
        'params_list': params_list,
        'updated_at': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime()),
    }
    path = param_config_path(username, scope_key, ff_alias)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
    return config


def delete_param_config(username: str, ff_alias: str, scope_key: str = DEFAULT_SCOPE_KEY) -> bool:
    _migrate_if_needed(username, scope_key, ff_alias)
    path = param_config_path(username, scope_key, ff_alias)
    if os.path.exists(path):
        os.remove(path)
        _cleanup_empty_scope_dirs(username)
        return True
    return False


def list_param_config_aliases(username: str, scope_key: str = DEFAULT_SCOPE_KEY) -> list[str]:
    _migrate_scope_dir(username, scope_key)
    d = param_config_dir(username, scope_key)
    if not os.path.isdir(d):
        return []
    return [
        os.path.splitext(fname)[0]
        for fname in sorted(os.listdir(d))
        if fname.endswith('.json')
    ]


def _migrate_scope_dir(username: str, scope_key: str) -> None:
    """Migrate all old flat files into the scope directory if any exist."""
    base = _base_config_dir(username)
    if not os.path.isdir(base):
        return
    target_dir = param_config_dir(username, scope_key)
    for entry in os.listdir(base):
        if not entry.endswith('.json'):
            continue
        old_path = os.path.join(base, entry)
        if os.path.isfile(old_path):
            new_path = os.path.join(target_dir, entry)
            if not os.path.exists(new_path):
                os.makedirs(target_dir, exist_ok=True)
                shutil.move(old_path, new_path)


def list_param_config_scopes(username: str) -> list[str]:
    """List all scope_keys for a user. Auto-migrates old flat files into 'default' scope."""
    _migrate_scope_dir(username, DEFAULT_SCOPE_KEY)
    base = _base_config_dir(username)
    if not os.path.isdir(base):
        return []
    scopes = [
        entry for entry in sorted(os.listdir(base))
        if os.path.isdir(os.path.join(base, entry))
        and not entry.startswith('.') and not entry.startswith('_')
    ]
    return scopes if scopes else [DEFAULT_SCOPE_KEY]


def ensure_scope_exists(username: str, scope_key: str) -> str:
    """Ensure a scope directory exists. Returns the scope_key."""
    if not scope_key or scope_key.strip() == '':
        scope_key = DEFAULT_SCOPE_KEY
    param_config_dir(username, scope_key)
    return scope_key


def list_all_aliases_across_scopes(username: str) -> dict[str, list[str]]:
    """Return {scope_key: [ff_alias, ...]} for all scopes."""
    result = {}
    for scope_key in list_param_config_scopes(username):
        aliases = list_param_config_aliases(username, scope_key)
        if aliases:
            result[scope_key] = aliases
    if not result:
        result[DEFAULT_SCOPE_KEY] = []
    return result


def rename_scope(username: str, old_scope_key: str, new_scope_key: str) -> bool:
    """Rename a scope directory."""
    base = _base_config_dir(username)
    old_path = os.path.join(base, old_scope_key)
    new_path = os.path.join(base, new_scope_key)
    if os.path.isdir(old_path) and not os.path.exists(new_path):
        shutil.move(old_path, new_path)
        return True
    return False


def delete_scope(username: str, scope_key: str) -> bool:
    """Delete an entire scope directory and its contents."""
    if scope_key == DEFAULT_SCOPE_KEY:
        return False
    path = os.path.join(_base_config_dir(username), scope_key)
    if os.path.isdir(path):
        shutil.rmtree(path)
        return True
    return False
