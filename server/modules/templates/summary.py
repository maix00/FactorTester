"""Summary builders for saved template snapshots."""

from __future__ import annotations


def build_snapshot_summary(snapshot: dict) -> dict:
    """Build a readable summary from a saved single-factor-test snapshot."""
    summary = {}

    time_data = snapshot.get('time_data', {})
    if time_data:
        start_date = time_data.get('start_date') or time_data.get('start') or ''
        start_time = time_data.get('start_time', '')
        end_date = time_data.get('end_date') or time_data.get('end') or ''
        end_time = time_data.get('end_time', '')
        parts = [start_date]
        if start_time:
            parts.append(' ' + start_time)
        parts.append(' ~ ')
        parts.append(end_date)
        if end_time:
            parts.append(' ' + end_time)
        suffix = ''
        if time_data.get('is_trading_day'):
            suffix = ' (交易日)'
        elif time_data.get('is_cn_futures_day'):
            suffix = ' (期货日盘)'
        elif time_data.get('is_cn_futures_night'):
            suffix = ' (期货夜盘)'
        timezone = time_data.get('timezone') or 'Asia/Shanghai'
        summary['time_range'] = [
            f"起始: {start_date}{(' ' + start_time) if start_time else ''}",
            f"终止: {end_date}{(' ' + end_time) if end_time else ''}",
            f"时区: {timezone}{suffix}",
        ]

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

    submissions = snapshot.get('submissions', [])
    if submissions:
        submission_items = []
        for index, submission in enumerate(submissions):
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

    return_freqs = snapshot.get('return_freqs', [])
    if return_freqs:
        freq_items = []
        for freq in return_freqs:
            if freq.get('checked') is False:
                continue
            alias = freq.get('alias', '?')
            return_freq = freq.get('return_freq', '')
            if return_freq:
                freq_items.append(f"{alias} · 收益率频率 {return_freq}")
            else:
                freq_items.append(f"{alias} · 收益率频率 默认")
        if freq_items:
            summary['return_freqs'] = freq_items

    group_settings = snapshot.get('group_settings', {})
    if group_settings:
        group_parts = []
        raw_groups = group_settings.get('groups') or []
        base_groups = [group for group in raw_groups if not group.get('isDerived')]
        derived_groups = [group for group in raw_groups if group.get('isDerived')]
        if not raw_groups:
            base_groups = group_settings.get('baseGroups') or []
            derived_groups = group_settings.get('derivedGraph') or []
        ls_configs = group_settings.get('lsConfigs') or []
        if base_groups or derived_groups or ls_configs:
            group_parts.append(
                f"基础组 {len(base_groups)} 个 · 派生组 {len(derived_groups)} 个 · Long-Short {len(ls_configs)} 个"
            )
            fee_labels = {'none': '无费率', 'uniform': '统一费率', 'per_product': '分品种费率', 'custom': '自定义费率'}
            rebalance_labels = {'hold': '组内持仓不动', 'daily': '每日调仓', 'signal': '信号频率调仓'}
            for group in base_groups[:8]:
                label = group.get('shortAlias') or group.get('name') or group.get('id') or '未命名组'
                group_index = group.get('groupIndex', '未设置')
                group_count_value = group.get('groupCount', '未设置')
                factor_alias = group.get('factorAlias') or '因子未设置'
                fee_mode_value = group.get('feeMode') or 'none'
                fee_text = fee_labels.get(fee_mode_value, fee_mode_value)
                fee_map = group.get('feeMap') if isinstance(group.get('feeMap'), dict) else {}
                if fee_mode_value in {'per_product', 'custom'} and fee_map:
                    fee_text += f"({len(fee_map)} 个品种)"
                rebalance = (group.get('rebalanceConfig') or {}).get('mode')
                rebalance_text = rebalance_labels.get(rebalance, rebalance or '默认调仓')
                group_parts.append(
                    f"{label} · 第{group_index}/{group_count_value}组 · 因子 {factor_alias} · {fee_text} · {rebalance_text}"
                )
            if len(base_groups) > 8:
                group_parts.append(f"…另 {len(base_groups) - 8} 个基础组")
            for derived in derived_groups[:4]:
                label = derived.get('shortAlias') or derived.get('name') or derived.get('id') or '未命名派生组'
                group_parts.append(f"派生组 {label} · 来源 {derived.get('baseGroupId') or '未设置'}")
            for ls_config in ls_configs[:4]:
                label = ls_config.get('shortAlias') or ls_config.get('name') or ls_config.get('id') or '未命名 Long-Short'
                group_parts.append(
                    f"Long-Short {label} · Long {ls_config.get('longGroupId') or '未设置'} · Short {ls_config.get('shortGroupId') or '未设置'}"
                )
            summary['group_test'] = group_parts
            return summary

        legacy = group_settings.get('_legacy') or group_settings
        group_count = group_settings.get('group_count', '')
        if not group_count:
            group_count = legacy.get('group_count', '')
        if group_count:
            group_parts.append(f"分组数={group_count}")
        fee_mode = group_settings.get('fee_mode', '') or legacy.get('fee_mode', '')
        if fee_mode and fee_mode != 'none':
            fee_labels = {'none': '无费率', 'percent': '百分比', 'fixed': '固定', 'uniform': '统一费率', 'per_product': '分品种费率', 'custom': '自定义费率'}
            group_parts.append(f"费率={fee_labels.get(fee_mode, fee_mode)}")
            if group_settings.get('fee_rate') or legacy.get('fee_rate'):
                group_parts.append(f"{group_settings.get('fee_rate') or legacy.get('fee_rate')}")
        if group_settings.get('use_closetoday') or legacy.get('use_closetoday'):
            group_parts.append('平今')

        group_start = '-'.join(filter(None, [
            legacy.get('group_start_year', ''),
            str(legacy.get('group_start_month', '')).zfill(2) if legacy.get('group_start_month') else '',
            str(legacy.get('group_start_day', '')).zfill(2) if legacy.get('group_start_day') else '',
        ]))
        group_end = '-'.join(filter(None, [
            legacy.get('group_end_year', ''),
            str(legacy.get('group_end_month', '')).zfill(2) if legacy.get('group_end_month') else '',
            str(legacy.get('group_end_day', '')).zfill(2) if legacy.get('group_end_day') else '',
        ]))
        if group_start and group_end:
            group_parts.append(f"{group_start} ~ {group_end}")
        elif group_start:
            group_parts.append(f"起始={group_start}")
        elif group_end:
            group_parts.append(f"终末={group_end}")
        if group_parts:
            summary['group_test'] = ', '.join(group_parts)

    return summary
