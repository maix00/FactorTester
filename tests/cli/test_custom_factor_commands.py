from __future__ import annotations

import json

from click.testing import CliRunner

from tools.cli.app import cli
from tools.cli.modules.custom_factors import controller


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


def test_owner_qualified_describe_resolves_metadata_without_source(
    monkeypatch,
) -> None:
    fake = _CatalogClient()
    monkeypatch.setattr(controller, "client_from_config", lambda: fake)

    result = CliRunner().invoke(cli, [
        "custom_factors",
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
        "custom_factors",
        "describe",
        "18717974771:SgCCS",
        "--source-code",
        "--json",
    ])

    assert result.exit_code != 0
    assert "只授权执行" in result.output
    assert fake.validations == []
