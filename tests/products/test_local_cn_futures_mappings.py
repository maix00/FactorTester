from __future__ import annotations

import importlib

from sources.LocalCNFutures import CNFutures as cn_futures_module


def _defined_cn_futures_products():
    products = []
    seen_names = set()
    for name in cn_futures_module._product_names_from_catalog(cn_futures_module._data):
        if name in seen_names:
            continue
        seen_names.add(name)
        products.append(cn_futures_module.CNFutures(name))
    return products


def test_catalog_product_without_metadata_uses_discovered_name():
    import pandas as pd

    catalog = pd.DataFrame([
        {
            '_product_name': 'BZ.DCE',
            cn_futures_module.code_col_name: 'BZ',
            cn_futures_module.exchange_code_col_name: 'DCE',
            cn_futures_module.version_col_name: None,
        }
    ])

    assert cn_futures_module._product_names_from_catalog(catalog) == ['BZ.DCE']


def test_all_defined_local_cn_futures_products_register_by_name_and_alias():
    products = _defined_cn_futures_products()

    assert products
    for product in products:
        assert cn_futures_module.CNFutures.get_by_product_name(product.name) is product
        assert cn_futures_module.CNFutures.get_by_product_name(product.alias) is not None


def test_local_cn_futures_wind_mapping_is_bidirectional_for_registered_products():
    _defined_cn_futures_products()
    contract_to_product, product_to_contracts = cn_futures_module._cn_futures_contract_maps()

    checked_products = 0
    checked_contracts = 0
    for product_name, contracts in product_to_contracts.items():
        parent = cn_futures_module.CNFutures.get_by_product_name(product_name)
        if parent is None:
            continue

        checked_products += 1
        assert cn_futures_module.CNFutures.get_contracts_for_product(product_name) == contracts
        for contract_uid in contracts:
            checked_contracts += 1
            assert contract_to_product[contract_uid] == product_name
            assert cn_futures_module.CNFutures.get_contract_parent(contract_uid) is parent

    assert checked_products > 0
    assert checked_contracts > 0


def test_local_cn_futures_contract_to_product_requires_wind_mapping(monkeypatch):
    product = cn_futures_module.CNFutures('IF.CFE')

    def fake_maps(path=None):
        return ({}, {product.alias: ['CFFEX|F|IF|2605']})

    monkeypatch.setattr(cn_futures_module, '_cn_futures_contract_maps', fake_maps)

    assert cn_futures_module.CNFutures.get_contract_parent('CFFEX|F|IF|2605') is None
    assert cn_futures_module.CNFutures.get_contracts_for_product(product.alias) == ['CFFEX|F|IF|2605']


def test_main_product_data_source_survives_cn_futures_module_reload():
    from tools.data.types import DataFreq

    product = next(
        item
        for item in cn_futures_module.CNFUTURES
        if DataFreq.MIN1 in item.list_available_freqs()
    )

    importlib.reload(cn_futures_module)

    assert DataFreq.MIN1 in product.list_available_freqs()
