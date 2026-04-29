"""
Shared global state and utility functions used across all server blueprints.
No Flask routes live here – only state, helpers, and the login_required decorator.
"""
import sys, os, importlib.util, threading, time, uuid, hashlib, hmac, secrets, re, json as _json
from functools import wraps
from flask import request, jsonify, render_template, session, redirect

import sys as _sys
# Make project root importable when this module is loaded from server/ sub-package
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in _sys.path:
    _sys.path.insert(0, _project_root)

from tools.factors.FactorFamily import FactorFamily
import Settings as Settings
import pandas as pd
from tools import DataColumn  # noqa: F401 – side-effect import used elsewhere

# ─── FactorFamily singleton cache ─────────────────────────────────────────────
_factor_family_cache: dict = {}
_factor_family_cache_lock = threading.Lock()

# ─── Submission list (FactorTester instances) ─────────────────────────────────
factor_testers: list = []
_factor_testers_lock = threading.Lock()

# ─── Global time range (updated by set_time_range route) ─────────────────────
start_point = None
end_point = None
start_calc_point = None

# ─── Per-session params store ─────────────────────────────────────────────────
_params_store: dict = {}  # key: (session_id, ff_alias) → list of param dicts
_params_store_lock = threading.Lock()

# ─── Auto-logout via IdleResourceManager ─────────────────────────────────────
# session 空闲超时通过 IdleResourceManager 的 registry 来追踪。
# 每次请求 touch，_check_login 检查 registry 中是否超时。
SESSION_IDLE_NAMESPACE = "flask_session"
SESSION_IDLE_TIMEOUT = 600  # 10 分钟


def _session_resource_id(sid: str) -> str:
    return f"{SESSION_IDLE_NAMESPACE}:{sid}"


def _touch_session_activity() -> None:
    """记录当前 session 的活动时间。"""
    if session.get('keep_login'):
        return
    sid = _get_session_id()
    try:
        from tools.base.IdleResourceManager import IdleResourceManager
        IdleResourceManager.get_instance().registry.record_use(_session_resource_id(sid))
    except Exception:
        pass


def _check_session_idle() -> bool:
    """检查当前 session 是否空闲超时。返回 True 表示已超时需退出。"""
    if session.get('keep_login'):
        return False
    sid = session.get('_sid')
    if sid is None:
        return False
    try:
        from tools.base.IdleResourceManager import IdleResourceManager
        rid = _session_resource_id(sid)
        idle_list = IdleResourceManager.get_instance().registry.get_idle_resources(SESSION_IDLE_TIMEOUT)
        return rid in idle_list
    except Exception:
        return False


def _cleanup_session_resource(sid: str) -> None:
    """从 registry 和 params_store 中清理指定 session。"""
    try:
        from tools.base.IdleResourceManager import IdleResourceManager
        IdleResourceManager.get_instance().registry.remove(_session_resource_id(sid))
    except Exception:
        pass
    with _params_store_lock:
        keys_to_remove = [k for k in _params_store if k[0] == sid]
        for k in keys_to_remove:
            _params_store.pop(k, None)

def _get_session_id() -> str:
    sid = session.get('_sid')
    if sid is None:
        sid = uuid.uuid4().hex
        session['_sid'] = sid
    return sid

def _get_session_params(ff_alias: str, ff) -> list:
    store_key = (_get_session_id(), ff_alias)
    with _params_store_lock:
        return list(_params_store.get(store_key, []))

def _save_session_params(ff_alias: str, params_list: list):
    store_key = (_get_session_id(), ff_alias)
    with _params_store_lock:
        _params_store[store_key] = list(params_list)

# ─── User system ──────────────────────────────────────────────────────────────
_DATA_DIR   = os.path.abspath(os.path.join(os.getcwd(), '..', 'data'))
_USERS_DIR  = os.path.join(_DATA_DIR, 'users')
_ACCTS_FILE = os.path.join(_USERS_DIR, 'accounts.json')
_accts_lock = threading.Lock()

_user_file_locks: dict = {}
_user_file_locks_meta = threading.Lock()

def _get_user_file_lock(username: str) -> threading.Lock:
    with _user_file_locks_meta:
        if username not in _user_file_locks:
            _user_file_locks[username] = threading.Lock()
        return _user_file_locks[username]

def _hash_password(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt.encode('utf-8'), 200_000).hex()

def _verify_password(password: str, salt: str, stored_hash: str) -> bool:
    return hmac.compare_digest(_hash_password(password, salt), stored_hash)

def _load_accounts() -> list:
    try:
        if os.path.exists(_ACCTS_FILE):
            with open(_ACCTS_FILE, 'r', encoding='utf-8') as f:
                data = _json.load(f)
            if isinstance(data, list):
                return data
    except Exception:
        pass
    return []

def _save_accounts(accounts: list):
    os.makedirs(os.path.dirname(_ACCTS_FILE), exist_ok=True)
    with open(_ACCTS_FILE, 'w', encoding='utf-8') as f:
        _json.dump(accounts, f, ensure_ascii=False, indent=2)

def _current_user() -> str | None:
    return session.get('username')

def _current_user_obj():
    """返回当前登录用户的 User 实例（None 若未登录）。"""
    username = _current_user()
    if not username:
        return None
    from tools.base.User import User
    with _accts_lock:
        accounts = _load_accounts()
    acct = next((a for a in accounts if a['username'] == username), None)
    is_admin = bool(acct and acct.get('is_admin', False))
    return User(name=username, is_admin=is_admin)

def _require_user() -> str:
    """Return current username. Only call within @login_required routes."""
    u = session.get('username')
    assert u is not None
    return u

def _user_data_dir(username: str) -> str:
    d = os.path.join(_USERS_DIR, username)
    os.makedirs(d, exist_ok=True)
    return d

def _user_tpl_path(username: str, kind: str, ff_alias: str | None = None) -> str:
    d = _user_data_dir(username)
    if kind == 'params' and ff_alias:
        d = os.path.join(d, 'params_templates')
        os.makedirs(d, exist_ok=True)
        return os.path.join(d, f'{ff_alias}.json')
    return os.path.join(d, f'{kind}_templates.json')

def _load_user_tpls(username: str, kind: str, ff_alias: str | None = None) -> list:
    path = _user_tpl_path(username, kind, ff_alias)
    try:
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                data = _json.load(f)
            if isinstance(data, list):
                return data
    except Exception:
        pass
    return []

def _save_user_tpls(username: str, kind: str, templates: list, ff_alias: str | None = None):
    path = _user_tpl_path(username, kind, ff_alias)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        _json.dump(templates, f, ensure_ascii=False, indent=2)

def _new_tpl_id() -> str:
    return str(int(time.time() * 1000))

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not _current_user():
            if request.is_json or request.method != 'GET':
                return jsonify({'success': False, 'error': '请先登录', 'login_required': True}), 401
            return redirect('/login')
        return f(*args, **kwargs)
    return decorated

# ─── FactorFamily utilities ───────────────────────────────────────────────────
def get_factor_family_instance(module_name):
    with _factor_family_cache_lock:
        if module_name in _factor_family_cache:
            return _factor_family_cache[module_name]
    factors_dir = os.path.join(os.getcwd(), "Factors")
    module_path = os.path.join(factors_dir, f"{module_name}.py")
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is not None and spec.loader is not None:
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        ff = getattr(module, module_name)()
        assert isinstance(ff, FactorFamily)
        with _factor_family_cache_lock:
            _factor_family_cache[module_name] = ff
        return ff
    else:
        raise ImportError(f"Cannot load module '{module_name}' from '{module_path}'")

def _load_chinese_names(factors_dir):
    result = {}
    for fname in os.listdir(factors_dir):
        if not fname.endswith('.py'):
            continue
        name = os.path.splitext(fname)[0]
        try:
            ff = get_factor_family_instance(name)
            cn = getattr(ff, 'desc', '') or getattr(ff, 'chinese_name', '') or ''
            result[name] = cn
        except Exception:
            result[name] = ''
    return result

_chinese_names_cache: dict = {}

def get_chinese_names(factors_dir):
    global _chinese_names_cache
    if not _chinese_names_cache:
        _chinese_names_cache = _load_chinese_names(factors_dir)
    return _chinese_names_cache

def get_factor_groups(factors_dir):
    factor_files = [f for f in os.listdir(factors_dir) if f.endswith(".py")]
    factor_names = [os.path.splitext(f)[0] for f in factor_files]

    def get_group(name):
        group = ""
        upper_count = 0
        for c in name:
            if c.isupper():
                upper_count += 1
                if upper_count == 1:
                    group += c
                elif upper_count == 2:
                    break
            else:
                if upper_count == 1:
                    group += c
        return group if group else name

    groups = {}
    for name in factor_names:
        group = get_group(name)
        groups.setdefault(group, []).append(name)
    return groups, factor_names

def build_group_html(groups, chinese_names: dict | None = None):
    if not groups:
        return '<div style="color:#888;">无匹配因子</div>'
    chinese_names = chinese_names or {}
    group_html = ""
    for group, names in sorted(groups.items()):
        group_html += f'<div class="factor-group">'
        group_html += f'<div class="factor-group-title">{group}</div>'
        group_html += '<ul class="factor-list">'
        for name in sorted(names):
            cn = chinese_names.get(name, '')
            label = f'{name} <span class="factor-cn-name">{cn}</span>' if cn else name
            group_html += f'<li><a href="?factor={name}">{label}</a></li>'
        group_html += '</ul>'
        group_html += '</div>'
    return group_html

def get_factor_main_section_html(factor_family_alias):
    try:
        ff = get_factor_family_instance(factor_family_alias)
        math_expr = getattr(ff, 'math_expr', '')
        chinese_name = getattr(ff, 'desc', '') or getattr(ff, 'chinese_name', '') or ''
        description = getattr(ff, 'description', '') or ''
        # 向后兼容：若无 description，尝试从 description_sections 转换
        if not description:
            ds = getattr(ff, 'description_sections', [])
            if ds and not isinstance(ds, property):
                from tools.factors.FactorFamily import FactorFamily
                description = FactorFamily._sections_to_markdown(ds)
        params = ff.params
        param_aliases = [p.alias for p in params]
        factors = ff.get_factors(params_list=_get_session_params(factor_family_alias, ff))
        start_date = getattr(Settings, 'default_test_start_date', '2020-01-01')
        start_date = start_date.strftime('%Y-%m-%d') if isinstance(start_date, pd.Timestamp) else start_date
        end_date = getattr(Settings, 'default_test_end_date', '2024-12-31')
        end_date = end_date.strftime('%Y-%m-%d') if isinstance(end_date, pd.Timestamp) else end_date
        start_time = getattr(Settings, 'default_day_start_time', '09:30')
        end_time = getattr(Settings, 'default_day_end_time', '15:00')
        return render_template(
            'factor_main.html',
            factor_family_alias=factor_family_alias,
            chinese_name=chinese_name,
            math_expr=math_expr,
            description=description,
            params=params,
            param_aliases=param_aliases,
            factors=factors,
            start_date=start_date,
            end_date=end_date,
            start_time=start_time,
            end_time=end_time
        )
    except Exception as e:
        return f"""
            <div class="section">
                <div class="section-title">当前因子: <b style="color:#0078d4;">{factor_family_alias}</b></div>
                <div style="color:#d40000;padding:20px;">加载因子失败: {e}</div>
            </div>
        """

# ─── Tree / product utilities ─────────────────────────────────────────────────
def convert_to_fancytree(tree_dict, checkbox_default=True):
    def create_node(key, value, path):
        key_str = str(key) if not isinstance(key, type) else key.__name__
        current_path = f"{path}/{key_str}" if path else key_str
        child_nodes = []
        if isinstance(value, dict) and "$SUBCLASS$" in value:
            sub_dict = value["$SUBCLASS$"]
            if isinstance(sub_dict, dict):
                for subkey, subval in sorted(sub_dict.items(), key=lambda x: str(x[0]) if not isinstance(x[0], type) else x[0].__name__):
                    if subkey not in ("$SUBCLASS$", "$OBJECTS$"):
                        child_nodes.append(create_node(subkey, subval, current_path))
        processed_keys = set()
        if isinstance(value, dict) and "$SUBCLASS$" in value and isinstance(value["$SUBCLASS$"], dict):
            processed_keys.update(value["$SUBCLASS$"].keys())
        if isinstance(value, dict):
            for k, v in sorted(value.items(), key=lambda x: str(x[0]) if not isinstance(x[0], type) else x[0].__name__):
                if k in ("$SUBCLASS$", "$OBJECTS$") or k in processed_keys:
                    continue
                child_nodes.append(create_node(k, v, current_path))
        has_objects = isinstance(value, dict) and "$OBJECTS$" in value and bool(value["$OBJECTS$"])
        has_subclass = isinstance(value, dict) and "$SUBCLASS$" in value and bool(value["$SUBCLASS$"])
        node = {"title": key_str, "key": current_path, "checkbox": checkbox_default}
        if child_nodes:
            node["folder"] = True
            node["lazy"] = False
            node["children"] = child_nodes
            if not has_objects or has_subclass:
                node["expanded"] = True
            if has_objects:
                node["desc"] = f"{len(value['$OBJECTS$'])} 个产品"
                product_folder = {
                    "title": "Product Lists",
                    "key": current_path + "/_products",
                    "folder": True,
                    "lazy": True,
                    "checkbox": False,
                }
                node["children"].insert(0, product_folder)
            else:
                node['checkbox'] = False
        elif has_objects:
            node["folder"] = True
            node["lazy"] = True
            node["desc"] = f"{len(value['$OBJECTS$'])} 个产品"
        else:
            node["folder"] = False
            node["lazy"] = False
        return node

    top_nodes = []
    for key, value in sorted(tree_dict.items(), key=lambda x: str(x[0]) if not isinstance(x[0], type) else x[0].__name__):
        if key not in ("$SUBCLASS$", "$OBJECTS$"):
            top_nodes.append(create_node(key, value, ""))
    return top_nodes

def find_node_by_path(tree_dict, path_parts):
    flag = False
    original_path_parts = path_parts.copy()
    if len(path_parts) >= 2 and path_parts[-2] == '_products':
        path_parts = path_parts[:-2]
        flag = True
    current = tree_dict
    for part in path_parts:
        found = None
        for key, value in current.items():
            key_str = str(key) if not isinstance(key, type) else key.__name__
            if key_str == part:
                if isinstance(value, dict):
                    current = value
                    found = True
                    break
                else:
                    return None
        if found:
            continue
        if '$SUBCLASS$' in current and isinstance(current['$SUBCLASS$'], dict):
            subclass_dict = current['$SUBCLASS$']
            for key, value in subclass_dict.items():
                key_str = str(key) if not isinstance(key, type) else key.__name__
                if key_str == part:
                    if isinstance(value, dict):
                        current = value
                        found = True
                        break
                    else:
                        return None
        if not found:
            return None
    if flag:
        assert '$OBJECTS$' in current and isinstance(current['$OBJECTS$'], list), \
            f"路径 {original_path_parts} 指向的节点没有 $OBJECTS$ 列表"
        current = current['$OBJECTS$']
        for obj in current:
            if obj.name == original_path_parts[-1]:
                return obj
        return None
    return current

def get_minimal_paths(paths):
    filtered = [p for p in paths if not p.endswith('/_products')]
    filtered.sort(key=len)
    result = []
    for p in filtered:
        if not any(p.startswith(r + '/') or p == r for r in result):
            result.append(p)
    return result

# ─── Category tree (loaded once at startup) ───────────────────────────────────
tree = Settings.get_cat_tree().tree
_fancytree_cache = None
