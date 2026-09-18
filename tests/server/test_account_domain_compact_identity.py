"""存储保留全量字段；跨服务器传输只带必要字段（紧凑身份）。"""

from __future__ import annotations

import json

from server.manager.storage.account_domain import factor_sync


def test_storage_keeps_full_fields():
    assert "resolved_math_expr" in factor_sync._FACTOR_KEYS, "本地存储应保留编译表达式"
    assert "parameter_definitions" in factor_sync._FACTOR_KEYS


def test_transfer_omits_rebuildable_heavy_fields():
    assert "resolved_math_expr" not in factor_sync._SYNC_FACTOR_KEYS
    assert "parameter_definitions" not in factor_sync._SYNC_FACTOR_KEYS
    assert "resolved_math_expr_version" in factor_sync._SYNC_FACTOR_KEYS
    assert "identity" in factor_sync._SYNC_FACTOR_KEYS
    assert "ref" in factor_sync._SYNC_FACTOR_KEYS
    assert "factor_dependencies" in factor_sync._SYNC_FACTOR_KEYS


def test_deep_chain_transfer_payload_stays_small():
    inner = {"ref": "factor:v2:leaf", "identity": {"f": "y" * 40}}
    node = inner
    for level in range(8):
        node = {"ref": f"factor:v2:n{level}",
                "identity": {"f": "z" * 40},
                "resolved_math_expr": "R" * 5000,          # 大串
                "parameter_definitions": "P" * 5000,       # 大串
                "resolved_math_expr_version": 3,
                "factor_dependencies": [node, inner]}
    flat = factor_sync._flatten_dependencies([node])
    for record in flat:
        assert "resolved_math_expr" not in record
        assert "parameter_definitions" not in record
        assert "factor_dependencies" not in record
    encoded = json.dumps(flat, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    assert len(encoded) < 512 * 1024
