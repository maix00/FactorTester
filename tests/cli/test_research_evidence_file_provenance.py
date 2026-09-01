from __future__ import annotations

import hashlib
import json
from pathlib import Path

from click.testing import CliRunner

from tools.cli.app import cli
from tools.cli.commands import research_evidence_sources
from tools.cli.protocols.research_evidence_provenance import (
    validate_file_provenance,
)


class _Client:
    def __init__(self) -> None:
        self.payload = None

    def upload_research_evidence_file(
        self, *, content, filename, content_type, sha256,
    ):
        assert content == b"exchange rules"
        assert filename == "exchange.pdf"
        assert content_type == "application/pdf"
        assert len(sha256) == 64
        return {
            "object_id": "evidence-file-object",
            "storage_server_id": "public-main",
        }

    def put_research_evidence_source(self, payload):
        self.payload = payload
        return {
            "source_ref": "source:file:sha256:" + "a" * 64,
            **payload,
        }


class _Library:
    def __init__(self, user_root: Path) -> None:
        self.root = user_root / "personal-workspace" / "evidence-library"
        self.recorded = None

    def record_artifact(self, **_kwargs):
        return {"relative_path": "artifacts/source/file.pdf"}

    def record_source(self, value):
        self.recorded = value


def test_provenance_validator_is_owned_by_packaged_cli() -> None:
    assert validate_file_provenance.__module__ == (
        "tools.cli.protocols.research_evidence_provenance"
    )
    source = Path(research_evidence_sources.__file__).read_text(encoding="utf-8")
    assert "from server" not in source


def test_capture_file_requires_reproducible_provenance(
    monkeypatch, tmp_path,
) -> None:
    user_root = tmp_path / "user"
    source = user_root / "downloads" / "exchange.pdf"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"exchange rules")
    provenance = tmp_path / "provenance.json"
    provenance.write_text(json.dumps({
        "provenance_kind": "authoritative_download",
        "source_url": "https://exchange.example/rules.pdf",
        "publisher": "示例交易所",
        "retrieved_at": "2026-08-01T12:00:00+08:00",
        "acquisition": {
            "method": "script",
            "script_ref": "git-blob:download-rules:abc123",
            "request_parameters": {"product": "SI"},
        },
    }), encoding="utf-8")
    client = _Client()
    library = _Library(user_root)
    monkeypatch.setattr(
        research_evidence_sources, "client_from_config", lambda: client,
    )
    monkeypatch.setattr(
        research_evidence_sources, "library_for_profile", lambda **_kw: library,
    )

    missing = CliRunner().invoke(cli, [
        "research", "evidence", "source", "capture-file", str(source),
        "--profile-id", "maxa",
    ])
    assert missing.exit_code != 0
    assert "--provenance-file" in missing.output

    result = CliRunner().invoke(cli, [
        "research", "evidence", "source", "capture-file", str(source),
        "--profile-id", "maxa", "--provenance-file", str(provenance),
        "--json",
    ])
    assert result.exit_code == 0, result.output
    assert client.payload["content_hash"] == hashlib.sha256(
        b"exchange rules"
    ).hexdigest()
    assert client.payload["audit"]["provenance"]["source_url"] == (
        "https://exchange.example/rules.pdf"
    )
    assert library.recorded["source_kind"] == "file"


def test_capture_file_rejects_agent_authored_file_without_authority_path(
    monkeypatch, tmp_path,
) -> None:
    user_root = tmp_path / "user"
    source = user_root / "research" / "agent-audit.md"
    source.parent.mkdir(parents=True)
    source.write_text("Agent conclusion", encoding="utf-8")
    provenance = tmp_path / "provenance.json"
    provenance.write_text(json.dumps({
        "provenance_kind": "local_note",
        "relative_path": "research/agent-audit.md",
    }), encoding="utf-8")
    monkeypatch.setattr(
        research_evidence_sources, "library_for_profile",
        lambda **_kw: _Library(user_root),
    )

    result = CliRunner().invoke(cli, [
        "research", "evidence", "source", "capture-file", str(source),
        "--profile-id", "maxa", "--provenance-file", str(provenance),
    ])
    assert result.exit_code != 0
    assert "authoritative_download or git_blob" in result.output
