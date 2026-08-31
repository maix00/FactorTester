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
    if force:
        path = shutil.which(name)
        if path:
            print(f"[_resolve_cli] Using installed command: {path}")
            return [path]
        raise RuntimeError(f"{name} not found in PATH. Install with: pip install -e .")
    return [sys.executable, "-m", "cli_anything.factortester_research"]


class TestCLISubprocess:
    CLI_BASE = _resolve_cli("cli-anything-factortester-research")

    def _run(self, args: list[str], *, env: dict[str, str] | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
        merged_env = os.environ.copy()
        harness_root = str(Path(__file__).resolve().parents[3])
        merged_env["PYTHONPATH"] = os.pathsep.join(filter(None, (
            harness_root,
            merged_env.get("PYTHONPATH", ""),
        )))
        if env:
            merged_env.update(env)
        return subprocess.run(self.CLI_BASE + args, capture_output=True, text=True, check=check, env=merged_env)

    def test_help(self) -> None:
        result = self._run(["--help"])
        assert "FactorTester research harness" in result.stdout
        assert "\n  cycle " not in result.stdout

    def test_strategy_intent_configure_delegates_exactly_to_factortester(
        self, tmp_path: Path,
    ) -> None:
        bindir = tmp_path / "bin"
        bindir.mkdir()
        fake = bindir / "factortester"
        fake.write_text(
            "#!/usr/bin/env python3\n"
            "import json, sys\n"
            "assert sys.argv[1:] == [\n"
            "  'strategy', 'intent', 'configure', 'A1',\n"
            "  '--role', 'screen=Gate', '--role', 'sizing=Size',\n"
            "  '--screen-rule', 'gte', '--screen-lower', '1.5',\n"
            "  '--allocation-policy', 'factor_sizing', '--json'\n"
            "]\n"
            "print(json.dumps({'workspace_id': 'w1', 'revision': 5}))\n",
            encoding="utf-8",
        )
        fake.chmod(fake.stat().st_mode | stat.S_IXUSR)

        result = self._run(
            [
                "strategy", "intent", "configure", "A1",
                "--role", "screen=Gate", "--role", "sizing=Size",
                "--screen-rule", "gte", "--screen-lower", "1.5",
                "--allocation-policy", "factor_sizing", "--json",
            ],
            env={"PATH": str(bindir) + os.pathsep + os.environ.get("PATH", "")},
        )

        assert json.loads(result.stdout) == {"workspace_id": "w1", "revision": 5}

    def test_margin_budget_configure_delegates_exactly_to_factortester(
        self, tmp_path: Path,
    ) -> None:
        bindir = tmp_path / "bin"
        bindir.mkdir()
        fake = bindir / "factortester"
        fake.write_text(
            "#!/usr/bin/env python3\n"
            "import json, sys\n"
            "assert sys.argv[1:] == [\n"
            "  'margin-budget', 'configure', 'A1',\n"
            "  '--target', '0.8', '--max', '0.85', '--tolerance', '0.01', '--json'\n"
            "]\n"
            "print(json.dumps({'workspace_id': 'w1', 'revision': 6}))\n",
            encoding="utf-8",
        )
        fake.chmod(fake.stat().st_mode | stat.S_IXUSR)

        result = self._run(
            [
                "margin-budget", "configure", "A1",
                "--target", "0.8", "--max", "0.85", "--tolerance", "0.01", "--json",
            ],
            env={"PATH": str(bindir) + os.pathsep + os.environ.get("PATH", "")},
        )

        assert json.loads(result.stdout) == {"workspace_id": "w1", "revision": 6}

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
            "--product",
            "A.DCE",
            "--source",
            "Local",
            "--configuration-file",
            "run-spec.json",
            "--json",
        ])
        data = json.loads(result.stdout)
        assert data["session"]["factor_families"] == ["SgCCS", "MmRet"]
        assert data["session"]["factors"] == ["SgCCS=SgCCS|P:CA|N:10d"]
        assert data["session"]["products"] == ["A.DCE"]
        assert data["session"]["data_sources"] == ["Local"]
        assert data["session"]["events"][-1]["event"] == "product_scope_confirmed"
        assert data["session"]["plan"][0]["phase"] == "inspect_data_availability"
        assert any(item["phase"] == "inspect_factor_expr_dsl" for item in data["session"]["plan"])
        assert any(item["phase"] == "submit_run" for item in data["session"]["plan"])
        assert any(item["phase"] == "prepare_factor_workspace" for item in data["session"]["plan"])
        assert any(item["phase"] == "understand_factor_source" for item in data["session"]["plan"])
        assert any(item["phase"] == "platform_gap_loop" for item in data["session"]["plan"])
        assert data["session"]["configuration_file"] == "run-spec.json"
        assert session.exists()

    def test_plan_rejects_unconfirmed_product_or_source_scope(
        self,
        tmp_path: Path,
    ) -> None:
        base = [
            "--session",
            str(tmp_path / "session.json"),
            "plan",
            "--factor-family",
            "SgCCS",
            "--configuration-file",
            "run-spec.json",
            "--json",
        ]
        missing_product = self._run(
            [*base, "--source", "Local"],
            check=False,
        )
        missing_source = self._run(
            [*base, "--product", "A.DCE"],
            check=False,
        )

        assert missing_product.returncode != 0
        assert "Missing option '--product'" in missing_product.stderr
        assert missing_source.returncode != 0
        assert "Missing option '--source'" in missing_source.stderr

    def test_graph_observed_json_projects_the_saved_plan(self, tmp_path: Path) -> None:
        session = tmp_path / "session.json"
        self._run([
            "--session",
            str(session),
            "plan",
            "--factor-family",
            "SgCCS",
            "--product",
            "A.DCE",
            "--source",
            "Local",
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
        assert payload["resolution"]["cache"]["scope"] == "process"
        assert payload["resolution"]["cache"]["hit"] is False
        assert payload["resolution"]["gaps"] == []
        assert {
            item["capability_id"]
            for item in payload["resolution"]["bindings"]
        } == {
            "research-hypothesis.preregister",
            "research-obligation.discover",
        }

        approved = self._run([
            "graph",
            "capabilities",
            "--product-group",
            "china_futures",
            "--approve-implementation",
            "local.research-obligation-cycle",
            "--json",
        ])
        approved_payload = json.loads(approved.stdout)
        assert approved_payload["resolution"]["gaps"] == []
        assert {
            item["capability_id"]
            for item in approved_payload["resolution"]["bindings"]
        } == {
            "research-hypothesis.preregister",
            "research-obligation.discover",
        }

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
            "performance.bootstrap-sharpe",
        }
        assert {
            item["capability_id"]
            for item in detailed_payload["resolution"][
                "undetermined_conditions"
            ]
        } >= {
            "multiple-testing.false-discovery-control",
            "performance.deflated-sharpe",
            "performance.backtest-overfit-probability",
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

        assert payload["status"] == "failed"
        assert payload["external_mutations"] == 0
        assert payload["errors"] == [
            "event 0: unsatisfied guards: "
            "obligation_discovery_checkpoint_fresh"
        ]

    def test_capture_job_source_delegates_to_fragment_bound_native_cli(
        self,
        tmp_path: Path,
    ) -> None:
        backend = {
            "source": {
                "source_ref": "source:job:sha256:" + "1" * 64,
                "source_kind": "job",
                "available_fragments": [{
                    "selector": {"field": "status"},
                    "title_zh": "任务终态",
                }],
            },
        }
        bindir = tmp_path / "bin"
        bindir.mkdir()
        fake = bindir / "factortester"
        fake.write_text(
            "#!/usr/bin/env python3\n"
            "import json, sys\n"
            "assert sys.argv[1:] == [\n"
            "  'research', 'evidence', 'source', 'capture-job', 'job-1', '--json'\n"
            "]\n"
            f"print(json.dumps({backend!r}))\n",
            encoding="utf-8",
        )
        fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
        session = tmp_path / "session.json"
        env = {
            "PATH": str(bindir) + os.pathsep + os.environ.get("PATH", "")
        }

        result = self._run([
            "--session", str(session),
            "evidence", "source", "capture-job", "job-1", "--json",
        ], env=env)
        payload = json.loads(result.stdout)

        assert payload == backend
        assert not session.exists()

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
        assert envelope["schema_version"] == 2
        assert "decision" not in envelope
        assert envelope["stop_condition"] == "platform_capability_gap"

    def test_status_hides_legacy_evidence_without_deleting_audit_record(
        self,
        tmp_path: Path,
    ) -> None:
        session = tmp_path / "legacy-session.json"
        legacy = {
            "schema_version": 1,
            "envelope_id": "legacy-1",
            "envelope_hash": "a" * 64,
            "decision": "continue",
            "metric_refs": ["metric:private"],
            "artifact_refs": ["artifact:private"],
        }
        session.write_text(json.dumps({
            "evidence_envelopes": [legacy],
            "events": [{
                "event": "historical_decision",
                "evidence": legacy,
            }],
        }), encoding="utf-8")

        result = self._run([
            "--session",
            str(session),
            "status",
            "--json",
        ])
        payload = json.loads(result.stdout)

        assert payload["evidence_envelopes"] == []
        assert payload["legacy_evidence_unavailable_count"] == 1
        assert "metric:private" not in result.stdout
        assert json.loads(
            session.read_text(encoding="utf-8")
        )["evidence_envelopes"] == [legacy]

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
