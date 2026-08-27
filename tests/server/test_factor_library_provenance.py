from __future__ import annotations

import json

import pytest

from server.services.factor_library_provenance import FactorLibraryProvenance


def _catalog() -> dict[str, object]:
    return {
        "factors": [
            {
                "factor_alias": "Mine|N:3m",
                "factor_family_alias": "Mine",
                "owner_username": "user@1",
                "owner_alias": "Mine",
                "product_group": "group-a",
                "params": {"N": "3m"},
                "source_code": "must not cross the control plane",
                "math_expr": "must not cross the control plane",
            },
            {
                "factor_alias": "Child|N:1m",
                "owner_username": "child@1",
                "owner_alias": "Child",
                "scope_key": "group-b",
            },
            {
                "factor_alias": "Public",
                "owner_username": "__public_jobs__",
            },
        ],
    }


def test_owners_list_only_visible_registered_user_libraries() -> None:
    value = FactorLibraryProvenance().owners(_catalog(), principal="user@1")

    assert value["sources"] == [
        {
            "owner_ref": "child@1",
            "owner_alias": "Child",
            "factor_count": 1,
        },
        {
            "owner_ref": "user@1",
            "owner_alias": "Mine",
            "factor_count": 1,
        },
    ]


def test_projection_is_source_free_deterministic_and_filterable() -> None:
    service = FactorLibraryProvenance()

    first = service.projection(
        _catalog(), principal="user@1", owner_ref="user@1",
    )
    second = service.projection(
        _catalog(), principal="user@1", owner_ref="user@1",
    )
    empty = service.projection(
        _catalog(), principal="user@1", owner_ref="user@1",
        product_group="group-b",
    )

    assert first["projection_hash"] == second["projection_hash"]
    assert first["projection"]["factors"] == [{
        "factor_alias": "Mine|N:3m",
        "factor_family_alias": "Mine",
        "owner_username": "user@1",
        "owner_alias": "Mine",
        "product_group": "group-a",
        "params": {"N": "3m"},
    }]
    assert empty["projection"]["factors"] == []
    encoded = json.dumps(first["projection"])
    assert "source_code" not in encoded
    assert "math_expr" not in encoded


def test_projection_rejects_an_owner_absent_from_visible_catalog() -> None:
    with pytest.raises(PermissionError, match="无权查看"):
        FactorLibraryProvenance().projection(
            _catalog(), principal="user@1", owner_ref="peer@1",
        )
