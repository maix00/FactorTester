from __future__ import annotations

import json

from click.testing import CliRunner

from tools.cli.app import cli
from tools.cli.modules.custom_factors import controller


def test_factor_library_is_the_only_public_factor_cli_entry() -> None:
    result = CliRunner().invoke(cli, ["--help"])

    assert result.exit_code == 0
    assert "factor-library" in result.output
    assert "custom_factors" not in result.output


class _CatalogClient:
    def __init__(self) -> None:
        self.include_subordinates = False
        self.validations: list[dict] = []

    def custom_factor_catalog(self, *, include_subordinates=False):
        self.include_subordinates = include_subordinates
        return {
            "current_username": "default$MaxA@1",
            "public_factors": [],
            "custom_factors": [{
                "id": "SgCCS",
                "name": "SgCCS",
                "factor_family": "SgCCS",
                "owner_username": "18717974771",
                "description": "registered factor metadata",
                "params": [{"alias": "N", "default_value": "2m"}],
            }],
        }

    def validate_factor_expr(self, payload):
        self.validations.append(payload)
        raise AssertionError("cross-owner describe must not request source validation")


class _OwnedCatalogClient(_CatalogClient):
    def custom_factor_catalog(self, *, include_subordinates=False):
        payload = super().custom_factor_catalog(
            include_subordinates=include_subordinates,
        )
        payload["current_username"] = "18717974771"
        return payload

    def validate_factor_expr(self, payload):
        self.validations.append(payload)
        return {
            "valid": True,
            "tree_repr": "CompositeExpr",
            "params": [{"alias": "N", "default_value": "2m"}],
            "column_refs": ["CA", "HA", "LA"],
        }


class _BusinessCatalogClient:
    def factor_catalog(self):
        return {
            "schema_version": 2,
            "principal": "GTHT@MaxJJW@1",
            "family_scopes": {
                "public": {
                    "families": [{
                        "family_ref": "family:public:MmTrend",
                        "factor_family_alias": "MmTrend",
                        "owner_alias": "公共因子库",
                    }],
                    "factors": [],
                },
                "mine": {
                    "families": [{
                        "family_ref": "family:mine:SgCCS",
                        "factor_family_alias": "SgCCS",
                        "owner_alias": "MaxJJW",
                    }],
                    "factors": [{
                        "factor_ref": "factor:mine:SgCCS:1",
                        "factor_alias": "SgCCS|N:3m|$F:1m|$Rev",
                        "factor_family_alias": "SgCCS",
                        "owner_alias": "MaxJJW",
                    }],
                },
                "subordinates": {
                    "families": [{
                        "family_ref": "family:child:ChildFactor",
                        "factor_family_alias": "ChildFactor",
                        "owner_alias": "testB",
                    }],
                    "factors": [],
                },
            },
        }

    def factor_set_catalog(self, *, query=""):
        return {
            "schema_version": 1,
            "item_scopes": {
                "mine": [{
                    "target_ref": "factor-set:mine:momentum",
                    "title_zh": "动量集合",
                    "owner_username": "GTHT@MaxJJW@1",
                    "member_count": 2,
                }],
                "subordinates": [{
                    "target_ref": "factor-set:child:one",
                    "title_zh": "下级集合",
                    "owner_username": "GTHT@testB@2",
                    "member_count": 1,
                }],
            },
            "query": query,
        }


def test_factor_library_families_uses_server_scopes(monkeypatch) -> None:
    from tools.cli.modules.custom_factors.factor_library import catalog

    monkeypatch.setattr(
        catalog, "client_from_config", lambda: _BusinessCatalogClient(),
    )
    result = CliRunner().invoke(cli, [
        "factor-library", "families",
        "--scope", "subordinates", "--json",
    ])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["object_type"] == "factor_family"
    assert payload["scope"] == "subordinates"
    assert [item["factor_family_alias"] for item in payload["items"]] == [
        "ChildFactor",
    ]


def test_factor_library_is_top_level_and_internal_catalog_is_hidden() -> None:
    root_help = CliRunner().invoke(cli, ["--help"])
    client_help = CliRunner().invoke(cli, ["client", "--help"])

    assert root_help.exit_code == 0
    assert "factor-library" in root_help.output
    assert client_help.exit_code == 0
    assert "catalog" not in client_help.output


def test_factor_library_factors_and_sets_share_web_projection(monkeypatch) -> None:
    from tools.cli.modules.custom_factors.factor_library import catalog

    monkeypatch.setattr(
        catalog, "client_from_config", lambda: _BusinessCatalogClient(),
    )
    factors = CliRunner().invoke(cli, [
        "factor-library", "factors",
        "--scope", "mine", "--json",
    ])
    sets = CliRunner().invoke(cli, [
        "factor-library", "factor-sets",
        "--scope", "mine", "--query", "momentum", "--json",
    ])

    assert factors.exit_code == 0, factors.output
    assert sets.exit_code == 0, sets.output
    assert json.loads(factors.output)["items"][0]["factor_alias"].startswith(
        "SgCCS|",
    )
    assert json.loads(sets.output)["items"][0]["title_zh"] == "动量集合"


def test_legacy_parameter_listing_is_explicit(monkeypatch) -> None:
    fake = type("ParameterClient", (), {
        "factor_library_overview": lambda self, **_values: {"factors": []},
    })()
    monkeypatch.setattr(controller, "client_from_config", lambda: fake)

    old = CliRunner().invoke(cli, [
        "factor-library", "list",
    ])
    explicit = CliRunner().invoke(cli, [
        "factor-library", "parameter-configs", "--json",
    ])

    assert old.exit_code != 0
    assert "parameter-configs" in old.output
    assert explicit.exit_code == 0
    assert json.loads(explicit.output)["items"] == []


def test_owner_qualified_describe_resolves_metadata_without_source(
    monkeypatch,
) -> None:
    fake = _CatalogClient()
    monkeypatch.setattr(controller, "client_from_config", lambda: fake)

    result = CliRunner().invoke(cli, [
        "factor-library",
        "describe",
        "18717974771:SgCCS",
        "--source",
        "custom",
        "--json",
    ])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert fake.include_subordinates is True
    assert fake.validations == []
    assert payload["factor"]["owner_username"] == "18717974771"
    assert payload["factor"]["source_access"] is False
    assert payload["tree_repr"] == ""
    assert "source_code" not in payload


def test_owner_qualified_describe_rejects_cross_owner_source_read(
    monkeypatch,
) -> None:
    fake = _CatalogClient()
    monkeypatch.setattr(controller, "client_from_config", lambda: fake)

    result = CliRunner().invoke(cli, [
        "factor-library",
        "describe",
        "18717974771:SgCCS",
        "--source-code",
        "--json",
    ])

    assert result.exit_code != 0
    assert "只授权执行" in result.output
    assert fake.validations == []


def test_describe_reports_fixed_column_refs_from_validation(monkeypatch) -> None:
    fake = _OwnedCatalogClient()
    monkeypatch.setattr(controller, "client_from_config", lambda: fake)

    result = CliRunner().invoke(cli, [
        "factor-library",
        "describe",
        "SgCCS",
        "--source",
        "custom",
        "--json",
    ])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert fake.validations == [{
        "factor_id": "SgCCS",
        "owner_username": "18717974771",
    }]
    assert payload["column_refs"] == ["CA", "HA", "LA"]
