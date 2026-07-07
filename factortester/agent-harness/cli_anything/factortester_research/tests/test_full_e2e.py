from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path


def _resolve_cli(name: str) -> list[str]:
    import shutil

    force = os.environ.get("CLI_ANYTHING_FORCE_INSTALLED", "").strip() == "1"
    path = shutil.which(name)
    if path:
        return [path]
    if force:
        raise RuntimeError(f"{name} not found in PATH. Install with: pip install -e .")
    return [sys.executable, "-m", "cli_anything.factortester_research"]


class TestCLISubprocess:
    CLI_BASE = _resolve_cli("cli-anything-factortester-research")

    def _run(self, args: list[str], *, env: dict[str, str] | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
        merged_env = os.environ.copy()
        if env:
            merged_env.update(env)
        return subprocess.run(self.CLI_BASE + args, capture_output=True, text=True, check=check, env=merged_env)

    def test_help(self) -> None:
        result = self._run(["--help"])
        assert "FactorTester research harness" in result.stdout

    def test_plan_json_writes_session(self, tmp_path: Path) -> None:
        session = tmp_path / "session.json"
        result = self._run([
            "--session",
            str(session),
            "plan",
            "--factor-family",
            "SgCCS",
            "--product-group",
            "中国期货日盘",
            "--n",
            "2m",
            "--json",
        ])
        data = json.loads(result.stdout)
        assert data["session"]["factor_family"] == "SgCCS"
        assert any(item["phase"] == "diagnose_ic" for item in data["session"]["plan"])
        assert any(item["phase"] == "prepare_factor_workspace" for item in data["session"]["plan"])
        assert any(item["phase"] == "understand_factor_source" for item in data["session"]["plan"])
        assert any(item["phase"] == "platform_gap_loop" for item in data["session"]["plan"])
        assert session.exists()

    def test_run_step_records_platform_gap_with_fake_factortester(self, tmp_path: Path) -> None:
        bindir = tmp_path / "bin"
        bindir.mkdir()
        fake = bindir / "factortester"
        fake.write_text(
            "#!/usr/bin/env python3\n"
            "import sys\n"
            "print('No such command: missing_feature', file=sys.stderr)\n"
            "sys.exit(2)\n",
            encoding="utf-8",
        )
        fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
        session = tmp_path / "session.json"
        result = self._run(
            ["--session", str(session), "run-step", "--json", "--", "missing_feature"],
            env={"PATH": str(bindir) + os.pathsep + os.environ.get("PATH", "")},
            check=False,
        )
        assert result.returncode == 0
        payload = json.loads(result.stdout)
        assert payload["session"]["status"] == "code_improvement_required"
        assert payload["session"]["gaps"][0]["status"] == "open"

    def test_gap_resolve_returns_to_research_ready(self, tmp_path: Path) -> None:
        session = tmp_path / "session.json"
        self._run(["--session", str(session), "gap", "add", "missing export", "need csv"])
        self._run(["--session", str(session), "gap", "resolve", "gap-1", "--note", "done"])
        result = self._run(["--session", str(session), "status", "--json"])
        data = json.loads(result.stdout)
        assert data["status"] == "research_ready"

    def test_operator_mode_blocks_client_only_service_restart(self, tmp_path: Path) -> None:
        session = tmp_path / "session.json"
        result = self._run(
            ["--session", str(session), "service", "restart", "--target-port", "8123", "--dry-run"],
            check=False,
        )
        assert result.returncode != 0
        assert "client_only" in result.stderr

    def test_operator_source_owner_persists_admin_port(self, tmp_path: Path) -> None:
        session = tmp_path / "session.json"
        self._run([
            "--session",
            str(session),
            "operator",
            "set",
            "--mode",
            "source_owner",
            "--admin-port",
            "7998",
        ])
        result = self._run(["--session", str(session), "status", "--json"])
        data = json.loads(result.stdout)
        assert data["operator_mode"] == "source_owner"
        assert data["admin_port"] == 7998
