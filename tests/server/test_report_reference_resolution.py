import pytest
from flask import Flask

from server.modules.shared import shared_bp
from server.modules.shared.price_services import cached_products
from server.modules.shared import report_references as routes  # noqa: F401
from server.services.report_reference_resolution import (
    resolve_report_reference,
)


def test_product_reference_is_resolved_from_the_registered_object():
    reference = resolve_report_reference(
        kind="product",
        target="SI.GFE",
        products=cached_products(),
        contracts=(),
    )

    assert reference == {
        "kind": "product",
        "target_ref": "Product/Futures/CNFutures/_products/SI.GFE",
        "label": "工业硅",
        "object": {
            "canonical_name": "SI.GFE",
            "description": "工业硅",
            "python_class": "sources.LocalCNFutures.CNFutures.CNFutures",
            "class_path": "Product/Futures/CNFutures",
            "entity_path": "Product/Futures/CNFutures/_products/SI.GFE",
        },
    }


def test_product_reference_rejects_a_path_with_concrete_categories():
    with pytest.raises(LookupError, match="does not resolve uniquely"):
        resolve_report_reference(
            kind="product",
            target=(
                "Product/Futures/CNFutures/日夜盘/日盘/"
                "_products/SI.GFE"
            ),
            products=cached_products(),
            contracts=(),
        )


def test_authenticated_report_reference_endpoint_returns_canonical_path():
    app = Flask(__name__)
    app.secret_key = "test-secret"
    app.register_blueprint(shared_bp)
    client = app.test_client()
    unauthorized = client.get(
        "/api/report-references/resolve",
        query_string={"kind": "product", "target": "SI.GFE"},
        headers={"Accept": "application/json"},
    )
    assert unauthorized.status_code == 401
    with client.session_transaction() as session:
        session["username"] = "alice"

    response = client.get(
        "/api/report-references/resolve",
        query_string={"kind": "product", "target": "SI.GFE"},
        headers={"Accept": "application/json"},
    )

    assert response.status_code == 200
    assert response.get_json()["reference"]["target_ref"] == (
        "Product/Futures/CNFutures/_products/SI.GFE"
    )
