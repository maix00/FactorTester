from __future__ import annotations

import hashlib

import pytest

import settings as Settings
from server.services.research_evidence_catalog.sources import (
    create_evidence,
    put_source_capture,
    put_source_fragment,
)


def _file_fragment(*, audit):
    source = put_source_capture(
        owner="alice",
        source_kind="file",
        identity={
            "relative_path": "research/agent-audit.md",
            "content_hash": "a" * 64,
        },
        content_hash="a" * 64,
        audit=audit,
    )
    return put_source_fragment(
        owner="alice",
        source_ref=source["source_ref"],
        selector={"line_range": {"start": 1, "end": 3}},
        fragment_hash=hashlib.sha256(b"fragment").hexdigest(),
        title_zh="来源片段",
        summary_zh="用于验证本地文件来源门禁的明确内容片段",
    )


def _compose(fragment_ref):
    return create_evidence(
        owner="alice",
        evidence_kind="data_contract",
        fragment_refs=[fragment_ref],
        title_zh="数据来源事实",
        description_zh="确认正式证据不能由无权威链路的本地报告生成",
        claim_summary="该片段具有可复核的原始来源身份",
        applicability={
            "contract_hash": "c" * 64,
            "methodology_hash": "d" * 64,
        },
        identity_refs={
            "contract_hash": "c" * 64,
            "methodology_hash": "d" * 64,
        },
        limitations=[],
        conflicts=[],
    )


def test_composition_rejects_local_file_without_authority_path(
    monkeypatch, tmp_path,
) -> None:
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", str(tmp_path / "catalog.db"))
    fragment = _file_fragment(audit={"size": 100})

    with pytest.raises(ValueError, match="Agent-authored reports"):
        _compose(fragment["fragment_ref"])


def test_composition_accepts_authoritative_download_snapshot(
    monkeypatch, tmp_path,
) -> None:
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", str(tmp_path / "catalog.db"))
    fragment = _file_fragment(audit={
        "size": 100,
        "provenance": {
            "provenance_kind": "authoritative_download",
            "source_url": "https://exchange.example/rules.pdf",
            "publisher": "示例交易所",
            "retrieved_at": "2026-08-01T12:00:00+08:00",
            "acquisition": {
                "method": "http",
                "request_parameters": {},
            },
        },
    })

    evidence = _compose(fragment["fragment_ref"])
    assert evidence["fragments"][0]["source"]["audit"]["provenance"][
        "source_url"
    ] == "https://exchange.example/rules.pdf"
