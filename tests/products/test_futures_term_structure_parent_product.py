from __future__ import annotations

from tools.products import AdjustableTermStructure as ats
from tools.products.Futures import Futures, FuturesContract
from sources.LocalCNFutures import CNFutures as cn_futures_module


def test_futures_contract_parent_product_resolves_from_term_structure(monkeypatch):
    parent = Futures('UNIT.TEST', term_structure_path='/tmp/unit-term-structure.parquet', _local_only=True)
    contract = FuturesContract('UNIT2406.TEST', _local_only=True)
    calls = {'count': 0}

    def fake_get_contract_product_map(path):
        calls['count'] += 1
        if path == '/tmp/unit-term-structure.parquet':
            return {'UNIT2406.TEST': 'UNIT.TEST'}
        return {}

    monkeypatch.setattr(ats, 'get_contract_product_map', fake_get_contract_product_map)

    resolved = contract.parent_product
    assert resolved is not None
    assert resolved.name == parent.name
    assert isinstance(resolved, Futures)
    first_count = calls['count']
    assert contract.parent_product is resolved
    assert calls['count'] == first_count
    assert ats.resolve_term_structure_product(contract).name == parent.name
    assert ats.resolve_term_structure_product('UNIT2406.TEST').name == parent.name


def test_cn_futures_contract_parent_product_uses_cn_futures_mapping(monkeypatch):
    parent = cn_futures_module.CNFutures('UNIT.TEST')
    contract = cn_futures_module.CNFuturesContract('UNIT|F|UNIT|2406')

    def fake_maps(path=None):
        return (
            {'UNIT|F|UNIT|2406': 'UNIT.TEST'},
            {'UNIT.TEST': ['UNIT|F|UNIT|2406']},
        )

    monkeypatch.setattr(cn_futures_module, '_cn_futures_contract_maps', fake_maps)

    assert contract.parent_product is parent
    assert cn_futures_module.CNFutures.get_contract_parent(contract.name) is parent
    assert cn_futures_module.CNFutures.get_contracts_for_product(parent.name) == [contract.name]


def test_cn_futures_contract_parent_product_falls_back_to_contract_name(monkeypatch):
    parent = cn_futures_module.CNFutures('UNIT.CFE')
    uid_contract = cn_futures_module.CNFuturesContract('CFFEX|F|UNIT|2406')

    def fake_maps(path=None):
        return ({}, {})

    monkeypatch.setattr(cn_futures_module, '_cn_futures_contract_maps', fake_maps)

    assert uid_contract.parent_product is parent
    assert cn_futures_module.CNFutures.get_contract_parent('CFFEX|F|UNIT|2406') is parent
    assert cn_futures_module.CNFutures.get_contract_parent('UNIT2406.CFE') is parent
