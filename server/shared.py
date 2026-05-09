"""
Shared global state and utility functions used across all server blueprints.
No Flask routes live here – only state, helpers, and the login_required decorator.
"""
from typing import TYPE_CHECKING, Any, Optional
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

if TYPE_CHECKING:
    from tools.factors import FactorTester

# ─── FactorFamily singleton cache ─────────────────────────────────────────────
_factor_family_cache: dict = {}
_factor_family_cache_lock = threading.Lock()

# ─── Submission list (FactorTester instances) ─────────────────────────────────
factor_testers: list = []
_factor_testers_lock = threading.Lock()
def get_factor_tester(alias: str, caller: Optional[Any] = None) -> 'FactorTester':
    with _factor_testers_lock:
        target_suffix = f":{alias}"
        tester = next((t for t in factor_testers if t.alias == str(alias) or t.alias.endswith(target_suffix)), None)
    assert tester is not None, f"{str(caller) + ': ' if caller is not None else ''}未找到对应的测试器实例"
    return tester

# ─── Per-page time range store ────────────────────────────────────────────────
# 按 page_uuid 隔离时间范围，避免同一用户的不同 tab 互相覆盖。
# key = page_uuid (前端在 set_time_range 时获取，后续 submit 时传回)
# value = (start, end, start_calc) 三元组
_MAX_PAGE_UUIDS = 500  # 每个 session 的 page_uuid 上限

_page_time_store: dict = {}  # page_uuid → (start, end, start_calc)
_page_time_store_lock = threading.Lock()


def get_default_time():
    """从 Settings 获取默认时间范围。永远可用，不依赖用户操作。"""
    start = Settings.default_test_start_date
    end   = Settings.default_test_end_date
    if start is None:
        start = pd.Timestamp('2025-01-02', tz='Asia/Shanghai')
    if end is None:
        end = pd.Timestamp('2025-05-31', tz='Asia/Shanghai')
    return start, end


def get_current_time(page_uuid: Optional[str] = None):
    """获取当前页面绑定的运行时时间范围。

    如果 page_uuid 有效且之前通过 set_time_range 设置过，返回该页面的时间；
    否则返回 Settings 默认值。
    """
    if page_uuid:
        with _page_time_store_lock:
            entry = _page_time_store.get(page_uuid)
            if entry is not None:
                return entry  # (start, end, start_calc)
    start, end = get_default_time()
    return start, end, start


def _set_runtime_time(page_uuid: str, start, end, start_calc=None):
    """写入 page_uuid 对应的运行时时间范围（由 set_time_range 路由调用）。"""
    if start_calc is None:
        start_calc = start
    with _page_time_store_lock:
        if page_uuid not in _page_time_store and len(_page_time_store) >= _MAX_PAGE_UUIDS:
            # 超过上限：清理最旧的一半
            keys_to_remove = list(_page_time_store.keys())[:len(_page_time_store) // 2]
            for k in keys_to_remove:
                _page_time_store.pop(k, None)
        _page_time_store[page_uuid] = (start, end, start_calc)

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
_ORGS_FILE = os.path.join(_USERS_DIR, 'organizations.json')
_accts_lock = threading.Lock()
_orgs_lock = threading.Lock()

DEFAULT_ORGANIZATION_ID = 'default'
DEFAULT_ORGANIZATION_NAME = '默认机构'
ROLE_SUPER_ADMIN = 'super_admin'
ROLE_ORG_ADMIN = 'org_admin'
ROLE_LEVEL_ADMIN = 'level_admin'
ROLE_USER = 'user'
ADMIN_ROLES = {ROLE_SUPER_ADMIN, ROLE_ORG_ADMIN, ROLE_LEVEL_ADMIN}

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

def _load_organizations() -> list:
    try:
        if os.path.exists(_ORGS_FILE):
            with open(_ORGS_FILE, 'r', encoding='utf-8') as f:
                data = _json.load(f)
            if isinstance(data, list):
                return data
    except Exception:
        pass
    return []

def _save_organizations(organizations: list):
    os.makedirs(os.path.dirname(_ORGS_FILE), exist_ok=True)
    with open(_ORGS_FILE, 'w', encoding='utf-8') as f:
        _json.dump(organizations, f, ensure_ascii=False, indent=2)

def _slugify_org_id(name: str) -> str:
    raw = re.sub(r'\s+', '_', (name or '').strip())
    raw = re.sub(r'[^\w\u4e00-\u9fff-]', '', raw)
    return raw or DEFAULT_ORGANIZATION_ID

def _compose_account_username(organization_id: str, alias: str, serial: int) -> str:
    """Canonical account id: {organization_id}${alias}@{serial}."""
    org_id = (organization_id or DEFAULT_ORGANIZATION_ID).strip() or DEFAULT_ORGANIZATION_ID
    return f'{org_id}${alias}@{serial}'

def _next_account_username(accounts: list, organization_id: str, alias: str) -> str:
    org_id = (organization_id or DEFAULT_ORGANIZATION_ID).strip() or DEFAULT_ORGANIZATION_ID
    same_name = [
        a for a in accounts
        if (a.get('alias') or a.get('username')) == alias
        and (a.get('organization_id') or DEFAULT_ORGANIZATION_ID) == org_id
    ]
    serial = max(
        (
            int(a['username'].rsplit('@', 1)[1])
            for a in same_name
            if '@' in a.get('username', '') and a['username'].rsplit('@', 1)[1].isdigit()
        ),
        default=0,
    ) + 1
    return _compose_account_username(org_id, alias, serial)

def _normalize_organization(org: dict) -> dict:
    normalized = dict(org or {})
    name = (normalized.get('name') or normalized.get('organization_name') or DEFAULT_ORGANIZATION_NAME).strip()
    normalized['name'] = name
    normalized['id'] = (normalized.get('id') or normalized.get('organization_id') or _slugify_org_id(name)).strip()
    normalized.setdefault('description', '')
    return normalized

def _list_organizations_with_default() -> list:
    with _orgs_lock:
        organizations = [_normalize_organization(o) for o in _load_organizations()]
    if not any(o.get('id') == DEFAULT_ORGANIZATION_ID for o in organizations):
        organizations.insert(0, {'id': DEFAULT_ORGANIZATION_ID, 'name': DEFAULT_ORGANIZATION_NAME, 'description': '系统默认机构'})
    return organizations

def _normalize_account(acct: dict) -> dict:
    """Return an account dict with organization and hierarchy fields populated.

    旧账号文件只有 is_admin；这里不强制写回磁盘，保证历史数据可无感读取。
    """
    normalized = dict(acct or {})
    normalized.setdefault('organization_id', DEFAULT_ORGANIZATION_ID)
    normalized.setdefault('organization_name', DEFAULT_ORGANIZATION_NAME)
    normalized.setdefault('parent_username', '')
    if normalized.get('is_admin'):
        # 历史账号里只有 is_admin 的，只有 True 被提升为超级管理员。
        normalized.setdefault('role', ROLE_SUPER_ADMIN)
    else:
        normalized.setdefault('role', ROLE_USER)
    normalized['is_admin'] = normalized.get('role') == ROLE_SUPER_ADMIN
    return normalized

def _normalize_accounts(accounts: list) -> list:
    return [_normalize_account(a) for a in accounts]

def _get_account(username: str | None) -> dict | None:
    if not username:
        return None
    with _accts_lock:
        accounts = _normalize_accounts(_load_accounts())
    return next((a for a in accounts if a.get('username') == username), None)

def _is_super_admin_account(acct: dict | None) -> bool:
    return bool(acct and (acct.get('role') == ROLE_SUPER_ADMIN or acct.get('is_admin')))

def _is_org_admin_account(acct: dict | None) -> bool:
    return bool(acct and (acct.get('role') == ROLE_ORG_ADMIN or _is_super_admin_account(acct)))

def _is_level_admin_account(acct: dict | None) -> bool:
    return bool(acct and (acct.get('role') == ROLE_LEVEL_ADMIN or _is_org_admin_account(acct)))

def _is_any_admin_account(acct: dict | None) -> bool:
    return bool(acct and (acct.get('role') in ADMIN_ROLES or _is_super_admin_account(acct)))

def _account_display_name(acct: dict | None) -> str:
    if not acct:
        return ''
    return acct.get('alias') or acct.get('username') or ''

def _visible_accounts_for(username: str | None, include_self: bool = True) -> list:
    """Accounts whose user-level resources can be viewed by username.

    普通用户：自己 + 直接下级。
    层级管理员：自己 + 直接下级（管理权限也限直接下级）。
    机构管理员：本机构用户。
    超级管理员：全部用户。
    """
    if not username:
        return []
    with _accts_lock:
        accounts = _normalize_accounts(_load_accounts())
    current = next((a for a in accounts if a.get('username') == username), None)
    if current is None:
        return []
    if _is_super_admin_account(current):
        visible = accounts
    elif current.get('role') == ROLE_ORG_ADMIN:
        org_id = current.get('organization_id') or DEFAULT_ORGANIZATION_ID
        visible = [a for a in accounts if (a.get('organization_id') or DEFAULT_ORGANIZATION_ID) == org_id]
    else:
        visible = [a for a in accounts if a.get('parent_username') == username]
        if include_self:
            visible.insert(0, current)
    if include_self and current not in visible:
        visible.insert(0, current)
    if not include_self:
        visible = [a for a in visible if a.get('username') != username]
    return visible

def _visible_usernames_for(username: str | None, include_self: bool = True) -> list[str]:
    return [a.get('username') for a in _visible_accounts_for(username, include_self=include_self) if a.get('username')]

def _can_view_user_scope(current_username: str | None, target_username: str | None) -> bool:
    if not current_username or not target_username:
        return False
    return target_username in set(_visible_usernames_for(current_username, include_self=True))

def _direct_child_accounts_for(username: str | None) -> list:
    if not username:
        return []
    with _accts_lock:
        accounts = _normalize_accounts(_load_accounts())
    return [a for a in accounts if a.get('parent_username') == username]

def _can_manage_user_account(current_username: str | None, target_username: str | None) -> bool:
    """Whether current user can edit target user's identity fields."""
    if not current_username or not target_username or current_username == target_username:
        return False
    with _accts_lock:
        accounts = _normalize_accounts(_load_accounts())
    current = next((a for a in accounts if a.get('username') == current_username), None)
    target = next((a for a in accounts if a.get('username') == target_username), None)
    if not current or not target:
        return False
    if _is_super_admin_account(current):
        return True
    if _is_super_admin_account(target):
        return False
    if current.get('role') == ROLE_ORG_ADMIN:
        return (current.get('organization_id') or DEFAULT_ORGANIZATION_ID) == (target.get('organization_id') or DEFAULT_ORGANIZATION_ID)
    if current.get('role') == ROLE_LEVEL_ADMIN:
        return target.get('parent_username') == current_username
    return False

def _serialize_account_public(acct: dict | None, current_username: str | None = None) -> dict:
    normalized = _normalize_account(acct or {})
    return {
        'username': normalized.get('username', ''),
        'alias': normalized.get('alias') or normalized.get('username', ''),
        'role': normalized.get('role') or ROLE_USER,
        'is_admin': normalized.get('role') == ROLE_SUPER_ADMIN,
        'organization_id': normalized.get('organization_id') or DEFAULT_ORGANIZATION_ID,
        'organization_name': normalized.get('organization_name') or DEFAULT_ORGANIZATION_NAME,
        'parent_username': normalized.get('parent_username') or '',
        'can_manage': _can_manage_user_account(current_username, normalized.get('username')) if current_username else False,
    }

def _visible_organizations_for(username: str | None) -> list:
    acct = _get_account(username)
    organizations = _list_organizations_with_default()
    if not acct:
        return []
    if _is_super_admin_account(acct):
        return organizations
    org_id = acct.get('organization_id') or DEFAULT_ORGANIZATION_ID
    return [o for o in organizations if o.get('id') == org_id]

def _can_manage_organization(current_username: str | None, organization_id: str | None) -> bool:
    acct = _get_account(current_username)
    if not acct:
        return False
    if _is_super_admin_account(acct):
        return True
    if acct.get('role') == ROLE_ORG_ADMIN:
        return (acct.get('organization_id') or DEFAULT_ORGANIZATION_ID) == (organization_id or DEFAULT_ORGANIZATION_ID)
    return False

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

def _user_tpl_path(username: str, kind: str, ff_alias: str | None = None, scope_key: str | None = None) -> str:
    """返回模板文件路径。
    
    - 如果提供了 scope_key，模板按 scope_key 隔离存储到 {kind}_templates/{scope_key}.json
    - 否则兼容旧行为：ff_alias 仅对 params 类型有效，其他类型存到 {kind}_templates.json
    """
    d = _user_data_dir(username)
    if scope_key:
        d = os.path.join(d, f'{kind}_templates')
        os.makedirs(d, exist_ok=True)
        return os.path.join(d, f'{scope_key}.json')
    if kind == 'params' and ff_alias:
        d = os.path.join(d, 'params_templates')
        os.makedirs(d, exist_ok=True)
        return os.path.join(d, f'{ff_alias}.json')
    return os.path.join(d, f'{kind}_templates.json')

def _load_user_tpls(username: str, kind: str, ff_alias: str | None = None, scope_key: str | None = None) -> list:
    path = _user_tpl_path(username, kind, ff_alias, scope_key=scope_key)
    try:
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                data = _json.load(f)
            if isinstance(data, list):
                return data
    except Exception:
        pass
    return []

def _save_user_tpls(username: str, kind: str, templates: list, ff_alias: str | None = None, scope_key: str | None = None):
    path = _user_tpl_path(username, kind, ff_alias, scope_key=scope_key)
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
def get_factor_family_instance(module_name, username: str | None = None):
    """获取因子族实例。优先从 Factors/ 目录加载公共因子，若找不到则尝试从用户自定义因子加载。"""
    with _factor_family_cache_lock:
        if module_name in _factor_family_cache:
            return _factor_family_cache[module_name]

    # ── 1. 尝试从公共 Factors/ 目录加载 ──
    factors_dir = os.path.join(os.getcwd(), "Factors")
    module_path = os.path.join(factors_dir, f"{module_name}.py")
    if os.path.exists(module_path):
        spec = importlib.util.spec_from_file_location(module_name, module_path)
        if spec is not None and spec.loader is not None:
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            ff = getattr(module, module_name)()
            assert isinstance(ff, FactorFamily)
            with _factor_family_cache_lock:
                _factor_family_cache[module_name] = ff
            return ff

    # ── 2. 尝试从用户自定义因子加载（先按 factor_id 查，再按 name 遍历匹配） ──
    if username is None:
        username = _current_user()
    if username:
        # 2a. 直接用 module_name 作为 factor_id 查找
        cf = get_custom_factor_instance(username, module_name)
        if cf is not None:
            return cf
        # 2b. 遍历所有自定义因子 .py，按 class 名匹配
        cf_dir = os.path.join(_user_data_dir(username), 'custom_factors')
        if os.path.isdir(cf_dir):
            for fname in os.listdir(cf_dir):
                if not fname.endswith('.py'):
                    continue
                factor_id = os.path.splitext(fname)[0]
                cf = get_custom_factor_instance(username, factor_id)
                if cf is not None and cf.__class__.__name__ == module_name:
                    return cf

    raise ImportError(f"Cannot load factor '{module_name}' from '{module_path}'")


def _build_custom_factor_family(username: str, factor_id: str) -> FactorFamily | None:
    """
    从用户自定义因子 .py 文件直接 import 构建 FactorFamily 实例。

    读取 data/users/{username}/custom_factors/{factor_id}.py，
    用 importlib 加载模块并实例化 FactorFamily 子类。
    """
    cf_dir = os.path.join(_user_data_dir(username), 'custom_factors')
    cf_path = os.path.join(cf_dir, f'{factor_id}.py')
    if not os.path.exists(cf_path):
        return None

    module_name = f'_cf_{username}_{factor_id}'
    try:
        spec = importlib.util.spec_from_file_location(module_name, cf_path)
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        # 找到模块中的 FactorFamily 子类
        factor_cls = None
        for attr_name in dir(module):
            obj = getattr(module, attr_name)
            if isinstance(obj, type) and issubclass(obj, FactorFamily) and obj is not FactorFamily:
                factor_cls = obj
                break
        if factor_cls is None:
            return None

        return factor_cls()
    except Exception:
        return None


# 自定义因子实例缓存（按 (username, factor_id) 缓存）
_custom_factor_cache: dict = {}
_custom_factor_cache_lock = threading.Lock()


def get_custom_factor_instance(username: str, factor_id: str) -> FactorFamily | None:
    """获取自定义因子实例（带缓存）。"""
    cache_key = (username, factor_id)
    with _custom_factor_cache_lock:
        if cache_key in _custom_factor_cache:
            return _custom_factor_cache[cache_key]
    instance = _build_custom_factor_family(username, factor_id)
    if instance is not None:
        with _custom_factor_cache_lock:
            _custom_factor_cache[cache_key] = instance
    return instance


def invalidate_custom_factor_cache(username: str, factor_id: str | None = None):
    """清除自定义因子缓存（更新/删除后调用）。"""
    with _custom_factor_cache_lock:
        if factor_id is not None:
            _custom_factor_cache.pop((username, factor_id), None)
        else:
            keys_to_remove = [k for k in _custom_factor_cache if k[0] == username]
            for k in keys_to_remove:
                _custom_factor_cache.pop(k, None)

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

def build_group_html(
    groups,
    chinese_names: dict | None = None,
    custom_factors: list | None = None,
    selected_name: str | None = None,
    selected_type: str | None = None,
    selected_owner_username: str | None = None,
):
    """构建侧边栏因子列表 HTML。
    
    自定义因子与公共因子按驼峰首段混合分组：
    - 自定义因子排在每组公共因子之前
    - 组内按字典序排列
    - 自定义因子有 ⭐ 标记，公共因子无标记
    """
    if not groups and not custom_factors:
        return '<div style="color:#888;">无匹配因子</div>'
    chinese_names = chinese_names or {}
    custom_factors = custom_factors or []
    import html as _html

    def get_group(name):
        """驼峰首段分组：取第一个大写字母+后续小写字母"""
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

    # ── 1. 公共因子分组（已有） + 自定义因子也按驼峰分组 ──
    merged_groups = {}  # {group: [{'name':..., 'type':'public'|'custom', 'owner_key':...}, ...]}

    # 公共因子
    for group, names in groups.items():
        for name in sorted(names):
            cn = chinese_names.get(name, '')
            merged_groups.setdefault(group, []).append({
                'name': name,
                'type': 'public',
                'id': name,
                'chinese_name': cn,
                'owner_key': '公共',
                'owner_label': '公共',
            })

    # 自定义因子
    for cf in custom_factors:
        cf_name = cf.get('name', '') or cf.get('id', '')
        cf_group = get_group(cf_name)
        merged_groups.setdefault(cf_group, []).append({
            'name': cf_name,
            'type': 'custom',
            'id': cf.get('id', ''),
            'chinese_name': cf.get('chinese_name', '') or cf_name,
            'category': cf.get('category', ''),
            'owner_username': cf.get('owner_username', ''),
            'owner_alias': cf.get('owner_alias', ''),
            'owner_organization_id': cf.get('owner_organization_id', ''),
            'owner_organization_name': cf.get('owner_organization_name', ''),
            'can_edit': bool(cf.get('can_edit')),
            'owner_key': (
                f"{cf.get('owner_organization_name') or cf.get('owner_organization_id') or '未分机构'}"
                f"/{cf.get('owner_alias') or cf.get('owner_username') or '未知用户'}"
            ),
            'owner_label': (
                '我的因子'
                if cf.get('can_edit')
                else f"{cf.get('owner_organization_name') or cf.get('owner_organization_id') or '未分机构'} / {cf.get('owner_alias') or cf.get('owner_username') or '未知用户'}"
            ),
        })

    # ── 2. 每组内排序：驼峰首峰、机构+用户名+公共、因子家族名 ──
    for grp in merged_groups:
        merged_groups[grp].sort(key=lambda x: (x.get('owner_key', ''), x['name']))

    # ── 3. 生成 HTML ──
    group_html = ""
    for group in sorted(merged_groups.keys()):
        items = merged_groups[group]
        owners = {}
        for item in items:
            owners.setdefault(item.get('owner_key') or '公共', []).append(item)
        group_html += '<div class="factor-group collapsible-factor-node collapsible-factor-group">'
        group_html += (
            '<button class="collapsible-factor-header" type="button">'
            '<span class="caret">▶</span>'
            f'<span class="collapsible-factor-title">{_html.escape(str(group))}</span>'
            f'<span class="collapsible-factor-count">{len(items)}</span>'
            '</button><div class="collapsible-factor-body">'
        )
        for owner_key in sorted(owners.keys()):
            owner_items = owners[owner_key]
            owner_label = owner_items[0].get('owner_label') or owner_key
            group_html += '<div class="collapsible-factor-node collapsible-factor-owner">'
            group_html += (
                '<button class="collapsible-factor-header" type="button">'
                '<span class="caret">▶</span>'
                f'<span class="collapsible-factor-title">{_html.escape(str(owner_label))}</span>'
                f'<span class="collapsible-factor-count">{len(owner_items)}</span>'
                '</button><div class="collapsible-factor-body">'
            )
            group_html += '<ul class="factor-list">'
            for item in owner_items:
                is_custom = (item['type'] == 'custom')
                if is_custom:
                    owner = item.get('owner_username') or ''
                    href = f'?factor={_html.escape(str(item["id"]))}&amp;type=custom'
                    if owner:
                        href += f'&amp;owner_username={_html.escape(str(owner))}'
                else:
                    href = f'?factor={_html.escape(str(item["id"]))}'
                is_active = False
                if selected_name:
                    if is_custom:
                        is_active = (
                            (selected_type == 'custom')
                            and (selected_owner_username or '') == (item.get('owner_username') or '')
                            and selected_name in {(item.get('id') or ''), (item.get('name') or '')}
                        )
                    else:
                        is_active = (selected_type != 'custom') and selected_name == (item.get('id') or '')
                cn = item.get('chinese_name', '')
                source_text = '我' if item.get('can_edit') else (item.get('owner_alias') or '下级')
                source_tag = f' <span class="factor-source-tag factor-source-custom">{_html.escape(source_text)}</span>' if is_custom else ' <span class="factor-source-tag factor-source-public">公共</span>'
                cat_tag = ''
                if is_custom and item.get('category'):
                    cat_tag = f' <span style="color:#999;font-size:11px;">[{_html.escape(str(item["category"]))}]</span>'
                name_html = _html.escape(str(item["name"]))
                if cn:
                    label = f'{name_html}{source_tag} <span class="factor-cn-name">{_html.escape(str(cn))}</span>{cat_tag}'
                else:
                    label = f'{name_html}{source_tag}{cat_tag}'
                active_cls = ' class="active"' if is_active else ''
                group_html += f'<li><a{active_cls} href="{href}">{label}</a></li>'
            group_html += '</ul></div></div>'
        group_html += '</div></div>'

    return group_html

def get_factor_main_section_html(factor_family_alias):
    try:
        ff = get_factor_family_instance(factor_family_alias)
        math_expr = getattr(ff, 'math_expr', '')
        chinese_name = getattr(ff, 'desc', '') or getattr(ff, 'chinese_name', '') or ''
        description = getattr(ff, 'description', '') or ''
        params = ff.params
        from server.param_meta import serialize_param_meta
        param_metas = [serialize_param_meta(p) for p in params]
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
            param_metas=param_metas,
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
        if len(current) == 1 and '$OBJECTS$' in current:
            flag = True
            break
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
