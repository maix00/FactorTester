from __future__ import annotations

import hashlib
import json
import pytest

from flask import Flask

from server.manager.services import public_catalog
from server.manager.services.account_domain_projection import factor_rows_from_sync
from server.manager.services.client_factor_catalog import ClientFactorCatalogMixin
from server.manager.services.federated_factor_projection import (
    merge_factor_library_projections,
)
from server.modules.custom_factors import (
    catalog_routes,
    editor_routes,
    factor_library_internal_bp,
    factor_library_service,
)
from server.modules.custom_factors.client_library import build_client_library_projection
from tools.cli.release.research_reporting.references.factor_formula import (
    build_factor_reference,
)
from tools.factors.formula_identity import freeze_factor_identity


@pytest.fixture(autouse=True)
def isolated_catalog_database(tmp_path, monkeypatch):
    import settings as Settings
    monkeypatch.setattr(Settings, 'CACHE_DB_PATH', tmp_path / 'catalog.sqlite')


def _frozen_factor(
    *, alias: str, family: str, owner_ref: str = "principal:alice",
) -> dict[str, str]:
    identity = {
        "owner_ref": owner_ref,
        "family_alias": family,
        "factor_alias": alias,
        "family_formula_fingerprint": "a" * 64,
        "self_formula_fingerprint": "b" * 64,
    }
    return {
        "factor_ref": build_factor_reference(**identity),
        "factor_owner_ref": owner_ref,
        "family_formula_fingerprint": identity["family_formula_fingerprint"],
        "self_formula_fingerprint": identity["self_formula_fingerprint"],
    }


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
    app.register_blueprint(factor_library_internal_bp)
    return app


def _login(client, username: str = "alice") -> None:
    with client.session_transaction() as session:
        session["username"] = username


def test_account_domain_projection_requires_complete_v2_factor_records() -> None:
    frozen = freeze_factor_identity(
        owner_ref="principal:alice",
        family_alias="Momentum",
        factor_alias="Momentum|N:20d",
        family_formula_fingerprint="a" * 64,
        self_formula_fingerprint="b" * 64,
        params={"N": "20d"},
    )

    class Sync:
        @staticmethod
        def entities(*_args, **_kwargs):
            return [{
                "principal": "alice",
                "entity_id": "default:Momentum",
                "payload": {
                    "schema_version": 2,
                    "factor_family_alias": "Momentum",
                    "resolved_factors": [
                        frozen,
                        {"factor_alias": "Momentum:0"},
                    ],
                },
            }]

    rows = factor_rows_from_sync(Sync(), "alice")

    assert len(rows) == 1
    assert rows[0]["factor_ref"] == frozen["ref"]
    assert rows[0]["factor_alias"] == "Momentum|N:20d"
    assert rows[0]["family_formula_fingerprint"] == "a" * 64


def test_account_domain_projection_restores_early_v2_record_without_ref() -> None:
    legacy = {
        "factor_owner_ref": "principal:alice",
        "factor_family_alias": "Momentum",
        "factor_alias": "Momentum|N:20d",
        "family_formula_fingerprint": "a" * 64,
        "self_formula_fingerprint": "b" * 64,
        "factor_params": [{"alias": "N", "value": "20d"}],
    }

    class Sync:
        @staticmethod
        def entities(*_args, **_kwargs):
            return [{
                "principal": "alice",
                "entity_id": "default:Momentum",
                "payload": {
                    "factor_family_alias": "Momentum",
                    "resolved_factors": [legacy],
                },
            }]

    rows = factor_rows_from_sync(Sync(), "alice")

    assert len(rows) == 1
    assert rows[0]["factor_alias"] == "Momentum|N:20d"
    assert rows[0]["factor_ref"].startswith("factor:v2:")


def test_source_family_projections_preserve_formula_fingerprint(monkeypatch) -> None:
    source = {
        "id": "Momentum",
        "name": "Momentum",
        "family_formula_fingerprint": "c" * 64,
        "params": [{
            "alias": "N",
            "type": "WindowParam",
            "default_value": "20d",
        }],
    }
    monkeypatch.setattr(
        "server.modules.custom_factors.catalog.list_public_factors",
        lambda: [source],
    )
    monkeypatch.setattr(
        "server.modules.custom_factors.catalog.list_custom_factors",
        lambda _username: [source],
    )

    public = public_catalog.public_factor_library()
    custom = ClientFactorCatalogMixin._custom_source_families("alice")

    assert public["families"][0]["family_formula_fingerprint"] == "c" * 64
    assert custom[0]["family_formula_fingerprint"] == "c" * 64
    assert custom[0]["params"] == source["params"]
    assert public["families"][0]["parameter_definitions"][0]["type"] == "WindowParam"
    assert custom[0]["parameter_definitions"][0]["type"] == "WindowParam"


def test_factor_projection_inherits_typed_definitions_from_matching_family() -> None:
    frozen = _frozen_factor(
        alias="Momentum|N:5d",
        family="Momentum",
    )
    payload = build_client_library_projection({
        "families": [{
            "factor_family_alias": "Momentum",
            "factor_family_name": "Momentum",
            "owner_username": "alice",
            "owner_alias": "Alice",
            "factor_owner_ref": "principal:alice",
            "source": "custom",
            "family_formula_fingerprint": "a" * 64,
            "params": [{
                "alias": "N",
                "type": "WindowParam",
                "default_value": "20d",
            }],
        }],
        "factors": [{
            "factor_alias": "Momentum|N:5d",
            "factor_family_alias": "Momentum",
            "factor_family_name": "Momentum",
            "owner_username": "alice",
            "owner_alias": "Alice",
            "source": "custom",
            "params": [{"alias": "N", "value": "5d"}],
            **frozen,
        }],
    }, principal="alice")

    definitions = payload["factors"][0]["parameter_definitions"]
    assert definitions[0]["type"] == "WindowParam"
    assert definitions[0]["default_value"] == "20d"
    assert definitions[0]["value"] == "5d"


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
        "/api/internal/factor-library/public-source-applied",
        json=payload,
    ).status_code == 403
    _login(client, "root")
    response = client.post(
        "/api/internal/factor-library/public-source-applied",
        json=payload,
    )

    assert response.status_code == 200
    assert response.get_json()["applied"] == ["PublicAlpha"]
    assert invalidated == ["PublicAlpha"]


def test_embedded_library_api_is_sanitized_and_redacts_local_paths(
) -> None:
    payload = build_client_library_projection(
        {
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
                "resolved_math_expr": r"\textcolor{red}{-}\operatorname{Resample}_{\textcolor{red}{10m}}(x)",
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
                **_frozen_factor(alias="SgCCS|N:2m", family="SgCCS"),
            }],
            "errors": [{
                "error": "/Users/alice/private_factor.py failed",
            }],
        },
        principal="alice",
    )
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
    assert payload["factors"][0]["resolved_math_expr"] == (
        r"\textcolor{red}{-}\operatorname{Resample}_{\textcolor{red}{10m}}(x)"
    )
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
        **_frozen_factor(alias="SgCCS|N:2m", family="SgCCS"),
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
    assert payload["factors"][0]["factor_owner_ref"] == "principal:alice"
    assert "factor_family_ref" not in payload["factors"][0]
    assert payload["factors"][0]["factor_params"] == payload["factors"][0]["params"]
    assert "factor_git_commit" not in payload["factors"][0]


def test_factor_projection_preserves_formula_identity_per_factor() -> None:
    payload = build_client_library_projection({
        "factors": [{
            "factor_alias": "Momentum|window:20",
            "factor_family_alias": "Momentum",
            "owner_username": "alice",
            "factor_owner_ref": "profile:alice",
            "family_formula_fingerprint": "a" * 64,
            "self_formula_fingerprint": "b" * 64,
            **_frozen_factor(
                alias="Momentum|window:20",
                family="Momentum",
                owner_ref="profile:alice",
            ),
            "params": [{"alias": "window", "value": "20"}],
            "source": "custom",
        }],
    }, principal="alice")

    factor = payload["factors"][0]
    assert factor["schema_version"] == 2
    assert factor["ref"] == factor["factor_ref"]
    assert factor["alias"] == factor["factor_alias"]
    assert factor["owner_ref"] == "profile:alice"
    assert factor["identity"] == {
        "family_ref": factor["identity"]["family_ref"],
        "family_alias": "Momentum",
        "family_formula_fingerprint": "a" * 64,
        "self_formula_fingerprint": "b" * 64,
        "params": {"window": "20"},
    }
    assert factor["factor_owner_ref"] == "profile:alice"
    assert factor["factor_params"] == factor["params"]
    assert factor["family_formula_fingerprint"] == "a" * 64
    assert factor["self_formula_fingerprint"] == "b" * 64
    assert "factor_git_commit" not in factor
    assert "factor_family_ref" not in factor


def test_factor_projection_preserves_nested_dependency_siblings() -> None:
    # Nested FactorParam factors are referenced from identity.params and must
    # stay reachable through factor_dependencies on the projected catalog row.
    # factorSubjects flattens those dependency links into RunSpec sibling
    # records; dropping them freezes a factor whose nested ref is missing, and
    # the server resolver rejects the configuration ("FactorParam 引用未在
    # RunSpec 中冻结").
    outer = {
        "factor_alias": "SgChgDurDay|Th:24",
        "factor_family_alias": "SgChgDurDay",
        "owner_username": "alice",
        "factor_owner_ref": "profile:alice",
        "family_formula_fingerprint": "a" * 64,
        "self_formula_fingerprint": "b" * 64,
        **_frozen_factor(
            alias="SgChgDurDay|Th:24",
            family="SgChgDurDay",
            owner_ref="profile:alice",
        ),
        "params": [{"alias": "Th", "value": "factor:v2:dependencydigest"}],
        "source": "custom",
    }
    nested_identity = {
        "family_ref": "factor-family:v2:familydigest",
        "family_alias": "SgChgPct",
        "family_formula_fingerprint": "c" * 64,
        "self_formula_fingerprint": "d" * 64,
        "params": {},
    }
    nested = {
        "schema_version": 2,
        "ref": "factor:v2:dependencydigest",
        "alias": "SgChgPct|Th:0",
        "owner_ref": "profile:alice",
        "identity": nested_identity,
    }
    payload = build_client_library_projection({
        "factors": [{**outer, "factor_dependencies": [nested]}],
    }, principal="alice")

    factor = payload["factors"][0]
    dependencies = factor["factor_dependencies"]
    assert len(dependencies) == 1
    assert dependencies[0]["ref"] == "factor:v2:dependencydigest"
    assert dependencies[0]["alias"] == "SgChgPct|Th:0"
    assert dependencies[0]["identity"]["family_alias"] == "SgChgPct"
    assert factor["identity"]["params"] == {"Th": "factor:v2:dependencydigest"}


def test_factor_projection_omits_empty_dependency_lists() -> None:
    payload = build_client_library_projection({
        "factors": [{
            "factor_alias": "Plain",
            "factor_family_alias": "Plain",
            "owner_username": "alice",
            "factor_owner_ref": "profile:alice",
            "family_formula_fingerprint": "a" * 64,
            "self_formula_fingerprint": "b" * 64,
            **_frozen_factor(
                alias="Plain",
                family="Plain",
                owner_ref="profile:alice",
            ),
            "params": [],
            "source": "custom",
            "factor_dependencies": [],
        }],
    }, principal="alice")
    assert "factor_dependencies" not in payload["factors"][0]


def test_family_projection_merges_registered_historical_factor_into_current_family() -> None:
    """A registered factor revision is a member, not a second family row."""
    payload = build_client_library_projection({
        "families": [{
            "factor_family_alias": "CA",
            "factor_family_name": "CA",
            "description": "复权收盘价",
            "category": "价格",
            "owner_username": "alice",
            "owner_alias": "Alice",
            "factor_owner_ref": "principal:alice",
            "source": "custom",
            "family_formula_fingerprint": "c" * 64,
        }],
        "factors": [{
            "factor_alias": "CA",
            "factor_family_alias": "CA",
            "owner_username": "alice",
            "owner_alias": "Alice",
            "source": "custom",
            **_frozen_factor(alias="CA", family="CA"),
        }],
    }, principal="alice")

    assert len(payload["families"]) == 1
    family = payload["families"][0]
    assert family["description"] == "复权收盘价"
    assert family["categories"] == ["价格"]
    assert family["family_formula_fingerprint"] == "c" * 64
    assert family["factor_count"] == 1
    assert family["factor_refs"] == [payload["factors"][0]["factor_ref"]]


def test_federated_projection_keeps_source_family_and_merges_member_counts() -> None:
    source = {
        "family_ref": "family:current",
        "factor_family_alias": "Momentum",
        "description": "当前说明",
        "categories": ["动量"],
        "owner_username": "__public_jobs__",
        "factor_owner_ref": "public",
        "source": "public",
        "factor_kind": "public",
        "has_source_definition": True,
        "family_formula_fingerprint": "c" * 64,
        "factor_count": 0,
        "factor_refs": [],
    }
    member = {
        "family_ref": "family:historical",
        "factor_family_alias": "Momentum",
        "owner_username": "__public_jobs__",
        "factor_owner_ref": "public",
        "source": "public",
        "factor_kind": "public",
        "has_source_definition": False,
        "family_formula_fingerprint": "a" * 64,
        "factor_count": 1,
        "factor_refs": ["factor:v2:member"],
    }

    payload = merge_factor_library_projections([
        {"schema_version": 2, "families": [source], "factors": []},
        {"schema_version": 2, "families": [member], "factors": []},
    ], principal="alice")

    assert len(payload["families"]) == 1
    family = payload["families"][0]
    assert family["family_ref"] == "family:current"
    assert family["family_formula_fingerprint"] == "c" * 64
    assert family["description"] == "当前说明"
    assert family["factor_count"] == 1


def test_source_version_route_exposes_stable_factor_family_identity(monkeypatch) -> None:
    fingerprint = "a" * 64
    monkeypatch.setattr(
        catalog_routes._SOURCE_CATALOG,
        "versions",
        lambda *_args, **_kwargs: {
            "success": True,
            "factor_owner_ref": "alice",
            "factor_family_alias": "Momentum",
            "current_fingerprint": fingerprint,
            "versions": [{
                "family_formula_fingerprint": fingerprint,
                "is_current": True,
            }],
        },
    )
    client = _app().test_client()
    _login(client, "alice")

    response = client.get(
        "/api/internal/factor-library/family-sources/custom/Momentum/versions",
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["factor_owner_ref"] == "alice"
    assert payload["factor_family_alias"] == "Momentum"
    assert "factor_family_ref" not in payload
    assert payload["current_fingerprint"] == fingerprint
    assert payload["versions"][0]["family_formula_fingerprint"] == fingerprint


def test_source_version_route_returns_persisted_snapshot_without_current_source(
    monkeypatch,
) -> None:
    fingerprint = "b" * 64
    source = "class Momentum(FactorFamily):\n    pass\n"
    monkeypatch.setattr(
        catalog_routes._SOURCE_CATALOG,
        "version",
        lambda *_args, **_kwargs: {
            "success": True,
            "family_formula_fingerprint": fingerprint,
            "source_code": source,
            "source_sha256": "hash",
            "source_kind": "public",
            "math_expr": "P_t",
            "chinese_name": "动量",
            "description": "历史版本",
            "params": [],
        },
    )
    client = _app().test_client()
    _login(client)

    response = client.get(
        f"/api/internal/factor-library/family-sources/public/Momentum/versions/{fingerprint}",
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["family_formula_fingerprint"] == fingerprint
    assert payload["source_code"] == source
    assert payload["source_kind"] == "public"


def test_source_version_current_returns_live_family_source(monkeypatch) -> None:
    source = "class Momentum(FactorFamily):\n    pass\n"
    fingerprint = "d" * 64
    monkeypatch.setattr(
        catalog_routes._SOURCE_CATALOG,
        "version",
        lambda *_args, **_kwargs: {
            "success": True,
            "source_code": source,
            "math_expr": "P_t-P_{t-1}",
            "family_formula_fingerprint": fingerprint,
            "factor_family_alias": "Momentum",
            "params": [],
        },
    )
    client = _app().test_client()
    _login(client)

    response = client.get(
        "/api/internal/factor-library/family-sources/public/Momentum/versions/current",
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["source_code"] == source
    assert payload["family_formula_fingerprint"] == fingerprint
    assert payload["factor_family_alias"] == "Momentum"


def test_client_library_keeps_public_family_templates_out_of_factor_rows() -> None:
    payload = build_client_library_projection({
        "families": [{
            "factor_family_alias": "PublicMomentum",
            "factor_family_name": "PublicMomentum",
            "chinese_name": "公共动量",
            "owner_username": "__public_jobs__",
            "owner_alias": "公共因子库",
            "source": "public",
            "factor_owner_ref": "public",
            "family_formula_fingerprint": "a" * 64,
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
            **_frozen_factor(
                alias="PublicMomentum|window:20",
                family="PublicMomentum",
                owner_ref="public",
            ),
        }],
    }, principal="alice")

    assert len(payload["families"]) == 1
    public = payload["families"][0]
    assert payload["factors"][0]["owner_username"] == "alice"
    assert public["params"][0]["alias"] == "window"
    assert public["factor_count"] == 1


def test_public_factor_registration_does_not_manufacture_user_family() -> None:
    payload = build_client_library_projection({
        "factors": [{
            "factor_family_alias": "PublicMomentum",
            "factor_family_name": "PublicMomentum",
            "factor_alias": "PublicMomentum|window:20",
            "owner_username": "alice",
            "owner_alias": "Alice",
            "source": "public",
            "params": [{"alias": "window", "value": "20"}],
            **_frozen_factor(
                alias="PublicMomentum|window:20",
                family="PublicMomentum",
                owner_ref="public",
            ),
        }],
    }, principal="alice")

    assert len(payload["factors"]) == 1
    assert payload["families"] == []


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
        "/api/internal/factor-library/validate",
        json={"source_code": source, "params": {"P": "CA", "N": "5d"}},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["valid"] is True
    assert payload["factor_name"] == "UploadedMomentum"
    assert payload["factor_alias"].startswith("UploadedMomentum|P:CA|N:5d")
    assert payload["normalized_params"]["N"] == "5d"
    assert r"\frac" in payload["math_expr"]


def test_validate_transient_factor_uses_defaults_when_params_are_omitted() -> None:
    client = _app().test_client()
    _login(client)
    source = "\n".join((
        "from tools.factors import FactorFamily",
        "from tools.parameters import DataColumnParam, WindowParam",
        "class DefaultMomentum(FactorFamily):",
        "    @staticmethod",
        "    def factor_expr():",
        "        P = DataColumnParam('P', default_value='CA')",
        "        N = WindowParam('N', default_value='25d')",
        "        return P / P.shift(N) - 1",
        "",
    ))

    response = client.post(
        "/api/internal/factor-library/validate",
        json={"source_code": source},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["valid"] is True
    assert payload["normalized_params"]["N"] == "25d"


def test_validate_transient_duration_factor_supports_bar_distance_source() -> None:
    client = _app().test_client()
    _login(client)
    source = "\n".join((
        "from tools.factors import CANDIDATE, CURRENT, FactorFamily, scope_bars",
        "from tools.factors.FactorExpr import CLOSE, VOLUME",
        "from tools.parameters import FactorParam, WindowParam",
        "class DurationSignal(FactorFamily):",
        "    source_freq = '1m'",
        "    @staticmethod",
        "    def factor_expr():",
        "        Th = FactorParam('Th', default_value=0.001)",
        "        K = WindowParam('K', default_value='30m')",
        "        match = (CURRENT - CANDIDATE).abs() / (CURRENT.abs() + 1e-10) >= Th",
        "        pdur = CLOSE.bar_distance(match, scope=scope_bars(K))",
        "        vdur = VOLUME.bar_distance(match, scope=scope_bars(K))",
        "        return ((pdur + vdur) / 2.0).as_intermediate('差持续期')",
        "",
    ))

    response = client.post(
        "/api/internal/factor-library/validate",
        json={"source_code": source},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["valid"] is True, payload
    assert payload["normalized_params"]["Th"] == "0.001"
    assert payload["normalized_params"]["K"] == "30m"
    assert r"\min_{[t-k,t]\in" in payload["math_expr"]
    assert r"\operatorname{argm" not in payload["math_expr"]
    assert r"\operatorname{ScopeBars}" in payload["math_expr"]
    assert (
        r"\operatorname{ScopeBars}\left(\textcolor{red}{K}\right)"
        in payload["math_expr"]
    )
    assert payload["math_expr"].count(":=") == 4
    assert r"\mathrm{差持续期}_t" in payload["math_expr"]
    # The bar-distance search body is rendered as a single-column continuation
    # so KaTeX does not move either row into an alignment column.
    assert r"\left\{k\middle|\begin{aligned}X_t:=" in payload["math_expr"]
    assert r"\left\{k\middle|\begin{aligned}X_t &" not in payload["math_expr"]
    assert r",\\&" not in payload["math_expr"]


def test_factor_operator_catalog_exposes_bar_search_operators() -> None:
    client = _app().test_client()
    _login(client)

    response = client.get("/api/internal/factor-library/operators")

    assert response.status_code == 200
    groups = response.get_json()["groups"]
    operators = {
        operator["key"]: operator
        for group in groups
        for operator in [*(group.get("operators") or []), *(group.get("more_operators") or [])]
    }
    assert {"bar_since", "bar_distance", "window_bars"} <= operators.keys()
    assert 'select="nearest"' in operators["bar_since"]["desc"]
    assert "include_current=True" in operators["bar_since"]["desc"]
    assert "CURRENT" in operators["bar_distance"]["desc"]
    assert "CANDIDATE" in operators["bar_distance"]["desc"]
    assert "session" in operators["bar_distance"]["desc"]
    assert "trading_day" in operators["bar_distance"]["desc"]
    assert "WindowParam" in operators["bar_distance"]["desc"]
    assert "当前 scope 已积累的距离" in operators["bar_distance"]["desc"]
    assert "搜索范围直接写 scope_bars(K)" in operators["window_bars"]["desc"]


def test_validate_factor_alias_accepts_unregistered_canonical_member(monkeypatch) -> None:
    class Family:
        @staticmethod
        def parse_alias(alias):
            assert alias == "Momentum|N:20d"
            return {"N": "20d"}

        @staticmethod
        def get_factor(**params):
            assert params == {"N": "20d"}
            return type("Factor", (), {"alias": "Momentum|N:20d"})()

    monkeypatch.setattr(editor_routes, "can_view_user_scope", lambda *_args: True)
    monkeypatch.setattr(
        editor_routes, "get_factor_family_instance",
        lambda family_ref, **_kwargs: Family()
        if family_ref == "alice:Momentum" else None,
    )
    monkeypatch.setattr(
        editor_routes, "_freeze_validated_factor",
        lambda *_args: {"schema_version": 2, "alias": "Momentum|N:20d"},
    )
    monkeypatch.setattr(
        editor_routes, "instantiate_factor_metadata",
        lambda *_args, **_kwargs: {
            "factor_alias": "Momentum|N:20d",
            "family_formula_fingerprint": "a" * 64,
            "self_formula_fingerprint": "b" * 64,
            "normalized_params": {"N": "20d"},
            "math_expr": r"\textcolor{red}{N}",
            "resolved_math_expr": "20d",
            "parameter_definitions": [{
                "alias": "N", "type": "WindowParam", "value": "20d",
            }],
        },
    )
    client = _app().test_client()
    _login(client)

    response = client.post(
        "/api/internal/factor-library/validate",
        json={
            "resolve_factor_alias": True,
            "factor_alias": "Momentum|N:20d",
            "factor_family_alias": "Momentum",
            "owner_username": "alice",
        },
    )

    assert response.status_code == 200
    assert response.get_json() == {
        "success": True,
        "valid": True,
        "error": None,
        "factor_alias": "Momentum|N:20d",
        "factor_family_alias": "Momentum",
        "factor": {
            "schema_version": 2,
            "alias": "Momentum|N:20d",
            "factor_family_alias": "Momentum",
            "factor_family_name": "Family",
            "factor_kind": "custom",
            "source": "custom",
            "factor_alias": "Momentum|N:20d",
            "family_formula_fingerprint": "a" * 64,
            "self_formula_fingerprint": "b" * 64,
            "normalized_params": {"N": "20d"},
            "math_expr": r"\textcolor{red}{N}",
            "resolved_math_expr": "20d",
            "parameter_definitions": [{
                "alias": "N", "type": "WindowParam", "value": "20d",
            }],
        },
    }
