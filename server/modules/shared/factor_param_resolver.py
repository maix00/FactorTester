"""Resolve serialized FactorParam selections from the visible factor library."""

from __future__ import annotations
import threading
from contextlib import contextmanager
from typing import cast

from server.modules.custom_factors.factor_library_service import build_factor_library_overview
from server.modules.custom_factors.catalog import _load_factor_family_from_source
from server.modules.shared.factor_param_utils import (
    frozen_factor_record,
    hydrate_frozen_factor_params,
    normalize_factor_param_row,
    unique_frozen_factor_records,
)
from server.services.factor_source_catalog import FactorSourceCatalog
from server.services.factor_registry import get_factor_family_instance
from server.services.session_runtime import current_user
from tools.factors.factor_param_resolution import register_factor_param_resolver
from tools.factors.factor_param_resolution import factor_param_resolver_scope
from tools.factors.formula_identity import require_frozen_factor


def resolve_factor_param_value(
    value, *, username: str | None = None,
    frozen_by_ref: dict[str, dict] | None = None,
    _resolving_refs: set[str] | None = None,
):
    """Return a Factor for a FactorParam value selected in the UI."""
    if isinstance(value, dict):
        if value.get('schema_version') == 2 and value.get('identity'):
            return _resolve_frozen_factor(
                value, username=username, frozen_by_ref=frozen_by_ref,
                resolving_refs=_resolving_refs,
            )
        item = value
    else:
        alias = str(value or '').strip()
        if not alias:
            raise ValueError('FactorParam 为空')
        if alias.startswith('factor:v2:'):
            frozen = (frozen_by_ref or {}).get(alias)
            if frozen is None:
                raise ValueError(f'FactorParam 引用未在 RunSpec 中冻结: {alias}')
            return _resolve_frozen_factor(
                frozen, username=username, frozen_by_ref=frozen_by_ref,
                resolving_refs=_resolving_refs,
            )
        # FactorParam._value_space.alias() 对 dict 用 [...] 包裹；
        # 前端回传的是 display 值，需要去掉方括号再匹配 factor_alias。
        if alias.startswith('[') and alias.endswith(']'):
            alias = alias[1:-1]
        item = _find_visible_factor(alias, username=username)

    family_alias = item.get('factor_family_alias') or item.get('factor_family_name')
    if not family_alias:
        raise ValueError('缺少因子家族')

    owner_username = item.get('owner_username') or username or current_user()
    ff = get_factor_family_instance(family_alias, username=owner_username)
    params = _params_list_to_dict(item.get('params') or [])
    normalized = normalize_factor_param_row(ff, params)
    return ff.get_factor(params_list=[normalized])


def _resolve_frozen_factor(
    value: dict, *, username: str | None = None,
    frozen_by_ref: dict[str, dict] | None = None,
    resolving_refs: set[str] | None = None,
):
    """Rebuild a nested factor from its exact recorded family source."""
    frozen = require_frozen_factor(value)
    factor_ref = frozen['ref']
    active_refs = resolving_refs if resolving_refs is not None else set()
    if factor_ref in active_refs:
        raise ValueError(f'FactorParam 依赖形成循环: {factor_ref}')
    with _resolving_factor(active_refs, factor_ref):
        dependencies = dict(frozen_by_ref or {})
        for dependency in value.get('factor_dependencies') or []:
            dependency = frozen_factor_record(dependency)
            if dependency is None:
                raise ValueError('FactorParam 依赖记录不是有效的冻结因子')
            # The outer record may carry only canonical identity for a child,
            # while the RunSpec index carries its complete provenance/source.
            # Compare and merge through the canonical DAG helper instead of
            # comparing those two transport shapes as raw dictionaries.
            merged_records = unique_frozen_factor_records([dependency])
            existing = dependencies.get(dependency['ref'])
            if existing is not None:
                merged_records = unique_frozen_factor_records([
                    existing, dependency,
                ])
            for merged in merged_records:
                dependencies[merged['ref']] = merged
        identity = frozen['identity']
        principal = str(username or current_user() or '').strip()
        owner_ref = str(frozen['owner_ref'] or '').strip()
        is_public = owner_ref in {'public', '__public_jobs__'}
        owner_username = owner_ref.removeprefix('principal:')
        source_kind = 'public' if is_public else 'custom'
        family_alias = str(identity['family_alias'])
        fingerprint = str(identity['family_formula_fingerprint'])
        embedded_source = str(value.get('source_code') or '').strip()
        has_inline_source = str(value.get('source_kind') or '') == 'transient'
        if has_inline_source:
            if not embedded_source:
                raise ValueError(f'当场创建的嵌套因子缺少冻结源码: {family_alias}')
            source = {'source_code': embedded_source}
        else:
            catalog = FactorSourceCatalog()
            current = catalog.version(
                principal, source_kind, family_alias, 'current',
                owner_username='' if is_public else owner_username,
            )
            source = current
            if str(current.get('family_formula_fingerprint') or '') != fingerprint:
                source = catalog.version(
                    principal, source_kind, family_alias, fingerprint,
                    owner_username='' if is_public else owner_username,
                )
        factor_cls, _ = _load_factor_family_from_source(
            str(source.get('source_code') or ''), family_alias,
        )
        if factor_cls is None:
            raise ValueError(f'因子家族源码无法加载: {family_alias}')
        family = factor_cls()
        if family.expr.semantic_fingerprint() != fingerprint:
            raise ValueError(f'因子家族源码指纹不匹配: {family_alias}')
        # Keep FactorParam refs as complete frozen records while generating the
        # alias.  Passing the opaque ref string straight into get_factor makes
        # FactorParam.alias() render ``factor:v2:...`` instead of the nested
        # factor alias, even though the expression resolver can still execute
        # it.  Hydrating only these transport refs preserves the one resolver
        # path and keeps identity.params unchanged on storage.
        identity_params = hydrate_frozen_factor_params(
            identity.get('params'), dependencies,
        )
        normalized = normalize_factor_param_row(family, identity_params)
        with factor_param_resolver_scope(lambda nested: resolve_factor_param_value(
            nested, username=principal, frozen_by_ref=dependencies,
            _resolving_refs=active_refs,
        )):
            factor = family.get_factor(**normalized)
        expression = getattr(factor, '_source_expr', None) or factor.expr
        if str(factor.alias) != frozen['alias']:
            raise ValueError(f'因子 alias 与冻结记录不匹配: {frozen["alias"]}')
        if expression.semantic_fingerprint() != identity['self_formula_fingerprint']:
            raise ValueError(f'因子公式指纹不匹配: {frozen["alias"]}')
        return factor


@contextmanager
def _resolving_factor(active_refs: set[str], factor_ref: str):
    active_refs.add(factor_ref)
    try:
        yield
    finally:
        active_refs.remove(factor_ref)


# 构建整库总览时会解析家族参数，而解析参数又会去找可见因子；不打断就会互相递归
# （总览 → 解析 → 总览 …），且每层都重跑 SQLite 的 _ensure_schema 与全量装载，于是
# 请求永不返回、一直抱着用户写锁。线程本地标记让「已在构建总览」期间的查找走窄路径。
_overview_build = threading.local()


def _visible_library_overview(username: str) -> dict:
    """Return the caller's library overview, built at most once per request.

    Resolving one nested chain asks for many aliases, and every lookup used to
    rebuild the whole overview (families plus factors for the user and their
    subordinates).  On a populated library that is quadratic in chain length and
    enough to push a simple registration past its timeout while it holds the
    user's write lock.  Caching per request keeps one build, and staying inside
    the request scope means a later write can never see a stale overview.
    """
    from flask import g, has_request_context

    if not has_request_context():
        return build_factor_library_overview(username, include_subordinates=True)
    cache = getattr(g, "_factor_library_overview_cache", None)
    if not isinstance(cache, dict):
        cache = {}
        g._factor_library_overview_cache = cache
    if username not in cache:
        cache[username] = build_factor_library_overview(username, include_subordinates=True)
    return cache[username]


def _find_visible_factor(alias: str, *, username: str | None = None) -> dict:
    import re
    resolved_username = username or cast(str, current_user())
    if getattr(_overview_build, "active", False):
        # 已在构建总览：不得再触发总览，否则递归无限展开且放大成永不返回。
        payload = {"factors": [], "families": []}
    else:
        _overview_build.active = True
        try:
            payload = _visible_library_overview(resolved_username)
        finally:
            _overview_build.active = False
    
    def _normalize(a: str) -> str:
        """去掉 $F:xxx 后做匹配，因为 FactorParam 的子因子无独立 SignalAlign。"""
        return re.sub(r'\|?\$F:[^|]+', '', a).strip()
    
    normalized_alias = _normalize(alias)
    matches = [item for item in payload.get('factors', [])
               if _normalize(item.get('factor_alias') or '') == normalized_alias]
    if not matches:
        # 兼容：直接前缀匹配（去掉 $F 后 lookup_alias 是 factor_alias 的前缀）
        matches = [item for item in payload.get('factors', [])
                   if _normalize(item.get('factor_alias') or '').startswith(normalized_alias)]
    if not matches:
        family_alias = alias.split('|', 1)[0]
        families = [item for item in payload.get('families', []) if str(
            item.get('factor_family_alias') or item.get('family_alias')
            or item.get('name') or item.get('id') or ''
        ) == family_alias]
        if len(families) == 1:
            family = families[0]
            owner = str(
                family.get('owner_username') or resolved_username,
            ).strip()
            family_ref = (
                f'public:{family_alias}'
                if family.get('factor_kind') == 'public'
                or family.get('source') == 'public'
                else f'{owner}:{family_alias}'
            )
            instance = get_factor_family_instance(
                family_ref, username=resolved_username,
            )
            factor = instance.factor_from_alias(alias)
            return {
                'factor_alias': str(factor.alias),
                'factor_family_alias': family_alias,
                'owner_username': owner,
                'params': [
                    {'alias': key, 'value': value}
                    for key, value in instance.parse_alias(alias).items()
                ],
            }
        raise ValueError(f'因子库中找不到且无法唯一解析因子: {alias}')
    return matches[0]


def register_factor_param_resolver_for_user(
    username: str, frozen_factors: list[dict] | None = None,
) -> None:
    """Bind FactorParam resolution to a frozen job owner in worker processes."""
    owner = str(username or '').strip()
    if not owner:
        raise ValueError('FactorParam worker resolver requires an owner')
    frozen_by_ref = {}
    for value in unique_frozen_factor_records(frozen_factors or []):
        frozen_by_ref[value['ref']] = value
    register_factor_param_resolver(lambda value: resolve_factor_param_value(
        value, username=owner, frozen_by_ref=frozen_by_ref,
    ))


def _params_list_to_dict(params: list) -> dict:
    row = {}
    for item in params:
        if isinstance(item, dict) and item.get('alias'):
            row[item['alias']] = item.get('value', '')
    return row


# Register the server adapter at import time. Core factor code now depends only on
# the engine seam, while the Flask layer decides how serialized UI values resolve.
register_factor_param_resolver(resolve_factor_param_value)
