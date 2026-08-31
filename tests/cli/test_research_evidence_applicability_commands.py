from __future__ import annotations

import json

from click.testing import CliRunner

from tools.cli.commands.research_evidence import research_evidence


class _Client:
    def __init__(self) -> None:
        self.updated = None

    def get_research_evidence(self, evidence_ref: str) -> dict:
        return {
            "evidence_ref": evidence_ref,
            "applicability": {"product_scope_ref": "product:AU.SHF"},
        }

    def get_research_evidence_applicability_schema(self) -> dict:
        return {"schema_version": 1, "sections": [], "fields": []}

    def update_research_evidence_applicability(
        self, evidence_ref: str, applicability: dict,
    ) -> dict:
        self.updated = (evidence_ref, applicability)
        return {"evidence_ref": evidence_ref, "applicability": applicability}


def test_applicability_show_and_update(monkeypatch, tmp_path) -> None:
    client = _Client()
    monkeypatch.setattr(
        "tools.cli.commands.research_evidence_query.client_from_config",
        lambda: client,
    )
    path = tmp_path / "applicability.json"
    path.write_text(json.dumps({
        "product_scope_ref": "product-group:day",
        "time_window": {"start": "2025-01-01"},
    }), encoding="utf-8")
    runner = CliRunner()

    shown = runner.invoke(research_evidence, [
        "applicability", "show", "evidence:data:sha256:" + "a" * 64,
        "--json",
    ])
    updated = runner.invoke(research_evidence, [
        "applicability", "update", "evidence:data:sha256:" + "a" * 64,
        "--file", str(path), "--json",
    ])

    assert shown.exit_code == 0, shown.output
    assert updated.exit_code == 0, updated.output
    assert client.updated[1]["time_window"] == {"start": "2025-01-01"}
