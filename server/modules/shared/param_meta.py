"""Serialize Parameter metadata for frontend tables and editors."""

from __future__ import annotations


def serialize_option_value(param, value):
    if value is None:
        return ''
    try:
        return param._value_space.alias(value)
    except Exception:
        pass
    if hasattr(value, 'value'):
        return value.value
    if hasattr(value, 'name'):
        return value.name
    return str(value)


def serialize_default(param):
    value = getattr(param, 'default_value', None)
    if value is None:
        return None
    try:
        return param.get_value_alias(value)
    except Exception:
        pass
    if hasattr(value, 'value'):
        return value.value
    if hasattr(value, 'name'):
        return value.name
    return str(value)


def serialize_param_meta(param):
    """Return frontend-safe metadata for a Parameter instance."""
    return {
        'alias': getattr(param, 'alias', ''),
        'name': getattr(param, 'name', '') or getattr(param, 'alias', ''),
        'desc': getattr(param, 'desc', '') or '',
        'type': display_param_type(param),
        'default_value': serialize_default(param),
        'value_space_desc': describe_value_space(param),
        'options': serialize_param_options(param),
        'input_mode': serialize_param_input_mode(param),
    }


def display_param_type(param) -> str:
    cls_name = type(param).__name__
    if cls_name.endswith('Param'):
        return cls_name
    return cls_name or 'Parameter'


def describe_value_space(param) -> str:
    vs = getattr(param, '_value_space', None)
    if vs is None:
        return ''
    parts = []
    for attr in ('desc', 'description', 'name'):
        val = getattr(vs, attr, None)
        if val:
            parts.append(str(val))
            break
    for attr in ('left', 'right', 'lower', 'upper', 'min_value', 'max_value'):
        if hasattr(vs, attr):
            try:
                parts.append(f'{attr}={getattr(vs, attr)}')
            except Exception:
                pass
    try:
        text = str(vs)
        if text and text not in parts and '<' not in text:
            parts.append(text)
    except Exception:
        pass
    return '；'.join(parts)


def serialize_param_options(param) -> list[dict]:
    """Return finite frontend choices when a parameter has an enumerable domain."""
    cls_name = type(param).__name__
    alias = getattr(param, 'alias', '')

    if cls_name == 'DataColumnParam':
        try:
            from tools.data.types import DataColumn
            return [
                {
                    'value': col.value,
                    'label': f'{col.name} ({col.value})',
                }
                for col in DataColumn
            ]
        except Exception:
            return []

    if cls_name == 'FactorParam':
        # FactorParam accepts both a visible factor and a raw ColumnRef.  The
        # account-scoped factor candidates are added by the editor; stable
        # column choices can be declared here.
        try:
            from tools.data.types import DataColumn
            return [
                {
                    'value': col.value,
                    'label': f'DataColumn.{col.name} ({col.value})',
                }
                for col in DataColumn
            ]
        except Exception:
            return []

    if alias == '$F':
        return [
            {'value': '1m', 'label': '1min'},
            {'value': '5m', 'label': '5min'},
            {'value': '15m', 'label': '15min'},
            {'value': '30m', 'label': '30min'},
            {'value': '1h', 'label': '1h'},
            {'value': '1d', 'label': '1d'},
            {'value': '5d', 'label': '5d'},
            {'value': '20d', 'label': '20d'},
            {'value': 'S', 'label': 'S'},
        ]

    if alias == '$Rev':
        return [
            {'value': '0', 'label': '不反转'},
            {'value': '1', 'label': '反转'},
        ]

    fin_values = getattr(param, '_fin_values', None)
    if isinstance(fin_values, list) and fin_values:
        return [
            {
                'value': serialize_option_value(param, value),
                'label': serialize_option_value(param, value),
            }
            for value in fin_values
        ]

    return []


def serialize_param_input_mode(param) -> str:
    """Frontend control mode declared by the parameter contract."""
    cls_name = type(param).__name__
    alias = getattr(param, 'alias', '')

    if cls_name == 'DataColumnParam':
        return 'enum'
    if cls_name == 'FactorParam':
        return 'factor_ref_custom'
    if alias == '$Rev':
        return 'enum'
    if alias == '$F':
        return 'enum_custom'
    if isinstance(getattr(param, '_fin_values', None), list) and getattr(param, '_fin_values', None):
        return 'enum'
    return 'text'
