from __future__ import annotations

from datetime import datetime, timezone
import json
import sys

import pandas as pd
import pytest
from flask import Flask

from server.modules.shared import shared_bp
from server.modules.shared import data_availability as availability_routes
from server.services.data_availability import availability_for_scope
from sources.Tiger.connector import TigerConnectorConfig
from tools.data.availability import build_availability_profile
from tools.data.availability.model import profile_document
from tools.data.availability.schema import availability_dimensions
from tools.data.providers.DataProviderProductTS import DataProviderProductTS
from tools.data.types import DataColumn
from tools.products.Product import Product


def test_local_parquet_profile_reports_footer_coverage_without_loading_frame(
    tmp_path,
    monkeypatch,
):
    path = tmp_path / "prices.parquet"
    frame = pd.DataFrame(
        {
            "trade_time": pd.to_datetime(
                ["2026-01-02 09:00:00", "2026-01-02 09:01:00"]
            ),
            "close_price": [100.0, 101.0],
        }
    )
    frame.to_parquet(path, row_group_size=1)
    product = Product("AVAILABILITY-TEST.LOCAL", timezone="Asia/Shanghai")
    source = DataProviderProductTS(
        key="AvailabilityTestLocalMIN1",
        data_freq="1min",
        get_object_path=lambda _product: str(path),
        timezone="Asia/Shanghai",
        time_cols_mapping={"trade_time": "1min"},
    )
    monkeypatch.setattr(
        pd,
        "read_parquet",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("availability must not load a full parquet frame")
        ),
    )

    try:
        profile = build_availability_profile(
            products=[product],
            sources=[source],
            as_of=datetime(2026, 1, 3, tzinfo=timezone.utc),
        )
    finally:
        source.delete()

    assert profile["schema_version"] == 1
    assert profile["product_scope"] == ["AVAILABILITY-TEST.LOCAL"]
    assert profile["as_of"] == "2026-01-03T00:00:00+00:00"
    assert profile["entries"] == [
        {
            "product": "AVAILABILITY-TEST.LOCAL",
            "source": "AvailabilityTestLocalMIN1",
            "sampling_mode": "bar",
            "data_kind": "ohlcv_bar",
            "market_depth": "not_applicable",
            "delivery_mode": "historical_snapshot",
            "status": "available",
            "frequency": "MIN1",
            "coverage": {
                "start": "2026-01-02T09:00:00",
                "end": "2026-01-02T09:01:00",
                "assurance": "parquet_footer_statistics",
            },
            "updated_at": profile["entries"][0]["updated_at"],
            "replayable": True,
            "snapshot_ref": profile["entries"][0]["snapshot_ref"],
        }
    ]
    assert profile["entries"][0]["snapshot_ref"].startswith("filemeta:sha256:")
    assert profile["profile_hash"].startswith("sha256:")


def test_local_profile_reports_direct_and_derived_required_fields(
    tmp_path,
) -> None:
    path = tmp_path / "prices.parquet"
    pd.DataFrame({
        "trade_time": pd.to_datetime(["2026-01-02 09:00:00"]),
        "close_price": [100.0],
        "volume": [12.0],
        "adjustment_mul": [1.01],
        "adjustment_add": [0.0],
    }).to_parquet(path)
    product = Product("FIELD-CATALOG.LOCAL", timezone="Asia/Shanghai")
    source = DataProviderProductTS(
        key="FieldCatalogLocalMIN1",
        data_freq="1min",
        get_object_path=lambda _product: str(path),
        timezone="Asia/Shanghai",
        time_cols_mapping={"trade_time": "1min"},
        data_cols_mapping={
            "close_price": DataColumn.CLOSE,
            "volume": DataColumn.VOLUME,
            "adjustment_mul": DataColumn.ADJUSTMENT_MUL,
            "adjustment_add": DataColumn.ADJUSTMENT_ADD,
        },
    )

    try:
        profile = build_availability_profile(
            products=[product],
            sources=[source],
            required_fields=["CLOSE_ADJUSTED", "VOLUME"],
        )
    finally:
        source.delete()

    assert profile["entries"][0]["required_fields"] == [
        {
            "field": "CLOSE_ADJUSTED",
            "status": "derived",
            "physical_fields": [
                "close_price",
                "adjustment_mul",
                "adjustment_add",
            ],
            "data_type": "double",
            "derivation": "price_mul_adjustment_plus_addition",
        },
        {
            "field": "VOLUME",
            "status": "direct",
            "physical_fields": ["volume"],
            "data_type": "double",
        },
    ]


def test_local_profile_catalogs_all_mapped_fields_from_footer_only(
    tmp_path,
) -> None:
    path = tmp_path / "catalog.parquet"
    pd.DataFrame({
        "trade_time": pd.to_datetime(["2026-01-02 09:00:00"]),
        "close_price": [100.0],
        "volume": [12.0],
        "adjustment_mul": [1.01],
        "adjustment_add": [0.0],
    }).to_parquet(path)
    product = Product("ALL-FIELDS.LOCAL", timezone="Asia/Shanghai")
    source = DataProviderProductTS(
        key="AllFieldsLocalMIN1",
        data_freq="1min",
        get_object_path=lambda _product: str(path),
        timezone="Asia/Shanghai",
        time_cols_mapping={"trade_time": "1min"},
        data_cols_mapping={
            "close_price": DataColumn.CLOSE,
            "volume": DataColumn.VOLUME,
            "adjustment_mul": DataColumn.ADJUSTMENT_MUL,
            "adjustment_add": DataColumn.ADJUSTMENT_ADD,
        },
    )

    try:
        profile = build_availability_profile(
            products=[product],
            sources=[source],
            include_field_catalog=True,
        )
    finally:
        source.delete()

    catalog = profile["entries"][0]["field_catalog"]
    assert {item["field"] for item in catalog} == {
        "ADJUSTMENT_ADD",
        "ADJUSTMENT_MUL",
        "CLOSE",
        "CLOSE_ADJUSTED",
        "VOLUME",
    }
    assert next(item for item in catalog if item["field"] == "CLOSE_ADJUSTED") == {
        "field": "CLOSE_ADJUSTED",
        "status": "derived",
        "physical_fields": ["close_price", "adjustment_mul", "adjustment_add"],
        "data_type": "double",
        "derivation": "price_mul_adjustment_plus_addition",
    }
    assert profile["entries"][0]["time_fields"] == [{
        "physical_field": "trade_time",
        "frequency": "MIN1",
        "data_type": "timestamp[us]",
    }]


def test_data_availability_endpoint_requires_and_preserves_explicit_scope(
    monkeypatch,
):
    captured = {}

    def fake_profile(**kwargs):
        captured.update(kwargs)
        return {
            "schema_version": 1,
            "profile_hash": "sha256:profile",
            "product_scope": kwargs["product_names"],
            "entries": [],
        }

    monkeypatch.setattr(availability_routes, "availability_for_scope", fake_profile)
    app = Flask(__name__)
    app.register_blueprint(shared_bp)
    client = app.test_client()

    missing = client.post("/api/data-availability", json={"sources": ["Local"]})
    response = client.post(
        "/api/data-availability",
        json={
            "products": ["A.DCE"],
            "sources": ["Local"],
            "probe": False,
            "expanded": False,
        },
    )

    assert missing.status_code == 400
    assert response.status_code == 200
    assert response.get_json()["product_scope"] == ["A.DCE"]
    assert captured == {
        "product_names": ["A.DCE"],
        "source_names": ["Local"],
        "frequency_names": [],
        "probe": False,
        "expanded": False,
        "required_fields": [],
        "include_field_catalog": False,
        "include_historical_fields": False,
    }


def test_profile_identity_includes_source_and_probe_semantics() -> None:
    as_of = datetime(2026, 7, 20, tzinfo=timezone.utc)
    static = profile_document(
        product_scope=["A.DCE"],
        source_scope=["Local"],
        probe=False,
        expanded=False,
        entries=[],
        as_of=as_of,
    )
    probed = profile_document(
        product_scope=["A.DCE"],
        source_scope=["Local"],
        probe=True,
        expanded=False,
        entries=[],
        as_of=as_of,
    )

    assert static["schema_version"] == 3
    assert static["source_scope"] == ["Local"]
    assert static["frequency_scope"] == []
    assert static["probe"] is False
    assert static["expanded"] is False
    assert static["profile_hash"] != probed["profile_hash"]


def test_availability_schema_rejects_market_depth_as_temporal_frequency() -> None:
    with pytest.raises(ValueError):
        availability_dimensions(
            sampling_mode="snapshot",
            frequency="L2",
            data_kind="order_book",
            market_depth="l2",
            delivery_mode="live_stream",
        )


def test_frequency_scope_does_not_invent_historical_tiger_bars(
    monkeypatch,
    tmp_path,
):
    props = tmp_path / "paper.properties"
    props.write_text("private_key=never-return-this\n", encoding="utf-8")
    bridge = tmp_path / "bridge.py"
    bridge.write_text(
        """
import json
import sys

request = json.load(sys.stdin)
print(json.dumps({
    "status": "ok",
    "received_at_ms": 1784322010000,
    "permissions": [{"name": "OSEFuturesQuoteLv2", "expire_at": -1}],
    "quotes": [{
        "identifier": request["products"][0]["identifier"],
        "latest_time": 1784322001028,
    }],
}))
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("FACTORTESTER_TIGER_PYTHON", sys.executable)
    monkeypatch.setenv("FACTORTESTER_TIGEROPEN_PROPS_PATH", str(props))
    monkeypatch.setattr(
        "sources.Tiger.connector.TigerConnectorConfig.from_env",
        lambda: TigerConnectorConfig(
            python_path=sys.executable,
            props_path=str(props),
            bridge_path=str(bridge),
            timeout_seconds=5,
        ),
    )

    profile = availability_for_scope(
        product_names=["JNI.OSE"],
        source_names=["Tiger"],
        frequency_names=["MIN1"],
        probe=True,
        expanded=False,
        refresh=True,
    )

    assert [entry["source"] for entry in profile["entries"]] == ["Tiger"]
    assert all(
        not entry["source"].startswith("Local")
        for entry in profile["entries"]
    )
    assert profile["entries"][-1]["entitled_realtime"] is True
    assert profile["entries"][-1]["latency_class"] == "unverified"
    assert profile["entries"][-1]["sampling_mode"] == "snapshot"
    assert profile["entries"][-1]["frequency"] is None
    assert profile["entries"][-1]["data_kind"] == "order_book"
    assert profile["entries"][-1]["market_depth"] == "l2"
    assert profile["entries"][-1]["delivery_mode"] == "live_stream"
    assert profile["schema_version"] == 3
    assert profile["source_scope"] == ["Tiger"]
    assert profile["frequency_scope"] == ["MIN1"]
    assert profile["probe"] is True
    assert "never-return-this" not in json.dumps(profile)
