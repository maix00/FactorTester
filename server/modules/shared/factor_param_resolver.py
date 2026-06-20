"""Resolve serialized FactorParam selections from the visible factor library."""

from __future__ import annotations
from typing import cast

from server.modules.custom_factors.param_config_service import build_param_factor_overview
from server.modules.shared.param_config import normalize_param_row
from server.services.factor_registry import get_factor_family_instance
from server.services.session_runtime import current_user
from tools.factors.factor_param_resolution import register_factor_param_resolver


def resolve_factor_param_value(value):
    """Return a Factor for a FactorParam value selected in the UI."""
    if isinstance(value, dict):
        item = value
    else:
        alias = str(value or '').strip()
        if not alias:
            raise ValueError('FactorParam 为空')
        # FactorParam._value_space.alias() 对 dict 用 [...] 包裹；
        # 前端回传的是 display 值，需要去掉方括号再匹配 factor_alias。
        if alias.startswith('[') and alias.endswith(']'):
            alias = alias[1:-1]
        item = _find_visible_factor(alias)

    family_alias = item.get('factor_family_alias') or item.get('factor_family_name')
    if not family_alias:
        raise ValueError('缺少因子家族')

    owner_username = item.get('owner_username') or current_user()
    ff = get_factor_family_instance(family_alias, username=owner_username)
    params = _params_list_to_dict(item.get('params') or [])
    normalized = normalize_param_row(ff, params)
    return ff.get_factor(params_list=[normalized])


def _find_visible_factor(alias: str) -> dict:
    import re
    username = cast(str, current_user())
    payload = build_param_factor_overview(username, include_subordinates=True)
    
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
        raise ValueError(f'因子库中找不到因子: {alias}')
    return matches[0]


def _params_list_to_dict(params: list) -> dict:
    row = {}
    for item in params:
        if isinstance(item, dict) and item.get('alias'):
            row[item['alias']] = item.get('value', '')
    return row


# Register the server adapter at import time. Core factor code now depends only on
# the engine seam, while the Flask layer decides how serialized UI values resolve.
register_factor_param_resolver(resolve_factor_param_value)
