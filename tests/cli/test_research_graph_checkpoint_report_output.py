from __future__ import annotations

import json

from click.testing import CliRunner

from tools.cli.app import cli
from tools.cli.commands import research_graph as commands


class _Client:
    def get_profile_research_branch(self, *_args):
        return {
            "report_checkpoint": {
                "current_node": "capability_resolution",
            },
        }

    def get_research_graph_node_info(self, *_args):
        return {
            "report_container": {
                "kind": "special",
                "anchor_node": "hypothesis_preregistration",
            },
        }

    def append_current_report_checkpoint(self, *_args, **_kwargs):
        return {
            "checkpoint_ref": "report-checkpoint:server-receipt",
        }


def test_checkpoint_report_names_local_and_server_receipts(
    tmp_path,
    monkeypatch,
) -> None:
    projection = tmp_path / "projection.json"
    projection.write_text("{}", encoding="utf-8")
    release_profile = tmp_path / "release-profile.json"
    release_profile.write_text("{}", encoding="utf-8")
    client = _Client()
    monkeypatch.setattr(
        commands, "load_profile_root", lambda _path: tmp_path,
    )
    monkeypatch.setattr(
        commands, "_client_for_profile", lambda *_args: client,
    )
    monkeypatch.setattr(
        commands, "resolve_local_graph_report", lambda **_kwargs: object(),
    )
    monkeypatch.setattr(
        commands,
        "reconcile_current_container",
        lambda *_args, **_kwargs: {"component_id": "detour"},
    )
    monkeypatch.setattr(
        commands,
        "report_container",
        lambda _packet: {
            "kind": "special",
            "anchor_node": "hypothesis_preregistration",
        },
    )
    monkeypatch.setattr(
        commands,
        "publish_current_node_report_checkpoint",
        lambda **_kwargs: {
            "checkpoint_ref": "report-checkpoint:local",
            "artifact": {"artifact_ref": "artifact:local"},
            "report_submission": {"schema_version": 1, "items": []},
            "report_artifact_ref": "artifact:local",
            "changed": True,
        },
    )

    result = CliRunner().invoke(cli, [
        "research", "graphs",
        "checkpoint-report",
        "instance",
        "branch",
        "--node-id",
        "capability_resolution",
        "--projection-file",
        str(projection),
        "--work-package-id",
        "work-package",
        "--profile-id",
        "maxa",
        "--agent-id",
        "research-maxa",
        "--release-profile",
        str(release_profile),
    ])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["local_checkpoint_ref"] == (
        "report-checkpoint:local"
    )
    assert payload["server_receipt"]["checkpoint_ref"] == (
        "report-checkpoint:server-receipt"
    )
    assert "checkpoint_ref" not in payload
    assert "receipt" not in payload
