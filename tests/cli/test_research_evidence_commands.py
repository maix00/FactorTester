from __future__ import annotations

import json

from click.testing import CliRunner

from tools.cli.app import cli
from tools.cli.commands import research_evidence_query
from tools.cli.commands import research_evidence_tags


_FACTOR_REF = (
    "factor:v1:profile-maxa:cGF0aA:U2dDUFM:"
    + "a" * 40 + ":" + "b" * 40
)


class _EvidenceClient:
    def __init__(self) -> None:
        self.query = None
        self.proposal = None
        self.lifecycle_prepare = None
        self.lifecycle_finalize = None
        self.status_change = None

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

    def get_research_evidence(self, evidence_ref):
        return {
            "evidence_ref": evidence_ref,
            "envelope": {"title_zh": "工业硅回测证据"},
            "lifecycle": {
                "status": (
                    "excluded" if self.lifecycle_finalize is not None
                    else "active"
                ),
            },
        }

    def prepare_research_evidence_lifecycle(self, evidence_ref, payload):
        self.lifecycle_prepare = (evidence_ref, payload)
        return {
            "transition_ref": "evidence-lifecycle:sha256:test",
            "evidence_ref": evidence_ref,
            "action": payload["action"],
            "from_status": "active",
            "to_status": "excluded",
            "reason_zh": payload["reason_zh"],
        }

    def change_research_evidence_status(self, evidence_ref, payload):
        self.status_change = (evidence_ref, payload)
        return {
            "status": "excluded",
            "evidence_ref": evidence_ref,
            "lifecycle": {"status": "excluded"},
        }


def test_research_evidence_help_exposes_fragment_workflow():
    result = CliRunner().invoke(cli, ["research", "evidence", "--help"])
    assert result.exit_code == 0, result.output
    assert all(
        name in result.output
        for name in ("source", "fragment", "create", "search", "facet", "tag")
    )
    assert "exclude" in result.output
    assert "restore" in result.output


def test_exclude_help_uses_only_evidence_scope():
    result = CliRunner().invoke(cli, [
        "research", "evidence", "exclude", "--help",
    ])
    assert result.exit_code == 0, result.output
    assert "EVIDENCE_REF" in result.output
    assert "INSTANCE_ID" not in result.output
    assert "BRANCH_ID" not in result.output


def test_guide_returns_machine_executable_next_action():
    result = CliRunner().invoke(cli, [
        "research", "evidence", "guide", "fragment", "--json",
    ])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["topic"] == "fragment"
    assert payload["next_actions"][0]["argv"][:3] == [
        "factortester", "research", "evidence",
    ]


def test_capture_guide_prefers_primary_sources_and_rejects_agent_reports():
    result = CliRunner().invoke(cli, [
        "research", "evidence", "guide", "capture", "--json",
    ])
    assert result.exit_code == 0, result.output
    rules = "\n".join(json.loads(result.output)["rules"])
    assert "外部 Web" in rules
    assert "Terminal" in rules
    assert "Agent 自写报告" in rules
    assert "Git commit/blob" in rules


def test_search_sends_scope_before_facets(monkeypatch):
    fake = _EvidenceClient()
    monkeypatch.setattr(
        research_evidence_query, "client_from_config", lambda: fake,
    )
    result = CliRunner().invoke(cli, [
        "research", "evidence", "search",
        "--product-ref", "product:SI.GFE",
        "--factor-ref", _FACTOR_REF,
        "--time-start", "2025-01-01",
        "--time-end", "2025-02-01",
        "--evidence-kind", "authoritative_backtest",
        "--tag-ref", "tag:intraday",
        "--include-excluded",
        "--json",
    ])
    assert result.exit_code == 0, result.output
    assert fake.query["product_ref"] == ["product:SI.GFE"]
    assert fake.query["factor_ref"] == [_FACTOR_REF]
    assert fake.query["tag_ref"] == ["tag:intraday"]
    assert fake.query["include_excluded"] == "1"
    assert json.loads(result.output)["next_actions"]


def test_tag_propose_returns_existing_candidate_without_create_token(
    monkeypatch,
):
    fake = _EvidenceClient()
    monkeypatch.setattr(
        research_evidence_tags, "client_from_config", lambda: fake,
    )
    result = CliRunner().invoke(cli, [
        "research", "evidence", "tag", "propose",
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


def test_exclude_changes_evidence_status_with_idempotency_key(monkeypatch):
    fake = _EvidenceClient()
    monkeypatch.setattr(
        research_evidence_query, "client_from_config", lambda: fake,
    )
    result = CliRunner().invoke(cli, [
        "research", "evidence", "exclude", "evidence:one",
        "--operation-id", "exclude-evidence-one",
        "--reason-zh", "该证据的样本范围不符合当前研究合同",
        "--json",
    ])

    assert result.exit_code == 0, result.output
    assert fake.status_change == (
        "evidence:one",
        {
            "action": "exclude",
            "reason_zh": "该证据的样本范围不符合当前研究合同",
            "operation_id": "exclude-evidence-one",
        },
    )
    payload = json.loads(result.output)
    assert payload["status"] == "excluded"
    assert payload["lifecycle"]["status"] == "excluded"
