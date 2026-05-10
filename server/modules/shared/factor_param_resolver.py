"""Resolve serialized FactorParam selections from the visible factor library."""

from __future__ import annotations

from server.modules.custom_factors.param_config_service import build_param_factor_overview
from server.modules.shared.param_config import normalize_param_row
from server.services.factor_registry import get_factor_family_instance
from server.services.runtime_state import current_user


def resolve_factor_param_value(value):
    """Return a Factor for a FactorParam value selected in the UI."""
    if isinstance(value, dict):
        item = value
    else:
        alias = str(value or '').strip()
        if not alias:
            raise ValueError('FactorParam 为空')
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
    payload = build_param_factor_overview(current_user(), include_subordinates=True)
    matches = [item for item in payload.get('factors', []) if item.get('factor_alias') == alias]
    if not matches:
        raise ValueError(f'因子库中找不到因子: {alias}')
    return matches[0]


def _params_list_to_dict(params: list) -> dict:
    row = {}
    for item in params:
        if isinstance(item, dict) and item.get('alias'):
            row[item['alias']] = item.get('value', '')
    return row
