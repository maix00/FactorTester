"""Product catalog and price-series HTTP routes.

The route layer is intentionally thin.  Product market data is projected by
``server.services.product_market_data`` so the 7998 Manager and a service
instance consume the same implementation without proxying catalog reads
through a selected backtest port.
"""

from __future__ import annotations

import traceback

from flask import jsonify, request

from server.modules.products.product_category_views import (
    normalize_category_selection,
    render_product_tree,
    tree_for_path,
)
from server.modules.shared.price_services import (
    available_product_categories,
    cached_contracts,
    cached_products,
    contract_has_data,
    find_product,
    product_public_fields,
)
from server.services.product_catalog_projection import product_source_descriptors
from server.services.product_market_data import (
    ProductMarketDataError,
    contract_listing,
    price_series,
)
from server.services.product_tree import find_node_by_path

from . import shared_bp


def _unexpected_error(error: Exception):
    return jsonify({
        "success": False,
        "error": str(error),
        "traceback": traceback.format_exc(),
    }), 500


@shared_bp.route("/api/internal/product-library/products")
def list_product_names():
    """Return all registered product names and reflected public fields."""
    try:
        result = []
        for product in cached_products():
            if product is None:
                continue
            name = str(
                getattr(product, "name", None)
                or getattr(product, "alias", None)
                or product
            )
            code = getattr(product, "code", None)
            result.append({
                "name": name,
                "desc": getattr(product, "desc", None) or name,
                "code": code or (name.split(".")[0] if "." in name else name),
                "exchange": (
                    name.split(".")[1].split("@")[0] if "." in name else ""
                ),
                "product_type": "product",
                "fields": product_public_fields(product),
            })
        return jsonify({"success": True, "products": result})
    except Exception as error:
        return _unexpected_error(error)


@shared_bp.route("/api/internal/product-library/tree")
def get_product_tree():
    """Return the product category tree in Fancytree format."""
    try:
        category_ids = normalize_category_selection(
            request.args.getlist("category"),
        )
        checkbox = str(request.args.get("checkbox") or "").lower() in {
            "1", "true",
        }
        return jsonify(render_product_tree(category_ids, checkbox_default=checkbox))
    except Exception as error:
        return _unexpected_error(error)


@shared_bp.route("/api/internal/product-library/categories")
def get_product_categories():
    """Return explicit base category dimensions and registered sources."""
    return jsonify({
        "success": True,
        "default_category_id": None,
        "categories": available_product_categories(),
        "sources": list(product_source_descriptors()),
    })


@shared_bp.route("/api/product-library/product-fields")
def get_product_fields():
    name = str(request.args.get("name") or "")
    if not name:
        return jsonify({"success": False, "error": "缺少 name 参数"}), 400
    try:
        product = find_product(cached_products(), name)
        if product is None:
            return jsonify({
                "success": False, "error": f"未找到品种: {name}",
            }), 404
        return jsonify({
            "success": True,
            "name": name,
            "fields": product_public_fields(product),
        })
    except Exception as error:
        return _unexpected_error(error)


@shared_bp.route("/api/internal/product-library/contract-tree")
def get_contract_tree():
    """Return contract-level lazy nodes for the selected tree path."""
    try:
        path = request.args.get("path")
        if path:
            node_path = path[:-10] if path.endswith("/_products") else path
            tree, node_path = tree_for_path(
                node_path,
                normalize_category_selection(request.args.getlist("category")),
            )
            node = find_node_by_path(tree, node_path.split("/"))
            contracts = (
                node.get("$OBJECTS$", [])
                if isinstance(node, dict) else ([node] if node else [])
            )
        else:
            contracts = cached_contracts()
        nodes = []
        for contract in sorted(
            contracts,
            key=lambda value: getattr(value, "name", str(value)),
        ):
            name = str(getattr(contract, "name", contract))
            has_data = contract_has_data(name)
            nodes.append({
                "title": name,
                "key": f"CNFuturesContract/{name}",
                "checkbox": False,
                "folder": False,
                "lazy": False,
                "extraClasses": (
                    "product-node contract-node"
                    + ("" if has_data else " disabled-contract-node")
                ),
                "desc": "合约" if has_data else "暂无价格数据",
                "product_name": name,
                "product_code": name,
                "product_type": "contract",
                "contract_uid": name,
                "has_data": has_data,
                "fields": product_public_fields(contract),
            })
        return jsonify(nodes)
    except Exception as error:
        return _unexpected_error(error)


@shared_bp.route("/api/internal/product-library/contracts")
def get_contracts():
    try:
        value = contract_listing(
            str(request.args.get("product") or ""),
            start_date=request.args.get("start_date"),
            end_date=request.args.get("end_date"),
        )
        return jsonify(value)
    except ProductMarketDataError as error:
        return jsonify({"success": False, "error": str(error)}), error.status
    except Exception as error:
        return _unexpected_error(error)


@shared_bp.route("/api/internal/market-data/prices", methods=["POST"])
def get_price_data():
    payload = request.get_json(silent=True) or {}
    try:
        return jsonify(price_series(payload))
    except ProductMarketDataError as error:
        return jsonify({"success": False, "error": str(error)}), error.status
    except Exception as error:
        return _unexpected_error(error)
