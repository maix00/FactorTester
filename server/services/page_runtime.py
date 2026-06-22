"""Page-scoped runtime state and lifecycle helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional
import threading
import uuid
from types import SimpleNamespace

import pandas as pd

import settings as Settings

if TYPE_CHECKING:
    from tools.factors import FactorTester


page_factor_testers: dict[str, list] = {}
page_product_selections: dict[str, list] = {}
page_owners: dict[str, str | None] = {}
page_states: dict[str, dict[str, Any]] = {}
# Submission mutations may call scoped lookup helpers while holding the state
# lock. An RLock preserves the atomic mutation without deadlocking that lookup.
factor_testers_lock = threading.RLock()

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


def find_factor_tester(
    submission_id: str | int | None,
    allow_suffix: bool = True,
    *,
    page_uuid: str,
):
    page_uuid = str(page_uuid).strip()
    if not page_uuid:
        raise ValueError("查找 FactorTester 必须提供 page_uuid")
    with factor_testers_lock:
        candidates = page_factor_testers.get(page_uuid, [])
        return next(
            (
                t for t in candidates
                if alias_matches_submission_id(getattr(t, 'alias', ''), submission_id, allow_suffix=allow_suffix)
            ),
            None,
        )


def _selection_id(selection: Any) -> str:
    return str(
        getattr(
            selection,
            "selection_id",
            getattr(selection, "product_path_selection_id", getattr(selection, "id", "")),
        )
        or ""
    )


def find_product_selection(
    submission_id: str | int | None,
    *,
    page_uuid: str,
):
    page_uuid = str(page_uuid).strip()
    if not page_uuid:
        raise ValueError("查找产品路径组合必须提供 page_uuid")
    sid = str(submission_id or "")
    with factor_testers_lock:
        return next(
            (
                selection for selection in page_product_selections.get(page_uuid, [])
                if _selection_id(selection) == sid
            ),
            None,
        )


def get_product_selection(
    submission_id: str | int | None,
    *,
    page_uuid: str,
):
    selection = find_product_selection(submission_id, page_uuid=page_uuid)
    if selection is None:
        available = [_selection_id(item) for item in page_product_selections.get(str(page_uuid), [])]
        raise AssertionError(
            f"未找到对应的产品路径组合 selection_id={submission_id!r}, "
            f"page_uuid={page_uuid!r}, available={available}"
        )
    return selection


def iter_product_selections(page_uuid: str) -> list:
    page_uuid = str(page_uuid).strip()
    if not page_uuid:
        raise ValueError("遍历产品路径组合必须提供 page_uuid")
    with factor_testers_lock:
        return list(page_product_selections.get(page_uuid, []))


def register_product_selection(selection: Any, page_uuid: str) -> None:
    page_uuid = str(page_uuid or "").strip()
    if not page_uuid:
        raise ValueError("注册产品路径组合必须提供 page_uuid")
    try:
        setattr(selection, "page_uuid", page_uuid)
    except Exception:
        pass
    sid = _selection_id(selection)
    with factor_testers_lock:
        items = page_product_selections.setdefault(page_uuid, [])
        items[:] = [item for item in items if _selection_id(item) != sid]
        items.append(selection)


def replace_page_product_selections(page_uuid: str, ordered_selections: list) -> None:
    page_uuid = str(page_uuid).strip()
    if not page_uuid:
        raise ValueError("重排产品路径组合必须提供 page_uuid")
    with factor_testers_lock:
        page_product_selections[page_uuid] = list(ordered_selections)


def remove_product_selection(selection: Any) -> None:
    page_uuid = str(getattr(selection, "page_uuid", "") or "").strip()
    if not page_uuid:
        return
    sid = _selection_id(selection)
    with factor_testers_lock:
        items = page_product_selections.get(page_uuid, [])
        items[:] = [item for item in items if _selection_id(item) != sid]
        if not items:
            page_product_selections.pop(page_uuid, None)


def clear_page_product_selections(page_uuid: str) -> None:
    page_uuid = str(page_uuid).strip()
    if not page_uuid:
        raise ValueError("清理产品路径组合必须提供 page_uuid")
    with factor_testers_lock:
        page_product_selections.pop(page_uuid, None)


def get_factor_tester(
    alias: str,
    caller: Optional[Any] = None,
    *,
    page_uuid: str,
) -> 'FactorTester':
    tester = find_factor_tester(alias, allow_suffix=True, page_uuid=page_uuid)
    if tester is None:
        with factor_testers_lock:
            candidates = page_factor_testers.get(str(page_uuid), [])
            aliases = [getattr(t, 'alias', '?') for t in candidates]
        raise AssertionError(
            f"{str(caller) + ': ' if caller is not None else ''}"
            f"未找到对应的测试器实例 alias={alias!r}, "
            f"page_uuid={page_uuid!r}, available={aliases}"
        )
    return tester


def iter_factor_testers(page_uuid: str) -> list:
    page_uuid = str(page_uuid).strip()
    if not page_uuid:
        raise ValueError("遍历 FactorTester 必须提供 page_uuid")
    with factor_testers_lock:
        return list(page_factor_testers.get(page_uuid, []))


def register_factor_tester(tester: Any, page_uuid: Optional[str] = None) -> None:
    if page_uuid is None:
        page_uuid = _tester_page_uuid(tester)
    page_uuid = str(page_uuid or '').strip()
    if not page_uuid:
        raise ValueError("注册 FactorTester 必须提供 page_uuid")
    try:
        setattr(tester, '_page_uuid', page_uuid)
    except Exception:
        pass
    with factor_testers_lock:
        items = page_factor_testers.setdefault(page_uuid, [])
        items[:] = [
            item for item in items
            if not alias_matches_submission_id(
                getattr(item, "alias", ""),
                getattr(tester, "alias", ""),
                allow_suffix=False,
            )
        ]
        items.append(tester)


def _remove_from_page_store_locked(tester: Any) -> None:
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
        _remove_from_page_store_locked(tester)
    if delete:
        try:
            tester.delete()
        except Exception:
            pass


def replace_page_factor_testers(page_uuid: str, ordered_testers: list) -> None:
    page_uuid = str(page_uuid).strip()
    if not page_uuid:
        raise ValueError("重排 FactorTester 必须提供 page_uuid")
    with factor_testers_lock:
        page_factor_testers[page_uuid] = list(ordered_testers)


def clear_page_factor_testers(page_uuid: str, *, delete: bool = True) -> None:
    page_uuid = str(page_uuid).strip()
    if not page_uuid:
        raise ValueError("清理 FactorTester 必须提供 page_uuid")
    with factor_testers_lock:
        testers = list(page_factor_testers.pop(page_uuid, []))
    if delete:
        for tester in testers:
            try:
                tester.delete()
            except Exception:
                pass


def clear_page_submissions(page_uuid: str, *, delete_testers: bool = True) -> None:
    clear_page_product_selections(page_uuid)
    clear_page_factor_testers(page_uuid, delete=delete_testers)


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
    from server.services.backtest_runs import cancel_page
    cancel_page(page_uuid)
    clear_page_submissions(page_uuid, delete_testers=True)
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


def get_page_owner(page_uuid: str) -> str | None:
    page_uuid = str(page_uuid).strip()
    if not page_uuid:
        return None
    with factor_testers_lock:
        return page_owners.get(page_uuid)


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
