"""Storage for factor-library user-scoped parameter configs."""

import json
import os
import time

from server.services.user_storage import user_data_dir


def param_config_dir(username: str) -> str:
    d = os.path.join(user_data_dir(username), 'factor_library_param_configs')
    os.makedirs(d, exist_ok=True)
    return d


def param_config_path(username: str, ff_alias: str) -> str:
    return os.path.join(param_config_dir(username), f'{ff_alias}.json')


def load_param_config(username: str, ff_alias: str) -> dict | None:
    path = param_config_path(username, ff_alias)
    try:
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if isinstance(data, dict) and isinstance(data.get('params_list'), list):
                return data
    except Exception:
        pass
    return None


def save_param_config(username: str, ff_alias: str, params_list: list) -> dict:
    config = {
        'id': username,
        'scope': 'user_id',
        'scope_user_id': username,
        'name': username,
        'params_list': params_list,
        'updated_at': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime()),
    }
    path = param_config_path(username, ff_alias)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
    return config


def delete_param_config(username: str, ff_alias: str) -> bool:
    path = param_config_path(username, ff_alias)
    if os.path.exists(path):
        os.remove(path)
        return True
    return False


def list_param_config_aliases(username: str) -> list[str]:
    d = param_config_dir(username)
    return [
        os.path.splitext(fname)[0]
        for fname in sorted(os.listdir(d))
        if fname.endswith('.json')
    ]
