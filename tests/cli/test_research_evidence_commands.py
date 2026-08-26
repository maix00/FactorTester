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

    def finalize_research_evidence_lifecycle(
        self, transition_ref, report_receipt,
    ):
        self.lifecycle_finalize = (transition_ref, report_receipt)
        return {
            "status": "excluded",
            "transition": {"transition_ref": transition_ref},
        }


class _EvidenceLibrary:
    def __init__(self) -> None:
        self.recorded = []
        self.rebuilt = False

    def record_evidence(self, evidence):
        self.recorded.append(evidence)

    def rebuild_index(self):
        self.rebuilt = True


def test_research_evidence_help_exposes_fragment_workflow():
    result = CliRunner().invoke(cli, ["research", "evidence", "--help"])
    assert result.exit_code == 0, result.output
    assert all(
        name in result.output
        for name in ("source", "fragment", "create", "search", "facet", "tag")
    )
    assert "exclude" in result.output
    assert "restore" in result.output


def test_exclude_help_uses_evidence_then_graph_scope_order():
    result = CliRunner().invoke(cli, [
        "research", "evidence", "exclude", "--help",
    ])
    assert result.exit_code == 0, result.output
    assert "EVIDENCE_REF INSTANCE_ID" in result.output
    assert "BRANCH_ID" in result.output


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


def test_exclude_reports_then_finalizes_and_refreshes_local_mirror(
    monkeypatch, tmp_path,
):
    fake = _EvidenceClient()
    library = _EvidenceLibrary()
    recorded = {}
    change_file = tmp_path / "exclude.json"
    change_file.write_text(json.dumps({
        "expected_projection_hash": "sha256:projection",
            "research_cycle": {
                "schema_version": 1,
                "parent_trace_ref": "trace:current",
                "events": [],
            },
        "obligation_delta": [],
        "obligation_presentations": {},
        "reason_markdown": "该证据的样本范围不符合当前研究合同",
    }), encoding="utf-8")

    monkeypatch.setattr(
        research_evidence_query, "client_from_config", lambda: fake,
    )
    monkeypatch.setattr(
        research_evidence_query, "library_for_profile",
        lambda **_kwargs: library,
    )

    def record_report(**kwargs):
        recorded.update(kwargs)
        return {
            "report_submission_sequence": 12,
            "report_components": {"special_id": "special:evidence-excluded"},
            "git": {"commit": "a" * 40},
            "ledger_generation": 7,
            "ledger_projection_hash": "sha256:next",
            "removed_evidence_use_count": 2,
        }

    monkeypatch.setattr(
        research_evidence_query,
        "record_evidence_lifecycle_report",
        record_report,
    )
    result = CliRunner().invoke(cli, [
        "research", "evidence", "exclude",
        "evidence:one", "instance-1", "branch-1",
        "--profile-id", "maxa",
        "--agent-id", "research-maxa",
        "--parent-id", "special:grill",
        "--reason-zh", "该证据的样本范围不符合当前研究合同",
        "--change-file", str(change_file),
        "--json",
    ])

    assert result.exit_code == 0, result.output
    assert fake.lifecycle_prepare == (
        "evidence:one",
        {
            "action": "exclude",
            "reason_zh": "该证据的样本范围不符合当前研究合同",
            "profile_ref": "profile:maxa",
            "agent_id": "research-maxa",
            "instance_id": "instance-1",
            "branch_id": "branch-1",
            "parent_id": "special:grill",
        },
    )
    assert recorded["parent_id"] == "special:grill"
    assert recorded["change_payload"]["obligation_delta"] == []
    assert fake.lifecycle_finalize == (
        "evidence-lifecycle:sha256:test",
        {
            "submission_sequence": 12,
            "component_id": "special:evidence-excluded",
            "git_commit": "a" * 40,
            "ledger_generation": 7,
            "ledger_projection_hash": "sha256:next",
        },
    )
    assert library.rebuilt is True
    assert library.recorded[-1]["lifecycle"]["status"] == "excluded"
