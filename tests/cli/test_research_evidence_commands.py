from __future__ import annotations

import json

from click.testing import CliRunner

from tools.cli.app import cli
from tools.cli.commands import research_evidence_query
from tools.cli.commands import research_evidence_tags


class _EvidenceClient:
    def __init__(self) -> None:
        self.query = None
        self.proposal = None

    def search_research_evidence(self, query):
        self.query = query
        return {
            "items": [],
            "next_actions": [{"action": "capture_source_if_no_match"}],
        }

    def propose_research_evidence_tag(self, payload):
        self.proposal = payload
        return {
            "proposal_token": None,
            "candidates": [{"tag_ref": "tag:existing"}],
            "next_actions": [{"action": "reuse_tag_or_explain_distinction"}],
        }


def test_research_evidence_help_exposes_fragment_workflow():
    result = CliRunner().invoke(cli, ["research-evidence", "--help"])
    assert result.exit_code == 0, result.output
    assert all(
        name in result.output
        for name in ("source", "fragment", "create", "search", "facet", "tag")
    )


def test_guide_returns_machine_executable_next_action():
    result = CliRunner().invoke(cli, [
        "research-evidence", "guide", "fragment", "--json",
    ])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["topic"] == "fragment"
    assert payload["next_actions"][0]["argv"][:2] == [
        "factortester", "research-evidence",
    ]


def test_search_sends_scope_before_facets(monkeypatch):
    fake = _EvidenceClient()
    monkeypatch.setattr(
        research_evidence_query, "client_from_config", lambda: fake,
    )
    result = CliRunner().invoke(cli, [
        "research-evidence", "search",
        "--product-ref", "product:SI.GFE",
        "--factor-ref", "factor:SgCPS",
        "--time-start", "2025-01-01",
        "--time-end", "2025-02-01",
        "--evidence-kind", "authoritative_backtest",
        "--tag-ref", "tag:intraday",
        "--json",
    ])
    assert result.exit_code == 0, result.output
    assert fake.query["product_ref"] == ["product:SI.GFE"]
    assert fake.query["factor_ref"] == ["factor:SgCPS"]
    assert fake.query["tag_ref"] == ["tag:intraday"]
    assert json.loads(result.output)["next_actions"]


def test_tag_propose_returns_existing_candidate_without_create_token(
    monkeypatch,
):
    fake = _EvidenceClient()
    monkeypatch.setattr(
        research_evidence_tags, "client_from_config", lambda: fake,
    )
    result = CliRunner().invoke(cli, [
        "research-evidence", "tag", "propose",
        "--title-zh", "日内证据",
        "--description-zh", "用于描述日内窗口的验证材料",
        "--profile-id", "maxa",
        "--json",
    ])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["proposal_token"] is None
    assert payload["candidates"][0]["tag_ref"] == "tag:existing"
    assert fake.proposal["created_by_profile_ref"] == "profile:maxa"
