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


def test_visible_fields_honor_visible_if() -> None:
    store = FieldStore(
        defaults={
            "allocation_mode": {"value": "equal_notional", "tab_key": "allocation", "order": 1},
            "vol_window": {
                "value": 20,
                "tab_key": "allocation",
                "order": 2,
                "rules": {"visible_if": {"allocation_mode": ["equal_risk"]}},
            },
        }
    )

    assert [key for key, _ in visible_fields(store, tab_key="allocation")] == ["allocation_mode"]
    store.set("allocation_mode", "equal_risk")
    assert [key for key, _ in visible_fields(store, tab_key="allocation")] == ["allocation_mode", "vol_window"]


def test_field_store_reports_editable_if_without_blocking_set() -> None:
    store = FieldStore(
        defaults={
            "engine_mode": {"value": "basic"},
            "warmup": {
                "value": "auto",
                "rules": {
                    "visible_if": {"engine_mode": ["auto"]},
                    "editable_if": {"engine_mode": ["auto"]},
                },
            },
            "engine": {
                "value": "Native",
                "rules": {"editable_if": {"engine_mode": ["advanced"]}},
            },
        }
    )

    assert not store.is_visible("warmup")
    assert not store.is_editable("warmup")
    assert not store.is_editable("engine")
    store.set("warmup", "fixed")
    assert store.effective("warmup") == "fixed"
    store.set("engine_mode", "auto")
    assert store.is_visible("warmup")
    assert store.is_editable("warmup")


def test_display_value_uses_conditional_default_when_field_is_locked() -> None:
    store = FieldStore(
        defaults={
            "mode": {"value": "basic"},
            "warmup": {
                "value": "30d",
                "rules": {
                    "editable_if": {"mode": ["advanced"]},
                    "default_if": {"mode": {"basic": "auto"}},
                },
            },
        },
        explicit_values={"warmup": "stale"},
    )

    assert store.display_value("warmup") == "auto"
    store.set("mode", "advanced")
    assert store.display_value("warmup") == "stale"


def test_condition_matching_accepts_manifest_scalar_stringification() -> None:
    store = FieldStore(
        defaults={
            "mode": {"value": 1},
            "dependent": {"value": "ok", "rules": {"visible_if": {"mode": ["1"]}}},
        }
    )

    assert store.is_visible("dependent")


def test_field_store_validates_registered_values() -> None:
    store = FieldStore(
        defaults={
            "engine": {
                "value": "Native",
                "value_descriptor": {
                    "value_type": "enum",
                    "editor": "select",
                    "options": [{"value": "Native", "label": "Native"}, {"value": "Backtrader", "label": "Backtrader"}],
                },
            },
            "window": {
                "value": 20,
                "value_descriptor": {
                    "value_type": "number", "editor": "number", "minimum": 1, "maximum": 30,
                },
            },
            "enabled": {"value": False, "value_descriptor": {"value_type": "boolean", "editor": "boolean"}},
        }
    )

    store.validate_value("engine", "Native")
    store.validate_value("window", "20")
    try:
        store.validate_value("window", "31")
    except ValueError as exc:
        assert "大于最大值" in str(exc)
    else:
        raise AssertionError("expected maximum to fail")
    store.validate_value("enabled", "true")
    try:
        store.validate_value("engine", "Bad")
    except ValueError as exc:
        assert "字段 engine 的值不合法" in str(exc)
    else:
        raise AssertionError("expected invalid option to fail")


def test_empty_matches_frontend_core_values() -> None:
    assert is_empty(None)
    assert is_empty("")
    assert is_empty([])
    assert not is_empty(0)
    assert not is_empty(False)
