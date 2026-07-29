import pytest
from flask import Flask

from server.modules.shared import shared_bp
from server.modules.shared.price_services import cached_contracts, cached_products
from server.modules.shared import report_references as routes  # noqa: F401
from server.services.report_reference_resolution import (
    validate_report_reference,
)


def test_exact_product_reference_is_validated_without_rewriting():
    target_ref = "Product/Futures/CNFutures/_products/SI.GFE"
    reference = validate_report_reference(
        kind="product",
        target_ref=target_ref,
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
    assert reference["target_ref"] == target_ref


def test_product_reference_rejects_a_noncanonical_path():
    with pytest.raises(LookupError, match="does not resolve uniquely"):
        validate_report_reference(
            kind="product",
            target_ref=(
                "Product/Futures/CNFutures/日夜盘/日盘/"
                "_products/SI.GFE"
            ),
            products=cached_products(),
            contracts=(),
        )


def test_authenticated_report_reference_endpoint_only_validates_exact_path():
    app = Flask(__name__)
    app.secret_key = "test-secret"
    app.register_blueprint(shared_bp)
    client = app.test_client()
    target_ref = "Product/Futures/CNFutures/_products/SI.GFE"
    unauthorized = client.get(
        "/api/report-references/validate",
        query_string={"kind": "product", "target_ref": target_ref},
        headers={"Accept": "application/json"},
    )
    assert unauthorized.status_code == 401
    with client.session_transaction() as session:
        session["username"] = "alice"

    response = client.get(
        "/api/report-references/validate",
        query_string={"kind": "product", "target_ref": target_ref},
        headers={"Accept": "application/json"},
    )

    assert response.status_code == 200
    assert response.get_json()["reference"]["target_ref"] == target_ref


def test_exact_contract_reference_is_validated_without_rewriting():
    target_ref = (
        "Product/FuturesContract/CNFuturesContract/_products/"
        "GFEX|F|SI|2605"
    )
    reference = validate_report_reference(
        kind="contract",
        target_ref=target_ref,
        products=cached_products(),
        contracts=cached_contracts(),
    )

    assert reference["target_ref"] == target_ref
    assert reference["label"] == "工业硅 · GFEX|F|SI|2605"


def test_exact_continuous_reference_is_validated_without_rewriting():
    target_ref = (
        "Product/Futures/CNFutures/_products/SI.GFE/"
        "_series/secondary_raw"
    )
    reference = validate_report_reference(
        kind="continuous_contract",
        target_ref=target_ref,
        products=cached_products(),
        contracts=cached_contracts(),
    )

    assert reference["target_ref"] == target_ref
    assert reference["label"] == "工业硅 · 次主连 · 原始"
    assert reference["object"]["backing_product_name"] == "SI_S.GFE"


def test_exact_product_reference_rejects_the_wrong_declared_kind():
    target_ref = "Product/Futures/CNFutures/_products/SI.GFE"

    with pytest.raises(LookupError, match="does not resolve uniquely"):
        validate_report_reference(
            kind="contract",
            target_ref=target_ref,
            products=cached_products(),
            contracts=cached_contracts(),
        )
