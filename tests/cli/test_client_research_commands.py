from __future__ import annotations

import json

from click.testing import CliRunner

from tools.cli.app import cli
from tools.cli.commands import client_research


class _FakeClient:
    def list_profile_research(self, **kwargs):
        assert kwargs == {
            "workspace_ref": "workspace:workspace-a",
            "limit": 7,
            "after": "",
        }
        return {
            "schema_version": 2,
            "items": [{"research_ref": "work-package:instance-a"}],
            "next_cursor": None,
        }

    def get_profile_research(self, research_ref):
        assert research_ref == "work-package:instance-a"
        return {
            "schema_version": 2,
            "work_package_ref": research_ref,
            "branches": [{"branch_ref": "graph-branch:instance-a:b"}],
        }

    def get_profile_research_branch(self, work_package_ref, branch_id):
        assert (work_package_ref, branch_id) == (
            "work-package:instance-a",
            "branch-1",
        )
        return {"branch_ref": "graph-branch:instance-a:branch-1"}

    def list_profile_research_branch_timeline(
        self,
        work_package_ref,
        branch_id,
        **kwargs,
    ):
        assert (work_package_ref, branch_id, kwargs) == (
            "work-package:instance-a",
            "branch-1",
            {"limit": 9, "after": ""},
        )
        return {"items": [{"step_ref": "trace:1"}], "next_cursor": None}


def test_client_research_list_exposes_stable_json(monkeypatch) -> None:
    monkeypatch.setattr(
        client_research,
        "client_from_config",
        lambda: _FakeClient(),
    )

    result = CliRunner().invoke(cli, [
        "client",
        "research",
        "list",
        "--workspace-ref",
        "workspace:workspace-a",
        "--limit",
        "7",
        "--json",
    ])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["items"][0]["research_ref"] == (
        "work-package:instance-a"
    )


def test_client_research_show_returns_work_package(monkeypatch) -> None:
    monkeypatch.setattr(
        client_research,
        "client_from_config",
        lambda: _FakeClient(),
    )

    result = CliRunner().invoke(cli, [
        "client",
        "research",
        "show",
        "work-package:instance-a",
        "--json",
    ])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["work_package_ref"] == (
        "work-package:instance-a"
    )


def test_client_research_branch_and_timeline_are_public(monkeypatch) -> None:
    monkeypatch.setattr(
        client_research,
        "client_from_config",
        lambda: _FakeClient(),
    )
    runner = CliRunner()

    branch = runner.invoke(cli, [
        "client", "research", "branch",
        "work-package:instance-a", "branch-1", "--json",
    ])
    timeline = runner.invoke(cli, [
        "client", "research", "timeline",
        "work-package:instance-a", "branch-1",
        "--limit", "9", "--json",
    ])

    assert branch.exit_code == 0, branch.output
    assert timeline.exit_code == 0, timeline.output
    assert json.loads(branch.output)["branch_ref"].endswith(":branch-1")
    assert json.loads(timeline.output)["items"][0]["step_ref"] == "trace:1"
