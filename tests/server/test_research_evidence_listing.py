from __future__ import annotations

import settings as Settings
from tools.data.sqlite.db import connect_sqlite
from server.services.research_evidence_catalog import (
    create_evidence,
    list_evidence_page,
    list_research_evidence_page,
    put_source_capture,
    put_source_fragment,
    update_evidence_applicability,
)


def _evidence(index: int) -> None:
    source = put_source_capture(
        owner="alice",
        source_kind="terminal",
        identity={"execution_id": f"exec-{index}"},
        content_hash=f"{index + 1:064x}",
        audit={"returncode": 0},
        captured_at=float(index),
    )
    fragment = put_source_fragment(
        owner="alice",
        source_ref=source["source_ref"],
        selector={"return_code": True},
        fragment_hash=f"{index + 101:064x}",
        title_zh=f"终端片段{index}",
        summary_zh="用于验证证据目录分页的终端片段",
        preview={"returncode": 0},
        created_at=float(index),
    )
    create_evidence(
        owner="alice",
        evidence_kind="data_availability",
        fragment_refs=[fragment["fragment_ref"]],
        title_zh=f"证据{index}",
        description_zh=f"分页目录证据 {index}",
        claim_summary="该终端片段可以用于验证分页目录",
        applicability={
            "contract_hash": "c" * 64,
            "methodology_hash": "d" * 64,
            "product_group_refs": ["product-group:daily"],
            "environment_refs": ["environment:public-main"],
            "time_window": {"start": "2025-01-01", "end": "2025-12-31"},
        },
        identity_refs={
            "contract_hash": "c" * 64,
            "methodology_hash": "d" * 64,
        },
        limitations=[],
        conflicts=[],
        created_at=float(index),
    )


def test_evidence_catalog_is_metadata_only_and_server_paged(
    monkeypatch, tmp_path,
) -> None:
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", str(tmp_path / "catalog.db"))
    for index in range(3):
        _evidence(index)

    first = list_evidence_page(owner="alice", page=1, page_size=2)
    second = list_evidence_page(owner="alice", page=2, page_size=2)

    assert first["total"] == 3
    assert first["has_next"] is True
    assert [item["title_zh"] for item in first["items"]] == ["证据2", "证据1"]
    assert [item["title_zh"] for item in second["items"]] == ["证据0"]
    assert "fragments" not in first["items"][0]
    assert first["items"][0]["access"]["access_basis"] == "owner"
    assert first["items"][0]["applicable_environment"][
        "product_group_refs"
    ] == ["product-group:daily"]


def test_applicability_is_mutable_without_changing_evidence_identity(
    monkeypatch, tmp_path,
) -> None:
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", str(tmp_path / "catalog.db"))
    _evidence(0)
    original = list_evidence_page(owner="alice")["items"][0]

    updated = update_evidence_applicability(
        owner="alice",
        evidence_ref=original["evidence_ref"],
        applicability={
            "contract_hash": "c" * 64,
            "methodology_hash": "d" * 64,
            "product_group_refs": ["product-group:night"],
        },
    )

    assert updated["evidence_ref"] == original["evidence_ref"]
    assert updated["applicability"]["product_group_refs"] == [
        "product-group:night"
    ]
    refreshed = list_evidence_page(owner="alice")["items"][0]
    assert refreshed["evidence_ref"] == original["evidence_ref"]


def test_research_evidence_is_derived_only_from_report_bindings(
    monkeypatch, tmp_path,
) -> None:
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", str(tmp_path / "catalog.db"))
    _evidence(0)
    evidence_ref = list_evidence_page(owner="alice")["items"][0]["evidence_ref"]
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        conn.execute("""CREATE TABLE research_catalog_evidence_links (
            link_ref TEXT PRIMARY KEY, research_id TEXT, evidence_ref TEXT,
            evidence_owner_ref TEXT, report_id TEXT, graph_ref TEXT,
            branch_ref TEXT, job_id TEXT, profile_ref TEXT, purpose TEXT,
            status TEXT, created_at REAL, revoked_at REAL
        )""")
        base = (
            "research-1", evidence_ref, "alice", "", "", "", "", "", "",
            "active", 1.0, 0.0,
        )
        conn.execute(
            "INSERT INTO research_catalog_evidence_links VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("direct", *base),
        )
        conn.execute(
            "INSERT INTO research_catalog_evidence_links VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("report-1", "research-1", evidence_ref, "alice", "report-a", "", "", "", "", "claim", "active", 2.0, 0.0),
        )
        conn.execute(
            "INSERT INTO research_catalog_evidence_links VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("report-2", "research-1", evidence_ref, "alice", "report-b", "", "", "", "", "claim", "active", 3.0, 0.0),
        )

    result = list_research_evidence_page(owner="alice", research_id="research-1")

    assert result["total"] == 1
    assert result["items"][0]["report_count"] == 2
    assert set(result["items"][0]["report_ids"]) == {"report-a", "report-b"}


def test_research_evidence_projection_reads_member_owned_evidence(
    monkeypatch, tmp_path,
) -> None:
    monkeypatch.setattr(Settings, "CACHE_DB_PATH", str(tmp_path / "catalog.db"))
    _evidence(0)
    evidence_ref = list_evidence_page(owner="alice")["items"][0]["evidence_ref"]
    with connect_sqlite(Settings.CACHE_DB_PATH) as conn:
        conn.execute("""CREATE TABLE research_catalog_evidence_links (
            link_ref TEXT PRIMARY KEY, research_id TEXT, evidence_ref TEXT,
            evidence_owner_ref TEXT, report_id TEXT, graph_ref TEXT,
            branch_ref TEXT, job_id TEXT, profile_ref TEXT, purpose TEXT,
            status TEXT, created_at REAL, revoked_at REAL
        )""")
        conn.execute(
            "INSERT INTO research_catalog_evidence_links VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "report-link", "research-1", evidence_ref, "alice", "report-a",
                "", "", "", "", "claim", "active", 1.0, 0.0,
            ),
        )

    result = list_research_evidence_page(owner="bob", research_id="research-1")

    assert result["total"] == 1
    assert result["items"][0]["evidence_owner_ref"] == "alice"
    assert result["items"][0]["title_zh"] == "证据0"
