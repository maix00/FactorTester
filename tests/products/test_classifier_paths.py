import pytest

from server.modules.shared.price_services import (
    cached_contracts,
    cached_product_tree,
    cached_product_tree_for_category,
    cached_products,
    normalize_product_category_id,
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
    assert normalize_product_category_id("sector_x_day_night") == (
        "day_night_x_sector"
    )
    assert normalize_product_category_id("行业×日夜盘") == (
        "day_night_x_sector"
    )

    tree = convert_to_fancytree(
        cached_product_tree_for_category("sector_x_day_night").tree,
        checkbox_default=False,
    )
    rendered_titles = {
        node["title"]
        for node in _walk_nodes(tree)
    }
    assert "日夜盘×行业" in rendered_titles


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
