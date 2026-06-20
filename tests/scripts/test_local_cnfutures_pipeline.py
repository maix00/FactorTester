from pathlib import Path

import pandas as pd

from sources.LocalCNFutures.scripts import pipeline


def test_pipeline_dry_run_does_not_write(monkeypatch, tmp_path: Path):
    discovered = pd.DataFrame([
        {"product_name": "BZ.DCE", "has_min1": 1, "has_day1": 1},
    ])
    monkeypatch.setattr(pipeline, "discover_products", lambda root: discovered)
    monkeypatch.setattr(pipeline, "CACHE_DB_PATH", tmp_path / "missing.sqlite")
    monkeypatch.setattr(pipeline, "sync_product_catalog", lambda **kwargs: (_ for _ in ()).throw(AssertionError("write")))

    result = pipeline.run_pipeline(data_dir=tmp_path, db_path=tmp_path / "catalog.sqlite", dry_run=True)

    assert result["dry_run"] is True
    assert result["new_products"] == ["BZ.DCE"]
    assert result["has_min1_count"] == 1


def test_pipeline_refreshes_catalog_without_running_heavy_generators(monkeypatch, tmp_path: Path):
    discovered = pd.DataFrame(columns=["product_name", "has_min1", "has_day1"])
    calls = []
    monkeypatch.setattr(pipeline, "discover_products", lambda root: discovered)
    monkeypatch.setattr(pipeline, "CACHE_DB_PATH", tmp_path / "missing.sqlite")
    monkeypatch.setattr(pipeline, "sync_product_catalog", lambda **kwargs: calls.append("catalog"))

    result = pipeline.run_pipeline(data_dir=tmp_path, db_path=tmp_path / "catalog.sqlite")

    assert calls == ["catalog"]
    assert result["generated_main"] is False
    assert result["generated_term_structure"] is False
    assert result["sessions_refreshed"] is False
