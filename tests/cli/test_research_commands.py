from __future__ import annotations

import json

from click.testing import CliRunner

from tools.cli.app import cli
from tools.cli.state import load_state


class FakeClient:
    def __init__(self) -> None:
        self.payload = None

    def create_workspace(self, **kwargs):
        self.created = kwargs
        return {"workspace_id": "workspace-1", "configuration": {"revision": 1}}

    def update_workspace_configuration(self, workspace_id, *, expected_revision, payload):
        assert (workspace_id, expected_revision) == ("workspace-1", 1)
        self.payload = payload
        return {"configuration_id": "config-1", "revision": 2, "payload": payload}

    def submit_run(self, workspace_id, configuration_revision, *, analyses, retention_mode, step_mode):
        assert (workspace_id, configuration_revision) == ("workspace-1", 2)
        return {
            "run_id": "run-1",
            "jobs": [{"job_id": f"job-{kind}", "kind": kind, "status": "queued"} for kind in analyses],
        }

    def save_configuration_template(self, workspace_id, *, name):
        return {"configuration_id": "template-1", "name": name}

    def load_configuration_template(self, workspace_id, *, expected_revision, configuration_id):
        assert (workspace_id, expected_revision, configuration_id) == ("workspace-1", 1, "template-1")
        return {"configuration_id": "config-1", "revision": 2}

    def list_jobs(self, **kwargs):
        self.list_job_args = kwargs
        return [{"job_id": "job-ic", "run_id": "run-1", "kind": "ic", "status": "running", "attempt": 1}]

    def job_result(self, job_id):
        return {
            "success": False,
            "job_id": job_id,
            "status": "failed",
            "error": {"message": "boom", "traceback": "trace"},
        }

    def clone_run_workspace(self, run_id, *, title=""):
        assert run_id == "run-1"
        self.clone_title = title
        return {
            "workspace_id": "workspace-clone",
            "title": title,
            "configuration": {"revision": 1},
        }

    def delete_user_artifacts(self, *, workspace_id=""):
        self.cleared_workspace_id = workspace_id
        return {"deleted_files": 3, "workspace_id": workspace_id}

    def delete_terminal_job_history(self, *, workspace_id):
        self.cleared_history_workspace_id = workspace_id
        return {"deleted_jobs": 4, "workspace_id": workspace_id}


def test_multi_factor_configuration_and_run_use_one_contract(tmp_path, monkeypatch) -> None:
    fake = FakeClient()
    monkeypatch.setenv("FACTORTESTER_HOME", str(tmp_path / "home"))
    monkeypatch.setattr("tools.cli.commands.research.client_from_config", lambda: fake)
    runner = CliRunner()
    config = tmp_path / "config.json"
    payload = {
        "schema_version": 1,
        "shared": {
            "factor_families": [{"alias": "MmRet"}, {"alias": "MmMADevRat"}],
            "factors": [],
        },
        "analyses": {"ic": {}},
        "ui": {},
    }
    config.write_text(json.dumps(payload), encoding="utf-8")

    created = runner.invoke(cli, [
        "workspace", "create",
        "--factor-family", "MmRet",
        "--factor-family", "MmMADevRat",
        "--factor", "MmRet=MmRet|P:CA|N:10d|$F:1d",
    ])
    updated = runner.invoke(cli, ["workspace", "update", "--file", str(config)])
    submitted = runner.invoke(cli, ["run", "submit", "--analysis", "ic"])

    assert created.exit_code == 0, created.output
    assert updated.exit_code == 0, updated.output
    assert submitted.exit_code == 0, submitted.output
    assert fake.created["factor_families"] == [{"alias": "MmRet"}, {"alias": "MmMADevRat"}]
    assert fake.created["factors"] == [{
        "factor_family_alias": "MmRet",
        "alias": "MmRet|P:CA|N:10d|$F:1d",
    }]
    assert fake.payload == payload
    assert load_state().configuration_revision == 2


def test_save_and_load_template_operate_on_same_configuration(tmp_path, monkeypatch) -> None:
    fake = FakeClient()
    monkeypatch.setenv("FACTORTESTER_HOME", str(tmp_path / "home"))
    monkeypatch.setattr("tools.cli.commands.research.client_from_config", lambda: fake)
    runner = CliRunner()
    assert runner.invoke(cli, ["workspace", "create", "--factor-family", "MmRet"]).exit_code == 0

    saved = runner.invoke(cli, ["workspace", "save-template", "Core 8"])
    loaded = runner.invoke(cli, ["workspace", "load-template", "template-1"])

    assert saved.exit_code == 0 and "configuration_id=template-1" in saved.output
    assert loaded.exit_code == 0 and "loaded_from=template-1" in loaded.output
    assert load_state().configuration_revision == 2


def test_job_queue_commands_expose_filtered_json_and_failure_result(tmp_path, monkeypatch) -> None:
    fake = FakeClient()
    monkeypatch.setenv("FACTORTESTER_HOME", str(tmp_path / "home"))
    monkeypatch.setattr("tools.cli.commands.research.client_from_config", lambda: fake)
    runner = CliRunner()
    assert runner.invoke(cli, ["workspace", "create", "--factor-family", "MmRet"]).exit_code == 0

    listed = runner.invoke(cli, [
        "job", "list", "--kind", "ic", "--status", "queued", "--status", "running",
        "--limit", "7", "--json",
    ])
    result = runner.invoke(cli, ["job", "result", "job-failed"])

    assert listed.exit_code == 0, listed.output
    assert json.loads(listed.output)["jobs"][0]["job_id"] == "job-ic"
    assert fake.list_job_args == {
        "workspace_id": "workspace-1", "status": "queued,running", "kind": "ic", "limit": 7,
    }
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["error"]["traceback"] == "trace"


def test_cli_restores_historical_run_and_bulk_clears_current_workspace(tmp_path, monkeypatch) -> None:
    fake = FakeClient()
    monkeypatch.setenv("FACTORTESTER_HOME", str(tmp_path / "home"))
    monkeypatch.setattr("tools.cli.commands.research.client_from_config", lambda: fake)
    runner = CliRunner()
    assert runner.invoke(cli, ["workspace", "create", "--factor-family", "MmRet"]).exit_code == 0

    cloned = runner.invoke(cli, [
        "run", "clone-workspace", "run-1", "--title", "Historical clone",
    ])
    cleared = runner.invoke(cli, ["job", "clear-results", "--workspace"])
    cleared_history = runner.invoke(cli, ["job", "clear-history", "--workspace"])

    assert cloned.exit_code == 0, cloned.output
    assert "workspace_id=workspace-clone" in cloned.output
    assert load_state().workspace_id == "workspace-clone"
    assert fake.clone_title == "Historical clone"
    assert cleared.exit_code == 0, cleared.output
    assert fake.cleared_workspace_id == "workspace-clone"
    assert cleared_history.exit_code == 0, cleared_history.output
    assert fake.cleared_history_workspace_id == "workspace-clone"
