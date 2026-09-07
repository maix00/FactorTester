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


def test_product_group_creation_freezes_creator_and_research_metadata(
    monkeypatch,
) -> None:
    state = []
    monkeypatch.setattr(product_group_store, "_load_product_groups", lambda username: [])
    monkeypatch.setattr(
        product_group_store,
        "_save_product_groups",
        lambda username, groups: state.extend(dict(item) for item in groups),
    )
    monkeypatch.setattr(
        product_group_store,
        "_resolve_group_products",
        lambda paths: ["SI.GFE"],
    )

    group = product_group_store.create_product_group(
        "alice",
        "硅产业",
        ["Products/Futures/CNFutures/_products/SI.GFE"],
        creator_kind="profile",
        creator_ref="profile:maxa",
        research_refs=["work-package:research-one"],
    )

    assert group is not None
    assert group["creator_kind"] == "profile"
    assert group["creator_ref"] == "profile:maxa"
    assert group["research_refs"] == ["work-package:research-one"]
    assert "product_names" not in group  # Membership is frozen at submission.
    assert state == [{key: value for key, value in group.items()
                      if key not in {"selection_paths", "path_bindings", "path_count"}}]


def test_product_group_creation_defaults_to_logged_in_user(monkeypatch) -> None:
    monkeypatch.setattr(product_group_store, "_load_product_groups", lambda username: [])
    monkeypatch.setattr(product_group_store, "_save_product_groups", lambda username, groups: None)
    monkeypatch.setattr(product_group_store, "_resolve_group_products", lambda paths: [])

    group = product_group_store.create_product_group("alice", "默认组", ["path"])

    assert group is not None
    assert group["creator_kind"] == "user"
    assert group["creator_ref"] == "user:alice"
    assert group["research_refs"] == []


@pytest.mark.parametrize(
    ("creator_kind", "creator_ref", "research_refs"),
    [
        ("user", "user:bob", []),
        ("profile", "maxa", []),
        ("robot", "profile:maxa", []),
        ("profile", "profile:maxa", ["not-stable"]),
    ],
)
def test_product_group_creation_rejects_unstable_provenance(
    monkeypatch,
    creator_kind: str,
    creator_ref: str,
    research_refs: list[str],
) -> None:
    monkeypatch.setattr(product_group_store, "_load_product_groups", lambda username: [])

    with pytest.raises(ValueError):
        product_group_store.create_product_group(
            "alice",
            "无效组",
            ["path"],
            creator_kind=creator_kind,
            creator_ref=creator_ref,
            research_refs=research_refs,
        )
