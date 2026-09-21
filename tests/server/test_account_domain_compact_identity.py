"""存储保留全量字段；跨服务器传输只带必要字段（紧凑身份）。"""

from __future__ import annotations

import json

from server.manager.storage.account_domain import factor_sync
from server.manager.storage.account_domain.service import AccountDomainSyncService


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


def test_local_rows_keep_heavy_fields_while_transfer_rows_drop_them():
    factor = {
        "ref": "factor:v2:abc",
        "identity": {"schema_version": 2},
        "resolved_math_expr": r"\mathrm{F}_t",
        "parameter_definitions": [{"alias": "N"}],
    }

    local = factor_sync._resolved_factor_rows([factor])[0]
    transfer = factor_sync._resolved_factor_rows([factor], transfer=True)[0]

    assert local["resolved_math_expr"] == r"\mathrm{F}_t"
    assert local["parameter_definitions"] == [{"alias": "N"}]
    assert "resolved_math_expr" not in transfer
    assert "parameter_definitions" not in transfer


def test_flush_sends_compact_projection_without_mutating_local_copy(tmp_path):
    class Control:
        def __init__(self):
            self.pushed = []

        def push_account_domain_entity(self, **item):
            self.pushed.append(item)
            return {"status": "ok", "revision": 1}

    control = Control()
    service = AccountDomainSyncService(
        sqlite_path=tmp_path / "manager.sqlite",
        control_store=control,
        manager_id="local",
    )
    payload = {
        "resolved_factors": [{
            "ref": "factor:v2:abc",
            "identity": {"schema_version": 2},
            "resolved_math_expr": r"\mathrm{F}_t",
            "parameter_definitions": [{"alias": "N"}],
        }],
    }

    service.upsert(
        "alice", "factor_param_config", "default:F", payload, flush=False,
    )
    service.flush(principal="alice")

    sent = control.pushed[0]["payload"]["resolved_factors"][0]
    assert "resolved_math_expr" not in sent
    assert "parameter_definitions" not in sent
    local = service.local.list_entities(
        principal="alice", entity_type="factor_param_config",
    )[0]["payload"]["resolved_factors"][0]
    assert local["resolved_math_expr"] == r"\mathrm{F}_t"
    assert local["parameter_definitions"] == [{"alias": "N"}]


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
