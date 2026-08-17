import pytest

from server.modules.shared.price_services import (
    CN_FUTURES_COMPOSITE_CATEGORY_ID,
    CN_FUTURES_DAY_NIGHT_CATEGORY_ID,
    CN_FUTURES_SECTOR_CATEGORY_ID,
    cached_contracts,
    cached_product_tree,
    cached_product_tree_for_category,
    cached_products,
    normalize_product_category_id,
)
from server.modules.products.product_category_views import (
    category_products_for_path,
    normalize_category_selection,
    render_product_tree,
    tree_for_path,
)
from server.services.product_tree import find_node_by_path
from server.services.product_tree import convert_to_fancytree
from tools.products.classifier_paths import (
    classifier_object_path,
    classifier_series_path,
    resolve_classifier_object_path,
)


def test_product_reference_uses_visible_python_classes_and_objects_container():
    product = next(
        product for product in cached_products() if product.name == "SI.GFE"
    )

    assert (
        classifier_object_path(product)
        == "Product/Futures/CNFutures/_products/SI.GFE"
    )


def test_classifier_path_resolves_the_exact_registered_object():
    product = next(
        product for product in cached_products() if product.name == "SI.GFE"
    )

    resolved = resolve_classifier_object_path(
        "Product/Futures/CNFutures/_products/SI.GFE",
        cached_products(),
    )

    assert resolved is product


def test_classifier_path_does_not_accept_concrete_category_nodes():
    with pytest.raises(LookupError, match="does not resolve uniquely"):
        resolve_classifier_object_path(
            "Product/Futures/CNFutures/工业品/_products/SI.GFE",
            cached_products(),
        )


def test_generated_path_is_legal_in_the_existing_classifier_tree():
    product = next(
        product for product in cached_products() if product.name == "SI.GFE"
    )
    path = classifier_object_path(product)

    resolved = find_node_by_path(
        cached_product_tree().tree,
        path.split("/"),
    )

    assert resolved is product


def test_default_product_tree_contains_only_classifier_levels():
    """Category projections are opt-in and must not leak into the base tree."""
    tree = convert_to_fancytree(cached_product_tree().tree, checkbox_default=False)

    def titles(nodes):
        for node in nodes:
            yield str(node.get("title") or "")
            yield from titles(node.get("children") or [])

    rendered_titles = set(titles(tree))
    assert {"Product", "Futures", "CNFutures"} <= rendered_titles
    assert rendered_titles.isdisjoint({"行业", "日夜盘", "行业×日夜盘", "日夜盘×行业"})


def test_explicit_product_category_composition_is_canonical_and_projected():
    assert normalize_product_category_id(
        f"{CN_FUTURES_SECTOR_CATEGORY_ID}×{CN_FUTURES_DAY_NIGHT_CATEGORY_ID}"
    ) == (
        CN_FUTURES_COMPOSITE_CATEGORY_ID
    )
    with pytest.raises(ValueError):
        normalize_product_category_id("行业×日夜盘")

    tree = convert_to_fancytree(
        cached_product_tree_for_category(CN_FUTURES_COMPOSITE_CATEGORY_ID).tree,
        checkbox_default=False,
    )
    rendered_titles = {
        node["title"]
        for node in _walk_nodes(tree)
    }
    assert "日夜盘×行业" in rendered_titles


def test_parallel_category_selection_keeps_sibling_trees_separate():
    assert normalize_category_selection([
        f"{CN_FUTURES_DAY_NIGHT_CATEGORY_ID},{CN_FUTURES_SECTOR_CATEGORY_ID}"
    ]) == [
        CN_FUTURES_DAY_NIGHT_CATEGORY_ID, CN_FUTURES_SECTOR_CATEGORY_ID,
    ]
    assert normalize_category_selection([CN_FUTURES_COMPOSITE_CATEGORY_ID]) == [
        CN_FUTURES_COMPOSITE_CATEGORY_ID,
    ]

    tree = render_product_tree([
        CN_FUTURES_DAY_NIGHT_CATEGORY_ID, CN_FUTURES_SECTOR_CATEGORY_ID,
    ])

    assert [node["key"] for node in tree] == ["Product"]
    assert not any(
        node["key"].startswith("ProductCategory/") for node in _walk_nodes(tree)
    )
    category_nodes = [
        node for node in _walk_nodes(tree)
        if "/ProductCategory/" in node.get("key", "")
        and node.get("key", "").endswith(
            (CN_FUTURES_DAY_NIGHT_CATEGORY_ID,
             CN_FUTURES_SECTOR_CATEGORY_ID),
        )
    ]
    assert {node["title"] for node in category_nodes} == {
        "中国期货日夜盘", "中国期货行业",
    }
    assert all(node["key"].startswith("Product/") for node in category_nodes)


def test_parallel_category_path_resolves_the_selected_sibling():
    path = (
        "Product/Futures/CNFutures/ProductCategory/"
        f"{CN_FUTURES_SECTOR_CATEGORY_ID}/有色金属"
    )
    tree, path = tree_for_path(
        path, [CN_FUTURES_DAY_NIGHT_CATEGORY_ID, CN_FUTURES_SECTOR_CATEGORY_ID],
    )

    assert path == "Product/Futures/CNFutures"
    assert find_node_by_path(tree, path.split("/")) is not None
    assert category_products_for_path(
        "Product/Futures/CNFutures/ProductCategory/"
        f"{CN_FUTURES_SECTOR_CATEGORY_ID}/有色金属",
        [CN_FUTURES_SECTOR_CATEGORY_ID],
    )


def _walk_nodes(nodes):
    for node in nodes:
        yield node
        yield from _walk_nodes(node.get("children") or [])


def test_contract_reference_uses_its_visible_python_class_lineage():
    contract = cached_contracts()[0]

    assert classifier_object_path(contract) == (
        "Product/FuturesContract/CNFuturesContract/_products/"
        f"{contract.name}"
    )


def test_continuous_reference_uses_the_existing_series_child_path():
    product = next(
        product for product in cached_products() if product.name == "SI.GFE"
    )
    primary_raw = next(
        series for series in product.get_series_variants()
        if series.variant == "primary_raw"
    )

    assert classifier_series_path(primary_raw) == (
        "Product/Futures/CNFutures/_products/SI.GFE/"
        "_series/primary_raw"
    )
