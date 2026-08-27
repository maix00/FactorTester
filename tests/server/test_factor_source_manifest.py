from __future__ import annotations

from server.services import factor_source_manifest
from server.services.factor_source_manifest import FactorSourceManifest


def test_manifest_separates_public_own_and_authorized_child(monkeypatch) -> None:
    rows = {
        "public": [{"factor_id": "PublicOne", "source_code": "public"}],
        "custom": [
            {
                "owner_username": "parent",
                "factor_id": "OwnOne",
                "source_code": "own",
            },
            {
                "owner_username": "child",
                "factor_id": "ChildOne",
                "source_code": "child",
            },
            {
                "owner_username": "peer",
                "factor_id": "PeerOne",
                "source_code": "peer",
            },
        ],
    }
    monkeypatch.setattr(
        factor_source_manifest, "list_factor_sources", lambda kind: rows[kind],
    )
    monkeypatch.setattr(
        factor_source_manifest, "can_view_user_scope",
        lambda principal, owner: (principal, owner) == ("parent", "child"),
    )

    def item(**values):
        return {
            "factor_id": values["factor_id"],
            "owner_username": values["owner"],
            "scope": "public" if values["kind"] == "public" else (
                "own" if values["owner"] == values["principal"]
                else "subordinate"
            ),
            "path": FactorSourceManifest._source_path(
                values["kind"], values["owner"], values["factor_id"],
                values["principal"],
            ),
            "storage_server_id": values["server_id"],
        }

    monkeypatch.setattr(FactorSourceManifest, "_item", staticmethod(item))

    value = FactorSourceManifest().build(
        "parent", server_id="public-main", include_subordinates=True,
    )

    assert [item["factor_id"] for item in value["items"]] == [
        "OwnOne", "PublicOne", "ChildOne",
    ]
    assert value["items"][0]["path"] == "custom_factors/OwnOne.py"
    assert value["items"][2]["path"].startswith("remote_factors/")
    assert "source_code" not in str(value)


def test_manifest_can_exclude_subordinate_sources(monkeypatch) -> None:
    monkeypatch.setattr(
        factor_source_manifest, "list_factor_sources",
        lambda kind: [] if kind == "public" else [{
            "owner_username": "child",
            "factor_id": "ChildOne",
            "source_code": "child",
        }],
    )
    monkeypatch.setattr(
        factor_source_manifest, "can_view_user_scope", lambda *_args: True,
    )

    value = FactorSourceManifest().build(
        "parent", server_id="public-main", include_subordinates=False,
    )

    assert value["items"] == []
