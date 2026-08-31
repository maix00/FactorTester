from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlencode

import pytest
from tools.cli.local_sources import ClientSourceCatalog
from tools.cli.catalog import LocalCatalogStore


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
    local = catalog(tmp_path)
    source = local.request("/api/client/product_sources")

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
    products = LocalCatalogStore(tmp_path / "client").list_products()
    assert {item["source_id"] for item in products} == {"local:Synthetic"}
    assert all(item["state"] == "unavailable" for item in products)


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
    product_list = next(
        node for node in _walk_tree(tree["tree"])
        if node.get("title") == "Product Lists"
    )
    assert product_list["lazy"] is True
    leaves = local.request("/api/client/contract_tree?" + urlencode({
        "path": product_list["key"], "page": 1, "limit": 1,
    }))
    assert leaves["total"] == 2
    assert len(leaves["nodes"]) == 1
    assert leaves["has_more"] is True
    searched = local.request("/api/client/contract_tree?" + urlencode({
        "path": product_list["key"], "query": "BETA",
    }))
    assert [item["product_name"] for item in searched["nodes"]] == ["BETA.X"]
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
    product_list = next(
        node for node in _walk_tree(tree["tree"])
        if node.get("title") == "Product Lists"
    )
    leaves = local.request("/api/client/contract_tree?" + urlencode({
        "path": product_list["key"],
        "category": "exchange_x_session_x_region",
    }))
    assert [item["product_name"] for item in leaves["nodes"]] == ["ALPHA.X"]


def test_client_catalog_keeps_alias_out_of_product_description(tmp_path: Path) -> None:
    source_root = tmp_path / "sources"
    source = source_root / "Descriptions"
    source.mkdir(parents=True)
    manifest = _manifest("Descriptions")
    manifest["products"][0]["display_name"] = "ALPHA.X"
    manifest["products"][0]["metadata"]["description_zh"] = "中文标的"
    manifest["products"][1]["display_name"] = "BETA.X"
    source.joinpath("source.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8",
    )

    products = ClientSourceCatalog(tmp_path / "client", source_root).request(
        "/api/client/product_names?data_source=Descriptions"
    )["products"]
    by_name = {item["name"]: item for item in products}

    assert by_name["ALPHA.X"]["desc"] == "中文标的"
    assert by_name["ALPHA.X"]["description"] == "中文标的"
    assert by_name["BETA.X"]["desc"] == ""
    assert by_name["BETA.X"]["description"] == ""


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
        "/api/product-library/data-sources",
        "/api/client/not-a-catalog-route",
    ],
)
def test_client_catalog_rejects_nonlocal_or_unknown_routes(
    tmp_path: Path,
    path: str,
) -> None:
    with pytest.raises(ValueError, match="route is not allowed"):
        catalog(tmp_path).request(path)
