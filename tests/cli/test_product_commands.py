from __future__ import annotations

import json

from click.testing import CliRunner

from tools.cli.app import cli
from tools.cli.modules.products import controller
from tools.cli.modules.products import liquidity


class _AvailabilityClient:
    def __init__(self, *, entry: dict | None = None) -> None:
        self.request: dict | None = None
        self.entry = entry or {
            "product": "A.DCE",
            "source": "LocalCNFuturesDAY1",
            "sampling_mode": "bar",
            "frequency": "DAY1",
            "data_kind": "ohlcv_bar",
            "market_depth": "not_applicable",
            "delivery_mode": "historical_snapshot",
            "status": "available",
            "coverage": {
                "start": "2010-01-04T00:00:00",
                "end": "2026-07-18T00:00:00",
                "assurance": "parquet_footer_statistics",
            },
        }

    def data_availability(
        self,
        *,
        products,
        sources,
        frequencies,
        probe,
        expanded,
        fields,
        include_field_catalog,
        include_historical_fields,
    ):
        self.request = {
            "products": list(products),
            "sources": list(sources),
            "frequencies": list(frequencies),
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
            "entries": [self.entry],
        }


class _LiquidityClient:
    def __init__(self) -> None:
        self.request: dict | None = None

    def product_liquidity(
        self,
        *,
        products,
        source,
        as_of,
        window_days,
    ):
        self.request = {
            "products": list(products),
            "source": source,
            "as_of": as_of,
            "window_days": window_days,
        }
        return {
            "schema_version": 1,
            "evidence_kind": "product_liquidity",
            "evidence_hash": "sha256:liquidity",
            "product_scope": list(products),
            "source": source,
            "frequency": "DAY1",
            "as_of": as_of,
            "window_days": window_days,
            "entries": [{
                "product": "A.DCE",
                "status": "available",
                "statistics_as_of": "2024-12-31",
                "latest_daily_volume": 1200.0,
                "average_daily_volume": 800.0,
                "zero_volume_days": 0,
                "coverage": {
                    "start": "2024-01-02",
                    "end": "2024-12-31",
                    "observed_days": 242,
                },
            }],
        }


class _ProductInfoClient:
    def product_fields(self, name: str) -> dict:
        return {
            "name": name,
            "fields": {
                "trading_day_sessions": {
                    "label": "交易时段",
                    "value": "09:00-10:15,10:30-11:30,13:30-15:00,21:00-23:00",
                    "type": "ProductDataDefinition",
                    "source": "current_variety_snapshot+openctp_fallback",
                    "note": "按交易所产品规则返回完整交易时段，跨夜盘时保留交易日归属",
                },
            },
        }


class _ProductGroupSubjectClient:
    def __init__(self) -> None:
        self.calls = []

    def product_group_subjects(self, **kwargs) -> dict:
        self.calls.append(kwargs)
        return {
            "success": True,
            "subjects": {
                "product_group_ref": kwargs["product_group_ref"],
                "product_group_name": "金属",
                "factor_refs": list(kwargs.get("factor_refs") or [
                    "factor:sha256:factor-a",
                ]),
                "factor_set_refs": list(kwargs.get("factor_set_refs") or []),
            },
        }


def test_products_info_wraps_long_cells_without_truncation(monkeypatch) -> None:
    monkeypatch.setattr(controller, "client_from_config", lambda: _ProductInfoClient())

    result = CliRunner().invoke(cli, ["products", "info", "SI.GFE"])

    assert result.exit_code == 0, result.output
    flattened = "".join(result.output.split())
    assert "…" not in result.output
    assert "trading_day_sessions" in flattened
    assert "13:30-15:00" in flattened
    assert "current_variety_snapshot+openctp_fallback" in flattened
    assert "ProductDataDefinition" in flattened
    assert "跨夜盘时保留交易日归属" in flattened


def test_products_liquidity_emits_batch_json_for_explicit_as_of(
    monkeypatch,
) -> None:
    fake = _LiquidityClient()
    monkeypatch.setattr(liquidity, "client_from_config", lambda: fake)

    result = CliRunner().invoke(cli, [
        "products",
        "liquidity",
        "--product",
        "A.DCE",
        "--source",
        "LocalCNFuturesDAY1",
        "--as-of",
        "2024-12-31",
        "--window-days",
        "365",
        "--json",
    ])

    assert result.exit_code == 0, result.output
    assert result.output.startswith("{\n")
    assert '\n  "entries": [' in result.output
    payload = json.loads(result.output)
    assert payload["evidence_kind"] == "product_liquidity"
    assert payload["entries"][0]["average_daily_volume"] == 800.0
    assert fake.request == {
        "products": ["A.DCE"],
        "source": "LocalCNFuturesDAY1",
        "as_of": "2024-12-31",
        "window_days": 365,
    }


def test_products_availability_emits_readable_json_for_explicit_scope(
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
    assert result.output.startswith("{\n")
    assert '\n  "product_scope": [' in result.output
    assert json.loads(result.output)["product_scope"] == ["A.DCE"]
    assert fake.request == {
            "products": ["A.DCE"],
            "sources": ["Local"],
            "frequencies": ["MIN1"],
            "probe": False,
        "expanded": False,
        "fields": [],
        "include_field_catalog": False,
        "include_historical_fields": False,
    }


def test_products_availability_compact_json_is_explicit(monkeypatch) -> None:
    fake = _AvailabilityClient()
    monkeypatch.setattr(controller, "client_from_config", lambda: fake)

    result = CliRunner().invoke(cli, [
        "products",
        "availability",
        "--product",
        "A.DCE",
        "--source",
        "Local",
        "--compact-json",
    ])

    assert result.exit_code == 0, result.output
    assert result.output.count("\n") == 1
    assert json.loads(result.output)["product_scope"] == ["A.DCE"]


def test_products_availability_does_not_import_server_runtime() -> None:
    result = CliRunner().invoke(cli, ["products", "availability", "--help"])

    assert result.exit_code == 0, result.output
    assert "--local-runtime" not in result.output


def test_product_group_subject_commands_use_one_canonical_cli(monkeypatch) -> None:
    fake = _ProductGroupSubjectClient()
    monkeypatch.setattr(controller, "client_from_config", lambda: fake)

    result = CliRunner().invoke(cli, [
        "products", "product-groups", "subjects", "add",
        "product-group:pg-metals",
        "--factor-ref", "factor:sha256:factor-a",
        "--factor-set-ref", "factor-set:profile-alice:momentum",
        "--json",
    ])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["subjects"]["product_group_name"] == "金属"
    assert fake.calls == [{
        "product_group_ref": "product-group:pg-metals",
        "action": "add",
        "factor_refs": ("factor:sha256:factor-a",),
        "factor_set_refs": ("factor-set:profile-alice:momentum",),
    }]


def test_products_availability_renders_orthogonal_stream_dimensions(
    monkeypatch,
) -> None:
    fake = _AvailabilityClient(entry={
        "product": "JNI.OSE",
        "source": "Tiger",
        "sampling_mode": "snapshot",
        "frequency": None,
        "data_kind": "order_book",
        "market_depth": "l2",
        "delivery_mode": "live_stream",
        "status": "available",
        "latency_class": "unverified",
    })
    monkeypatch.setattr(controller, "client_from_config", lambda: fake)

    result = CliRunner().invoke(cli, [
        "products",
        "availability",
        "--product",
        "JNI.OSE",
        "--source",
        "Tiger",
    ])

    assert result.exit_code == 0, result.output
    for heading in ("采样", "时间频率", "内容", "深度", "交付"):
        assert heading in result.output
    for value in ("snapshot", "order_book", "l2", "live_stream"):
        assert value in result.output
