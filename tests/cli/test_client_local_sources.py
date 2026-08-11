from __future__ import annotations

import json
from pathlib import Path

import pytest
from tools.cli.local_sources import ClientSourceCatalog


def _manifest(source_id: str = "Synthetic") -> dict:
    products = [
        {
            "product_ref": f"{source_id}:ALPHA.X",
            "alias": "ALPHA.X",
            "display_name": "Alpha",
            "class_path": "Product",
            "category_values": {
                "exchange": ["X"],
                "session": ["日盘"],
                "region": ["测试"],
            },
            "product_kind": "future",
            "metadata": {"code": "ALPHA"},
        },
        {
            "product_ref": f"{source_id}:BETA.X",
            "alias": "BETA.X",
            "display_name": "Beta",
            "class_path": "Product",
            "category_values": {
                "exchange": ["X"],
                "session": ["夜盘"],
                "region": ["测试"],
            },
            "product_kind": "future",
            "metadata": {"code": "BETA"},
        },
    ]
    return {
        "schema_version": 1,
        "managed_by": "factortester-client",
        "source_id": source_id,
        "source_name": source_id,
        "source_kind": "external_connector",
        "provider_kind": "synthetic",
        "version": "1",
        "connector": {
            "entrypoint": "connector.py",
            "probe_mode": "explicit",
            "credential_store": "keychain",
        },
        "availability": {
            "status": "not_probed",
            "available_product_refs": [],
        },
        "members": [{
            "id": "l2",
            "label": "Synthetic L2",
            "timezone": "Asia/Taipei",
            "time_columns": {"timestamp": "timestamp"},
            "data_columns": {"bid": "bid", "ask": "ask"},
            "data_mode": {
                "id": "realtime_l2",
                "title_zh": "实时 L2 行情",
                "available": True,
                "sampling_mode": "snapshot",
                "frequency": None,
                "data_kind": "order_book",
                "market_depth": "l2",
                "delivery_mode": "live_stream",
            },
        }],
        "categories": [
            {
                "id": dimension,
                "alias": title,
                "title_zh": title,
                "dimensions": [dimension],
                "composable": True,
                "is_composite": False,
            }
            for dimension, title in (
                ("exchange", "交易所"),
                ("session", "交易时段"),
                ("region", "地区"),
            )
        ],
        "products": products,
    }


def catalog(tmp_path: Path) -> ClientSourceCatalog:
    source_root = tmp_path / "sources"
    source = source_root / "Synthetic"
    source.mkdir(parents=True)
    source.joinpath("source.json").write_text(
        json.dumps(_manifest(), ensure_ascii=False), encoding="utf-8",
    )
    return ClientSourceCatalog(
        tmp_path / "client",
        source_root,
    )


def test_client_catalog_projects_tiger_as_live_l2_only(tmp_path: Path) -> None:
    source = catalog(tmp_path).request("/api/client/product_sources")

    assert source["origin"] == "local"
    assert [item["id"] for item in source["sources"]] == ["Synthetic"]
    tiger = source["sources"][0]
    assert tiger["server_provided"] is False
    assert tiger["catalog_product_count"] == 2
    assert tiger["availability"] == {
        "status": "not_probed",
        "product_count": 0,
        "frequency_names": [],
    }
    assert tiger["data_modes"] == [{
        "id": "realtime_l2",
        "title_zh": "实时 L2 行情",
        "available": True,
        "sampling_mode": "snapshot",
        "frequency": None,
        "data_kind": "order_book",
        "market_depth": "l2",
        "delivery_mode": "live_stream",
    }]


def test_client_catalog_reads_products_and_tree_from_local_manifest(
    tmp_path: Path,
) -> None:
    local = catalog(tmp_path)
    products = local.request(
        "/api/client/product_names?data_source=Synthetic"
    )
    tree = local.request(
        "/api/client/product_tree?data_source=Synthetic"
    )

    assert {item["name"] for item in products["products"]} == {
        "ALPHA.X", "BETA.X",
    }
    assert tree["source"] == "local"
    assert tree["source_ids"] == ["Synthetic"]
    assert tree["tree"][0]["title"] == "Product"
    assert tree["tree"][0]["_product_count"] == 2
    assert "交易所" not in json.dumps(tree["tree"], ensure_ascii=False)
    assert "OSE" not in {
        node["title"] for node in _walk_tree(tree["tree"])
        if node.get("folder")
    }

    exchange_tree = local.request(
        "/api/client/product_tree?data_source=Synthetic&category=exchange"
    )
    exchange_titles = {node["title"] for node in _walk_tree(exchange_tree["tree"])}
    assert {"交易所", "X", "Product Lists"} <= exchange_titles


def test_client_catalog_projects_nested_category_products(tmp_path: Path) -> None:
    source_root = tmp_path / "sources"
    source = source_root / "Nested"
    source.mkdir(parents=True)
    manifest = _manifest("Nested")
    manifest["source_id"] = "Nested"
    manifest["source_name"] = "Nested"
    manifest["categories"] = [
        {
            "id": category_id,
            "alias": title,
            "title_zh": title,
            "dimensions": [category_id],
            "composable": True,
            "is_composite": False,
        }
        for category_id, title in (
            ("exchange", "交易所"),
            ("session", "交易时段"),
            ("region", "地区"),
        )
    ]
    manifest["products"] = [{
        **manifest["products"][0],
        "alias": "ALPHA.X",
        "product_ref": "Nested:ALPHA.X",
        "category_values": {
            "exchange": ["OSE"],
            "session": ["日盘"],
            "region": ["日本"],
        },
    }]
    source.joinpath("source.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    local = ClientSourceCatalog(tmp_path / "client", source_root)

    tree = local.request(
        "/api/client/product_tree?category=exchange_x_session_x_region"
    )
    titles = {node["title"] for node in _walk_tree(tree["tree"])}

    assert "交易所×交易时段×地区" in titles
    assert "(OSE×日盘×日本)" in titles
    assert "ALPHA.X" in titles


def test_client_catalog_reports_invalid_local_manifest(tmp_path: Path) -> None:
    source_root = tmp_path / "sources"
    invalid = source_root / "Broken"
    invalid.mkdir(parents=True)
    (invalid / "source.json").write_text("{}", encoding="utf-8")
    local = ClientSourceCatalog(tmp_path / "client", source_root)

    with pytest.raises(ValueError, match="invalid local source manifest: Broken"):
        local.request("/api/client/product_sources")


def _walk_tree(nodes):
    for node in nodes:
        yield node
        yield from _walk_tree(node.get("children", []))


@pytest.mark.parametrize(
    "path",
    [
        "https://example.test/api/client/product_sources",
        "/api/catalog/sources",
        "/api/client/not-a-catalog-route",
    ],
)
def test_client_catalog_rejects_nonlocal_or_unknown_routes(
    tmp_path: Path,
    path: str,
) -> None:
    with pytest.raises(ValueError, match="route is not allowed"):
        catalog(tmp_path).request(path)
