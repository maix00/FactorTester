from __future__ import annotations

import pandas as pd
from flask import Flask
import pytest
import pyarrow.dataset as pyarrow_dataset

from server.modules.shared import shared_bp
from server.modules.shared import product_liquidity as liquidity_routes
from server.services import product_liquidity as liquidity_service
from tools.data.product_liquidity import summarize_day1_volume_batch
from tools.data.providers.DistributedComponents import LocalPathResolver
from tools.data.types import DataFreq


def test_day1_liquidity_is_point_in_time_and_aggregated_per_product(
    tmp_path,
) -> None:
    a_path = tmp_path / "A.DCE.parquet"
    rb_path = tmp_path / "RB.SHF.parquet"
    pd.DataFrame({
        "trading_day": pd.to_datetime([
            "2024-01-03",
            "2024-12-30",
            "2024-12-30",
            "2025-01-02",
        ]),
        "volume": [10.0, 20.0, 5.0, 999999.0],
    }).to_parquet(a_path, index=False)
    pd.DataFrame({
        "trading_day": pd.to_datetime([
            "2024-06-03",
            "2024-12-31",
        ]),
        "volume": [0.0, 40.0],
    }).to_parquet(rb_path, index=False)

    entries = summarize_day1_volume_batch(
        product_paths={
            "A.DCE": str(a_path),
            "RB.SHF": str(rb_path),
        },
        day_column="trading_day",
        volume_column="volume",
        as_of="2024-12-31",
        window_days=365,
    )

    assert entries == [
        {
            "product": "A.DCE",
            "status": "available",
            "statistics_as_of": "2024-12-30",
            "latest_daily_volume": 25.0,
            "average_daily_volume": 17.5,
            "zero_volume_days": 0,
            "coverage": {
                "requested_start": "2024-01-02",
                "requested_end": "2024-12-31",
                "start": "2024-01-03",
                "end": "2024-12-30",
                "observed_days": 2,
            },
        },
        {
            "product": "RB.SHF",
            "status": "available",
            "statistics_as_of": "2024-12-31",
            "latest_daily_volume": 40.0,
            "average_daily_volume": 20.0,
            "zero_volume_days": 1,
            "coverage": {
                "requested_start": "2024-01-02",
                "requested_end": "2024-12-31",
                "start": "2024-06-03",
                "end": "2024-12-31",
                "observed_days": 2,
            },
        },
    ]


def test_day1_liquidity_reports_capability_gap_instead_of_approximating(
    tmp_path,
) -> None:
    wrong_schema = tmp_path / "A.DCE.parquet"
    pd.DataFrame({
        "trading_day": pd.to_datetime(["2024-12-31"]),
        "turnover": [1000.0],
    }).to_parquet(wrong_schema, index=False)

    entries = summarize_day1_volume_batch(
        product_paths={
            "A.DCE": str(wrong_schema),
            "RB.SHF": str(tmp_path / "missing.parquet"),
            "ZN.SHF": None,
        },
        day_column="trading_day",
        volume_column="volume",
        as_of="2024-12-31",
        window_days=365,
    )

    assert [(item["product"], item["status"], item["gap_reason"]) for item in entries] == [
        ("A.DCE", "capability_gap", "volume_column_missing"),
        ("RB.SHF", "capability_gap", "source_file_missing"),
        ("ZN.SHF", "capability_gap", "source_path_unresolved"),
    ]
    assert all(item["average_daily_volume"] is None for item in entries)


def test_day1_liquidity_reuses_unchanged_batch_scan(
    tmp_path,
    monkeypatch,
) -> None:
    path = tmp_path / "A.DCE.parquet"
    pd.DataFrame({
        "trading_day": pd.to_datetime(["2024-12-31"]),
        "volume": [100.0],
    }).to_parquet(path, index=False)
    scan_count = 0
    real_dataset = pyarrow_dataset.dataset

    def counted_dataset(*args, **kwargs):
        nonlocal scan_count
        scan_count += 1
        return real_dataset(*args, **kwargs)

    monkeypatch.setattr(pyarrow_dataset, "dataset", counted_dataset)
    request = {
        "product_paths": {"A.DCE": str(path)},
        "day_column": "trading_day",
        "volume_column": "volume",
        "as_of": "2024-12-31",
        "window_days": 365,
    }

    first = summarize_day1_volume_batch(**request)
    second = summarize_day1_volume_batch(**request)

    assert first == second
    assert scan_count == 1


def test_day1_liquidity_rejects_ambiguous_cutoff_date(tmp_path) -> None:
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        summarize_day1_volume_batch(
            product_paths={"A.DCE": str(tmp_path / "A.DCE.parquet")},
            day_column="trading_day",
            volume_column="volume",
            as_of="2024",
            window_days=365,
        )


def test_product_liquidity_evidence_is_batch_scoped_and_hash_bound(
    tmp_path,
    monkeypatch,
) -> None:
    paths = {}
    products = []
    for name, volume in (("A.DCE", 100.0), ("RB.SHF", 200.0)):
        path = tmp_path / f"{name}.parquet"
        pd.DataFrame({
            "trading_day": pd.to_datetime(["2024-12-31"]),
            "volume": [volume],
        }).to_parquet(path, index=False)
        paths[name] = str(path)
        products.append(type("ProductStub", (), {"name": name})())

    source = type("SourceStub", (), {
        "key": "LocalCNFuturesDAY1",
        "freq": DataFreq.DAY1,
        "time_cols_mapping": {"trading_day": "DAY1"},
        "data_cols_mapping": {"volume": "VOLUME"},
        "_path_resolver": LocalPathResolver(lambda product: paths[product.name]),
        "get_path": lambda self, product: paths[product.name],
    })()
    monkeypatch.setattr(liquidity_service, "_resolve_products", lambda names: products)
    monkeypatch.setattr(liquidity_service, "_resolve_source", lambda name: source)

    evidence = liquidity_service.product_liquidity_for_scope(
        product_names=["A.DCE", "RB.SHF"],
        source_name="LocalCNFuturesDAY1",
        as_of="2024-12-31",
        window_days=365,
    )

    assert evidence["evidence_kind"] == "product_liquidity"
    assert evidence["frequency"] == "DAY1"
    assert evidence["metric_definition"]["missing_calendar_days"] == "not_counted_as_zero"
    assert evidence["read_strategy"] == {
        "mode": "single_pyarrow_dataset_scan",
        "requested_product_count": 2,
        "candidate_file_count": 2,
        "projected_columns": ["trading_day", "volume"],
        "database_reads": 0,
    }
    assert evidence["evidence_hash"].startswith("sha256:")
    assert [item["product"] for item in evidence["entries"]] == ["A.DCE", "RB.SHF"]


def test_product_liquidity_endpoint_requires_explicit_scope_and_cutoff(
    monkeypatch,
) -> None:
    captured = {}

    def fake_evidence(**kwargs):
        captured.update(kwargs)
        return {
            "schema_version": 1,
            "evidence_kind": "product_liquidity",
            "evidence_hash": "sha256:evidence",
            "entries": [],
        }

    monkeypatch.setattr(
        liquidity_routes,
        "product_liquidity_for_scope",
        fake_evidence,
    )
    app = Flask(__name__)
    app.register_blueprint(shared_bp)
    client = app.test_client()

    missing = client.post("/api/product-liquidity", json={
        "products": ["A.DCE"],
        "source": "LocalCNFuturesDAY1",
    })
    response = client.post("/api/product-liquidity", json={
        "products": ["A.DCE", "RB.SHF"],
        "source": "LocalCNFuturesDAY1",
        "as_of": "2024-12-31",
        "window_days": 365,
    })

    assert missing.status_code == 400
    assert response.status_code == 200
    assert response.get_json()["evidence_hash"] == "sha256:evidence"
    assert captured == {
        "product_names": ["A.DCE", "RB.SHF"],
        "source_name": "LocalCNFuturesDAY1",
        "as_of": "2024-12-31",
        "window_days": 365,
    }
