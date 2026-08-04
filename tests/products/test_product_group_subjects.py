from __future__ import annotations

import pytest

from server.modules.products import product_group_store


def _store(monkeypatch):
    state = [{
        "id": "pg-metals",
        "name": "金属",
        "paths": ["Futures/Metals"],
        "product_names": ["SI.GFE"],
        "factor_refs": [],
        "factor_set_refs": [],
    }]

    monkeypatch.setattr(
        product_group_store,
        "_load_product_groups",
        lambda username: [dict(item) for item in state],
    )

    def save(username, groups):
        state[:] = [dict(item) for item in groups]

    monkeypatch.setattr(product_group_store, "_save_product_groups", save)
    return state


def test_product_group_owns_factor_and_factor_set_associations(monkeypatch) -> None:
    state = _store(monkeypatch)

    value = product_group_store.change_product_group_subjects(
        "alice",
        "product-group:pg-metals",
        action="add",
        factor_refs=["factor:sha256:factor-a"],
        factor_set_refs=["factor-set:profile-alice:momentum"],
    )

    assert value == {
        "product_group_ref": "product-group:pg-metals",
        "product_group_id": "pg-metals",
        "product_group_name": "金属",
        "factor_refs": ["factor:sha256:factor-a"],
        "factor_set_refs": ["factor-set:profile-alice:momentum"],
    }
    assert state[0]["factor_refs"] == ["factor:sha256:factor-a"]
    assert state[0]["factor_set_refs"] == ["factor-set:profile-alice:momentum"]

    removed = product_group_store.change_product_group_subjects(
        "alice",
        "product-group:pg-metals",
        action="remove",
        factor_refs=["factor:sha256:factor-a"],
        factor_set_refs=[],
    )
    assert removed["factor_refs"] == []
    assert removed["factor_set_refs"] == ["factor-set:profile-alice:momentum"]


def test_product_group_subjects_rejects_family_and_empty_changes(monkeypatch) -> None:
    _store(monkeypatch)

    with pytest.raises(ValueError, match="invalid reference"):
        product_group_store.change_product_group_subjects(
            "alice",
            "product-group:pg-metals",
            action="add",
            factor_refs=["factor-family:v1:family-a"],
            factor_set_refs=[],
        )
    with pytest.raises(ValueError, match="at least one"):
        product_group_store.change_product_group_subjects(
            "alice",
            "product-group:pg-metals",
            action="add",
            factor_refs=[],
            factor_set_refs=[],
        )
