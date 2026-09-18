"""配置的冻结映射只应包含「参数数据真正引用到」的 ref。

历史缺陷：metadata.factor_dependencies 里遗留的旧身份记录会被无条件注入 frozen_by_ref，
嵌套因子据此被重建、再被原样写回 —— 于是重算永远复现旧 self_formula_fingerprint，
而服务端校验侧重算的是新身份，两侧永久不一致，任何 RunSpec 都被判
"factor formula changed after RunSpec freeze"。
"""

from __future__ import annotations

from server.modules.custom_factors import factor_library_service as service
from tools.cli.identities.factor import freeze_factor_identity

FP_A = 'a' * 64
FP_B = 'b' * 64
FP_FAMILY = 'c' * 64


def _record(owner_ref, self_fp):
    return freeze_factor_identity(
        owner_ref=owner_ref,
        family_alias='SomeFamily',
        factor_alias='SomeFamily|N:[10d]',
        family_formula_fingerprint=FP_FAMILY,
        self_formula_fingerprint=self_fp,
        params={'N': '10d'},
    )


def test_orphan_legacy_dependency_records_are_not_injected(monkeypatch):
    """未被任何参数引用的遗留记录必须被丢弃，否则旧身份会自我延续。"""
    monkeypatch.setattr(service, 'frozen_factor_records_from_values', lambda values: [])

    legacy = _record('public', FP_A)
    config = {'metadata': {'factor_dependencies': [legacy]}}
    values = {'N': '10d'}  # 只引用别名，不引用任何 ref

    assert service._configuration_frozen_factor_map(config, values) == {}


def test_referenced_dependency_records_are_kept(monkeypatch):
    """被参数真正引用的记录必须保留，否则冻结 DAG 会断。"""
    monkeypatch.setattr(service, 'frozen_factor_records_from_values', lambda values: [])

    legacy = _record('public', FP_A)
    live = _record('GTHT@MaxJJW@1', FP_B)
    config = {'metadata': {'factor_dependencies': [legacy, live]}}

    frozen = service._configuration_frozen_factor_map(config, {'X': live['ref']})

    assert set(frozen) == {live['ref']}
    assert frozen[live['ref']]['identity']['self_formula_fingerprint'] == FP_B


def test_records_carried_by_the_values_themselves_are_kept(monkeypatch):
    """参数数据里自带的记录（刚解析出来的）永远保留，不受元数据过滤影响。"""
    fresh = _record('GTHT@MaxJJW@1', FP_B)
    legacy = _record('public', FP_A)
    monkeypatch.setattr(service, 'frozen_factor_records_from_values',
                        lambda values: [fresh] if values else [])

    config = {'metadata': {'factor_dependencies': [legacy]}}
    frozen = service._configuration_frozen_factor_map(config, {'X': fresh['ref']})

    assert set(frozen) == {fresh['ref']}


def test_without_values_the_metadata_is_still_read(monkeypatch):
    """不传 values 的调用点（读取路径）保持原语义：直接用元数据记录。"""
    legacy = _record('public', FP_A)
    config = {'metadata': {'factor_dependencies': [legacy]}}

    frozen = service._configuration_frozen_factor_map(config)

    assert set(frozen) == {legacy['ref']}


def test_referenced_refs_walks_nested_structures():
    deep = _record('public', FP_A)
    listed = _record('public', FP_B)

    refs = service._referenced_factor_refs({
        'X': deep['ref'],
        'list': [{'ref': listed['ref']}],
        'other': 'not-a-ref',
    })

    assert refs == {deep['ref'], listed['ref']}
