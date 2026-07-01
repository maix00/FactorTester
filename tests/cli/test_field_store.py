from __future__ import annotations

from tools.cli.field_store import FieldStore, is_empty, visible_fields


def test_effective_uses_own_value_before_default_and_parent() -> None:
    parent = FieldStore(
        defaults={"product_path_selection": {"value": {"id": "page-default"}}},
        explicit_values={"product_path_selection": {"id": "page-live"}},
    )
    store = FieldStore(
        defaults={
            "product_path_selection": {
                "value": None,
                "serialization": {"shared_page_field": "product_path_selection"},
            }
        },
        parent=parent,
    )

    assert store.effective("product_path_selection") == {"id": "page-live"}
    store.set("product_path_selection", {"id": "local"})
    assert store.effective("product_path_selection") == {"id": "local"}


def test_effective_supports_candidate_fallback() -> None:
    store = FieldStore(
        defaults={
            "factor_candidates": {"value": ["SgCCS|N:2m"]},
            "factor": {
                "value": None,
                "serialization": {
                    "fallback": "candidates",
                    "candidate_field": "factor_candidates",
                },
            },
        }
    )

    assert store.effective("factor") == ["SgCCS|N:2m"]
    store.set("factor", "SgCCS|N:1m")
    assert store.effective("factor") == "SgCCS|N:1m"


def test_set_many_and_delete_keep_payload_explicit_only() -> None:
    store = FieldStore(defaults={"a": {"value": 1}, "b": {"value": 2}})

    store.set_many({"a": 3, "b": 4})
    store.delete("b")

    assert store.effective("a") == 3
    assert store.effective("b") == 2
    assert store.to_payload() == {"a": 3}


def test_visible_fields_honor_visible_when() -> None:
    store = FieldStore(
        defaults={
            "allocation_mode": {"value": "equal_notional", "tab_key": "allocation", "order": 1},
            "vol_window": {
                "value": 20,
                "tab_key": "allocation",
                "order": 2,
                "visible_when": {"allocation_mode": ["equal_risk"]},
            },
        }
    )

    assert [key for key, _ in visible_fields(store, tab_key="allocation")] == ["allocation_mode"]
    store.set("allocation_mode", "equal_risk")
    assert [key for key, _ in visible_fields(store, tab_key="allocation")] == ["allocation_mode", "vol_window"]


def test_empty_matches_frontend_core_values() -> None:
    assert is_empty(None)
    assert is_empty("")
    assert is_empty([])
    assert not is_empty(0)
    assert not is_empty(False)

