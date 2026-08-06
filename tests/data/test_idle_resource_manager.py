from __future__ import annotations

import threading

from tools.data.cache.IdleResourceManager import (
    IdleResourceManager,
    LocalResourceRegistry,
)


def _manager_for_test() -> IdleResourceManager:
    manager = object.__new__(IdleResourceManager)
    manager._registry = LocalResourceRegistry()
    manager._cache = {}
    manager._cache_lock = threading.Lock()
    return manager


def test_invalidate_prefix_removes_only_matching_namespace_and_keys():
    manager = _manager_for_test()
    manager._cache = {
        ("datameta", "SRC:P:MIN1"): {"data": object()},
        ("datameta", "SRC:P:MIN1:projection:a"): {"data": object()},
        ("datameta", "SRC:P:DAY1:projection:b"): {"data": object()},
        ("other", "SRC:P:MIN1:projection:c"): {"data": object()},
    }
    for namespace, path in manager._cache:
        manager._registry.record_use(manager._to_resource_id(namespace, path))

    removed = manager.invalidate_prefix("datameta", "SRC:P:MIN1")

    assert removed == 2
    assert ("datameta", "SRC:P:MIN1") not in manager._cache
    assert ("datameta", "SRC:P:MIN1:projection:a") not in manager._cache
    assert ("datameta", "SRC:P:DAY1:projection:b") in manager._cache
    assert ("other", "SRC:P:MIN1:projection:c") in manager._cache
    assert all(
        resource_id not in manager._registry._last_access
        for resource_id in (
            "datameta:SRC:P:MIN1",
            "datameta:SRC:P:MIN1:projection:a",
        )
    )

