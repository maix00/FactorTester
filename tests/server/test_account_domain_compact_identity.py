"""账户域/冻结镜像不存可重建的大字段：深链载荷必须远小于 512KiB。"""

from __future__ import annotations

import json

from server.manager.storage.account_domain import factor_sync


def test_factor_keys_omit_rebuildable_heavy_fields():
    assert "resolved_math_expr" not in factor_sync._FACTOR_KEYS
    assert "parameter_definitions" not in factor_sync._FACTOR_KEYS
    assert "resolved_math_expr_version" in factor_sync._FACTOR_KEYS
    assert "identity" in factor_sync._FACTOR_KEYS
    assert "ref" in factor_sync._FACTOR_KEYS


def test_deep_chain_payload_stays_small():
    # 8 层、每层带大段 math_expr 的深链，扁平去重后必须远小于 512KiB
    inner = {"ref": "factor:v2:leaf", "identity": {"f": "y" * 40}}
    node = inner
    for level in range(8):
        node = {"ref": f"factor:v2:n{level}",
                "identity": {"f": "z" * 40},
                "math_expr": "X" * 5000,            # 大串，但不应进入账户域载荷
                "resolved_math_expr": "R" * 5000,   # 已从 _FACTOR_KEYS 移除
                "resolved_math_expr_version": 3,
                "factor_dependencies": [node, inner]}
    flat = factor_sync._flatten_dependencies([node])
    for record in flat:
        assert "resolved_math_expr" not in record, "冻结记录不应携带整棵编译表达式"
        assert "parameter_definitions" not in record
    encoded = json.dumps(flat, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    assert len(encoded) < 512 * 1024
