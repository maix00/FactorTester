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
        assert any(item["phase"] == "inspect_factor_expr_dsl" for item in data["session"]["plan"])
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

    def test_workspace_inspect_records_gap_on_source_tree_mismatch(self, tmp_path: Path) -> None:
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        (workspace / "MyAlpha.py").write_text(
            "class MyAlpha(FactorFamily):\n"
            "    def factor_expr():\n"
            "        return CLOSE.rolling_mean(N)\n",
            encoding="utf-8",
        )
        bindir = tmp_path / "bin"
        bindir.mkdir()
        fake = bindir / "factortester"
        fake.write_text(
            "#!/usr/bin/env python3\n"
            "import json, sys\n"
            "args = sys.argv[1:]\n"
            "if args[:3] == ['custom_factors', 'workspace', 'show']:\n"
            f"    print('实际目录: {workspace}')\n"
            "    sys.exit(0)\n"
            "if args[:3] == ['custom_factors', 'describe', 'MyAlpha']:\n"
            "    print(json.dumps({\n"
            "        'factor': {'name': 'MyAlpha'},\n"
            "        'tree_repr': 'ColumnRef CLOSE',\n"
            "        'operator_keys': [],\n"
            "        'source_checks': {'ok': False, 'has_tree': True, 'source_tokens': ['rolling_mean'], 'tree_tokens': [], 'missing_in_tree': ['rolling_mean']}\n"
            "    }, ensure_ascii=False))\n"
            "    sys.exit(0)\n"
            "print('unexpected: ' + ' '.join(args), file=sys.stderr)\n"
            "sys.exit(2)\n",
            encoding="utf-8",
        )
        fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
        session = tmp_path / "session.json"
        result = self._run(
            ["--session", str(session), "workspace", "inspect", "--factor-family", "MyAlpha", "--no-sync", "--json"],
            env={"PATH": str(bindir) + os.pathsep + os.environ.get("PATH", "")},
            check=False,
        )
        assert result.returncode != 0
        payload = json.loads(session.read_text(encoding="utf-8"))
        assert payload["status"] == "code_improvement_required"
        assert payload["gaps"][0]["title"] == "Factor source and operator tree mismatch"

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
