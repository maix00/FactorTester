"""Page lifecycle routes."""

from __future__ import annotations

from flask import request

from server.services.api_response import api_fail, api_ok, route_guard
from server.services.factor_registry import clear_page_factor_family
from server.services.page_state_debug import build_page_debug_payload
from server.services.session_runtime import current_user
import server.services.page_runtime as page_runtime

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


@shared_bp.route('/unregister_page', methods=['POST'])
@route_guard
def unregister_page():
    """Mark a page observer as detaching; cancellation happens after lease grace."""
    data = request.get_json(silent=True) or {}
    page_uuid = str(data.get('page_uuid', '')).strip()
    if not page_uuid:
        return api_fail('缺少 page_uuid', status_code=400)
    if page_runtime.get_page_owner(page_uuid) != current_user():
        return api_fail('page_uuid 不属于当前用户', status_code=403)
    page_runtime.unregister_page(page_uuid)
    return api_ok({'page_uuid': page_uuid, 'detaching': True, 'grace_seconds': page_runtime.PAGE_LEASE_GRACE_SECONDS})


@shared_bp.route('/page_heartbeat', methods=['POST'])
@route_guard
def page_heartbeat():
    """Renew a page lease during refresh/reconnect and keep queued/running jobs alive."""
    data = request.get_json(silent=True) or {}
    page_uuid = str(data.get('page_uuid', '')).strip()
    if not page_uuid:
        return api_fail('缺少 page_uuid', status_code=400)
    owner = page_runtime.get_page_owner(page_uuid)
    current = current_user()
    if owner is not None and owner != current:
        return api_fail('page_uuid 不属于当前用户', status_code=403)
    page_runtime.heartbeat_page(page_uuid, current)
    return api_ok({'page_uuid': page_uuid, 'lease': 'active'})


@shared_bp.route('/api/debug/page_state')
@route_guard
def debug_page_state():
    """Debug-only page runtime snapshot."""
    page_uuid = str(request.args.get('page_uuid', '')).strip()
    if not page_uuid:
        return api_ok({'page_uuid': '', 'found': False})
    return api_ok(build_page_debug_payload(page_uuid))
