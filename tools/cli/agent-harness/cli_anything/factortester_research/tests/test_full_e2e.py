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
            "--factor-family",
            "MmRet",
            "--factor",
            "SgCCS=SgCCS|P:CA|N:10d",
            "--configuration-file",
            "run-spec.json",
            "--json",
        ])
        data = json.loads(result.stdout)
        assert data["session"]["factor_families"] == ["SgCCS", "MmRet"]
        assert data["session"]["factors"] == ["SgCCS=SgCCS|P:CA|N:10d"]
        assert any(item["phase"] == "inspect_factor_expr_dsl" for item in data["session"]["plan"])
        assert any(item["phase"] == "submit_run" for item in data["session"]["plan"])
        assert any(item["phase"] == "prepare_factor_workspace" for item in data["session"]["plan"])
        assert any(item["phase"] == "understand_factor_source" for item in data["session"]["plan"])
        assert any(item["phase"] == "platform_gap_loop" for item in data["session"]["plan"])
        assert data["session"]["configuration_file"] == "run-spec.json"
        assert session.exists()

    def test_graph_observed_json_projects_the_saved_plan(self, tmp_path: Path) -> None:
        session = tmp_path / "session.json"
        self._run([
            "--session",
            str(session),
            "plan",
            "--factor-family",
            "SgCCS",
            "--configuration-file",
            "run-spec.json",
            "--json",
        ])

        result = self._run([
            "--session",
            str(session),
            "graph",
            "observed",
            "--json",
        ])
        graph = json.loads(result.stdout)

        assert graph["lifecycle"] == "observed"
        assert len(graph["content_hash"]) == 64
        assert any(
            item["node_id"] == "code_improvement_required"
            for item in graph["nodes"]
        )

    def test_graph_draft_capabilities_reports_product_bindings_and_gaps(
        self,
    ) -> None:
        draft_result = self._run(["graph", "draft", "--json"])
        draft = json.loads(draft_result.stdout)
        assert draft["research_semantics"] == "product_neutral"

        result = self._run([
            "graph",
            "capabilities",
            "--product-group",
            "china_futures",
            "--json",
        ])
        payload = json.loads(result.stdout)
        assert len(result.stdout.encode()) < 6000
        assert payload["product_group"] == "china_futures"
        assert payload["graph"]["lifecycle"] == "draft"
        assert "contracts" not in payload
        assert payload["resolution"]["node_id"] == (
            "hypothesis_preregistration"
        )
        assert payload["resolution"]["gaps"] == []
        assert {
            item["capability_id"]
            for item in payload["resolution"]["bindings"]
        } == {"research-hypothesis.preregister"}

        detailed = self._run([
            "graph",
            "capabilities",
            "--product-group",
            "china_futures",
            "--all",
            "--include-contracts",
            "--json",
        ])
        detailed_payload = json.loads(detailed.stdout)
        assert "contracts" in detailed_payload
        assert any(
            item["implementation_id"] == "factortester.analysis.ic"
            for item in detailed_payload["resolution"]["bindings"]
        )
        assert {
            item["capability_id"]
            for item in detailed_payload["resolution"]["gaps"]
        } >= {
            "multiple-testing.trial-ledger",
            "multiple-testing.false-discovery-control",
            "performance.deflated-sharpe",
        }

    def test_graph_replay_is_non_mutating(self) -> None:
        fixture = (
            Path(__file__).resolve().parent
            / "fixtures"
            / "historical_preflight_2026_07_16.json"
        )
        result = self._run([
            "graph",
            "replay",
            str(fixture),
            "--json",
        ])
        payload = json.loads(result.stdout)

        assert payload["status"] == "expected_block"
        assert payload["external_mutations"] == 0

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
        envelope = payload["session"]["evidence_envelopes"][0]
        assert envelope["command"]["returncode"] == 2
        assert envelope["command"]["stderr_ref"].startswith("local-artifact:")
        assert envelope["decision"] == "capability_gap"
        assert envelope["stop_condition"] == "platform_capability_gap"

    def test_gap_resolve_returns_to_research_ready(self, tmp_path: Path) -> None:
        session = tmp_path / "session.json"
        self._run(["--session", str(session), "gap", "add", "missing export", "need csv"])
        self._run(["--session", str(session), "gap", "resolve", "gap-1", "--note", "done"])
        result = self._run(["--session", str(session), "status", "--json"])
        data = json.loads(result.stdout)
        assert data["status"] == "research_ready"

    def test_skill_usage_is_a_local_audit_chain(self, tmp_path: Path) -> None:
        session = tmp_path / "session.json"
        common = [
            "--capability-description",
            "Challenge a graph change",
            "--descriptor-hash",
            "a" * 64,
            "--skill-name",
            "grill-me",
            "--skill-description",
            "Adversarial plan review",
            "--provider",
            "local",
            "--version",
            "1",
            "--source-fingerprint",
            "b" * 64,
            "--approval-ref",
            "audit:17",
            "--matching-rationale",
            "Matches the requested review semantics",
        ]
        loaded = self._run([
            "--session",
            str(session),
            "skill-usage",
            "record",
            *common,
            "--load-mode",
            "loaded",
            "--skill-document-tokens",
            "90",
            "--json",
        ])
        reused = self._run([
            "--session",
            str(session),
            "skill-usage",
            "record",
            *common,
            "--load-mode",
            "reused",
            "--cache-read-tokens",
            "70",
            "--json",
        ])

        first = json.loads(loaded.stdout)["skill_usage"]
        second = json.loads(reused.stdout)["skill_usage"]
        assert second["previous_record_hash"] == first["record_hash"]
        assert second["skill_document_tokens"] == 0

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
