"""Serialize Parameter metadata for frontend tables and editors."""

from __future__ import annotations


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
