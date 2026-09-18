"""账户域载荷的 factor_dependencies 必须扁平去重，否则深链超 512KiB。"""

from __future__ import annotations

import json

from server.manager.storage.account_domain import factor_sync


def _rec(**kw):
    return dict(kw)


def test_flatten_dedupes_and_removes_nesting():
    shared_child = _rec(ref="factor:v2:child", identity={"f": "x"},
                        factor_dependencies=[_rec(ref="factor:v2:grand", identity={})])
    dependencies = [
        _rec(ref="factor:v2:a", factor_dependencies=[shared_child]),
        _rec(ref="factor:v2:b", factor_dependencies=[shared_child]),
    ]
    flat = factor_sync._flatten_dependencies(dependencies)
    refs = [record["ref"] for record in flat]
    assert refs.count("factor:v2:child") == 1, "重复引用的子记录只应出现一次"
    assert "factor:v2:grand" in refs, "孙子记录也应被扁平化出来"
    assert all("factor_dependencies" not in record for record in flat),         "扁平化后的记录不得再嵌套 factor_dependencies"


def test_deep_chain_payload_stays_small():
    # 构造一条 8 层、每层重复引用同一个子图的深链，验证扁平化后远小于 512KiB
    inner = _rec(ref="factor:v2:leaf", identity={"fingerprint": "y" * 40})
    node = inner
    for level in range(8):
        node = _rec(ref=f"factor:v2:n{level}", identity={"fingerprint": "z" * 40},
                    factor_dependencies=[node, inner])
    flat = factor_sync._flatten_dependencies([node])
    encoded = json.dumps(flat, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    assert len(flat) == 9, f"应只有 9 个唯一记录，实际 {len(flat)}"
    assert len(encoded) < 512 * 1024, "载荷应远小于 512KiB"
