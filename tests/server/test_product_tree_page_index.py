"""Derived catalog indexes must preserve identities, scope and resource limits."""
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from server.services.product_tree_pages import ProductTreePages


@pytest.fixture
def index():
    value = ProductTreePages()
    yield value
    value.clear()


def product(ref, name="Same", sources=("bundle-a/minute", "bundle-b/day")):
    return SimpleNamespace(ref=ref, name=name, sources=sources)


def request(index, objects, calls, *, scope=("manager-a", "alice", "bundle-a"),
            query="", page=1, limit=2):
    def project(item, path):
        calls.append(path)
        return {"title": item.name, "key": path, "product_path": path,
                "source_ids": list(item.sources), "product_code": item.name}
    return index.page(scope=scope, objects=objects, object_path=lambda p: p.ref,
                      project=project, query=query, page=page, limit=limit)


def test_unique_identity_preserves_overlapping_sources_and_same_name(index):
    a, b = product("Product/ExchangeA/X"), product("Product/ExchangeB/X")
    alternate = product(a.ref, sources=("bundle-c/hour",))
    rows = request(index, [a, a, alternate, b], [])
    assert rows["total"] == 2
    assert {row["key"] for row in rows["nodes"]} == {a.ref, b.ref}
    by_ref = {row["key"]: row["source_ids"] for row in rows["nodes"]}
    assert by_ref[a.ref] == sorted((*a.sources, *alternate.sources))
    assert by_ref[b.ref] == list(b.sources)


def test_lazy_pages_and_warm_search_do_not_probe_sources_again(index):
    objects = tuple(product(str(i), f"P{i:05d}") for i in range(1000))
    calls = []
    assert request(index, objects, calls, page=100, limit=3)["nodes"][0]["title"] == "P00297"
    assert len(calls) == 3
    assert request(index, objects, calls, query="bundle-b", limit=25)["total"] == 1000
    assert len(calls) == 1000
    for page in (1, 4, 40, 41):
        result = request(index, objects, calls, query="BUNDLE-B".casefold(), page=page, limit=25)
        assert result["total"] == 1000
    assert len(calls) == 1000
    assert not result["nodes"] and not result["has_more"]


def test_scope_node_installation_principal_and_source_are_independent(index):
    objects = (product("Product/X"),)
    calls = []
    for scope in (("node-a", "install-1", "alice", "bundle"),
                  ("node-b", "install-1", "alice", "bundle"),
                  ("node-a", "install-2", "alice", "bundle"),
                  ("node-a", "install-1", "bob", "bundle"),
                  ("node-a", "install-1", "alice", "other-bundle")):
        assert request(index, objects, calls, scope=scope)["total"] == 1
    assert len(calls) == 5
    # This verifies generic key isolation, not actual remote discovery/admission.


def test_membership_replacement_deletion_and_response_mutation(index):
    objects = [product("Product/Old")]
    first = request(index, objects, [])
    first["nodes"][0]["source_ids"].clear()
    assert request(index, objects, [])["nodes"][0]["source_ids"]
    objects[:] = [product("Product/New")]
    assert request(index, objects, [])["nodes"][0]["key"] == "Product/New"
    objects.clear()
    assert request(index, objects, [])["total"] == 0


def test_refresh_drops_old_availability_and_removes_temporary_storage(index):
    objects = (product("Product/X"),)
    assert request(index, objects, [])["nodes"][0]["source_ids"]
    connection = index._db
    objects[0].sources = ()
    index.clear()
    import sqlite3
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        connection.execute("SELECT 1")
    assert request(index, objects, [])["nodes"][0]["source_ids"] == []


def test_concurrent_search_materializes_each_product_once(index):
    objects = tuple(product(str(i)) for i in range(50))
    calls = []
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(request, index, objects, calls, query="bundle") for _ in range(4)]
        assert all(future.result()["total"] == 50 for future in futures)
    assert len(calls) == 50


def test_lru_object_limit_and_capacity_failure_are_explicit():
    index = ProductTreePages(max_objects=3, max_scopes=2, disk_mib=1)
    try:
        calls = []
        objects = (product("1"), product("2"))
        request(index, objects, calls, scope=("a",))
        request(index, objects, calls, scope=("b",))
        assert len(index._directories) == 1
        request(index, objects, calls, scope=("a",))
        assert len(calls) == 6
        with pytest.raises(ValueError, match="容量"):
            request(index, [product(str(i)) for i in range(4)], calls)
        assert index._db is None
        huge = product("x", sources=("x" * 2_000_000,))
        import sqlite3
        with pytest.raises(sqlite3.OperationalError, match="full"):
            request(index, [huge], [])
        assert index._db is None
    finally:
        index.clear()


def test_explicit_empty_source_scope_is_not_all_sources(monkeypatch):
    from server.services import product_catalog_projection as projection
    projection.clear_product_catalog_projection_cache()
    monkeypatch.setattr(projection, "normalize_source_ids", lambda ids: tuple(ids))
    assert projection.filter_product_tree({"$OBJECTS$": [product("x")]}, ()) == {}


def test_filtered_tree_reuses_support_checks_and_refresh_invalidates(monkeypatch):
    from server.services import product_catalog_projection as projection
    projection.clear_product_catalog_projection_cache()
    probes = []
    source = SimpleNamespace(supports_product=lambda item: probes.append(item.ref) or True)
    monkeypatch.setattr(projection, "normalize_source_ids", lambda ids: tuple(ids))
    monkeypatch.setattr(projection, "_visible_source_index", lambda: {"bundle": source})
    # Explicit clear expects the standard lru-cache interface.
    projection._visible_source_index.cache_clear = lambda: None
    tree = {"$OBJECTS$": [product("x"), product("y")]}
    first = projection.filter_product_tree(tree, ("bundle",))
    assert projection.filter_product_tree(tree, ("bundle",)) is first
    assert len(probes) == 2
    projection.clear_product_catalog_projection_cache()
    projection.filter_product_tree(tree, ("bundle",))
    assert len(probes) == 4
    projection.clear_product_catalog_projection_cache()


def test_member_family_mapping_does_not_project_product_availability(monkeypatch):
    from server.services import product_catalog_projection as projection
    projection.source_member_families.cache_clear()
    monkeypatch.setattr(projection, "load_all_sources", lambda: None)
    sources = (SimpleNamespace(key="bundle-a", members=(SimpleNamespace(key="a/minute"),)),
               SimpleNamespace(key="bundle-b", members=(SimpleNamespace(key="b/day"),)))
    monkeypatch.setattr(projection, "data_source_declarations", lambda: sources)
    assert projection.source_family_ids_for_member_ids(["a/minute", "b/day"]) == ("bundle-a", "bundle-b")
    projection.source_member_families.cache_clear()


def test_bundle_inventory_replacement_advances_epoch(monkeypatch):
    from server.services import product_catalog_projection as projection
    inventory = [object()]
    monkeypatch.setattr(projection, "installed_bundles", lambda: inventory[0])
    first = projection.product_catalog_revision()
    assert projection.product_catalog_revision() == first
    inventory[0] = object()
    assert projection.product_catalog_revision() > first
