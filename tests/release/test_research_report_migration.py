from __future__ import annotations

import json

import pytest

from tools.cli.release.research_reporting.document.migration import (
    migrate_legacy_journal,
)
from tools.cli.release.research_reporting.document.store import (
    load_bindings,
    load_document,
)


def _fragment(checkpoint: str, *, branch: str = "graph-branch:instance:main") -> dict:
    return {
        "schema_version": 3,
        "checkpoint_ref": checkpoint,
        "created_at": 100.0,
        "graph_ref": "factor-research@v1",
        "branch_ref": branch,
        "evidence_refs": ["evidence:historical"],
        "sections": [{
            "section_id": "same-id",
            "title": f"结论 {checkpoint}",
            "body": r"正文含行内公式 \(x_t\)",
            "evidence_refs": ["evidence:section"],
            "links": [{
                "link_id": "job-link", "kind": "job",
                "target_ref": "job:backtest-1",
            }],
            "blocks": [
                {"kind": "paragraph", "text": "正文条目"},
                {"kind": "math", "latex": "x_t", "fallback": "x"},
                {"kind": "table", "columns": ["指标"],
                 "rows": [{"cells": ["1"]}]},
                {"kind": "figure", "asset": {
                    "asset_ref": "asset:equity", "media_type": "image/png",
                    "filename": "equity.png", "caption": "权益曲线",
                }},
                {"kind": "obligation_change", "text": "义务已完成",
                 "graph_ref": "factor-research@v1",
                 "checkpoint_ref": "trace:one",
                 "report_binding": {"report_requirement_id": "req-1"}},
            ],
        }],
    }


def test_legacy_report_migration_splits_content_and_bindings(tmp_path) -> None:
    sections = tmp_path / "research" / "package-1" / "branches" / "main" / "sections"
    sections.mkdir(parents=True)
    for index, checkpoint in enumerate(("trace:one", "trace:two")):
        (sections / f"fragment-{index}.json").write_text(
            json.dumps(_fragment(checkpoint), ensure_ascii=False), encoding="utf-8"
        )
    document_output = tmp_path / "report.json"
    bindings_output = tmp_path / "report.json.bindings.json"
    first = migrate_legacy_journal(tmp_path, document_output, bindings_output)
    document = first["document"]
    bindings = first["bindings"]
    assert first["metadata"]["migrated_sections"] == 2
    assert first["metadata"]["skipped_files"] == 0
    assert set(document) == {
        "schema_version", "document_id", "title", "language", "revision",
        "components", "assets",
    }
    assert {item["kind"] for item in document["components"]} >= {
        "chapter", "section", "entry", "special", "table", "image"
    }
    assert any(
        item["target_ref"] == "evidence:section"
        for item in bindings["bindings"]
    )
    assert "graph_ref" not in json.dumps(document, ensure_ascii=False)
    assert "checkpoint_ref" not in json.dumps(document, ensure_ascii=False)
    assert "report_binding" not in json.dumps(document, ensure_ascii=False)
    assert "req-1" in json.dumps(bindings, ensure_ascii=False)
    assert document["assets"][0]["filename"] == "equity.png"
    before_document = document_output.read_bytes()
    before_bindings = bindings_output.read_bytes()
    second = migrate_legacy_journal(tmp_path, document_output, bindings_output)
    assert second["migrated"] is False
    assert document_output.read_bytes() == before_document
    assert bindings_output.read_bytes() == before_bindings
    assert load_document(document_output) == document
    assert load_bindings(bindings_output, document) == bindings


def test_migration_rejects_partial_output(tmp_path) -> None:
    document_output = tmp_path / "report.json"
    document_output.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="both content and bindings"):
        migrate_legacy_journal(tmp_path, document_output, tmp_path / "bindings.json")


def test_migration_fails_closed_on_malformed_history(tmp_path) -> None:
    sections = tmp_path / "branches" / "main" / "sections"
    sections.mkdir(parents=True)
    (sections / "broken.json").write_text("not-json", encoding="utf-8")
    with pytest.raises(ValueError, match="cannot migrate legacy fragment"):
        migrate_legacy_journal(
            tmp_path, tmp_path / "report.json", tmp_path / "bindings.json"
        )
