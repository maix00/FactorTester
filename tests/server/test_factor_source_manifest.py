from __future__ import annotations

from server.services import factor_source_manifest
from server.services.factor_source_manifest import FactorSourceManifest


def test_manifest_separates_public_own_and_authorized_child(monkeypatch) -> None:
    rows = {
        "public": [{"factor_id": "PublicOne", "family_formula_fingerprint": "p" * 64}],
        "custom": [
            {
                "owner_username": "parent",
                "factor_id": "OwnOne",
                "family_formula_fingerprint": "o" * 64,
            },
            {
                "owner_username": "child",
                "factor_id": "ChildOne",
                "family_formula_fingerprint": "c" * 64,
            },
            {
                "owner_username": "peer",
                "factor_id": "PeerOne",
                "family_formula_fingerprint": "x" * 64,
            },
        ],
    }
    monkeypatch.setattr(
        factor_source_manifest, "list_factor_summaries",
        lambda kind, owner="": rows[kind],
    )
    checked = []
    monkeypatch.setattr(
        factor_source_manifest, "keycloak_authorized_factor_sources",
        lambda token, *, refs, scope: checked.extend(refs) or {
            ("parent", "OwnOne"), ("child", "ChildOne"),
        },
    )
    loaded = []
    monkeypatch.setattr(
        factor_source_manifest, "load_public_factor_source",
        lambda factor_id: "public" if factor_id == "PublicOne" else None,
    )
    monkeypatch.setattr(
        factor_source_manifest, "load_factor_source",
        lambda owner, factor_id: loaded.append((owner, factor_id)) or {
            ("parent", "OwnOne"): "own",
            ("child", "ChildOne"): "child",
            ("peer", "PeerOne"): "peer",
        }.get((owner, factor_id), ""),
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
            "family_formula_fingerprint": values["family_formula_fingerprint"],
        }

    monkeypatch.setattr(FactorSourceManifest, "_item", staticmethod(item))

    value = FactorSourceManifest().build(
        "parent", server_id="public-main", access_token="verified-token",
        include_subordinates=True,
    )

    assert [item["factor_id"] for item in value["items"]] == [
        "OwnOne", "PublicOne", "ChildOne",
    ]
    assert value["items"][0]["path"] == "custom_factors/OwnOne.py"
    assert value["items"][2]["path"].startswith("remote_factors/")
    assert "source_code" not in str(value)
    assert checked == [
        ("parent", "OwnOne"), ("child", "ChildOne"), ("peer", "PeerOne"),
    ]
    assert loaded == [("parent", "OwnOne"), ("child", "ChildOne")]


def test_manifest_can_exclude_subordinate_sources(monkeypatch) -> None:
    monkeypatch.setattr(
        factor_source_manifest, "list_factor_summaries",
        lambda kind, owner="": [] if kind == "public" else [{
            "owner_username": "child",
            "factor_id": "ChildOne",
            "family_formula_fingerprint": "c" * 64,
        }],
    )
    monkeypatch.setattr(
        factor_source_manifest, "keycloak_authorized_factor_sources",
        lambda *_args, **_kwargs: {("child", "ChildOne")},
    )
    monkeypatch.setattr(
        factor_source_manifest, "load_factor_source", lambda *_args: "child",
    )

    value = FactorSourceManifest().build(
        "parent", server_id="public-main", access_token="verified-token",
        include_subordinates=False,
    )

    assert value["items"] == []
