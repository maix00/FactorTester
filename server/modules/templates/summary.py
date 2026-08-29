"""Summary builders for saved template snapshots."""

from __future__ import annotations

from typing import Any

from tools.testers.settings import backtest_setting_registry


def build_snapshot_summary(snapshot: dict) -> dict[str, Any]:
    """Build a readable summary from a saved single-factor-test snapshot."""
    summary: dict[str, Any] = {}

    execution = snapshot.get('execution') or {}
    backend_local = execution.get('settings') if isinstance(execution, dict) else {}
    backend_local = backend_local if isinstance(backend_local, dict) else {}

    if backend_local:
        try:
            app_settings = backtest_setting_registry.get(
                'group_test'
            )
            manifest = app_settings.manifest()
            defaults = manifest.get('defaults') or {}
            values = {
                key: item.get('value')
                for key, item in defaults.items()
                if isinstance(item, dict)
            }
            values.update(backend_local)
            for tab in (manifest.get('tab_lists') or {}).get('local-settings') or []:
                template = tab.get('summary_template')
                if not template:
                    continue
                keys = tab.get('summary_keys') or [
                    key for key, item in defaults.items()
                    if isinstance(item, dict) and item.get('tab_key') == tab.get('key')
                ]
                if not any(key in backend_local for key in keys):
                    continue
                text = str(template)
                for key in keys:
                    text = text.replace('{' + key + '}', str(values.get(key) or ''))
                summary.setdefault('backtest_settings', []).append(
                    f"{tab.get('label') or tab.get('key')}: {' '.join(text.split())}"
                )
        except Exception:
            pass
        explicit_keys = sorted(
            key for key in backend_local
        )
        parts = summary.setdefault('backtest_settings', [])
        if explicit_keys:
            parts.append('显式字段: ' + ', '.join(explicit_keys))

    params = snapshot.get('params_list', [])
    if params:
        if params[0] and 'params' in params[0]:
            params = [item.get('params', {}) for item in params]
        param_items = []
        for index, param_row in enumerate(params):
            if not param_row:
                continue
            pairs = [f"{key}={value}" for key, value in sorted(param_row.items())]
            param_items.append(f"参数组{index + 1}: " + ', '.join(pairs))
        if param_items:
            summary['params'] = param_items

    selections = _snapshot_product_path_selections(snapshot)
    if selections:
        submission_items = []
        for index, submission in enumerate(selections):
            label = (
                submission.get('product_group')
                or submission.get('label')
                or submission.get('factor_tester_serial')
                or submission.get('id')
                or f"#{index + 1}"
            )
            product_count = submission.get('product_count')
            count_desc = f"{product_count} 个产品" if product_count is not None else (submission.get('count_desc') or '产品数待计算')
            paths = submission.get('selected_paths') or submission.get('paths') or []
            path_desc = '路径: ' + '；'.join(paths) if paths else '未选择路径'
            submission_items.append(f"{label} · {count_desc} · {path_desc}")
        if submission_items:
            summary['products'] = submission_items

    group_settings = snapshot.get('group_settings', {})
    if group_settings:
        group_parts = []
        raw_groups = group_settings.get('groups') or []
        flat_groups = [group for group in raw_groups if not group.get('parentId')]
        screened_groups = [group for group in raw_groups if group.get('product_names') or group.get('productNames')]
        ls_configs = group_settings.get('lsConfigs') or []
        total_groups = len(flat_groups) + len(screened_groups)
        if total_groups or ls_configs:
            screen_note = f" · 含 {len(screened_groups)} 个品种筛选组" if screened_groups else ""
            group_parts.append(
                f"共 {total_groups} 组{screen_note} · Long-Short {len(ls_configs)} 个"
            )
            fee_labels = {
                'auto': '自动费率',
                'close_yesterday': '平昨费率',
                'close_today': '平今费率',
                'custom': '自定义品种/合约',
                'fixed': '固定费率',
                'zero': '无费用',
                'none': '无费用',
                'market': '自动费率',
            }
            trigger_labels = {
                'on_factor_signal': '因子信号事件',
                'membership_change': '成员变化事件',
                'scheduled': '日历计划事件',
            }
            position_labels = {
                'rebalance_to_target': '按目标调仓',
                'buy_and_hold': '买入持有',
                'incremental_buy_and_hold_fixed_leverage': '增量式 Hold（固定杠杆）',
            }
            for group in flat_groups[:8]:
                label = group.get('name') or group.get('id') or '未命名组'
                group_index = group.get('groupIndex', '未设置')
                group_count_value = group.get('splitCount', '未设置')
                factor_alias = group.get('factorAlias') or '因子未设置'
                overrides = group if isinstance(group, dict) else {}
                fee_mode_value = str(overrides.get('fee_mode') or '默认')
                fee_text = fee_labels.get(fee_mode_value, fee_mode_value)
                trigger = str(overrides.get('rebalance_trigger') or '')
                trigger_text = trigger_labels.get(trigger, trigger or '默认触发')
                position_policy = str(overrides.get('position_policy') or '')
                position_text = position_labels.get(position_policy, position_policy or '默认持仓')
                group_parts.append(
                    f"{label} · 第{group_index}/{group_count_value}组 · 因子 {factor_alias} · {fee_text} · {trigger_text} · {position_text}"
                )
            if len(flat_groups) > 8:
                group_parts.append(f"…另 {len(flat_groups) - 8} 个组")
            for ls_config in ls_configs[:4]:
                label = ls_config.get('name') or ls_config.get('id') or '未命名 Long-Short'
                group_parts.append(
                    f"Long-Short {label} · Long {ls_config.get('longGroupId') or '未设置'} · Short {ls_config.get('shortGroupId') or '未设置'}"
                )
            summary['group_test'] = group_parts
            return summary

        group_count = group_settings.get('splitCount', '')
        if group_count:
            group_parts.append(f"分组数={group_count}")
        fee_mode = group_settings.get('fee_mode', '')
        if fee_mode and fee_mode not in ('none', 'zero'):
            fee_labels = {
                'auto': '自动费率',
                'close_yesterday': '平昨费率',
                'close_today': '平今费率',
                'fixed': '固定费率',
                'custom': '自定义品种/合约',
                'market': '自动费率',
            }
            group_parts.append(f"费率={fee_labels.get(fee_mode, fee_mode)}")
            if group_settings.get('fee_rate'):
                group_parts.append(f"{group_settings.get('fee_rate')}")
        if group_settings.get('use_closetoday'):
            group_parts.append('平今')

        group_start = '-'.join(filter(None, [
            group_settings.get('group_start_year', ''),
            str(group_settings.get('group_start_month', '')).zfill(2) if group_settings.get('group_start_month') else '',
            str(group_settings.get('group_start_day', '')).zfill(2) if group_settings.get('group_start_day') else '',
        ]))
        group_end = '-'.join(filter(None, [
            group_settings.get('group_end_year', ''),
            str(group_settings.get('group_end_month', '')).zfill(2) if group_settings.get('group_end_month') else '',
            str(group_settings.get('group_end_day', '')).zfill(2) if group_settings.get('group_end_day') else '',
        ]))
        if group_start and group_end:
            group_parts.append(f"{group_start} ~ {group_end}")
        elif group_start:
            group_parts.append(f"起始={group_start}")
        elif group_end:
            group_parts.append(f"终末={group_end}")
        if group_parts:
            summary['group_test'] = [', '.join(group_parts)]

    return summary


def _snapshot_product_path_selections(snapshot: dict) -> list[dict]:
    selections: list[dict] = []
    seen: set[str] = set()

    def add(item):
        if not isinstance(item, dict):
            return
        sid = str(item.get('product_path_selection_id') or item.get('id') or len(selections))
        if sid in seen:
            return
        seen.add(sid)
        selections.append(item)

    execution = snapshot.get('execution')
    settings = execution.get('settings') if isinstance(execution, dict) else None
    if isinstance(settings, dict):
        add(settings.get('product_path_selection'))
    group_settings = snapshot.get('group_settings')
    if isinstance(group_settings, dict):
        for group in group_settings.get('groups') or []:
            if isinstance(group, dict):
                add(group.get('product_path_selection'))
    return selections
