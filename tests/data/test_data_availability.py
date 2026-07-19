from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
from flask import Flask

from server.modules.shared import shared_bp
from server.modules.shared import data_availability as availability_routes
from tools.data.availability import build_availability_profile
from tools.data.providers.DataProviderProductTS import DataProviderProductTS
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
            "mode": "historical_snapshot",
            "status": "available",
            "frequency": "MIN1",
            "coverage": {
                "start": "2026-01-02T09:00:00",
                "end": "2026-01-02T09:01:00",
                "assurance": "parquet_footer_statistics",
            },
            "updated_at": profile["entries"][0]["updated_at"],
            "replayable": True,
            "point_in_time": False,
            "snapshot_ref": profile["entries"][0]["snapshot_ref"],
        }
    ]
    assert profile["entries"][0]["snapshot_ref"].startswith("filemeta:sha256:")
    assert profile["profile_hash"].startswith("sha256:")


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
        "probe": False,
        "expanded": False,
    }
