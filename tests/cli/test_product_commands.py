from __future__ import annotations

import json

from click.testing import CliRunner

from tools.cli.app import cli
from tools.cli.modules.products import controller


class _AvailabilityClient:
    def __init__(self) -> None:
        self.request: dict | None = None

    def data_availability(
        self,
        *,
        products,
        sources,
        probe,
        expanded,
        fields,
        include_field_catalog,
        include_historical_fields,
    ):
        self.request = {
            "products": list(products),
            "sources": list(sources),
            "probe": probe,
            "expanded": expanded,
            "fields": list(fields),
            "include_field_catalog": include_field_catalog,
            "include_historical_fields": include_historical_fields,
        }
        return {
            "schema_version": 1,
            "profile_hash": "sha256:profile",
            "as_of": "2026-07-19T00:00:00+00:00",
            "product_scope": ["A.DCE"],
            "entries": [{
                "product": "A.DCE",
                "source": "LocalCNFuturesDAY1",
                "mode": "historical_snapshot",
                "status": "available",
                "frequency": "DAY1",
                "coverage": {
                    "start": "2010-01-04T00:00:00",
                    "end": "2026-07-18T00:00:00",
                    "assurance": "parquet_footer_statistics",
                },
            }],
        }


def test_products_availability_emits_compact_json_for_explicit_scope(
    monkeypatch,
) -> None:
    fake = _AvailabilityClient()
    monkeypatch.setattr(controller, "client_from_config", lambda: fake)

    result = CliRunner().invoke(cli, [
        "products",
        "availability",
        "--product",
        "A.DCE",
        "--source",
        "Local",
        "--json",
    ])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["product_scope"] == ["A.DCE"]
    assert fake.request == {
        "products": ["A.DCE"],
        "sources": ["Local"],
        "probe": False,
        "expanded": False,
        "fields": [],
        "include_field_catalog": False,
        "include_historical_fields": False,
    }


def test_products_availability_does_not_import_server_runtime() -> None:
    result = CliRunner().invoke(cli, ["products", "availability", "--help"])

    assert result.exit_code == 0, result.output
    assert "--local-runtime" not in result.output
