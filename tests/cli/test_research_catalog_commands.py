from __future__ import annotations

import json

from click.testing import CliRunner

from tools.cli.app import cli


class FakeResearchClient:
    def __init__(self) -> None:
        self.created = None
        self.removed_report = None
        self.removed_profile = None

    def create_research_report(self, research_id, payload):
        self.created = (research_id, payload)
        return {"report_id": "report:v1:new", **payload}

    def remove_research_report(self, research_id, report_id):
        self.removed_report = (research_id, report_id)
        return {"report_id": report_id, "status": "archived"}

    def remove_research_member(self, research_id, profile_ref):
        self.removed_profile = (research_id, profile_ref)
        return {"profile_ref": profile_ref, "status": "revoked"}


def test_research_cli_exposes_report_spaces_without_link_command(monkeypatch):
    fake = FakeResearchClient()
    monkeypatch.setattr(
        "tools.cli.commands.research_catalog.client_from_config", lambda: fake,
    )
    runner = CliRunner()

    help_result = runner.invoke(cli, ["research", "--help"])
    created = runner.invoke(cli, [
        "research", "report-create", "research:v1:one",
        "--title", "报告一", "--profile", "self",
    ])
    removed = runner.invoke(cli, [
        "research", "report-remove", "research:v1:one", "report:v1:new",
    ])
    member = runner.invoke(cli, [
        "research", "member-remove", "research:v1:one", "--profile", "self",
    ])

    assert help_result.exit_code == 0
    assert "report-create" in help_result.output
    assert "report-remove" in help_result.output
    assert "report-link" not in help_result.output
    assert created.exit_code == 0, created.output
    assert json.loads(created.output)["report_id"] == "report:v1:new"
    assert fake.created == ("research:v1:one", {
        "title": "报告一", "profile_ref": "self",
        "visibility": "private", "authorized_users": [],
    })
    assert removed.exit_code == 0, removed.output
    assert fake.removed_report == ("research:v1:one", "report:v1:new")
    assert member.exit_code == 0, member.output
    assert fake.removed_profile == ("research:v1:one", "self")
