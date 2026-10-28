"""Authenticated, source-free alpha formula previews for editors."""
import json

from alpha.factor.serialized_formula import RESOLVED_MATH_EXPR_VERSION, preview_expression
from flask import request

from server.modules.custom_factors import factor_library_internal_bp
from server.services.api_response import api_fail, api_ok
from server.services.http_auth import login_required
from . import factors_bp


@factors_bp.post('/api/factor-library/families/formula-preview')
@factor_library_internal_bp.post('/formula-preview')
@login_required
def formula_preview():
    # Bounds apply once per user preview, never to factor calculation or each Bar.
    raw = request.stream.read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024:
        return api_fail('Formula preview payload is too large', 413)
    try:
        value = json.loads(raw)
    except (ValueError, UnicodeDecodeError, RecursionError):
        return api_fail('Invalid formula JSON', 400)
    if not isinstance(value, dict) or not isinstance(value.get('factor'), dict):
        return api_fail('Formula preview requires a factor object', 400)
    pending = [(value, 0)]
    count = 0
    while pending:
        item, depth = pending.pop()
        count += 1
        if count > 10000 or depth > 48:
            return api_fail('Formula preview nesting is too large', 400)
        if isinstance(item, dict):
            pending.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            pending.extend((child, depth + 1) for child in item)
    parameters = value.get('parameter_values')
    if parameters is not None and not isinstance(parameters, dict):
        return api_fail('Formula parameter values must be an object', 400)
    try:
        rendered = preview_expression(
            value['factor'], parameters,
            include_nested_definitions=value.get('include_nested_definitions', True) is not False,
            max_chars=512 * 1024,
        )
    except (TypeError, ValueError, RecursionError) as error:
        return api_fail(str(error), 400)
    return api_ok({'latex': rendered, 'renderer_version': RESOLVED_MATH_EXPR_VERSION})
