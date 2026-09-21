"""Business helpers for factor-library user-scoped parameter configs."""

from __future__ import annotations

import time
from typing import cast

from server.modules.custom_factors.catalog import (
    list_custom_factors,
    list_public_factors,
)
from server.modules.custom_factors.factor_library_store import (
    DEFAULT_SCOPE_KEY,
    delete_factor_param_config,
    list_factor_param_config_aliases,
    list_factor_param_config_scopes,
    load_factor_param_config,
    normalize_product_group,
    save_factor_param_config,
)
from server.modules.products.product_group_store import load_product_groups
from server.modules.shared.factor_param_utils import (
    build_factor_param_item,
    factor_param_value_storage,
    frozen_factor_records_from_values,
    hydrate_frozen_factor_params,
    normalize_factor_param_row,
    sanitize_factor_record_dependencies,
    serialize_factor_param_rows,
    unique_frozen_factor_records,
)
from server.services.factor_registry import (
    factor_group_key,
    get_custom_factor_instance,
    get_factor_family_instance,
)
from tools.data.account_manage import (
    account_display_name,
    direct_subordinate_accounts_for,
    get_account,
)
from tools.factors.factor_param_resolution import factor_param_resolver_scope
from tools.factors.formula_identity import freeze_factor_identity
from tools.parameters import FactorParam


def _freeze_alias_factor_param_rows(username, factor_family, params_list: list) -> list:
    """把 FactorParam 槽位里的**因子别名**解析并冻结成规范记录（ref 由代码派生）。

    与 ``editor_routes._freeze_validated_factor`` 是同一环：解析 → 归一化 →
    ``freeze_factor_identity``。必须在配置自身冻结映射的作用域**之外**执行：别名解析要查
    可见因子库，靠的是平台默认解析器；一旦被「只认本配置 ref」的映射覆盖，别名就解析不到
    （本项目曾因此把别名按原样落库，使冻结侧与校验侧对同一行算出不同的 self_fingerprint）。

    只处理「确实指向一个因子」的取值：别名带 ``|`` 参数段；DataColumn 与常值按原样保留。
    """
    declared = getattr(factor_family, 'params', None)
    if declared is None:
        # 非家族对象（占位/桩）：没有任何 FactorParam 槽位可冻结。
        # 别名冻结的不变量仍由序列化路径（normalize_factor_param_rows →
        # freeze_factor_param_alias）强制，这里只是提前做，以便解析器作用域生效。
        return params_list
    factor_params = [p for p in declared if isinstance(p, FactorParam)]
    if not factor_params:
        return params_list
    # 延迟导入：factor_param_resolver 在模块层反向依赖本模块，顶部导入会成环。
    from server.modules.shared.factor_param_resolver import (
        _find_visible_factor,
        _params_list_to_dict,
    )
    frozen_rows = []
    for row in params_list:
        if not isinstance(row, dict):
            frozen_rows.append(row)
            continue
        frozen_row = dict(row)
        for param in factor_params:
            value = frozen_row.get(param.alias)
            if not isinstance(value, str):
                continue
            text = value.strip()
            if not text or text.startswith('factor:v2:') or '|' not in text:
                continue
            item = _find_visible_factor(text, username=username)
            family_alias = item.get('factor_family_alias') or item.get('factor_family_name')
            if not family_alias:
                raise ValueError(f'因子别名缺少家族信息: {text}')
            owner = item.get('owner_username') or username
            nested_family = get_factor_family_instance(family_alias, username=owner)
            factor = nested_family.factor_from_alias(str(item.get('factor_alias') or text))
            normalized = normalize_factor_param_row(
                nested_family, _params_list_to_dict(item.get('params') or []),
            )
            expression = getattr(factor, '_source_expr', None) or factor.expr
            frozen_row[param.alias] = freeze_factor_identity(
                owner_ref=str(item.get('owner_ref') or '').strip(),
                family_alias=str(family_alias).strip(),
                factor_alias=str(factor.alias),
                family_formula_fingerprint=nested_family.expr.semantic_fingerprint(),
                self_formula_fingerprint=expression.semantic_fingerprint(),
                params={
                    p.alias: factor_param_value_storage(p, normalized.get(p.alias))
                    for p in nested_family.params
                },
            )
        frozen_rows.append(frozen_row)
    return frozen_rows


def _configuration_factor_resolver(
    config: dict, username: str, values=None,
):
    """Resolve stored FactorParam refs only from this config's frozen DAG."""
    frozen_by_ref = _configuration_frozen_factor_map(config, values)
    from server.modules.shared.factor_param_resolver import resolve_factor_param_value
    return factor_param_resolver_scope(lambda value: resolve_factor_param_value(
        value, username=username, frozen_by_ref=frozen_by_ref,
    ))


def _referenced_factor_refs(values) -> set[str]:
    """收集参数数据里真正被引用到的 factor ref（含深层嵌套）。"""
    refs: set[str] = set()

    def visit(node) -> None:
        if isinstance(node, dict):
            ref = node.get('ref')
            if isinstance(ref, str) and ref.startswith('factor:v2:'):
                refs.add(ref)
            for item in node.values():
                visit(item)
        elif isinstance(node, (list, tuple)):
            for item in node:
                visit(item)
        elif isinstance(node, str) and node.startswith('factor:v2:'):
            refs.add(node)

    visit(values)
    return refs


def _configuration_frozen_factor_map(
    config: dict, values=None,
) -> dict[str, dict]:
    """本次解析可用的冻结记录：只包含参数数据**真正引用到**的 ref。

    遗留记录必须丢弃：老配置的 metadata.factor_dependencies 里可能留着早先版本产出的身份
    （例如 groupby_scope 渲染修正前的 self_formula_fingerprint）。若把它交进 frozen_by_ref，
    嵌套因子会以该身份被重建、再被原样写回，于是「重算」永远复现旧身份，而校验侧重算的是
    新身份 —— 两侧永久不一致，任何 RunSpec 都被判 factor formula changed after RunSpec freeze。
    """
    metadata = config.get('metadata') if isinstance(config.get('metadata'), dict) else {}
    records = list(metadata.get('factor_dependencies') or [])
    if values is not None:
        # 只保留被引用的记录，再补上参数数据里自带的记录。
        referenced = _referenced_factor_refs(values)
        records = [
            record for record in records
            if str(record.get('ref') or '') in referenced
        ]
        records.extend(frozen_factor_records_from_values(values))
    return {
        value['ref']: value
        for value in unique_frozen_factor_records(records)
    }


def template_time_from_id(template: dict) -> str:
    updated_at = cast(str | None, template.get('updated_at'))
    if updated_at:
        return updated_at
    try:
        timestamp = int(str(template.get('id', ''))[:13]) / 1000
        return time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(timestamp))
    except Exception:
        return ''


def alias_map(factors: list[dict]) -> dict:
    result = {}
    for factor in factors:
        result[factor.get('id')] = factor
        result[factor.get('name')] = factor
    return result


def resolve_param_factor_family(owner_username: str, ff_alias: str, public_by_alias: dict, custom_by_alias: dict):
    custom_meta = custom_by_alias.get(ff_alias)
    if custom_meta:
        factor_family = get_custom_factor_instance(owner_username, custom_meta.get('id') or ff_alias)
        if factor_family is not None:
            return factor_family, dict(custom_meta, source='custom')
    public_meta = public_by_alias.get(ff_alias)
    if public_meta:
        return get_factor_family_instance(public_meta.get('id') or ff_alias), dict(public_meta, source='public')
    factor_family = get_factor_family_instance(ff_alias, username=owner_username)
    return factor_family, {
        'id': ff_alias,
        'name': getattr(factor_family, 'alias', ff_alias),
        'category': getattr(factor_family, 'category', '') or '',
        'chinese_name': getattr(factor_family, 'desc', '') or '',
        'description': getattr(factor_family, 'description', '') or '',
        'factor_family': factor_family.__class__.__name__,
        'source': 'unknown',
    }


def build_library_factor_param_item(
    current_username: str,
    owner_account: dict,
    ff_alias: str,
    config: dict,
    row: dict,
    row_index: int,
    public_by_alias: dict,
    custom_by_alias: dict,
) -> dict:
    owner_username = owner_account.get('username') or ''
    # 配置里已物化过与 params_list 逐行对齐的解析结果（由同一构造函数 build_factor_library_config_factors
    # 产出后按 _FACTOR_KEYS 落库）。读取时直接复用，不要重新解析整棵依赖链：深链单实例数秒，
    # 24 个实例即可把一次 GET 拖到数分钟并触发客户端断连。仅当物化缺失/不对齐时回退到实时解析。
    materialised = config.get('resolved_factors') if isinstance(config, dict) else None
    params_list = config.get('params_list') if isinstance(config, dict) else None
    if (
        isinstance(materialised, list)
        and isinstance(params_list, list)
        and len(materialised) == len(params_list)
        and 0 <= row_index < len(materialised)
        and isinstance(materialised[row_index], dict)
        and materialised[row_index].get('ref')
    ):
        # 物化记录里可能留着同一别名的旧/新两条身份（历史写入）。上报前统一按
        # 「依赖 = 本行 params 引用到的因子」收敛，否则平台唯一性守卫生效：
        # 400 factor alias must be unique: <alias>。
        return sanitize_factor_record_dependencies(dict(materialised[row_index]))
    factor_family, meta = resolve_param_factor_family(owner_username, ff_alias, public_by_alias, custom_by_alias)
    account = dict(owner_account)
    account['alias'] = account_display_name(owner_account)
    frozen_by_ref = _configuration_frozen_factor_map(config, row)
    row = hydrate_frozen_factor_params(row, frozen_by_ref)
    with _configuration_factor_resolver(
        config, current_username, values=row,
    ):
        return sanitize_factor_record_dependencies(build_factor_param_item(
            factor_family, row or {}, row_index, account, current_username,
            meta=meta, config=config,
        ))


def build_factor_library_config_factors(current_username: str, owner_account: dict, ff_alias: str, config: dict) -> list:
    owner_username = owner_account.get('username') or ''
    public_by_alias = alias_map(list_public_factors())
    custom_by_alias = alias_map(list_custom_factors(owner_username))
    factors = []
    params_list = config.get('params_list') or []
    if not isinstance(params_list, list):
        return factors
    for row_index, row in enumerate(params_list):
        factors.append(build_library_factor_param_item(
            current_username, owner_account, ff_alias, config,
            row if isinstance(row, dict) else {}, row_index,
            public_by_alias, custom_by_alias,
        ))
        factors[-1]['scope_key'] = config.get('scope_key') or config.get('product_group') or DEFAULT_SCOPE_KEY
        factors[-1]['product_group'] = config.get('product_group') or config.get('scope_key') or DEFAULT_SCOPE_KEY
        if isinstance(config.get('metadata'), dict):
            factors[-1]['metadata'] = config.get('metadata')
            for key in (
                'factor_owner_ref',
                'family_formula_fingerprint', 'self_formula_fingerprint',
            ):
                value = config['metadata'].get(key)
                if value:
                    factors[-1][key] = value
    return factors


def list_factor_library_product_groups(username: str) -> list[str]:
    """Product groups available to the factor library for a user.

    The product-group manager is the source of truth, while existing library
    directories are kept visible so old configs remain reachable.
    """
    groups = [DEFAULT_SCOPE_KEY]
    try:
        groups.extend([
            str(group.get('name') or '').strip()
            for group in load_product_groups(username)
            if str(group.get('name') or '').strip()
        ])
    except Exception:
        pass
    try:
        groups.extend(list_factor_param_config_scopes(username))
    except Exception:
        pass
    seen = set()
    result = []
    for group in groups:
        group = normalize_product_group(group)
        if group in seen:
            continue
        seen.add(group)
        result.append(group)
    return result


def build_factor_library_overview(
    current_username: str,
    include_subordinates: bool,
    product_group: str | None = None,
    factor_family_alias: str | None = None,
    *,
    account: dict | None = None,
    include_scope_catalog: bool = True,
) -> dict:
    product_group = normalize_product_group(product_group) if product_group else None
    current = account or get_account(current_username) or {
        'username': current_username,
    }
    accounts = [current]
    if include_subordinates:
        accounts.extend(direct_subordinate_accounts_for(current_username))
    current_account = account or get_account(current_username) or {}
    can_filter_organization = bool(current_account.get('role') == 'super_admin' or current_account.get('is_admin'))
    public_by_alias = alias_map(list_public_factors())

    items = []
    errors = []
    for account in accounts:
        owner_username = account.get('username')
        if not owner_username:
            continue
        custom_by_alias = alias_map(list_custom_factors(owner_username))
        # Determine which product groups to iterate.
        if product_group:
            scope_keys = [product_group] if product_group in list_factor_library_product_groups(owner_username) else []
        else:
            scope_keys = list_factor_param_config_scopes(owner_username)

        for sk in scope_keys:
            for ff_alias in list_factor_param_config_aliases(owner_username, sk):
                if factor_family_alias and ff_alias != factor_family_alias:
                    continue
                config = load_factor_param_config(owner_username, ff_alias, sk)
                if not config:
                    continue
                params_list = config.get('params_list') or []
                for row_index, row in enumerate(params_list):
                    try:
                        item = build_library_factor_param_item(
                            current_username,
                            account,
                            ff_alias,
                            config,
                            row if isinstance(row, dict) else {},
                            row_index,
                            public_by_alias,
                            custom_by_alias,
                        )
                        item['scope_key'] = sk
                        item['product_group'] = sk
                        items.append(item)
                    except Exception as exc:
                        errors.append({
                            'owner_username': owner_username,
                            'scope_key': sk,
                            'product_group': sk,
                            'factor_family_alias': ff_alias,
                            'template_name': config.get('name') or '',
                            'row_index': row_index,
                            'error': str(exc),
                        })

    items.sort(key=lambda factor: (
        factor_group_key(str(factor.get('factor_family_alias') or factor.get('factor_family_name') or '')),
        factor.get('owner_organization_name') or factor.get('owner_organization_id') or '',
        factor.get('owner_alias') or factor.get('owner_username') or '',
        factor.get('factor_family_alias') or '',
        factor.get('factor_alias') or '',
        factor.get('template_name') or '',
    ))
    scope_catalog = (
        list_factor_library_product_groups(current_username)
        if include_scope_catalog else []
    )
    return {
        'factors': items,
        'errors': errors,
        'include_subordinates': include_subordinates,
        'current_username': current_username,
        'can_filter_organization': can_filter_organization,
        'scopes': scope_catalog,
        'product_groups': scope_catalog,
    }


def list_factor_library_config_users(current_username: str, ff_alias: str, product_group: str = DEFAULT_SCOPE_KEY) -> dict:
    product_group = normalize_product_group(product_group)
    accounts = [
        get_account(current_username) or {'username': current_username},
        *direct_subordinate_accounts_for(current_username),
    ]
    current_account = get_account(current_username) or {}
    can_filter_organization = bool(current_account.get('role') == 'super_admin' or current_account.get('is_admin'))
    public_by_alias = alias_map(list_public_factors())

    users = []
    for account in accounts:
        owner_username = account.get('username')
        if not owner_username:
            continue
        config = load_factor_param_config(owner_username, ff_alias, product_group)
        factors = []
        custom_by_alias = alias_map(list_custom_factors(owner_username))
        if config:
            params_list = config.get('params_list') or []
            if not isinstance(params_list, list):
                params_list = []
            for row_index, row in enumerate(params_list):
                try:
                    factors.append(build_library_factor_param_item(
                        current_username,
                        account,
                        ff_alias,
                        config,
                        row if isinstance(row, dict) else {},
                        row_index,
                        public_by_alias,
                        custom_by_alias,
                    ))
                except Exception:
                    continue
        users.append({
            'owner_username': owner_username,
            'owner_alias': account_display_name(account),
            'owner_organization_id': account.get('organization_id') or '',
            'owner_organization_name': account.get('organization_name') or '',
            'editable': owner_username == current_username,
            'config': {
                'id': config.get('id') if config else owner_username,
                'name': config.get('name') if config else owner_username,
                'updated_at': template_time_from_id(config) if config else '',
                'factor_count': len(config.get('params_list') or []) if config else 0,
                'params_list': config.get('params_list') if config else [],
                'metadata': config.get('metadata') if config and isinstance(config.get('metadata'), dict) else {},
            } if config else None,
            'factors': factors,
        })
    return {
        'users': users,
        'can_filter_organization': can_filter_organization,
        'scope_key': product_group,
        'product_group': product_group,
    }


def _clean_library_metadata(metadata: dict | None) -> dict:
    if not isinstance(metadata, dict):
        return {}
    cleaned = {}
    for key in (
        'note',
        'research_report',
        'factor_owner_ref',
        'family_formula_fingerprint',
        'self_formula_fingerprint',
        'product_group_id',
        'product_group_name',
        'product_group_paths',
        'product_names',
        'product_count',
        'factor_dependencies',
    ):
        value = metadata.get(key)
        if key == 'factor_dependencies':
            if isinstance(value, list):
                cleaned[key] = [item for item in value if isinstance(item, dict)]
            continue
        if isinstance(value, str):
            value = value.strip()
        if isinstance(value, list):
            value = [str(item).strip() for item in value if str(item).strip()]
        if value not in (None, '', []):
            cleaned[key] = value
    return cleaned


def _product_group_metadata(username: str, product_group: str) -> dict:
    product_group = normalize_product_group(product_group)
    if product_group == DEFAULT_SCOPE_KEY:
        return {}
    try:
        for group in load_product_groups(username):
            if str(group.get('name') or '').strip() != product_group:
                continue
            metadata = {
                'product_group_name': product_group,
                'product_group_id': group.get('id') or '',
                'product_group_paths': group.get('paths') or [],
                'product_names': group.get('product_names') or [],
                'product_count': group.get('product_count') or len(group.get('product_names') or []),
            }
            return _clean_library_metadata(metadata)
    except Exception:
        return {}
    return {}


def _merged_library_metadata(
    current_username: str,
    ff_alias: str,
    product_group: str,
    metadata: dict | None,
) -> dict:
    existing = load_factor_param_config(current_username, ff_alias, product_group) or {}
    merged = _clean_library_metadata(existing.get('metadata') if isinstance(existing, dict) else {})
    group_metadata = _product_group_metadata(current_username, product_group)
    for key, value in group_metadata.items():
        merged[key] = value
    if isinstance(metadata, dict):
        for key in ('family_formula_fingerprint', 'self_formula_fingerprint'):
            if not metadata.get(key):
                merged.pop(key, None)
    provided = _clean_library_metadata(metadata)
    for key, value in provided.items():
        merged[key] = value
    return merged


def save_current_user_library_config(
    current_username: str,
    ff_alias: str,
    params_list: list,
    product_group: str = DEFAULT_SCOPE_KEY,
    metadata: dict | None = None,
    *,
    _preserved_factors: dict[int, dict] | None = None,
) -> tuple[dict, list]:
    product_group = normalize_product_group(product_group)
    factor_family = get_factor_family_instance(ff_alias, username=current_username)
    params_list = _freeze_alias_factor_param_rows(current_username, factor_family, params_list)
    config_metadata = _merged_library_metadata(current_username, ff_alias, product_group, metadata)
    dependency_records = unique_frozen_factor_records([
        *(config_metadata.get('factor_dependencies') or []),
        *frozen_factor_records_from_values(params_list),
    ])
    if dependency_records:
        config_metadata['factor_dependencies'] = dependency_records
    else:
        config_metadata.pop('factor_dependencies', None)
    with _configuration_factor_resolver(
        {'metadata': config_metadata}, current_username, values=params_list,
    ):
        preserved = _preserved_factors or {}
        serialized_rows = [row if index in preserved else
                           serialize_factor_param_rows(factor_family, [row])[0]
                           for index, row in enumerate(params_list)]
    candidate_config = {
        'params_list': serialized_rows,
        'metadata': config_metadata,
        'scope_key': product_group,
        'product_group': product_group,
    }
    account = get_account(current_username) or {'username': current_username}
    changed_rows = [row for index, row in enumerate(serialized_rows) if index not in preserved]
    changed = iter(build_factor_library_config_factors(
        current_username, account, ff_alias, {**candidate_config, 'params_list': changed_rows},
    )) if changed_rows else iter(())
    candidate_factors = [dict(preserved[index]) if index in preserved else next(changed, {})
                         for index in range(len(serialized_rows))]
    if serialized_rows and (len(candidate_factors) != len(serialized_rows) or not all(candidate_factors)):
        raise ValueError(
            f'因子配置无法按冻结依赖恢复: {ff_alias} '
            f'({len(candidate_factors)}/{len(serialized_rows)})'
        )
    # Freeze once. Authored configuration, catalog mirror and outbox commit
    # together, so a crash cannot leave a successful write unpublished.
    from server.manager.storage.account_domain.factor_sync import (
        _FACTOR_KEYS,
        _flatten_dependencies,
    )

    # 保留各字段（resolved_math_expr / parameter_definitions 等本地消费方要用），
    # 但 factor_dependencies 必须扁平去重：递归依赖会在深链下指数级膨胀（实测单实例
    # ~528KB），把整个家族配置撑到读不动。
    resolved = []
    for item in candidate_factors:
        record = {key: item[key] for key in _FACTOR_KEYS if item.get(key) not in (None, '')}
        if 'factor_dependencies' in record:
            record['factor_dependencies'] = _flatten_dependencies(record['factor_dependencies'])
        resolved.append(record)
    config = save_factor_param_config(
        current_username,
        ff_alias,
        serialized_rows,
        product_group,
        metadata=config_metadata,
        resolved_factors=resolved,
    )
    return config, candidate_factors


def save_single_library_factor(
    current_username: str,
    ff_alias: str,
    params: dict,
    *,
    product_group: str = DEFAULT_SCOPE_KEY,
    metadata: dict | None = None,
    replace_factor_ref: str = "",
) -> tuple[dict, dict]:
    """Append a registration, or replace exactly the frozen identity edited.

    The caller holds the user's write lock across this read/modify/write.
    A missing edit target is a stale edit, never permission to append or
    replace a different registration in the same family.
    """
    if not isinstance(params, dict):
        raise ValueError('因子参数格式无效')
    scope = normalize_product_group(product_group)
    existing = load_factor_param_config(current_username, ff_alias, scope) or {}
    rows = list(existing.get('params_list') or [])
    factors = existing.get('resolved_factors')
    if not isinstance(factors, list) or len(factors) != len(rows):
        account = get_account(current_username) or {'username': current_username}
        factors = build_factor_library_config_factors(
            current_username, account, ff_alias, existing,
        ) if rows else []
    if len(factors) != len(rows):
        raise ValueError('原有因子无法恢复，请刷新后重试')
    index = len(rows)
    if replace_factor_ref:
        matches = [i for i, factor in enumerate(factors)
                   if (factor.get('factor_ref') or factor.get('ref')) == replace_factor_ref]
        if len(matches) != 1:
            raise ValueError('因子已变更或不存在，请刷新后重新编辑')
        index = matches[0]
        rows[index] = params
    else:
        # 幂等：相同参数（同一 canonical alias）不应重复追加。此前每次登记都 append，
        # 同一参数的重复登记会留下多个因子行，导致后续按别名引用时「无法唯一解析」。
        try:
            family = get_factor_family_instance(ff_alias, username=current_username)
            new_alias = str(family.get_alias(**params) or "").strip()
        except Exception:
            new_alias = ""
        if new_alias:
            for position, row in enumerate(rows):
                if not isinstance(row, dict):
                    continue
                try:
                    row_alias = str(family.get_alias(**row) or "").strip()
                except Exception:
                    row_alias = ""
                if row_alias and row_alias == new_alias:
                    return existing, factors[position]
        rows.append(params)
    config, factors = save_current_user_library_config(
        current_username, ff_alias, rows, product_group=scope, metadata=metadata,
        _preserved_factors={i: factor for i, factor in enumerate(factors) if i != index},
    )
    return config, factors[index]


def delete_factor_library_factor(
    current_username: str,
    ff_alias: str,
    factor_alias: str,
    product_group: str = DEFAULT_SCOPE_KEY,
) -> bool:
    """Remove one registered factor row without deleting its family config.

    The catalog's ``我的因子`` rows are parameterized registrations, not
    source families.  Deleting a row must therefore preserve the other
    parameter rows in the same family/product-group scope.
    """
    scope_key = normalize_product_group(product_group)
    target_alias = str(factor_alias or "").strip()
    if not target_alias:
        return False
    config = load_factor_param_config(current_username, ff_alias, scope_key)
    if not config:
        return False
    rows = config.get("params_list") or []
    if not isinstance(rows, list):
        return False
    try:
        family = get_factor_family_instance(ff_alias, username=current_username)
    except (ImportError, KeyError, TypeError, ValueError):
        return False
    remaining = []
    removed = False
    for row in rows:
        if not isinstance(row, dict):
            remaining.append(row)
            continue
        try:
            alias = str(family.get_alias(**row) or "").strip()
        except (AttributeError, TypeError, ValueError):
            alias = ""
        if not removed and alias == target_alias:
            removed = True
            continue
        remaining.append(row)
    if not removed:
        return False
    if remaining:
        save_current_user_library_config(
            current_username,
            ff_alias,
            remaining,
            scope_key,
            metadata=config.get("metadata")
            if isinstance(config.get("metadata"), dict) else None,
        )
    else:
        delete_factor_param_config(current_username, ff_alias, scope_key)
    return True
