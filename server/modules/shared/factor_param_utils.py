"""Shared helpers for FactorFamily parameter rows.

Routes still own their storage semantics: single-factor tests store rows in the
session, while the factor library stores one user-scoped config per family.
"""

from __future__ import annotations

from tools.cli.release.research_reporting.references.factor_formula import (
    build_factor_reference,
)
from tools.factors.formula_identity import freeze_factor_identity
from tools.factors.formula_identity import require_frozen_factor
from tools.parameters import FactorParam, TypeParam


def _coerce_transport_value(param, value):
    """Convert text controls for numeric TypeParam values before validation."""
    if not isinstance(param, TypeParam) or not isinstance(value, str):
        return value

    if isinstance(param, FactorParam):
        from tools.factors.FactorExpr import ConstExpr
        default = getattr(param, 'default_value', None)
        if isinstance(default, ConstExpr):
            try:
                if isinstance(default.value, bool):
                    normalized = value.strip().lower()
                    if normalized in {'true', '1'}:
                        return True
                    if normalized in {'false', '0'}:
                        return False
                    return value
                if isinstance(default.value, int):
                    return int(value.strip())
                if isinstance(default.value, float):
                    return float(value.strip())
            except ValueError:
                return value

    typ = getattr(param, '_typ', None)
    if typ is None:
        return value
    types = typ if isinstance(typ, tuple) else (typ,)
    default_type = type(getattr(param, 'default_value', None))
    try:
        if default_type is int and int in types:
            return int(value.strip())
        if float in types:
            return float(value.strip())
        if int in types:
            return int(value.strip())
    except ValueError:
        return value
    return value


def normalize_factor_param_rows(factor_family, params_list: list) -> list:
    normalized_rows = []
    for params in params_list:
        if not isinstance(params, dict):
            raise ValueError('参数行必须是对象')
        normalized = factor_family._normalize_param_kwargs(**params)
        normalized = {
            alias: _coerce_transport_value(factor_family.params_dict[alias], value)
            for alias, value in normalized.items()
        }
        factor_family._check_in_space(**normalized)
        row = {}
        for p in factor_family.params:
            if p.alias in normalized:
                v = p._value_space.rectify(normalized[p.alias])
            else:
                v = p.default_value
            row[p.alias] = v
        normalized_rows.append(row)
    return normalized_rows


def normalize_factor_param_row(factor_family, params: dict) -> dict:
    return normalize_factor_param_rows(factor_family, [params])[0]


def factor_param_value_display(param, value) -> str:
    if value is None:
        return ''
    try:
        return param._value_space.alias(value)
    except Exception:
        return str(value)


def factor_param_value_storage(param, value):
    """Store FactorParam dependencies by opaque v2 ref, never nested inline."""
    if isinstance(param, FactorParam) and isinstance(value, dict):
        return require_frozen_factor(value)['ref']
    if isinstance(param, FactorParam):
        from tools.factors.FactorExpr import ConstExpr
        if isinstance(value, ConstExpr):
            return value.value
    return factor_param_value_display(param, value)


def frozen_factor_dependencies(parameters, values: dict) -> list[dict]:
    """Flatten complete FactorParam records in stable parameter order."""
    result = []
    seen = set()
    for param in parameters:
        value = values.get(param.alias)
        if not isinstance(param, FactorParam) or not isinstance(value, dict):
            continue
        factor = require_frozen_factor(value)
        for dependency in value.get('factor_dependencies') or []:
            dependency = require_frozen_factor(dependency)
            if dependency['ref'] not in seen:
                seen.add(dependency['ref'])
                result.append(dependency)
        if factor['ref'] not in seen:
            seen.add(factor['ref'])
            result.append(factor)
    return result


def build_factor_rows(factor_family, params_list: list) -> list:
    """Build factor row payload for parameter table rendering."""
    factors = factor_family.get_factors(params_list=params_list)
    rows = []
    for idx, (factor, row) in enumerate(zip(factors, params_list)):
        display_params = {
            p.alias: factor_param_value_display(p, row.get(p.alias))
            for p in factor_family.params
        }
        rows.append({
            'index': idx,
            'factor_alias': factor.alias,
            'params': display_params,
        })
    return rows


def serialize_factor_param_rows(factor_family, params_list: list) -> list:
    """Normalize rows, then store JSON-safe value aliases."""
    normalized_rows = normalize_factor_param_rows(factor_family, params_list)
    rows = []
    seen_aliases = set()
    for idx, row in enumerate(normalized_rows):
        factor_alias = factor_family.get_alias(**row)
        if factor_alias in seen_aliases:
            continue
        seen_aliases.add(factor_alias)
        item = {
            p.alias: factor_param_value_storage(p, row.get(p.alias))
            for p in factor_family.params
        }
        # 保留条目级 category（如果原始 params_list 中提供）
        if idx < len(params_list) and isinstance(params_list[idx], dict):
            cat = (params_list[idx].get('category') or '').strip()
            if cat:
                item['category'] = cat
        rows.append(item)
    return rows


def build_factor_param_item(
    factor_family,
    params: dict,
    row_idx: int,
    owner_acct: dict,
    current_username: str,
    meta: dict | None = None,
    config: dict | None = None,
) -> dict:
    meta = meta or {}
    config = config or {}
    owner_username = owner_acct.get('username') or ''
    normalized_row = normalize_factor_param_row(factor_family, params)
    params_display = [
        {
            'alias': p.alias,
            'value': factor_param_value_display(p, normalized_row.get(p.alias)),
        }
        for p in factor_family.params
    ]
    source = meta.get('source') or 'unknown'
    family_alias = getattr(factor_family, 'alias', None) or meta.get('name') or ''
    factor = factor_family.get_factor(**normalized_row)
    expression = getattr(factor, '_source_expr', None) or factor.expr
    family_formula_fingerprint = factor_family.expr.semantic_fingerprint()
    self_formula_fingerprint = expression.semantic_fingerprint()
    metadata = (
        config.get('metadata')
        if isinstance(config.get('metadata'), dict) else {}
    )
    owner_ref = str(
        metadata.get('factor_owner_ref')
        or ('public' if source == 'public' else owner_username)
    ).strip()
    factor_ref = build_factor_reference(
        owner_ref=owner_ref,
        family_alias=family_alias,
        factor_alias=str(factor.alias),
        family_formula_fingerprint=family_formula_fingerprint,
        self_formula_fingerprint=self_formula_fingerprint,
    )
    frozen = freeze_factor_identity(
        owner_ref=owner_ref,
        family_alias=family_alias,
        factor_alias=str(factor.alias),
        family_formula_fingerprint=family_formula_fingerprint,
        self_formula_fingerprint=self_formula_fingerprint,
        params={
            p.alias: factor_param_value_storage(
                p, normalized_row.get(p.alias),
            )
            for p in factor_family.params
        },
    )
    # 条目级 category 优先于因子家族 meta category
    row_category = params.get('category', '') if isinstance(params, dict) else ''
    family_category = meta.get('category') or ''
    return {
        **frozen,
        'id': f"{owner_username}:{getattr(factor_family, 'alias', '')}:{config.get('id')}:{row_idx}",
        'factor_ref': factor_ref,
        'factor_alias': str(factor.alias),
        'factor_family_alias': family_alias,
        'factor_family_id': meta.get('id') or getattr(factor_family, 'alias', ''),
        'factor_family_name': meta.get('name') or getattr(factor_family, 'alias', ''),
        'chinese_name': meta.get('chinese_name') or '',
        'description': meta.get('description')
        or getattr(factor_family, 'description', '') or '',
        'math_expr': meta.get('math_expr')
        or getattr(factor_family, 'math_expr', '') or '',
        'category': row_category or family_category,
        'source': source,
        'source_label': '公共因子' if source == 'public' else ('自定义因子' if source == 'custom' else '未知来源'),
        'template_id': config.get('id') or '',
        'template_name': config.get('name') or '未命名配置',
        'template_row_index': row_idx,
        'params': params_display,
        'factor_params': params_display,
        'factor_dependencies': frozen_factor_dependencies(
            factor_family.params, normalized_row,
        ) or list(metadata.get('factor_dependencies') or []),
        'params_count': len(params_display),
        'owner_username': owner_username,
        'owner_alias': owner_acct.get('alias') or owner_username,
        'owner_organization_id': owner_acct.get('organization_id') or '',
        'owner_organization_name': owner_acct.get('organization_name') or '',
        'can_edit': owner_username == current_username,
        'updated_at': config.get('updated_at') or '',
        'metadata': metadata,
        'note': metadata.get('note') or '',
        'research_report': metadata.get('research_report') or '',
        'factor_owner_ref': owner_ref,
        'family_formula_fingerprint': family_formula_fingerprint,
        'self_formula_fingerprint': self_formula_fingerprint,
    }
