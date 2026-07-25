from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

from click.testing import CliRunner

from server.services.research_step import (
    build_inspect_contract,
    build_prepare_contract,
)
from tests.server.research_step.test_contracts import (
    _execution,
    _next_packet,
)
from tools.cli.app import cli
from tools.cli.commands import research_step as commands


class _Client:
    def inspect_research_step(self, instance_id: str, branch_id: str):
        assert (instance_id, branch_id) == ("instance-1", "branch-1")
        return build_inspect_contract(_next_packet(), _execution())

    def prepare_research_step(
        self, *, instance_id: str, branch_id: str, request: dict,
    ):
        assert (instance_id, branch_id) == ("instance-1", "branch-1")
        inspect = build_inspect_contract(_next_packet(), _execution())
        return build_prepare_contract(inspect, request)


def _request(inspect: dict) -> dict:
    return {
        "schema_version": 1,
        "context_ref": inspect["graph"]["context_ref"],
        "action_id": inspect["action"]["action_id"],
        "configurations": [{
            "configuration_id": "config-1",
            "configuration_revision": 1,
            "configuration_fingerprint": "7" * 64,
            "analyses": ["ic"],
            "trial_role": "candidate",
            "comparison_id": "comparison-1",
        }],
    }


def test_inspect_and_prepare_write_json(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(commands, "client_from_config", lambda: _Client())
    runner = CliRunner()
    inspect_file = tmp_path / "inspect.json"
    result = runner.invoke(cli, [
        "research", "step", "inspect", "instance-1", "branch-1",
        "--output", str(inspect_file),
    ])
    assert result.exit_code == 0, result.output
    inspect = json.loads(inspect_file.read_text(encoding="utf-8"))
    request_file = tmp_path / "request.json"
    request_file.write_text(
        json.dumps(_request(inspect)), encoding="utf-8",
    )
    contract_file = tmp_path / "contract.json"

    result = runner.invoke(cli, [
        "research", "step", "prepare",
        "--inspect-file", str(inspect_file),
        "--request-file", str(request_file),
        "--output", str(contract_file),
    ])

    assert result.exit_code == 0, result.output
    contract = json.loads(contract_file.read_text(encoding="utf-8"))
    assert contract["execution_ready"] is False


def test_validate_is_offline(monkeypatch, tmp_path) -> None:
    inspect = build_inspect_contract(_next_packet(), _execution())
    contract = build_prepare_contract(inspect, _request(inspect))
    path = tmp_path / "contract.json"
    path.write_text(json.dumps(contract), encoding="utf-8")

    def no_client():
        raise AssertionError("validate must not construct an HTTP client")

    monkeypatch.setattr(commands, "client_from_config", no_client)
    result = CliRunner().invoke(cli, [
        "research", "step", "validate", "--contract-file", str(path),
    ])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["valid"] is True


def test_help_exposes_only_batch_one_operations() -> None:
    result = CliRunner().invoke(cli, ["research", "step", "--help"])

    assert result.exit_code == 0
    assert "inspect" in result.output
    assert "prepare" in result.output
    assert "validate" in result.output
    assert "\n  execute " not in result.output


def test_public_command_imports_without_server_package() -> None:
    root = Path(__file__).resolve().parents[2]
    script = """
import importlib.abc
import sys
class BlockServer(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "server" or fullname.startswith("server."):
            raise ImportError("server package is unavailable in client wheel")
        return None
sys.meta_path.insert(0, BlockServer())
import tools.cli.commands.research_step
print("ok")
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd="/",
        env={
            **os.environ,
            "PYTHONPATH": str(root),
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


def test_atomic_output_preserves_previous_file_on_replace_failure(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(commands, "client_from_config", lambda: _Client())
    output = tmp_path / "inspect.json"
    output.write_text("previous\n", encoding="utf-8")

    def fail_replace(source, destination):
        raise OSError("simulated replace failure")

    monkeypatch.setattr(commands.os, "replace", fail_replace)
    result = CliRunner().invoke(cli, [
        "research", "step", "inspect", "instance-1", "branch-1",
        "--output", str(output),
    ])

    assert result.exit_code != 0
    assert output.read_text(encoding="utf-8") == "previous\n"
    assert list(tmp_path.glob(".inspect.json.*.tmp")) == []
