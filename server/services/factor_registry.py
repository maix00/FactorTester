"""
FactorFamily 加载、缓存与失效管理。

生命周期：
  - FactorFamily 实例由 page_uuid 持有，不设全局强引用缓存
  - 页面关闭/超时时自动回收
  - Factor 缓存同样由 page_uuid 管理（FactorFamily.get_factor 优先查页级缓存）

元数据：
  - 因子中文名/描述从 SQLite factor_family_catalog 表读取（懒加载，不实例化）
  - 因子列表 get_factor_groups() 从 SQLite 公共因子注册表读取（不实例化）

核心函数：
  get_factor_family_instance()  加载因子族实例 → 优先从 page 级缓存查找
  invalidate_factor_family_cache()  失效特定的或全部公共因子缓存
  invalidate_custom_factor_cache()  失效特定用户的或某用户全部的的自定义因子缓存
  get_factor_groups()           返回按前缀分组的因子名列表（Mm/Oi/Vl/Vp 等）
  factor_group_key()            从类名提取分组前缀（MmRet → Mm）
"""

from __future__ import annotations

import importlib.util
import os
import sqlite3
import tempfile
import threading
from contextlib import contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING

from flask import has_request_context, session

from tools.cli.factor_subject_refs import split_owner_qualified_factor_family
from tools.data.account_manage import can_view_user_scope
from tools.data.factor_workspace.storage import (
    load_factor_source,
    load_public_factor_source,
)
from tools.data.sqlite.db import connect_sqlite
from tools.factors.FactorFamily import FactorFamily

if TYPE_CHECKING:
    from tools.factors.Factors import Factor

import settings as Settings

# ── 页级缓存（由 page_uuid 持有，替代全局强引用） ──
# page_families: {page_uuid: {module_name: FactorFamily}}
# page_factors:   {page_uuid: {factor_name: Factor}}
page_families: dict[str, dict[str, FactorFamily]] = {}
page_factors: dict[str, dict[str, 'Factor']] = {}
_page_cache_lock = threading.Lock()

# 自定义因子缓存（按 (username, factor_id) 缓存，自定义因子量少）
_custom_factor_cache: dict = {}
_custom_factor_cache_versions: dict = {}
_custom_factor_cache_lock = threading.Lock()

# 中文名缓存（从 SQLite 一次性加载，轻量，不实例化 FactorFamily）
_chinese_names_cache: dict = {}
_chinese_names_cache_loaded = False

# A worker activates one opaque Run source scope for the duration of a task.
# The scope is never a source authority by itself; the service validates its
# owner and per-file hash before returning source text.
_active_transient_source_scope: ContextVar[str] = ContextVar(
    "active_transient_factor_source_scope", default=""
)
_active_transient_source_overrides: ContextVar[dict[str, str]] = ContextVar(
    "active_transient_factor_source_overrides", default={}
)
_active_portable_source_overrides: ContextVar[dict[str, dict[str, str]]] = ContextVar(
    "active_portable_factor_source_overrides", default={}
)
_active_transient_source_owner: ContextVar[str] = ContextVar(
    "active_transient_factor_source_owner", default=""
)
_authorized_factor_source_owners: ContextVar[frozenset[str]] = ContextVar(
    "authorized_factor_source_owners", default=frozenset()
)


@contextmanager
def authorized_factor_source_owners(owners: object):
    """Apply Manager-validated source visibility to one freeze operation."""
    normalized = frozenset(
        str(owner or "").strip()
        for owner in (owners if isinstance(owners, (list, tuple, set, frozenset)) else [])
        if str(owner or "").strip()
    )
    token = _authorized_factor_source_owners.set(normalized)
    try:
        yield
    finally:
        _authorized_factor_source_owners.reset(token)


@contextmanager
def transient_factor_source_scope(
    scope_id: str = "",
    *,
    owner: str = "",
    overrides: dict[str, str] | None = None,
    portable_overrides: dict[str, object] | None = None,
):
    owner = str(owner or "").strip()
    if (overrides or portable_overrides) and not owner:
        raise ValueError("transient factor source override owner is required")
    token = _active_transient_source_scope.set(str(scope_id or "").strip())
    override_token = _active_transient_source_overrides.set(
        dict(overrides or {})
    )
    normalized_portable: dict[str, dict[str, str]] = {}
    for canonical_ref, value in (portable_overrides or {}).items():
        if isinstance(value, dict):
            source_code = str(value.get("source_code") or "")
            source_policy = str(value.get("source_access_policy") or "")
        else:
            source_code = str(value or "")
            source_policy = (
                "public" if str(canonical_ref).startswith("public:")
                else "owner_only"
            )
        if source_code:
            normalized_portable[str(canonical_ref)] = {
                "source_code": source_code,
                "source_access_policy": source_policy,
            }
    portable_token = _active_portable_source_overrides.set(normalized_portable)
    owner_token = _active_transient_source_owner.set(owner)
    try:
        yield
    finally:
        _active_transient_source_scope.reset(token)
        _active_transient_source_overrides.reset(override_token)
        _active_portable_source_overrides.reset(portable_token)
        _active_transient_source_owner.reset(owner_token)


def _active_run_source_record(
    source_kind: str,
    source_owner: str,
    factor_id: str,
) -> tuple[str, str]:
    source_kind = str(source_kind or "").strip()
    source_owner = str(source_owner or "").strip()
    factor_id = str(factor_id or "").strip()
    task_owner = _active_transient_source_owner.get()
    if not source_kind or not source_owner or not factor_id or not task_owner:
        return "", ""
    canonical_ref = (
        f"public:{factor_id}"
        if source_kind == "public" else f"{source_owner}:{factor_id}"
    )
    override = _active_portable_source_overrides.get().get(canonical_ref)
    if override:
        policy = str(override.get("source_access_policy") or "")
        source_mode = "" if policy in {"public", "owner_only"} else policy
        return str(override.get("source_code") or ""), source_mode
    if source_kind == "custom" and source_owner == task_owner:
        override = _active_transient_source_overrides.get().get(factor_id)
        if override:
            return override, "transient_run_source"
    scope_id = _active_transient_source_scope.get()
    if not scope_id:
        return "", ""
    try:
        from server.services.transient_factor_sources import load_source_record

        record = load_source_record(
            scope_id,
            factor_id,
            owner=task_owner,
            source_kind=source_kind,
            source_owner=source_owner,
        )
        if not record:
            return "", ""
        policy = str(record.get("source_access_policy") or "")
        source_mode = "" if policy in {"public", "owner_only"} else policy
        return str(record.get("source_code") or ""), source_mode
    except Exception:
        return "", ""


def _active_run_source(
    source_kind: str,
    source_owner: str,
    factor_id: str,
) -> str:
    return _active_run_source_record(source_kind, source_owner, factor_id)[0]


def _transient_source(owner: str, factor_id: str) -> str:
    return _active_run_source("custom", owner, factor_id)


# ── 页级缓存操作 ──

def register_page(page_uuid: str) -> None:
    """注册新页面。"""
    with _page_cache_lock:
        page_families.setdefault(page_uuid, {})
        page_factors.setdefault(page_uuid, {})


def unregister_page(page_uuid: str) -> None:
    """注销页面，释放其持有的 FactorFamily 和 Factor。"""
    with _page_cache_lock:
        page_families.pop(page_uuid, {})
        factors = page_factors.pop(page_uuid, {})
    # 清理 Factor（调 clear 释放中间数据）
    for f in factors.values():
        try:
            f.clear()
            f.delete()
        except Exception:
            pass
    # FactorFamily 实例随 dict 回收自然释放（无其他强引用）


def clear_page_factor_family(page_uuid: str, factor_family_alias: str) -> None:
    """清理某个 page_uuid 下指定因子家族的缓存。"""
    page_uuid = str(page_uuid).strip()
    factor_family_alias = str(factor_family_alias).strip()
    if not page_uuid or not factor_family_alias:
        return
    with _page_cache_lock:
        families = page_families.get(page_uuid, {})
        family = families.pop(factor_family_alias, None)
        if not families:
            page_families.pop(page_uuid, None)
        factors = page_factors.get(page_uuid, {})
        removed = [
            alias
            for alias, factor in list(factors.items())
            if getattr(getattr(factor, 'family', None), 'alias', None) == factor_family_alias
        ]
        removed_factors = [factors.pop(alias, None) for alias in removed]
        if not factors:
            page_factors.pop(page_uuid, None)
    for factor in removed_factors:
        if factor is None:
            continue
        try:
            factor.clear()
            factor.delete()
        except Exception:
            pass
    if family is not None:
        try:
            del family
        except Exception:
            pass


def _build_factor_from_source(
    module_name: str,
    source_code: str,
    *,
    user_prefix: str | None = "public",
) -> FactorFamily | None:
    if not source_code:
        return None
    tmpdir = tempfile.mkdtemp(prefix='factor_src_')
    tmpfile = os.path.join(tmpdir, f'{module_name}.py')
    token = None
    try:
        with open(tmpfile, 'w', encoding='utf-8') as file:
            file.write(source_code)
        spec = importlib.util.spec_from_file_location(module_name, tmpfile)
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        from tools.factors.FactorTester import _active_user_prefix
        token = _active_user_prefix.set(user_prefix or "")
        for attr_name in dir(module):
            obj = getattr(module, attr_name)
            if isinstance(obj, type) and issubclass(obj, FactorFamily) and obj is not FactorFamily:
                return obj()
        return None
    except Exception:
        return None
    finally:
        if token is not None:
            try:
                from tools.factors.FactorTester import _active_user_prefix
                _active_user_prefix.reset(token)
            except Exception:
                pass
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


def _split_factor_owner_ref(ref: str) -> tuple[str | None, str]:
    return split_owner_qualified_factor_family(ref)


def _public_factor_source_exists(factor_id: str) -> bool:
    return bool(
        _active_run_source("public", "public", factor_id)
        or load_public_factor_source(factor_id)
    )


def _is_registered_shared_factor(
    owner_username: str,
    factor_id: str,
) -> bool:
    """Return whether an owner explicitly registered a factor for research."""
    try:
        with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
            row = conn.execute(
                """
                SELECT 1 FROM account_factor_param_configs
                WHERE username=? AND ff_alias=?
                LIMIT 1
                """,
                (owner_username, factor_id),
            ).fetchone()
    except (OSError, sqlite3.Error):
        return False
    return row is not None


def _resolve_factor_family_ref(module_name: str, username: str | None) -> tuple[str, str, str, str]:
    """Resolve an optional owner-qualified factor family reference.

    Long-lived custom sources remain owner-qualified. Another visible account
    may execute one only after the owner has explicitly registered that factor
    family in the factor library. Page UUIDs remain a cache, never an authority
    for source identity or sharing.
    """
    owner, factor_id = _split_factor_owner_ref(module_name)
    session_user = session.get("username") if has_request_context() else ""
    active_user = str(username or session_user or "").strip() or None
    if owner == "public":
        return "public", "public", factor_id, f"public:{factor_id}"
    if owner:
        if _active_run_source("custom", owner, factor_id):
            return "custom", owner, factor_id, f"{owner}:{factor_id}"
        owner_visible = bool(
            active_user
            and (
                owner == active_user
                or owner in _authorized_factor_source_owners.get()
                or can_view_user_scope(active_user, owner)
            )
        )
        visible_shared_factor = bool(
            owner != active_user
            and owner_visible
            and (
                _is_registered_shared_factor(owner, factor_id)
                # A federated Manager persists an authorized 7997 hydration
                # before retrying RunSpec freeze.  That canonical local copy
                # is sufficient authority for the same visible owner; do not
                # require an unrelated factor-library row to have arrived in
                # the account-domain mirror first.
                or load_factor_source(owner, factor_id)
            )
        )
        if owner != active_user and not visible_shared_factor:
            if owner_visible:
                # A visible child account may have registered this family on
                # another Manager.  Report a missing canonical source so the
                # Manager can consult synchronized metadata and hydrate it via
                # 7997.  The hydrator still refuses objects absent from the
                # principal's authorized account-domain view.
                raise ImportError(
                    f"Cannot load factor family source for {module_name!r}"
                )
            raise PermissionError(
                f"Cannot load factor family {module_name!r}: "
                f"owner {owner!r} is not accessible for current user {active_user!r}"
            )
        return "custom", owner, factor_id, f"{owner}:{factor_id}"
    # An unqualified factor reference normally resolves to the public library.
    # During a Run, an explicitly supplied Profile source is stronger than
    # that default; otherwise a same-named public factor would silently win.
    if active_user and _transient_source(active_user, factor_id):
        return "custom", active_user, factor_id, f"{active_user}:{factor_id}"
    if _public_factor_source_exists(factor_id):
        return "public", "public", factor_id, f"public:{factor_id}"
    return "custom", active_user or "", factor_id, f"{active_user}:{factor_id}" if active_user else factor_id


def resolve_factor_family_source(
    module_name: str,
    *,
    username: str | None,
) -> dict[str, str]:
    """Resolve executable source identity without exposing it over HTTP."""
    source_kind, owner, factor_id, _ = _resolve_factor_family_ref(
        module_name,
        username,
    )
    source_code, source_mode = _active_run_source_record(
        source_kind, owner, factor_id,
    )
    if not source_code:
        source_code = (
            load_public_factor_source(factor_id)
            if source_kind == "public"
            else load_factor_source(owner, factor_id)
        ) or ""
    if not source_code:
        raise ImportError(
            f"Cannot load factor family source for {module_name!r}"
        )
    canonical_ref = (
        f"public:{factor_id}"
        if source_kind == "public" else f"{owner}:{factor_id}"
    )
    return {
        "canonical_family_ref": canonical_ref,
        "source_kind": source_kind,
        "source_owner": owner,
        "factor_id": factor_id,
        "source_code": source_code,
        "source_mode": source_mode,
    }


def get_factor_family_instance(module_name, username: str | None = None, page_uuid: str | None = None):
    """Load a FactorFamily instance.

    Priority:
      1. Resolve source identity from public factor library or current user's
         custom factor library. page_uuid is never an authority for existence.
      2. Reuse page cache only after the long-lived source identity is valid.
      3. Build a new instance from that source when cache misses.
    """
    module_name = str(module_name or "").strip()
    source_kind, owner, factor_id, cache_key = _resolve_factor_family_ref(module_name, username)
    source_code = ""

    transient_source = _active_run_source(source_kind, owner, factor_id)

    if source_kind == "public":
        source_code = transient_source or load_public_factor_source(factor_id) or ''
        if not source_code:
            raise ImportError(
                f"Cannot load factor '{factor_id}': not found in public factor registry"
            )
        user_prefix = "public"
    else:
        if not owner:
            raise ImportError(
                f"Cannot load factor '{factor_id}': not found in the public "
                "registry and no active user session"
            )
        source_code = transient_source or load_factor_source(owner, factor_id) or ''
        if not source_code:
            raise ImportError(f"Cannot load factor '{factor_id}': not found in custom factor library for user '{owner}'")
        user_prefix = owner

    # page cache is only a reuse layer after source existence is proven above.
    # A transient source must never enter a long-lived cache keyed only by
    # (owner, factor_id), otherwise a later Run could observe stale source.
    if page_uuid and not transient_source:
        with _page_cache_lock:
            ff_dict = page_families.get(page_uuid, {})
            if cache_key in ff_dict:
                return ff_dict[cache_key]
            if source_kind == "public" and factor_id in ff_dict:
                return ff_dict[factor_id]

    ff = _build_factor_from_source(factor_id, source_code, user_prefix=user_prefix)
    if ff is None:
        location = (
            "public factor registry"
            if source_kind == "public"
            else f"custom factor library for user '{owner}'"
        )
        raise ImportError(f"Cannot load factor '{factor_id}': source exists but no FactorFamily class found in {location}")
    if source_kind == "custom" and not transient_source:
        with _custom_factor_cache_lock:
            _custom_factor_cache[(owner, factor_id)] = ff

    if page_uuid and not transient_source:
        with _page_cache_lock:
            page_families.setdefault(page_uuid, {})[cache_key] = ff

    return ff


def factor_from_alias(factor_alias: str, *, username: str | None = None, page_uuid: str | None = None):
    """Create a one-off Factor from a transport alias without page storage.

    The family portion may be ``Family`` or ``owner:Family``.  Resolution is
    restricted to public families and the current user's own custom families.
    The created Factor is not inserted into page_factors.
    """
    alias = str(factor_alias or "").strip()
    if not alias:
        raise ValueError("factor_alias is empty")
    family_ref = alias.split("|", 1)[0]
    owner, family_id = _split_factor_owner_ref(family_ref)
    family = get_factor_family_instance(family_ref, username=username, page_uuid=page_uuid)
    family_alias = getattr(family, "alias", family_id)
    canonical_alias = alias
    if owner:
        canonical_alias = f"{family_alias}{alias[len(family_ref):]}"
    return family.factor_from_alias(canonical_alias)


def _build_custom_factor_family(username: str, factor_id: str) -> FactorFamily | None:
    source_code = load_factor_source(username, factor_id) or ''
    if not source_code:
        return None
    return _build_factor_from_source(f'_cf_{username}_{factor_id}', source_code, user_prefix=username)


def get_custom_factor_instance(username: str, factor_id: str) -> FactorFamily | None:
    from tools.data.sqlite.factor_source_store import factor_source_revision
    cache_key = (username, factor_id)
    revision = factor_source_revision('custom', username, factor_id)
    with _custom_factor_cache_lock:
        if cache_key in _custom_factor_cache and _custom_factor_cache_versions.get(cache_key) == revision:
            return _custom_factor_cache[cache_key]
    instance = _build_custom_factor_family(username, factor_id)
    if instance is not None:
        with _custom_factor_cache_lock:
            _custom_factor_cache[cache_key] = instance
            _custom_factor_cache_versions[cache_key] = revision
    return instance


def invalidate_custom_factor_cache(username: str, factor_id: str | None = None):
    with _custom_factor_cache_lock:
        if factor_id is not None:
            _custom_factor_cache.pop((username, factor_id), None)
            _custom_factor_cache_versions.pop((username, factor_id), None)
        else:
            keys_to_remove = [key for key in _custom_factor_cache if key[0] == username]
            for key in keys_to_remove:
                _custom_factor_cache.pop(key, None)
                _custom_factor_cache_versions.pop(key, None)


def invalidate_factor_family_cache(factor_name: str | None = None, page_uuid: str | None = None):
    """失效 FactorFamily 缓存。

    - 指定 factor_name + page_uuid：从该页面缓存中移除
    - 指定 factor_name 无 page_uuid：从所有页面缓存中移除
    - 不指定 factor_name：清空指定页面（或所有页面）的 families + factors
    """
    with _page_cache_lock:
        if factor_name:
            if page_uuid:
                ff_dict = page_families.get(page_uuid, {})
                ff_dict.pop(factor_name, None)
            else:
                for ff_dict in page_families.values():
                    ff_dict.pop(factor_name, None)
        else:
            if page_uuid:
                page_families.pop(page_uuid, None)
                page_factors.pop(page_uuid, None)
            else:
                page_families.clear()
                page_factors.clear()


def _load_chinese_names_from_sqlite() -> dict[str, str]:
    """从 SQLite factor_family_catalog 表加载所有公共因子的中文名。
    
    不实例化 FactorFamily，纯 SQL 读取，快且懒加载友好。
    """
    result: dict[str, str] = {}
    db_path = str(Settings.CACHE_DB_PATH)
    if not os.path.isfile(db_path):
        return result
    try:
        with connect_sqlite(db_path) as conn:
            rows = conn.execute(
                "SELECT factor_id, chinese_name FROM factor_family_catalog "
                "WHERE source_kind='public' AND load_error=0"
            ).fetchall()
        for row in rows:
            name = row["factor_id"] or ""
            cn = row["chinese_name"] or ""
            if name:
                result[name] = cn
    except Exception:
        pass
    return result


def get_chinese_names(factors_dir=None) -> dict[str, str]:
    """返回所有公共因子的 {模块名: 中文名} 映射。从 SQLite 懒加载。"""
    global _chinese_names_cache_loaded, _chinese_names_cache
    if not _chinese_names_cache_loaded:
        _chinese_names_cache = _load_chinese_names_from_sqlite()
        _chinese_names_cache_loaded = True
    return _chinese_names_cache


def factor_group_key(name: str) -> str:
    group = ""
    upper_count = 0
    for char in name:
        if char.isupper():
            upper_count += 1
            if upper_count == 1:
                group += char
            elif upper_count == 2:
                break
        elif upper_count == 1:
            group += char
    return group if group else name


def get_factor_groups():
    """Return public factor IDs grouped from the source registry."""
    from tools.data.sqlite.factor_source_store import list_factor_sources

    factor_names = [
        str(row.get("factor_id") or "")
        for row in list_factor_sources("public")
        if str(row.get("factor_id") or "")
    ]

    groups = {}
    for name in factor_names:
        group = factor_group_key(name)
        groups.setdefault(group, []).append(name)
    return groups, factor_names


# ── Page 级 Factor 缓存操作 ──

def get_page_factor(page_uuid: str, factor_alias: str) -> 'Factor | None':
    """从 page 级缓存获取 Factor。"""
    with _page_cache_lock:
        pf = page_factors.get(page_uuid, {})
        return pf.get(factor_alias)


def set_page_factor(page_uuid: str, factor_alias: str, factor: 'Factor') -> None:
    """将 Factor 写入 page 级缓存。"""
    with _page_cache_lock:
        page_factors.setdefault(page_uuid, {})[factor_alias] = factor


def remove_page_factor(page_uuid: str, factor_alias: str) -> 'Factor | None':
    """从 page 级缓存移除并清理 Factor（释放中间数据 + 强引用）。"""
    factor = None
    with _page_cache_lock:
        pf = page_factors.get(page_uuid, {})
        factor = pf.pop(factor_alias, None)
    if factor is not None:
        try:
            factor.clear()
            factor.delete()
        except Exception:
            pass
    return factor


def _single_factor_debug_items(page_uuid: str) -> list[dict[str, object]]:
    with _page_cache_lock:
        family_aliases = list(page_families.get(page_uuid, {}))
        factor_aliases = list(page_factors.get(page_uuid, {}))
    return [
        {'label': 'page_uuid', 'value': page_uuid},
        {'label': 'factor_family_count', 'value': len(family_aliases)},
        {'label': 'factor_family_aliases', 'value': family_aliases},
        {'label': 'factor_count', 'value': len(factor_aliases)},
        {'label': 'factor_aliases', 'value': factor_aliases},
    ]


from server.services.page_state_debug import register_page_debug_section

register_page_debug_section(
    'single_factor_test',
    'factor_registry',
    '单因子测试对象',
    _single_factor_debug_items,
)
