from pathlib import Path

from flask import Flask

from server.modules.shared import submissions
from sources.LocalCNFutures import CNFutures as cn_module
from tools.products.Futures import Futures
from tools.products.Product import Product
from tools.products.categories.Category import CategoryTree


def test_product_and_futures_expose_typed_primary_variants():
    product = Product("SERIES.PLAIN", _local_only=True)
    future = Futures("SERIES.FUT", _local_only=True)

    assert [item.variant for item in product.get_series_variants()] == ["primary_raw"]
    assert [item.variant for item in future.get_series_variants()] == [
        "primary_raw",
        "primary_adjusted",
    ]


def test_local_cn_futures_adds_secondary_variants_only_when_data_exists(monkeypatch, tmp_path: Path):
    minute = tmp_path / "main_mink"
    daily = tmp_path / "main_dayk"
    minute.mkdir()
    daily.mkdir()
    (minute / "SERIES_S.DCE.parquet").touch()
    monkeypatch.setattr(cn_module, "data_dir_min", str(minute))
    monkeypatch.setattr(cn_module, "data_dir_day", str(daily))
    future = cn_module.CNFutures("SERIES.DCE")

    refs = future.get_series_variants()

    assert [item.variant for item in refs] == [
        "primary_raw",
        "primary_adjusted",
        "secondary_raw",
        "secondary_adjusted",
    ]
    assert refs[-1].backing_product_name == "SERIES_S.DCE"


def test_get_products_adds_series_children_only_for_price_view(monkeypatch):
    product = Futures("SERIES.TREE", _local_only=True)
    tree = CategoryTree({Product: {"Group": {"$OBJECTS$": [product]}}})
    monkeypatch.setattr(
        "server.modules.shared.price_services.cached_product_tree",
        lambda: tree,
    )
    app = Flask(__name__)

    with app.test_request_context("/get_products?path=Product/Group/_products&checkbox=false"):
        plain = submissions.get_products().get_json()
    with app.test_request_context(
        "/get_products?path=Product/Group/_products&checkbox=false&series_variants=true"
    ):
        priced = submissions.get_products().get_json()

    assert "children" not in plain[0]
    assert [child["series_variant"] for child in priced[0]["children"]] == [
        "primary_raw",
        "primary_adjusted",
    ]
