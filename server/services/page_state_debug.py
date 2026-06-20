"""Registry and payload builder for page-scoped debug information."""

from __future__ import annotations

from collections.abc import Callable
import threading
from typing import Any


PageDebugProvider = Callable[[str], list[dict[str, Any]]]

_global_providers: dict[str, tuple[str, PageDebugProvider]] = {}
_page_kind_providers: dict[str, dict[str, tuple[str, PageDebugProvider]]] = {}
_providers_lock = threading.Lock()


def register_global_debug_section(
    section_id: str,
    title: str,
    provider: PageDebugProvider,
) -> None:
    """Register one section that is shown for every page kind."""
    section_id = str(section_id).strip()
    if not section_id:
        raise ValueError('section_id is required')
    with _providers_lock:
        _global_providers[section_id] = (str(title), provider)


def register_page_debug_section(
    page_kind: str,
    section_id: str,
    title: str,
    provider: PageDebugProvider,
) -> None:
    """Register one section owned by a page-scoped runtime module."""
    page_kind = str(page_kind).strip()
    section_id = str(section_id).strip()
    if not page_kind or not section_id:
        raise ValueError('page_kind and section_id are required')
    with _providers_lock:
        _page_kind_providers.setdefault(page_kind, {})[section_id] = (str(title), provider)


def _collect_sections(page_uuid: str, page_kind: str) -> list[dict[str, Any]]:
    with _providers_lock:
        providers = list(_global_providers.values())
        providers.extend(_page_kind_providers.get(page_kind, {}).values())

    sections = []
    for title, provider in providers:
        items = provider(page_uuid)
        if not isinstance(items, list):
            raise TypeError(f'debug provider {title!r} must return a list')
        has_page_uuid = any(
            isinstance(item, dict)
            and item.get('label') == 'page_uuid'
            and item.get('value') == page_uuid
            for item in items
        )
        if not has_page_uuid:
            raise ValueError(f'debug provider {title!r} must include the requested page_uuid')
        sections.append({'title': title, 'items': items})
    return sections


def build_page_debug_payload(page_uuid: str) -> dict[str, Any]:
    """Build a full snapshot from the providers active for the requested page."""
    from server.services import page_runtime

    page_uuid = str(page_uuid).strip()
    page_state = page_runtime.get_page_state(page_uuid)
    page_kind = str(getattr(page_state, 'page_kind', '') or '')
    with page_runtime.factor_testers_lock:
        found = page_uuid in page_runtime.page_states
    return {
        'page_uuid': page_uuid,
        'found': found,
        'debug_sections': _collect_sections(page_uuid, page_kind),
    }
