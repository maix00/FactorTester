"""Resolve serialized FactorParam selections from the visible factor library."""

from __future__ import annotations
from typing import cast

from server.modules.custom_factors.factor_library_service import build_factor_library_overview
from server.modules.custom_factors.catalog import _load_factor_family_from_source
from server.modules.shared.factor_param_utils import normalize_factor_param_row
from server.services.factor_source_catalog import FactorSourceCatalog
from server.services.factor_registry import get_factor_family_instance
from server.services.session_runtime import current_user
from tools.factors.factor_param_resolution import register_factor_param_resolver
from tools.factors.formula_identity import require_frozen_factor


def resolve_factor_param_value(
    value, *, username: str | None = None,
    frozen_by_ref: dict[str, dict] | None = None,
):
    """Return a Factor for a FactorParam value selected in the UI."""
    if isinstance(value, dict):
        if value.get('schema_version') == 2 and value.get('identity'):
            return _resolve_frozen_factor(value, username=username)
        item = value
    else:
        alias = str(value or '').strip()
        if not alias:
            raise ValueError('FactorParam 为空')
        if alias.startswith('factor:v2:'):
            frozen = (frozen_by_ref or {}).get(alias)
            if frozen is None:
                raise ValueError(f'FactorParam 引用未在 RunSpec 中冻结: {alias}')
            return _resolve_frozen_factor(frozen, username=username)
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


def _resolve_frozen_factor(value: dict, *, username: str | None = None):
    """Rebuild a nested factor from its exact recorded family source."""
    frozen = require_frozen_factor(value)
    identity = frozen['identity']
    principal = str(username or current_user() or '').strip()
    owner_ref = str(frozen['owner_ref'] or '').strip()
    is_public = owner_ref in {'public', '__public_jobs__'}
    owner_username = owner_ref.removeprefix('principal:')
    source_kind = 'public' if is_public else 'custom'
    family_alias = str(identity['family_alias'])
    fingerprint = str(identity['family_formula_fingerprint'])
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
    normalized = normalize_factor_param_row(family, identity.get('params') or {})
    factor = family.get_factor(**normalized)
    expression = getattr(factor, '_source_expr', None) or factor.expr
    if str(factor.alias) != frozen['alias']:
        raise ValueError(f'因子 alias 与冻结记录不匹配: {frozen["alias"]}')
    if expression.semantic_fingerprint() != identity['self_formula_fingerprint']:
        raise ValueError(f'因子公式指纹不匹配: {frozen["alias"]}')
    return factor


def _find_visible_factor(alias: str, *, username: str | None = None) -> dict:
    import re
    resolved_username = username or cast(str, current_user())
    payload = build_factor_library_overview(resolved_username, include_subordinates=True)
    
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
    for value in frozen_factors or []:
        try:
            frozen = require_frozen_factor(value)
        except (TypeError, ValueError):
            continue
        frozen_by_ref[frozen['ref']] = frozen
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
