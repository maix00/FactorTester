"""Shared helpers for FactorFamily parameter rows.

Routes still own their storage semantics: single-factor tests store rows in the
session, while the factor library stores one user-scoped config per family.
"""

from __future__ import annotations

import re

from tools.cli.release.research_reporting.references.factor_formula import (
    build_factor_reference,
)
from tools.factors.formula_identity import freeze_factor_identity
from tools.factors.formula_identity import require_frozen_factor
from tools.parameters import FactorParam, TypeParam
from server.modules.shared.factor_preview_latex import RESOLVED_MATH_EXPR_VERSION


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
        # Every FactorParam accepts a numeric ConstExpr, including parameters
        # whose default is None or a factor/data-column reference. Keep
        # non-numeric strings deferred so aliases still resolve normally.
        stripped = value.strip()
        if re.fullmatch(r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?', stripped):
            try:
                return float(stripped) if any(mark in stripped.lower() for mark in ('.', 'e')) else int(stripped)
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


def freeze_factor_param_alias(param, value) -> dict | None:
    """FactorParam 槽位填的是**因子别名**时，由代码解析并冻结成规范记录。

    平台的既有形态是 ``factor:v2:`` ref（唯一标识）。调用方（API / CLI / 前端）应当只给出
    别名，ref 必须由代码派生 —— 不能要求调用方手写，否则会像手工拼接那样写出别名形态的行，
    使冻结侧与校验侧对同一行算出不同的 self_formula_fingerprint。

    取名与做法都对齐平台既有的一环：``editor_routes._freeze_validated_factor``
    （解析 → 冻结 → 返回规范记录）。

    只处理「确实指向一个因子」的取值：别名带 ``|`` 参数段；列引用与常值（例如 ``'2m'``、
    ``'CA'``）不参与解析，按原样存储。
    """
    if not isinstance(param, FactorParam) or not isinstance(value, str):
        return None
    text = value.strip()
    if not text or text.startswith('factor:v2:') or '|' not in text:
        return None
    try:
        from tools.factors.factor_param_resolution import resolve_factor_param_value

        resolved = resolve_factor_param_value(text)
    except Exception:
        # 解析不了就不是因子别名（列/常值等），保持原样。
        return None
    return frozen_factor_record(resolved)


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
                # Keep a frozen Factor record as transport data.  Rectifying
                # it through FactorParam would turn it into a FactorExpr and
                # lose the dependency identity before the caller serializes
                # the row.
                frozen = (
                    frozen_factor_record(normalized[p.alias])
                    if isinstance(p, FactorParam) else None
                )
                if frozen is None:
                    # 调用方给的是别名：这里解析并冻结成规范记录（ref 由代码派生）。
                    frozen = freeze_factor_param_alias(p, normalized[p.alias])
                v = frozen if frozen is not None else p._value_space.rectify(
                    normalized[p.alias]
                )
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
    if isinstance(param, FactorParam):
        frozen = frozen_factor_record(value)
        if frozen is not None:
            return frozen['ref']
        from tools.factors.FactorExpr import ConstExpr
        if isinstance(value, ConstExpr):
            return value.value
        # A runtime Factor resolved from a frozen record keeps its immutable
        # identity on the object.  Accept it here too so callers that already
        # resolved a value do not silently fall back to a mutable alias.
        factor_ref = str(getattr(value, 'factor_ref', '') or '').strip()
        if factor_ref.startswith('factor:v2:'):
            return factor_ref
    return factor_param_value_display(param, value)


def frozen_factor_dependency_record(value: dict) -> dict:
    """Keep canonical identity plus the source required by inline factors."""
    frozen = require_frozen_factor(value)
    source_kind = str(value.get('source_kind') or '').strip()
    is_configuration_local = value.get('temporary') is True or str(
        value.get('source_origin') or '',
    ) == 'test_inline'
    if not is_configuration_local:
        return frozen
    record = {
        **frozen,
        'temporary': True,
        'source_kind': source_kind or 'factor_library',
        'source_origin': 'test_inline',
        **({
            'transient_factor_id': str(value.get('transient_factor_id')),
        } if value.get('transient_factor_id') else {}),
    }
    if source_kind == 'transient':
        source_code = str(value.get('source_code') or '').strip()
        if not source_code:
            raise ValueError(f'当场源码嵌套因子缺少冻结源码: {frozen["alias"]}')
        record['source_code'] = source_code
    return record


def frozen_factor_record(value) -> dict | None:
    """Return a canonical frozen record while retaining its child links.

    UI transport values are dictionaries, while the engine may hand a caller
    a ``Factor`` object carrying ``frozen_identity``.  Both forms represent
    the same dependency node and must feed the same persistence path.
    """
    if isinstance(value, dict):
        raw = value
    else:
        identity = getattr(value, 'frozen_identity', None)
        if not isinstance(identity, dict):
            return None
        raw = {
            **identity,
            **{
                key: getattr(value, key)
                for key in (
                    'temporary', 'source_kind', 'source_origin',
                    'transient_factor_id', 'source_code',
                    'factor_dependencies',
                )
                if getattr(value, key, None) not in (None, '', [])
            },
        }
    if raw.get('schema_version') != 2 or not raw.get('identity'):
        return None
    record = frozen_factor_dependency_record(raw)
    dependencies = raw.get('factor_dependencies')
    if isinstance(dependencies, list) and dependencies:
        record['factor_dependencies'] = [
            dependency for dependency in dependencies
            if isinstance(dependency, dict)
        ]
    return record


def unique_frozen_factor_records(values) -> list[dict]:
    """Canonicalize factors without discarding configuration-local evidence.

    ``require_frozen_factor`` intentionally returns only the immutable v2
    identity.  That is correct for references, but a RunSpec also needs the
    source and flattened dependency graph of factors created inside the test
    configuration.  This helper keeps only those explicitly supported fields,
    recursively flattens dependencies, and rejects conflicting duplicates.
    """
    if values is None:
        return []
    if not isinstance(values, (list, tuple)):
        raise ValueError('frozen factors must be a list')

    ordered: list[dict] = []
    positions: dict[str, int] = {}
    visiting: set[str] = set()

    def add(raw: dict) -> dict:
        if not isinstance(raw, dict):
            raise ValueError('frozen factor must be an object')
        record = frozen_factor_dependency_record(raw)
        factor_ref = record['ref']
        if factor_ref in visiting:
            raise ValueError(f'FactorParam 依赖形成循环: {factor_ref}')
        visiting.add(factor_ref)
        dependencies: list[dict] = []
        dependency_refs: set[str] = set()
        for dependency in raw.get('factor_dependencies') or []:
            normalized = add(dependency)
            if normalized['ref'] not in dependency_refs:
                dependency_refs.add(normalized['ref'])
                dependencies.append({
                    key: value for key, value in normalized.items()
                    if key != 'factor_dependencies'
                })
        visiting.remove(factor_ref)
        if dependencies:
            record['factor_dependencies'] = dependencies

        index = positions.get(factor_ref)
        if index is None:
            positions[factor_ref] = len(ordered)
            ordered.append(record)
            return record
        merged = _merge_frozen_factor_records(ordered[index], record)
        ordered[index] = merged
        return merged

    for value in values:
        add(value)
    return ordered


def frozen_factor_records_from_values(values) -> list[dict]:
    """Collect and flatten every frozen Factor node found in parameter data."""
    records = []

    def visit(value) -> None:
        record = frozen_factor_record(value)
        if record is not None:
            records.append(record)
            for dependency in record.get('factor_dependencies') or []:
                visit(dependency)
            return
        if isinstance(value, dict):
            for child in value.values():
                visit(child)
        elif isinstance(value, (list, tuple)):
            for child in value:
                visit(child)

    visit(values)
    return unique_frozen_factor_records(records)


def hydrate_frozen_factor_params(
    values: dict | None, frozen_by_ref: dict[str, dict] | None,
) -> dict:
    """Replace opaque FactorParam refs with their complete frozen records.

    FactorFamily uses the value's alias while constructing a Factor alias, so
    an opaque ``factor:v2`` string would be rendered literally.  Hydration is
    only a temporary calculation input; persistence continues to store the
    opaque ref in ``identity.params``.
    """
    result = dict(values or {})
    for key, value in list(result.items()):
        if isinstance(value, str) and value.startswith('factor:v2:'):
            result[key] = (frozen_by_ref or {}).get(value, value)
    return result


def _merge_frozen_factor_records(left: dict, right: dict) -> dict:
    if require_frozen_factor(left) != require_frozen_factor(right):
        raise ValueError(
            'different frozen records share factor ref: '
            f'{left.get("ref") or right.get("ref")}',
        )
    result = dict(require_frozen_factor(left))
    for key in (
        'temporary', 'source_kind', 'source_origin',
        'transient_factor_id', 'source_code',
    ):
        left_value = left.get(key)
        right_value = right.get(key)
        if left_value not in (None, '') and right_value not in (None, '') \
                and left_value != right_value:
            raise ValueError(f'因子冻结来源冲突: {result["ref"]} ({key})')
        value = right_value if right_value not in (None, '') else left_value
        if value not in (None, ''):
            result[key] = value
    dependencies = unique_frozen_factor_records([
        *(left.get('factor_dependencies') or []),
        *(right.get('factor_dependencies') or []),
    ])
    if dependencies:
        result['factor_dependencies'] = [
            {key: value for key, value in item.items()
             if key != 'factor_dependencies'}
            for item in dependencies
        ]
    return result


def frozen_factor_dependencies(parameters, values: dict) -> list[dict]:
    """Flatten complete FactorParam records in stable parameter order."""
    records = []
    for param in parameters:
        value = values.get(param.alias)
        if not isinstance(param, FactorParam):
            continue
        record = frozen_factor_record(value)
        if record is not None:
            records.append(record)
    return unique_frozen_factor_records(records)


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
    dependency_records = frozen_factor_dependencies(
        factor_family.params, normalized_row,
    ) or list(metadata.get('factor_dependencies') or [])
    from server.modules.shared.factor_instance_metadata import (
        build_factor_instance_metadata,
    )
    instance_metadata = build_factor_instance_metadata(
        factor_family, factor, normalized_row,
        factor_dependencies=dependency_records,
        username=current_username,
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
        # math_expr = 因子家族的_LATEX模板_（自包含，参数以 \textcolor{red}{alias} 占位，
        # 尚未做参数替换/嵌套叠加）。TOKEN preview 用它当起点。
        # resolved_math_expr = 参数解析+嵌套因子叠加后的完整公式（前端查看模式渲染）。
        # 注意：math_expr 是"模板/输入"，resolved_math_expr 是"最终/输出"，勿混用。
        'math_expr': meta.get('math_expr')
        or getattr(factor_family, 'math_expr', '') or '',
        'resolved_math_expr': instance_metadata['resolved_math_expr'],
        'resolved_math_expr_version': RESOLVED_MATH_EXPR_VERSION,
        'category': row_category or family_category,
        'source': source,
        'source_label': '公共因子' if source == 'public' else ('自定义因子' if source == 'custom' else '未知来源'),
        'template_id': config.get('id') or '',
        'template_name': config.get('name') or '未命名配置',
        'template_row_index': row_idx,
        'params': params_display,
        'factor_params': params_display,
        'parameter_definitions': instance_metadata['parameter_definitions'],
        'factor_dependencies': dependency_records,
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
