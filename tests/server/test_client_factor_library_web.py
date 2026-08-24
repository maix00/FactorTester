from __future__ import annotations

import hashlib
import json

from flask import Flask

from server.modules.custom_factors import (
    catalog_routes,
    cf_bp,
    editor_routes,
    factor_library_routes,
    factor_library_service,
)
from server.modules.custom_factors.client_library import build_client_library_projection


def test_projection_overview_can_skip_expensive_product_scope_catalog(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(
        factor_library_service, "get_account",
        lambda username: {"username": username},
    )
    monkeypatch.setattr(factor_library_service, "list_public_factors", lambda: [])
    monkeypatch.setattr(factor_library_service, "list_custom_factors", lambda _owner: [])
    monkeypatch.setattr(
        factor_library_service, "list_factor_param_config_scopes", lambda _owner: [],
    )
    monkeypatch.setattr(
        factor_library_service,
        "list_factor_library_product_groups",
        lambda owner: calls.append(owner) or ["default", "expensive"],
    )

    compact = factor_library_service.build_factor_library_overview(
        "alice", include_subordinates=False, include_scope_catalog=False,
    )
    complete = factor_library_service.build_factor_library_overview(
        "alice", include_subordinates=False,
    )

    assert compact["scopes"] == compact["product_groups"] == []
    assert complete["scopes"] == complete["product_groups"] == [
        "default", "expensive",
    ]
    assert calls == ["alice"]


def _app() -> Flask:
    app = Flask(
        __name__,
        static_folder=None,
        template_folder=None,
    )
    app.secret_key = "client-library-test"
    app.register_blueprint(cf_bp)
    return app


def _login(client, username: str = "alice") -> None:
    with client.session_transaction() as session:
        session["username"] = username


def test_public_source_applied_requires_superadmin_and_verifies_source(
    monkeypatch,
) -> None:
    source = "class PublicAlpha:\n    pass\n"
    raw = source.encode()
    digest = hashlib.sha256(raw).hexdigest()
    invalidated: list[str] = []
    monkeypatch.setattr(editor_routes, "get_account", lambda name: {"name": name})
    monkeypatch.setattr(
        editor_routes, "is_super_admin_account", lambda account: account["name"] == "root",
    )
    monkeypatch.setattr(
        editor_routes, "load_public_factor_source", lambda factor_id: source,
    )
    monkeypatch.setattr(
        editor_routes, "invalidate_factor_family_cache", invalidated.append,
    )
    client = _app().test_client()
    payload = {"factors": [{
        "factor_id": "PublicAlpha",
        "source_sha256": digest,
        "source_bytes": len(raw),
    }]}

    _login(client, "alice")
    assert client.post(
        "/custom-factors/api/internal/public-source-applied", json=payload,
    ).status_code == 403
    _login(client, "root")
    response = client.post(
        "/custom-factors/api/internal/public-source-applied", json=payload,
    )

    assert response.status_code == 200
    assert response.get_json()["applied"] == ["PublicAlpha"]
    assert invalidated == ["PublicAlpha"]


def test_embedded_library_api_is_sanitized_and_redacts_local_paths(
    monkeypatch,
) -> None:
    calls: list[dict] = []

    def overview(
        username,
        include_subordinates,
        product_group=None,
        factor_family_alias=None,
    ):
        calls.append({
            "username": username,
            "include_subordinates": include_subordinates,
            "product_group": product_group,
            "factor_family_alias": factor_family_alias,
        })
        return {
            "factors": [{
                "id": "private-db-id",
                "factor_alias": "SgCCS|N:2m",
                "factor_family_alias": "SgCCS",
                "factor_family_name": "SgCCS",
                "chinese_name": "期限结构",
                "category": "期限结构",
                "source": "custom",
                "source_code": "class Secret: pass",
                "math_expr": r"\frac{x}{y}",
                "tree_repr": "private expression tree",
                "source_path": "/Users/alice/Secret.py",
                "params": [
                    {"alias": "N", "value": "2m"},
                    {
                        "alias": "local_file",
                        "value": "/Users/alice/private_factor.py",
                    },
                    {
                        "alias": "server_file",
                        "value": "/opt/factortester/factor.py:12",
                    },
                ],
                "owner_username": "alice",
                "owner_alias": "Alice",
                "owner_organization_name": "Research",
                "product_group": "CNFutures",
                "updated_at": "2026-07-20",
            }],
            "errors": [{
                "error": "/Users/alice/private_factor.py failed",
            }],
        }

    monkeypatch.setattr(
        factor_library_routes,
        "build_factor_library_overview",
        overview,
    )
    client = _app().test_client()
    _login(client)

    response = client.get(
        "/custom-factors/api/client/factor-library"
        "?include_subordinates=1&product_group=CNFutures"
        "&factor_family_alias=SgCCS"
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert calls == [{
        "username": "alice",
        "include_subordinates": True,
        "product_group": "CNFutures",
        "factor_family_alias": "SgCCS",
    }]
    assert payload["mode"] == "embedded_read_only_library"
    assert payload["schema_version"] == 2
    assert payload["families"][0]["factor_family_alias"] == "SgCCS"
    assert payload["factors"][0]["params"] == [
        {"alias": "N", "redacted": False, "value": "2m"},
        {"alias": "local_file", "redacted": True, "value": None},
        {"alias": "server_file", "redacted": True, "value": None},
    ]
    assert payload["omitted_error_count"] == 1
    assert "product_group_refs" not in payload["factors"][0]
    assert "product_group_names" not in payload["factors"][0]
    assert "product_group_refs" not in payload["families"][0]
    serialized = json.dumps(payload, ensure_ascii=False)
    assert payload["families"][0]["math_expr"] == r"\frac{x}{y}"
    for forbidden in (
        "source_code",
        "tree_repr",
        "source_path",
        "/Users/",
        "/opt/",
        "private_factor.py",
        "class Secret",
    ):
        assert forbidden not in serialized


def test_factor_projection_deduplicates_old_scopes_without_owning_group_refs() -> None:
    base = {
        "factor_alias": "SgCCS|N:2m",
        "factor_family_alias": "SgCCS",
        "owner_username": "alice",
        "owner_alias": "Alice",
        "source": "custom",
    }

    payload = build_client_library_projection({
        "factors": [
            {**base, "product_group": "日盘"},
            {**base, "product_group": "夜盘"},
        ],
    }, principal="alice")

    assert len(payload["factors"]) == 1
    assert payload["families"][0]["factor_count"] == 1
    assert "product_group_refs" not in payload["factors"][0]
    assert "product_group_names" not in payload["factors"][0]
    assert "product_groups" not in payload
    assert payload["factors"][0]["factor_owner_ref"] == "alice"
    assert payload["factors"][0]["factor_family_ref"]
    assert payload["factors"][0]["factor_params"] == payload["factors"][0]["params"]
    assert "factor_git_commit" not in payload["factors"][0]


def test_factor_projection_preserves_historical_source_marker_per_factor() -> None:
    payload = build_client_library_projection({
        "factors": [{
            "factor_alias": "Momentum|window:20",
            "factor_family_alias": "Momentum",
            "owner_username": "alice",
            "factor_owner_ref": "profile:alice",
            "factor_family_ref": "family:momentum",
            "factor_git_commit": "a" * 40,
            "params": [{"alias": "window", "value": "20"}],
            "source": "custom",
        }],
    }, principal="alice")

    factor = payload["factors"][0]
    assert factor["factor_owner_ref"] == "profile:alice"
    assert factor["factor_family_ref"] == "family:momentum"
    assert factor["factor_params"] == factor["params"]
    assert factor["factor_git_commit"] == "a" * 40


def test_source_version_route_exposes_stable_factor_family_identity(monkeypatch) -> None:
    source = "class Momentum(FactorFamily):\n    pass\n"
    monkeypatch.setattr(catalog_routes, "can_view_user_scope", lambda *_: True)
    monkeypatch.setattr(
        catalog_routes, "load_factor_source", lambda _owner, _family: source,
    )
    monkeypatch.setattr(
        catalog_routes,
        "list_factor_source_versions",
        lambda **_kwargs: {
            "available": True,
            "versions": [],
            "current": {"commit": "a" * 40, "is_current": True},
        },
    )
    client = _app().test_client()
    _login(client, "alice")

    response = client.get(
        "/custom-factors/api/source-versions/custom/Momentum",
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["factor_owner_ref"] == "alice"
    assert payload["factor_family_ref"].startswith("factor-family:sha256:")
    assert payload["current"]["commit"] == "a" * 40


def test_client_library_keeps_public_family_templates_out_of_factor_rows() -> None:
    payload = build_client_library_projection({
        "families": [{
            "factor_family_alias": "PublicMomentum",
            "factor_family_name": "PublicMomentum",
            "chinese_name": "公共动量",
            "owner_username": "__public_jobs__",
            "owner_alias": "公共因子库",
            "source": "public",
            "params": [{"alias": "window", "value": "20"}],
        }],
        "factors": [{
            "factor_family_alias": "PublicMomentum",
            "factor_family_name": "PublicMomentum",
            "factor_alias": "PublicMomentum|window:20",
            "owner_username": "alice",
            "owner_alias": "Alice",
            "source": "public",
            "params": [{"alias": "window", "value": "20"}],
        }],
    }, principal="alice")

    assert len(payload["families"]) == 2
    public = next(
        item for item in payload["families"]
        if item["owner_username"] == "__public_jobs__"
    )
    mine = next(
        item for item in payload["families"]
        if item["owner_username"] == "alice"
    )
    assert payload["factors"][0]["owner_username"] == "alice"
    assert public["factor_count"] == 0
    assert public["params"][0]["alias"] == "window"
    assert mine["factor_count"] == 1


def test_workspace_snapshot_exposes_server_git_state_but_rejects_direct_source_import(
    monkeypatch,
) -> None:
    rows = {
        "custom": [{
            "owner_username": "alice",
            "factor_id": "LocalAlpha",
            "source_code": "class LocalAlpha: pass\n",
        }],
        "public": [{
            "owner_username": "",
            "factor_id": "PublicAlpha",
            "source_code": "class PublicAlpha: pass\n",
        }],
    }
    monkeypatch.setattr(editor_routes, "list_factor_sources", lambda kind: rows[kind])
    monkeypatch.setattr(
        editor_routes,
        "get_factor_workspace_git_state",
        lambda username: {
            "workspace_root": "/srv/factors/alice",
            "git_head": "abc1234",
            "git_current_branch": "main",
        },
    )
    monkeypatch.setattr(editor_routes, "get_account", lambda username: {})
    monkeypatch.setattr(editor_routes, "is_super_admin_account", lambda account: False)

    client = _app().test_client()
    _login(client)
    response = client.get("/custom-factors/api/workspace/snapshot")
    assert response.status_code == 200
    snapshot = response.get_json()["snapshot"]
    assert snapshot["git_head"] == "abc1234"
    assert [item["path"] for item in snapshot["files"]] == [
        "custom_factors/LocalAlpha.py",
        "public_factors/PublicAlpha.py",
    ]
    assert all("source_code" not in item for item in snapshot["files"])
    assert all(item["source_sha256"] for item in snapshot["files"])

    imported = client.post(
        "/custom-factors/api/workspace/snapshot",
        json={
            "snapshot": {
                "files": [{
                    "path": "custom_factors/NextAlpha.py",
                    "source_code": "class NextAlpha: pass\n",
                }],
            },
        },
    )
    assert imported.status_code == 410
    assert imported.get_json()["code"] == "workspace_snapshot_write_disabled"


def test_validate_transient_factor_returns_instantiated_alias_and_formula() -> None:
    client = _app().test_client()
    _login(client)
    source = "\n".join((
        "from tools.factors import FactorFamily",
        "from tools.parameters import DataColumnParam, WindowParam",
        "class UploadedMomentum(FactorFamily):",
        "    desc = '上传动量'",
        "    @staticmethod",
        "    def factor_expr():",
        "        P = DataColumnParam('P', default_value='CA')",
        "        N = WindowParam('N', default_value='2d')",
        "        return P / P.shift(N) - 1",
        "",
    ))

    response = client.post(
        "/custom-factors/api/validate",
        json={"source_code": source, "params": {"P": "CA", "N": "5d"}},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["valid"] is True
    assert payload["factor_name"] == "UploadedMomentum"
    assert payload["factor_alias"].startswith("UploadedMomentum|P:CA|N:5d")
    assert payload["normalized_params"]["N"] == "5d"
    assert r"\frac" in payload["math_expr"]
