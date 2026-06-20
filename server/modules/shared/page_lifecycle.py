"""Page lifecycle routes."""

from __future__ import annotations

from flask import request

from server.services.api_response import api_ok, route_guard
from server.services.factor_registry import clear_page_factor_family
from server.services.page_state_debug import build_page_debug_payload

from . import shared_bp


@shared_bp.route('/close_page', methods=['POST'])
@route_guard
def close_page():
    """Clear the current page's active factor-family cache."""
    data = request.get_json(silent=True) or {}
    page_uuid = str(data.get('page_uuid', '')).strip()
    factor_family_alias = str(data.get('factor_family_alias', '')).strip()
    if page_uuid and factor_family_alias:
        clear_page_factor_family(page_uuid, factor_family_alias)
    return api_ok({'page_uuid': page_uuid, 'factor_family_alias': factor_family_alias})


@shared_bp.route('/api/debug/page_state')
@route_guard
def debug_page_state():
    """Debug-only page runtime snapshot."""
    page_uuid = str(request.args.get('page_uuid', '')).strip()
    if not page_uuid:
        return api_ok({'page_uuid': '', 'found': False})
    return api_ok(build_page_debug_payload(page_uuid))
