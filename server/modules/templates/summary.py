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
        summary['time_range'] = ''.join(parts) + suffix

    params = snapshot.get('params_list', [])
    if params:
        if params[0] and 'params' in params[0]:
            params = [item.get('params', {}) for item in params]
        param_items = []
        for index, param_row in enumerate(params):
            if not param_row:
                continue
            pairs = [f"{key}={value}" for key, value in sorted(param_row.items())]
            if len(params) > 1:
                param_items.append(f"#{index + 1}: " + ', '.join(pairs))
            else:
                param_items.append(', '.join(pairs))
        if param_items:
            summary['params'] = param_items

    submissions = snapshot.get('submissions', [])
    if submissions:
        submission_items = []
        for submission in submissions:
            label = submission.get('label', '')
            count_desc = submission.get('count_desc', '')
            if label and count_desc:
                submission_items.append(f"{label}({count_desc})")
            elif label:
                submission_items.append(label)
            elif count_desc:
                submission_items.append(count_desc)
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
                freq_items.append(f"{alias}:{return_freq}")
            else:
                freq_items.append(f"{alias}(默认)")
        if freq_items:
            summary['return_freqs'] = freq_items

    group_settings = snapshot.get('group_settings', {})
    if group_settings:
        group_parts = []
        group_count = group_settings.get('group_count', '')
        if group_count:
            group_parts.append(f"分组数={group_count}")
        fee_mode = group_settings.get('fee_mode', '')
        if fee_mode and fee_mode != 'none':
            fee_labels = {'none': '无', 'percent': '百分比', 'fixed': '固定'}
            group_parts.append(f"费率={fee_labels.get(fee_mode, fee_mode)}")
            if group_settings.get('fee_rate'):
                group_parts.append(f"{group_settings['fee_rate']}%")
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
            summary['group_test'] = ', '.join(group_parts)

    return summary
