from __future__ import annotations

import hashlib
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
        print(f"[_resolve_cli] Using installed command: {path}")
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

    def test_cycle_next_reads_only_the_compact_backend_packet(
        self,
        tmp_path: Path,
    ) -> None:
        bindir = tmp_path / "bin"
        bindir.mkdir()
        fake = bindir / "factortester"
        fake.write_text(
            "#!/usr/bin/env python3\n"
            "import json, sys\n"
            "assert sys.argv[1:] == [\n"
            "  'research-graph', 'next', 'instance-1', 'branch-1'\n"
            "]\n"
            "print(json.dumps({\n"
            "  'graph': 'factor-research@v2',\n"
            "  'node': {'node_id': 'factor_semantics'},\n"
            "  'current_obligations': [],\n"
            "  'candidate_trial_frontier': [],\n"
            "  'capabilities': [],\n"
            "  'changed_refs': ['trace:7'],\n"
            "  'next_bytes': 311\n"
            "}))\n",
            encoding="utf-8",
        )
        fake.chmod(fake.stat().st_mode | stat.S_IXUSR)

        result = self._run(
            ["cycle", "next", "instance-1", "branch-1", "--json"],
            env={"PATH": str(bindir) + os.pathsep + os.environ.get("PATH", "")},
        )
        packet = json.loads(result.stdout)

        assert packet["node"]["node_id"] == "factor_semantics"
        assert packet["changed_refs"] == ["trace:7"]
        assert "stdout" not in packet
        assert not (tmp_path / "session.json").exists()

    def test_cycle_inspect_loads_only_one_referenced_obligation(
        self,
        tmp_path: Path,
    ) -> None:
        bindir = tmp_path / "bin"
        bindir.mkdir()
        fake = bindir / "factortester"
        fake.write_text(
            "#!/usr/bin/env python3\n"
            "import json, sys\n"
            "assert sys.argv[1:] == [\n"
            "  'research-graph', 'cycle-object', 'instance-1', 'branch-1',\n"
            "  'obligation', 'obligation-1'\n"
            "]\n"
            "print(json.dumps({\n"
            "  'obligation_id': 'obligation-1',\n"
            "  'epistemic_question': 'Does the mechanism survive?'\n"
            "}))\n",
            encoding="utf-8",
        )
        fake.chmod(fake.stat().st_mode | stat.S_IXUSR)

        result = self._run(
            [
                "cycle", "inspect", "instance-1", "branch-1",
                "obligation", "obligation-1", "--json",
            ],
            env={"PATH": str(bindir) + os.pathsep + os.environ.get("PATH", "")},
        )

        assert json.loads(result.stdout)["obligation_id"] == "obligation-1"

    def test_capture_job_evidence_reuses_server_owned_envelope(
        self,
        tmp_path: Path,
    ) -> None:
        envelope = {
            "schema_version": 2,
            "envelope_id": "job-attempt:job-1",
            "evidence_kind": "job_attempt",
            "source_refs": ["research-job:job-1", "research-run:run-1"],
            "identity_refs": {
                "contract_hash": "1" * 64,
                "methodology_hash": "2" * 64,
                "trial_plan_hash": "3" * 64,
                "run_spec_hash": "4" * 64,
            },
            "facts": {
                "job_id": "job-1",
                "run_id": "run-1",
                "kind": "ic",
                "status": "succeeded",
                "attempt": 1,
                "trial_stage": "selection",
                "assurance": {
                    "policy_hash": "7" * 64,
                    "backend_revision": "backend-1",
                    "disposition": "trusted",
                    "anomaly_codes": [],
                },
            },
            "metric_refs": ["result-summary:sha256:" + "5" * 64],
            "artifact_refs": [
                "artifact-manifest:sha256:" + "6" * 64
            ],
            "hypotheses_tested": 0,
            "stop_condition": None,
            "limitations": [
                "The backend does not emit a canonical hypotheses-tested count."
            ],
            "conflicts": [],
        }
        envelope["envelope_hash"] = hashlib.sha256(
            json.dumps(
                envelope,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        backend = {
            "job_id": "job-1",
            "status": "succeeded",
            "evidence": {
                "job_attempt": envelope,
                "terminal_assurance": {
                    "run_spec_hash": "4" * 64,
                    "result_summary_hash": "5" * 64,
                    "artifact_manifest_hash": "6" * 64,
                    "policy_hash": "7" * 64,
                    "backend_revision": "backend-1",
                    "disposition": "trusted",
                    "anomaly_codes": [],
                },
            },
        }
        bindir = tmp_path / "bin"
        bindir.mkdir()
        fake = bindir / "factortester"
        fake.write_text(
            "#!/usr/bin/env python3\n"
            "import json\n"
            f"print(json.dumps({backend!r}))\n",
            encoding="utf-8",
        )
        fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
        session = tmp_path / "session.json"
        env = {
            "PATH": str(bindir) + os.pathsep + os.environ.get("PATH", "")
        }

        first = self._run([
            "--session", str(session),
            "evidence", "capture-job", "job-1", "--json",
        ], env=env)
        second = self._run([
            "--session", str(session),
            "evidence", "capture-job", "job-1", "--json",
        ], env=env)
        first_payload = json.loads(first.stdout)
        second_payload = json.loads(second.stdout)
        persisted = json.loads(session.read_text(encoding="utf-8"))

        assert first_payload["reused"] is False
        assert second_payload["reused"] is True
        assert first_payload["evidence_envelope"] == envelope
        assert len(persisted["evidence_envelopes"]) == 1
        assert persisted["events"][-1]["event"] == "job_evidence_captured"
        assert persisted["events"][-1]["assurance_disposition"] == "trusted"

    def test_cycle_advance_validates_before_real_backend_submission(
        self,
        tmp_path: Path,
    ) -> None:
        bindir = tmp_path / "bin"
        bindir.mkdir()
        marker = tmp_path / "backend-called"
        fake = bindir / "factortester"
        fake.write_text(
            "#!/usr/bin/env python3\n"
            "import json, pathlib, sys\n"
            f"pathlib.Path({str(marker)!r}).write_text('called')\n"
            "print(json.dumps({'branch_id': 'branch-1', 'status': 'active'}))\n",
            encoding="utf-8",
        )
        fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
        session = tmp_path / "session.json"
        invalid = tmp_path / "legacy.json"
        invalid.write_text(json.dumps({
            "evidence_envelope": {
                "schema_version": 1,
                "envelope_id": "legacy-1",
                "decision": "continue",
            },
        }), encoding="utf-8")
        env = {
            "PATH": str(bindir) + os.pathsep + os.environ.get("PATH", "")
        }

        rejected = self._run([
            "--session",
            str(session),
            "cycle",
            "advance",
            "instance-1",
            "branch-1",
            "--edge-id",
            "edge-1",
            "--evidence-file",
            str(invalid),
            "--json",
        ], env=env, check=False)

        assert rejected.returncode != 0
        assert not marker.exists()
        valid = tmp_path / "current.json"
        valid.write_text(json.dumps({
            "research_cycle": {"schema_version": 1, "events": []},
        }), encoding="utf-8")
        accepted = self._run([
            "--session",
            str(session),
            "cycle",
            "advance",
            "instance-1",
            "branch-1",
            "--edge-id",
            "edge-1",
            "--evidence-file",
            str(valid),
            "--json",
        ], env=env)
        payload = json.loads(accepted.stdout)

        assert marker.exists()
        assert payload["backend"]["branch_id"] == "branch-1"
        assert payload["local_validation"]["proposal_count"] == 0
        persisted = json.loads(session.read_text(encoding="utf-8"))
        assert persisted["events"][-1]["event"] == "research_cycle_advanced"
        assert persisted["evidence_envelopes"][-1]["schema_version"] == 2

    def test_cycle_continuation_preview_is_read_only_and_continue_is_audited(
        self,
        tmp_path: Path,
    ) -> None:
        bindir = tmp_path / "bin"
        bindir.mkdir()
        fake = bindir / "factortester"
        fake.write_text(
            "#!/usr/bin/env python3\n"
            "import json, sys\n"
            "if 'continuation-preview' in sys.argv:\n"
            " print(json.dumps({'target_hash': 'c' * 64}))\n"
            "else:\n"
            " print(json.dumps({'instance_id': 'instance-v6',"
            " 'graph_version': 6, 'branches': [{'branch_id': 'branch-v6'}]}))\n",
            encoding="utf-8",
        )
        fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
        session = tmp_path / "session.json"
        env = {
            "PATH": str(bindir) + os.pathsep + os.environ.get("PATH", "")
        }

        preview = self._run([
            "--session", str(session),
            "cycle", "continuation-preview",
            "instance-v5", "branch-v5",
            "--target-version", "6",
            "--job-id", "job-1",
            "--json",
        ], env=env)
        assert json.loads(preview.stdout)["target_hash"] == "c" * 64
        assert not session.exists()

        continued = self._run([
            "--session", str(session),
            "cycle", "continue",
            "instance-v5", "branch-v5",
            "--target-version", "6",
            "--job-id", "job-1",
            "--expected-target-hash", "c" * 64,
            "--human-authorization-id", "gate-146",
            "--json",
        ], env=env)
        payload = json.loads(continued.stdout)
        persisted = json.loads(session.read_text(encoding="utf-8"))
        assert payload["backend"]["instance_id"] == "instance-v6"
        assert persisted["events"][-1]["event"] == (
            "graph_continuation_created"
        )
        assert len(persisted["evidence_envelopes"]) == 1

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
