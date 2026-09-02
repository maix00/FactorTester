"""Page-scoped runtime state and lifecycle helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, Optional
from dataclasses import dataclass
import os
import threading
import time
import uuid
from types import SimpleNamespace

if TYPE_CHECKING:
    from tools.factors import FactorTester


# 统一的页级对象注册表：page_objects[page_uuid][kind.name] -> list[obj]（保序）。
# 取代原先各类型各自维护的 page_factor_testers / page_product_selections 字典——
# 所有"页内活对象"（FactorTester / 产品路径选择 / 分类 …）走同一套生命周期管理。
page_objects: dict[str, dict[str, list]] = {}
page_owners: dict[str, str | None] = {}
page_states: dict[str, dict[str, Any]] = {}
page_leases: dict[str, dict[str, Any]] = {}
# Submission mutations may call scoped lookup helpers while holding the state
# lock. An RLock preserves the atomic mutation without deadlocking that lookup.
factor_testers_lock = threading.RLock()

MAX_PAGE_UUIDS = 500
PAGE_LEASE_GRACE_SECONDS = max(0.5, float(os.environ.get("GTHT_PAGE_LEASE_GRACE_SECONDS", "10.0")))
page_time_store: dict = {}
page_time_store_lock = threading.Lock()
_page_lease_timers: dict[str, threading.Timer] = {}


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


def _selection_id(selection: Any) -> str:
    return str(
        getattr(
            selection,
            "selection_id",
            getattr(selection, "product_path_selection_id", getattr(selection, "id", "")),
        )
        or ""
    )


def _factor_tester_id(tester: Any) -> str:
    return str(getattr(tester, "alias", "") or "")


def _category_id(category: Any) -> str:
    return str(getattr(category, "alias", None) or getattr(category, "id", "") or "")


@dataclass(frozen=True)
class PageObjectKind:
    """描述一类"页内活对象"的身份与生命周期，供通用注册表统一处理。"""
    name: str
    id_of: Callable[[Any], str]
    page_uuid_attr: str = "page_uuid"      # 对象上记录所属页的属性名
    allow_suffix: bool = False             # 默认查找是否允许 ":id" 后缀匹配
    deletes_on_remove: bool = False        # remove/clear 时是否调用 obj.delete()

    def matches(self, obj: Any, query_id: str, allow_suffix: Optional[bool] = None) -> bool:
        suffix = self.allow_suffix if allow_suffix is None else allow_suffix
        oid = self.id_of(obj)
        if oid == query_id:
            return True
        return bool(suffix and query_id and oid.endswith(f":{query_id}"))


# 已注册的 kind。新增一类页内活对象 = 在此加一个 PageObjectKind，无需另写一套增删查改。
FACTOR_TESTER = PageObjectKind(
    "factor_tester", _factor_tester_id,
    page_uuid_attr="_page_uuid", allow_suffix=True, deletes_on_remove=True,
)
PRODUCT_SELECTION = PageObjectKind(
    "product_selection", _selection_id,
    page_uuid_attr="page_uuid", allow_suffix=False, deletes_on_remove=False,
)
CATEGORY = PageObjectKind(
    "category", _category_id,
    page_uuid_attr="page_uuid", allow_suffix=False, deletes_on_remove=False,
)
_ALL_KINDS: tuple[PageObjectKind, ...] = (FACTOR_TESTER, PRODUCT_SELECTION, CATEGORY)


def _require_page_uuid(page_uuid: Any, action: str) -> str:
    page_uuid = str(page_uuid or "").strip()
    if not page_uuid:
        raise ValueError(f"{action}必须提供 page_uuid")
    return page_uuid


def register_page_object(kind: PageObjectKind, obj: Any, *, page_uuid: Optional[str] = None) -> None:
    if page_uuid is None:
        page_uuid = getattr(obj, kind.page_uuid_attr, None)
    page_uuid = _require_page_uuid(page_uuid, f"注册 {kind.name}")
    try:
        setattr(obj, kind.page_uuid_attr, page_uuid)
    except Exception:
        pass
    oid = kind.id_of(obj)
    with factor_testers_lock:
        items = page_objects.setdefault(page_uuid, {}).setdefault(kind.name, [])
        items[:] = [it for it in items if kind.id_of(it) != oid]
        items.append(obj)


def iter_page_objects(kind: PageObjectKind, *, page_uuid: str) -> list:
    page_uuid = _require_page_uuid(page_uuid, f"遍历 {kind.name}")
    with factor_testers_lock:
        return list(page_objects.get(page_uuid, {}).get(kind.name, []))


def find_page_object(
    kind: PageObjectKind,
    query_id: str | int | None,
    *,
    page_uuid: str,
    allow_suffix: Optional[bool] = None,
) -> Any:
    page_uuid = _require_page_uuid(page_uuid, f"查找 {kind.name}")
    qid = str(query_id or "")
    with factor_testers_lock:
        for obj in page_objects.get(page_uuid, {}).get(kind.name, []):
            if kind.matches(obj, qid, allow_suffix):
                return obj
    return None


def get_page_object(
    kind: PageObjectKind,
    query_id: str | int | None,
    *,
    page_uuid: str,
    caller: Optional[Any] = None,
    allow_suffix: Optional[bool] = None,
) -> Any:
    obj = find_page_object(kind, query_id, page_uuid=page_uuid, allow_suffix=allow_suffix)
    if obj is None:
        with factor_testers_lock:
            available = [kind.id_of(o) for o in page_objects.get(str(page_uuid), {}).get(kind.name, [])]
        prefix = f"{caller}: " if caller is not None else ""
        raise AssertionError(
            f"{prefix}未找到 {kind.name} id={query_id!r}, page_uuid={page_uuid!r}, available={available}"
        )
    return obj


def replace_page_objects(kind: PageObjectKind, *, page_uuid: str, ordered: list) -> None:
    page_uuid = _require_page_uuid(page_uuid, f"重排 {kind.name}")
    with factor_testers_lock:
        page_objects.setdefault(page_uuid, {})[kind.name] = list(ordered)


def remove_page_object(kind: PageObjectKind, obj: Any, *, delete: Optional[bool] = None) -> None:
    if delete is None:
        delete = kind.deletes_on_remove
    page_uuid = str(getattr(obj, kind.page_uuid_attr, "") or "").strip()
    if page_uuid:
        oid = kind.id_of(obj)
        with factor_testers_lock:
            store = page_objects.get(page_uuid)
            items = store.get(kind.name) if store else None
            if items:
                items[:] = [it for it in items if kind.id_of(it) != oid]
                if not items:
                    store.pop(kind.name, None)
                if not store:
                    page_objects.pop(page_uuid, None)
    if delete:
        try:
            obj.delete()
        except Exception:
            pass


def clear_page_objects(kind: PageObjectKind, *, page_uuid: str, delete: Optional[bool] = None) -> None:
    page_uuid = _require_page_uuid(page_uuid, f"清理 {kind.name}")
    if delete is None:
        delete = kind.deletes_on_remove
    with factor_testers_lock:
        store = page_objects.get(page_uuid, {})
        removed = list(store.pop(kind.name, []))
        if not store:
            page_objects.pop(page_uuid, None)
    if delete:
        for obj in removed:
            try:
                obj.delete()
            except Exception:
                pass


def clear_page(page_uuid: str, *, delete: bool = True) -> None:
    """清空某页的所有页内活对象（取代旧的 clear_page_submissions）。

    delete 控制是否对"有删除语义"的 kind（如 FactorTester）调用 obj.delete()。
    """
    page_uuid = str(page_uuid).strip()
    if not page_uuid:
        return
    with factor_testers_lock:
        store = page_objects.pop(page_uuid, {})
    if delete:
        for kind in _ALL_KINDS:
            if kind.deletes_on_remove:
                for obj in store.get(kind.name, []):
                    try:
                        obj.delete()
                    except Exception:
                        pass


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
        page_leases[page_uuid] = {
            "owner": owner,
            "status": "active",
            "last_heartbeat_at": time.time(),
            "detached_at": None,
            "expires_at": None,
        }
        timer = _page_lease_timers.pop(page_uuid, None)
        if timer is not None:
            timer.cancel()
    _reg_page(page_uuid)


def heartbeat_page(page_uuid: str, owner: str | None = None) -> None:
    page_uuid = str(page_uuid).strip()
    if not page_uuid:
        return
    now = time.time()
    with factor_testers_lock:
        if owner is not None:
            page_owners[page_uuid] = owner
        page_leases[page_uuid] = {
            "owner": page_owners.get(page_uuid, owner),
            "status": "active",
            "last_heartbeat_at": now,
            "detached_at": None,
            "expires_at": None,
        }
        timer = _page_lease_timers.pop(page_uuid, None)
        if timer is not None:
            timer.cancel()


def unregister_page(page_uuid: str) -> None:
    mark_page_detaching(page_uuid)


def mark_page_detaching(page_uuid: str, *, grace_seconds: float | None = None) -> None:
    page_uuid = str(page_uuid).strip()
    if not page_uuid:
        return
    grace = PAGE_LEASE_GRACE_SECONDS if grace_seconds is None else max(0.0, float(grace_seconds))
    now = time.time()
    expires_at = now + grace
    with factor_testers_lock:
        lease = page_leases.setdefault(page_uuid, {"owner": page_owners.get(page_uuid)})
        lease.update({
            "status": "detaching",
            "detached_at": now,
            "expires_at": expires_at,
        })
        timer = _page_lease_timers.pop(page_uuid, None)
        if timer is not None:
            timer.cancel()
        timer = threading.Timer(grace, expire_detached_pages)
        timer.daemon = True
        _page_lease_timers[page_uuid] = timer
        timer.start()


def _finalize_unregistered_page(page_uuid: str) -> None:
    from server.services.backtest_runs import cancel_page
    cancel_page(page_uuid)
    clear_page(page_uuid, delete=True)
    from server.services.factor_registry import unregister_page as _unreg_page
    _unreg_page(page_uuid)
    with page_time_store_lock:
        page_time_store.pop(page_uuid, None)
    with factor_testers_lock:
        page_owners.pop(page_uuid, None)
        page_states.pop(page_uuid, None)
        page_leases.pop(page_uuid, None)
        timer = _page_lease_timers.pop(page_uuid, None)
        if timer is not None:
            timer.cancel()


def expire_detached_pages(now: float | None = None) -> int:
    now = time.time() if now is None else now
    with factor_testers_lock:
        expired = [
            page_uuid for page_uuid, lease in page_leases.items()
            if lease.get("status") == "detaching"
            and lease.get("expires_at") is not None
            and float(lease.get("expires_at") or 0.0) <= now
        ]
    for page_uuid in expired:
        _finalize_unregistered_page(page_uuid)
    return len(expired)


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
