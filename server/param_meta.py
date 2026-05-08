"""Parameter metadata helpers shared by factor pages."""


def serialize_default(param):
    """Serialize a parameter default value using its display alias."""
    try:
        dv = param.default_value
        try:
            dv = param.get_value_alias(dv)
        except Exception:
            pass
    except Exception:
        return None
    if dv is None:
        return None
    import pandas as pd
    if isinstance(dv, pd.Timedelta):
        return str(dv)
    if isinstance(dv, pd.Timestamp):
        return dv.strftime('%Y-%m-%d')
    if isinstance(dv, (int, float, str, bool)):
        return dv
    return str(dv)


def serialize_param_meta(param):
    """Serialize parameter metadata for UI tables and tooltips."""
    return {
        'alias': param.alias,
        'name': getattr(param, 'name', '') or param.alias,
        'desc': getattr(param, 'desc', '') or '',
        'default_value': serialize_default(param),
        'type': display_param_type(param),
        'value_space_desc': describe_value_space(param),
    }


def display_param_type(param) -> str:
    if param.alias == '$F':
        return 'FactorFreqParam'
    if param.alias == '$Rev':
        return 'ReverseParam'
    if param.alias == '$RF':
        return 'ReturnFreqParam'
    return type(param).__name__


def describe_value_space(param) -> str:
    typ = display_param_type(param)
    desc = getattr(param, 'desc', '') or ''
    if typ == 'FactorFreqParam':
        base = '合法值：因子信号频率，支持任意正时长以及特殊值 S，如 1d、5d、30min。'
    elif typ == 'ReverseParam':
        base = '合法值：反转标志；1/True/-1 表示反转，0/False 表示保持原方向。'
    elif typ == 'ReturnFreqParam':
        base = '合法值：收益率计算频率；None 表示使用默认，或任意正时长如 1d、5d、30min。'
    elif typ == 'DataColumnParam':
        base = '合法值：DataColumn 枚举中的数据列，如 CA/HA/LA/OI 等。'
    elif typ == 'WindowParam':
        base = '合法值：正整数窗口，或可转换为正 Timedelta 的时间窗口，如 10、10d、30min。'
    elif typ == 'TimeDeltaParam':
        flag = getattr(param, 'flag', None)
        flag_desc = {
            'pos': '正时长',
            'neg': '负时长',
            'nonneg': '非负时长',
            'nonpos': '非正时长',
        }.get(flag, '任意时长')
        base = f'合法值：可转换为 pandas Timedelta 的{flag_desc}，如 1d、5d、30min。'
    elif typ == 'FinRangeParam':
        values = getattr(param, 'value_space', None) or getattr(param, '_fin_values', None) or []
        base = '合法值：有限枚举 ' + ', '.join(str(v) for v in values)
    elif typ == 'TypeParam':
        t = getattr(param, '_typ', None)
        if isinstance(t, tuple):
            type_names = ', '.join(getattr(x, '__name__', str(x)) for x in t)
        else:
            type_names = getattr(t, '__name__', str(t))
        base = f'合法值：Python 类型 {type_names}。'
    elif typ == 'FactorParam':
        base = '合法值：FactorExpr 或 None，用于引用另一个因子表达式。'
    else:
        base = '合法值：由该参数的 ValueSpace 校验、标准化并转换为展示别名。'
    return f'{desc}\n{base}' if desc else base
