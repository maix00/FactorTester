"""Page lifecycle routes."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from flask import request

from server.services.api_response import api_ok, route_guard
import server.services.page_runtime as page_runtime
from server.services.factor_registry import clear_page_factor_family, page_families, page_factors
from server.services.session_runtime import current_user, get_session_id

from . import shared_bp


PageDebugProvider = Callable[[str], dict[str, Any] | list[dict[str, Any]] | None]
_page_debug_providers: dict[str, PageDebugProvider] = {}


def register_page_debug_provider(page_kind: str, provider: PageDebugProvider) -> None:
    """Register a page-kind-specific debug payload provider."""
    page_kind = str(page_kind).strip()
    if not page_kind:
        return
    _page_debug_providers[page_kind] = provider


def _normalize_debug_sections(payload: dict[str, Any] | list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    if not payload:
        return []
    if isinstance(payload, list):
        return [section for section in payload if isinstance(section, dict)]
    if isinstance(payload, dict):
        sections = payload.get('sections')
        if isinstance(sections, list):
            return [section for section in sections if isinstance(section, dict)]
        return [{
            'title': str(payload.get('title') or '模块调试'),
            'items': payload.get('items') if isinstance(payload.get('items'), list) else [
                {'label': str(key), 'value': value}
                for key, value in payload.items()
                if key not in {'title', 'items', 'sections', 'summary'}
            ],
        }]
    return []


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

    session_id = get_session_id()
    with page_runtime.factor_testers_lock:
        testers = list(page_runtime.page_factor_testers.get(page_uuid, []))
        owner = page_runtime.page_owners.get(page_uuid)
    page_state = page_runtime.get_page_state(page_uuid)
    with page_runtime.page_time_store_lock:
        time_entry = page_runtime.page_time_store.get(page_uuid)
    with page_runtime.factor_testers_lock:
        page_families_keys = list((page_families.get(page_uuid, {}) or {}).keys())
        page_factors_keys = list((page_factors.get(page_uuid, {}) or {}).keys())

    page_kind = getattr(page_state, 'page_kind', '') if page_state is not None else ''
    provider = _page_debug_providers.get(str(page_kind).strip())
    provider_payload = provider(page_uuid) if provider else None
    module_sections = _normalize_debug_sections(provider_payload)
    summary = provider_payload.get('summary') if isinstance(provider_payload, dict) else {}
    summary_factor_family_aliases = summary.get('factor_family_aliases') if isinstance(summary, dict) else None
    summary_factor_aliases = summary.get('factor_aliases') if isinstance(summary, dict) else None
    summary_factor_count = summary.get('factor_count') if isinstance(summary, dict) else None
    summary_factor_family_count = summary.get('factor_family_count') if isinstance(summary, dict) else None

    payload = {
        'page_uuid': page_uuid,
        'found': bool(time_entry or testers or owner or page_families_keys or page_factors_keys),
        'session_id': session_id,
        'owner': owner,
        'page_state': {
            'page_kind': page_kind,
            'factor_family_alias': getattr(page_state, 'factor_family_alias', ''),
        } if page_state is not None else {},
        'tester_count': len(testers),
        'tester_aliases': [getattr(t, 'alias', '') for t in testers],
        'time_range': {
            'start': str(time_entry[0]) if time_entry else '',
            'end': str(time_entry[1]) if time_entry else '',
            'start_calc': str(time_entry[2]) if time_entry and len(time_entry) > 2 else '',
        },
        'factor_family_count': int(summary_factor_family_count) if summary_factor_family_count is not None else len(page_families_keys),
        'factor_family_aliases': list(summary_factor_family_aliases) if isinstance(summary_factor_family_aliases, list) else page_families_keys,
        'factor_count': int(summary_factor_count) if summary_factor_count is not None else len(page_factors_keys),
        'factor_aliases': list(summary_factor_aliases) if isinstance(summary_factor_aliases, list) else page_factors_keys,
        'debug_sections': module_sections,
    }
    return api_ok(payload)
