"""FactorTester is a thin task-dispatch wrapper -- state lives on
FactorTesterState, behavior lives in factor_tester_tasks.py. These tests
confirm dispatch("task_name", **kwargs) produces identical results to the
equivalent direct method call, and that attribute access still forwards
to .state unchanged (the contract tools/factors/Factors.py and
tools/factors/FactorFamily.py rely on via duck typing).
"""

from __future__ import annotations

from tools.factors.FactorTester import FactorTester
from tools.products.Product import Product


def _tester(alias: str = "T") -> FactorTester:
    products = [Product(name="P1", point_value=1, currency="CNY")]
    return FactorTester(products=products, alias=alias)


def test_attribute_access_forwards_to_state():
    tester = _tester()
    assert tester.products == tester.state.products
    tester.sync_signal_index = "marker"
    assert tester.state.sync_signal_index == "marker"


def test_dispatch_sift_product_matches_direct_call_semantics():
    tester = _tester()
    product = next(iter(tester.products))
    tester.dispatch("sift_product", sift_func=lambda p: p is product)
    assert tester.products == {product}


def test_dispatch_get_result_returns_same_object_as_private_method():
    tester = _tester()

    class _FakeFactor:
        pass

    factor = _FakeFactor()
    direct = tester._get_result(factor)
    via_dispatch = tester.dispatch("get_result", factor=factor)
    assert direct is via_dispatch


def test_dispatch_resolve_factor_unknown_alias_returns_none():
    tester = _tester()
    assert tester.dispatch("resolve_factor", factor_alias="nope") is None
    assert tester.resolve_factor("nope") is None


def test_account_slot_defaults_to_none_and_is_settable():
    tester = _tester()
    assert tester.account is None
    sentinel = object()
    tester.account = sentinel
    assert tester.account is sentinel
    assert tester.state.account is sentinel
