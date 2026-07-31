from __future__ import annotations

import json

from tools.cli.release.research_evidence_library import EvidenceLibrary


def test_library_mirrors_records_and_rebuilds_index(tmp_path) -> None:
    library = EvidenceLibrary(tmp_path / "personal-workspace")
    source = {
        "source_ref": "source:file:sha256:" + "a" * 64,
        "source_kind": "file",
        "content_hash": "b" * 64,
        "identity": {"relative_path": "notes/a.md"},
    }
    fragment = {
        "fragment_ref": "fragment:file:sha256:" + "c" * 64,
        "source_ref": source["source_ref"],
        "title_zh": "文件片段",
        "summary_zh": "指定文件中的一段研究记录",
    }
    evidence = {
        "evidence_ref": "evidence:data_availability:sha256:" + "d" * 64,
        "evidence_kind": "data_availability",
        "fragment_refs": [fragment["fragment_ref"]],
        "title_zh": "数据记录片段",
        "description_zh": "文件记录中可复用的数据事实",
        "tags": [],
    }
    tag = {
        "tag_ref": "tag:one",
        "title_zh": "数据质量",
        "description_zh": "用于检索数据质量相关证据",
        "status": "active",
    }

    library.record_source(source)
    library.record_fragment(fragment)
    library.record_evidence(evidence)
    library.record_tag(tag)
    result = library.rebuild_index()

    assert result["sources"] == 1
    assert result["fragments"] == 1
    assert result["evidence"] == 1
    assert result["tags"] == 1
    stored = json.loads(
        library.path_for("evidence", evidence["evidence_ref"]).read_text()
    )
    assert stored["title_zh"] == "数据记录片段"


def test_library_writes_terminal_artifact_with_content_hash(tmp_path) -> None:
    library = EvidenceLibrary(tmp_path / "personal-workspace")

    record = library.record_artifact(
        source_ref="source:terminal:sha256:" + "a" * 64,
        name="stdout.txt",
        content=b"ok\n",
    )

    assert record["content_hash"]
    assert library.root.joinpath(record["relative_path"]).read_bytes() == b"ok\n"


def test_library_retains_but_does_not_index_excluded_evidence(
    tmp_path,
) -> None:
    library = EvidenceLibrary(tmp_path / "personal-workspace")
    evidence = {
        "evidence_ref": "evidence:data_availability:sha256:" + "d" * 64,
        "evidence_kind": "data_availability",
        "title_zh": "已排除的数据记录",
        "description_zh": "保留审计详情但不参与默认检索",
        "lifecycle": {"status": "excluded"},
    }

    path = library.record_evidence(evidence)
    result = library.rebuild_index()

    assert path.exists()
    assert result["evidence"] == 0
