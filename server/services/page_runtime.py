"""Page-scoped runtime state and lifecycle helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional
import threading
import uuid
from types import SimpleNamespace

import pandas as pd

import Settings as Settings

if TYPE_CHECKING:
    from tools.factors import FactorTester


factor_testers: list = []
page_factor_testers: dict[str, list] = {}
page_owners: dict[str, str | None] = {}
page_states: dict[str, dict[str, Any]] = {}
factor_testers_lock = threading.Lock()

MAX_PAGE_UUIDS = 500
page_time_store: dict = {}
page_time_store_lock = threading.Lock()


def create_page_uuid() -> str:
    return uuid.uuid4().hex


def _tester_page_uuid(tester: Any) -> Optional[str]:
    page_uuid = getattr(tester, '_page_uuid', None)
    if page_uuid is None:
        return None
    page_uuid = str(page_uuid).strip()
    return page_uuid or None


def alias_matches_submission_id(alias: str, submission_id: str | int | None, allow_suffix: bool = True) -> bool:
    if submission_id is None:
        return False
    sid = str(submission_id)
    if alias == sid:
        return True
    if allow_suffix:
        return alias.endswith(f":{sid}")
    return False


def find_factor_tester(submission_id: str | int | None, allow_suffix: bool = True):
    with factor_testers_lock:
        return next(
            (
                t for t in factor_testers
                if alias_matches_submission_id(getattr(t, 'alias', ''), submission_id, allow_suffix=allow_suffix)
            ),
            None,
        )


def get_factor_tester(alias: str, caller: Optional[Any] = None) -> 'FactorTester':
    tester = find_factor_tester(alias, allow_suffix=True)
    if tester is None:
        aliases = [getattr(t, 'alias', '?') for t in factor_testers]
        raise AssertionError(
            f"{str(caller) + ': ' if caller is not None else ''}"
            f"未找到对应的测试器实例 alias={alias!r}, "
            f"available={aliases}"
        )
    return tester


def iter_factor_testers(page_uuid: Optional[str] = None) -> list:
    with factor_testers_lock:
        if page_uuid:
            return list(page_factor_testers.get(page_uuid, []))
        return list(factor_testers)


def register_factor_tester(tester: Any, page_uuid: Optional[str] = None) -> None:
    if page_uuid is None:
        page_uuid = _tester_page_uuid(tester)
    if page_uuid:
        try:
            setattr(tester, '_page_uuid', page_uuid)
        except Exception:
            pass
    with factor_testers_lock:
        factor_testers.append(tester)
        if page_uuid:
            page_factor_testers.setdefault(page_uuid, []).append(tester)


def _remove_from_flat_store_locked(tester: Any) -> None:
    try:
        factor_testers.remove(tester)
    except ValueError:
        pass
    page_uuid = _tester_page_uuid(tester)
    if not page_uuid:
        return
    page_list = page_factor_testers.get(page_uuid)
    if not page_list:
        return
    try:
        page_list.remove(tester)
    except ValueError:
        pass
    if not page_list:
        page_factor_testers.pop(page_uuid, None)


def remove_factor_tester(tester: Any, *, delete: bool = True) -> None:
    with factor_testers_lock:
        _remove_from_flat_store_locked(tester)
    if delete:
        try:
            tester.delete()
        except Exception:
            pass


def replace_page_factor_testers(page_uuid: str, ordered_testers: list) -> None:
    page_uuid = str(page_uuid).strip()
    with factor_testers_lock:
        page_factor_testers[page_uuid] = list(ordered_testers)
        new_flat: list = []
        inserted = False
        for tester in factor_testers:
            if _tester_page_uuid(tester) == page_uuid:
                if not inserted:
                    new_flat.extend(ordered_testers)
                    inserted = True
                continue
            new_flat.append(tester)
        if not inserted:
            new_flat.extend(ordered_testers)
        factor_testers[:] = new_flat


def clear_page_factor_testers(page_uuid: str | None, *, delete: bool = True) -> None:
    if page_uuid is None:
        with factor_testers_lock:
            testers = list(factor_testers)
            factor_testers.clear()
            page_factor_testers.clear()
        if delete:
            for tester in testers:
                try:
                    tester.delete()
                except Exception:
                    pass
        return
    page_uuid = str(page_uuid).strip()
    with factor_testers_lock:
        testers = list(page_factor_testers.pop(page_uuid, []))
        factor_testers[:] = [tester for tester in factor_testers if _tester_page_uuid(tester) != page_uuid]
    if delete:
        for tester in testers:
            try:
                tester.delete()
            except Exception:
                pass


def get_default_time():
    start = Settings.default_test_start_date
    end = Settings.default_test_end_date
    if start is None:
        start = pd.Timestamp('2025-01-02', tz='Asia/Shanghai')
    if end is None:
        end = pd.Timestamp('2025-05-31', tz='Asia/Shanghai')
    return start, end


def get_current_time(page_uuid: Optional[str] = None):
    if page_uuid:
        with page_time_store_lock:
            entry = page_time_store.get(page_uuid)
            if entry is not None:
                return entry
    return None


def set_runtime_time(page_uuid: str, start, end, start_calc=None):
    if start_calc is None:
        start_calc = start
    with page_time_store_lock:
        if page_uuid not in page_time_store and len(page_time_store) >= MAX_PAGE_UUIDS:
            keys_to_remove = list(page_time_store.keys())[:len(page_time_store) // 2]
            for key in keys_to_remove:
                page_time_store.pop(key, None)
                _evict_page(key)
        page_time_store[page_uuid] = (start, end, start_calc)


def register_page(page_uuid: str, owner: str | None = None, **state: Any) -> None:
    from server.services.factor_registry import register_page as _reg_page
    page_uuid = str(page_uuid).strip()
    if not page_uuid:
        return
    with factor_testers_lock:
        page_owners[page_uuid] = owner
        page_state = page_states.setdefault(page_uuid, {})
        if state:
            page_state.update(state)
    _reg_page(page_uuid)


def unregister_page(page_uuid: str) -> None:
    page_uuid = str(page_uuid).strip()
    if not page_uuid:
        return
    clear_page_factor_testers(page_uuid, delete=True)
    from server.services.factor_registry import unregister_page as _unreg_page
    _unreg_page(page_uuid)
    with page_time_store_lock:
        page_time_store.pop(page_uuid, None)
    with factor_testers_lock:
        page_owners.pop(page_uuid, None)
        page_states.pop(page_uuid, None)


def update_page_state(page_uuid: str, **kwargs: Any) -> None:
    page_uuid = str(page_uuid).strip()
    if not page_uuid:
        return
    with factor_testers_lock:
        state = page_states.setdefault(page_uuid, {})
        state.update(kwargs)


def get_page_state(page_uuid: str) -> Any:
    page_uuid = str(page_uuid).strip()
    if not page_uuid:
        return None
    with factor_testers_lock:
        state = dict(page_states.get(page_uuid, {}))
    if not state:
        return None
    return SimpleNamespace(**state)


def cleanup_user_pages(user: Any) -> None:
    if user is None:
        return
    with factor_testers_lock:
        user_name = getattr(user, 'name', None)
        page_uuids = {
            page_uuid
            for page_uuid, owner in page_owners.items()
            if owner == user_name
        }
    for page_uuid in page_uuids:
        unregister_page(page_uuid)


def cleanup_user_testers(user: Any) -> None:
    if user is None:
        return
    with factor_testers_lock:
        testers = [tester for tester in factor_testers if getattr(tester, 'user', None) is user]
    for tester in testers:
        remove_factor_tester(tester, delete=True)


def _evict_page(page_uuid: str) -> None:
    unregister_page(page_uuid)


def _page_identity_debug_items(page_uuid: str) -> list[dict[str, Any]]:
    from server.services.session_runtime import get_session_id

    return [
        {'label': 'page_uuid', 'value': page_uuid},
        {'label': 'session_id', 'value': get_session_id()},
    ]


from server.services.page_state_debug import register_global_debug_section

register_global_debug_section(
    'page_identity',
    '页面标识',
    _page_identity_debug_items,
)
