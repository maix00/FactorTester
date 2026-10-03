from __future__ import annotations

import hashlib
import json

from click.testing import CliRunner

from tools.cli.app import cli
from tools.cli.http import BinaryResponse
from tools.cli.state import load_state, save_state
from tools.cli.step.values import render_value


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

    def get_workspace_configuration(self, workspace_id):
        assert workspace_id == "workspace-1"
        return {"payload": {
            "schema_version": 1,
            "shared": {"factor_families": [], "factors": []},
            "analyses": {"ic": {}},
            "ui": {},
        }}

    def submit_run(
        self,
        workspace_id,
        configuration_revision,
        *,
        analyses,
        retention_mode,
        step_mode,
        trial_binding=None,
        report_binding=None,
        performance_profile=None,
        configuration_snapshot_id="",
        configuration_snapshot_revision=None,
    ):
        assert workspace_id == "workspace-1"
        if configuration_snapshot_id:
            assert configuration_revision is None
        else:
            assert configuration_revision == 2
        self.trial_binding = trial_binding
        self.report_binding = report_binding
        self.performance_profile = performance_profile
        self.snapshot_selection = (
            configuration_snapshot_id,
            configuration_snapshot_revision,
        )
        return {
            "run_id": "run-1",
            "jobs": [{"job_id": f"job-{kind}", "kind": kind, "status": "queued"} for kind in analyses],
            "report_projection": {
                "schema_version": 1,
                "run_spec": {
                    "alias_zh": "截面 IC · 日盘 · SgCPS",
                },
            },
        }

    def save_configuration_template(self, workspace_id, *, name):
        return {"configuration_id": "template-1", "name": name}

    def create_configuration_snapshot(self, workspace_id, **kwargs):
        self.snapshot_create = (workspace_id, kwargs)
        return {
            "snapshot_id": "snapshot-1",
            "workspace_id": workspace_id,
            "snapshot_revision": 1,
            "name": kwargs["name"],
        }

    def list_configuration_snapshots(self, workspace_id):
        return [{
            "snapshot_id": "snapshot-1",
            "workspace_id": workspace_id,
            "snapshot_revision": 1,
            "name": "Day",
        }]

    def load_configuration_template(self, workspace_id, *, expected_revision, configuration_id):
        assert (workspace_id, expected_revision, configuration_id) == ("workspace-1", 1, "template-1")
        return {"configuration_id": "config-1", "revision": 2}

    def list_jobs(self, **kwargs):
        self.list_job_args = kwargs
        return [{"job_id": "job-ic", "run_id": "run-1", "kind": "ic", "status": "running", "attempt": 1}]

    def job_result(self, job_id):
        if job_id == "job-ic-summary":
            return {
                "success": True,
                "factors": [{
                    "factor_alias": "MmEarlyLateSemivarianceOrder|H:5m|$F:1m",
                    "primary_forward_return_horizon": "MIN1",
                    "ic_stats_by_forward_horizon": {
                        "MIN1": {"0": {"mean": 0.03, "IR": 0.1, "t_stat": 2.4}},
                    },
                    "forward_ic_half_life": {"status": "estimated", "duration": "MIN4"},
                }],
            }
        return {
            "success": False,
            "job_id": job_id,
            "status": "failed",
            "error": {"message": "boom", "traceback": "trace"},
        }

    def job_artifact(self, job_id, name):
        assert (job_id, name) == ("job-curve", "equity_curve_report")
        return BinaryResponse(
            content=b"<svg><title>curve</title></svg>",
            content_type="image/svg+xml",
        )

    def list_job_artifacts(self, job_id):
        assert job_id == "job-curve"
        return [{
            "name": "equity_curve_report",
            "file_name": "curve.svg",
            "content_type": "image/svg+xml",
            "content_hash": hashlib.sha256(
                b"<svg><title>curve</title></svg>"
            ).hexdigest(),
            "size_bytes": 31,
            "state": "active",
            "role": "output",
        }]

    def job_artifact_to_path(self, job_id, name, destination):
        response = self.job_artifact(job_id, name)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(response.content)
        return {
            "path": str(destination),
            "size_bytes": len(response.content),
            "content_hash": hashlib.sha256(response.content).hexdigest(),
            "content_type": response.content_type,
        }

    def job_order_audit(self, job_id):
        assert job_id == "job-orders"
        return {
            "run_id": "run-orders",
            "strategies": {
                "A1": {
                    "groups": [{
                        "order_group_id": "G1",
                        "status": "partially_filled",
                        "execution_policy": "sequential_close_then_open",
                        "supersedes_group_id": "",
                        "products": ["RB.SHF"],
                        "requested_quantity": 15.0,
                        "filled_quantity": 6.0,
                        "active_leaves": 9.0,
                        "terminal_unfilled": 9.0,
                        "child_count": 2,
                        "child_order_ids": ["C1", "O1"],
                    }],
                    "orders": [
                        {
                            "order_id": "C1", "order_group_id": "G1",
                            "product": "RB.SHF", "side": "sell",
                            "offset": "close", "status": "partially_filled",
                            "requested_quantity": 10.0, "filled_quantity": 6.0,
                            "active_leaves": 4.0, "terminal_unfilled": 4.0,
                            "next_attempt_at": "2026-01-05T09:02:00",
                        },
                        {
                            "order_id": "O1", "order_group_id": "G1",
                            "product": "RB.SHF", "side": "sell",
                            "offset": "open", "status": "blocked",
                            "requested_quantity": 5.0, "filled_quantity": 0.0,
                            "active_leaves": 5.0, "terminal_unfilled": 5.0,
                            "next_attempt_at": None,
                        },
                    ],
                    "attempts": [{
                        "attempt_id": "C1:attempt:1", "order_id": "C1",
                        "revision": 0, "timestamp": "2026-01-05T09:01:00",
                        "market_timestamp": "2026-01-05T09:01:00",
                    }],
                    "fills": [{
                        "fill_id": "C1:fill:1", "order_id": "C1",
                        "attempt_id": "C1:attempt:1",
                        "timestamp": "2026-01-05T09:01:00",
                        "quantity": 6.0, "price": 3500.0, "fee": 1.0,
                    }],
                    "settlements": [{
                        "fill_id": "C1:fill:1", "realized_pnl": 10.0,
                        "fee": 1.0, "cash_before": 100.0, "cash_after": 109.0,
                        "margin_before": 20.0, "margin_after": 8.0,
                    }],
                    "actions": [],
                },
            },
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

    def continue_job(self, job_id, *, action="continue", until=""):
        self.continue_args = {
            "job_id": job_id,
            "action": action,
            "until": until,
        }
        return {"job_id": job_id, "status": "running"}

    def stream_job_id(self, job_id, *, after=0):
        self.stream_args = {"job_id": job_id, "after": after}
        yield {
            "event": "step",
            "data": {
                "timestamp": "2026-01-05 09:01:00",
                "flow_id": "apply_fill",
                "flow_phase": "event",
                "current_event": {"event_kind": "ORDER", "batch_count": 1, "subjects": []},
                "strategies": [{"strategy": "A1", "ledgers": ["L1"]}],
                "inputs": [{
                    "field": "CashPoolModule.cash",
                    "values": [{
                        "scope": "ledger", "ledger": "L1", "cash_pool": "P1",
                        "value": {"amount": 12345, "currency": "CNY", "use_minor_units": True, "scale": 2},
                    }],
                }],
                "outputs": [],
                "output_changes": [{
                    "field": "LedgerModule.positions",
                    "scope": "ledger", "ledger": "L1", "cash_pool": "P1",
                    "changes": [{
                        "instrument": "RB.SHF",
                        "before": {"quantity": 0},
                        "after": {"quantity": 2},
                    }],
                }],
                "ledger_changes": [],
                "event_payload_changes": [],
                "input_contract_violations": [],
            },
        }


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
    assert fake.trial_binding is None
    assert load_state().configuration_revision == 2


def test_run_submit_can_enable_cumulative_flow_profile(tmp_path, monkeypatch) -> None:
    fake = FakeClient()
    monkeypatch.setenv("FACTORTESTER_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(
        "tools.cli.commands.research.client_from_config", lambda: fake,
    )
    state = load_state()
    state.workspace_id = "workspace-1"
    state.configuration_revision = 2
    save_state(state)

    result = CliRunner().invoke(cli, [
        "run", "submit", "--analysis", "backtest",
        "--flow-profile", "--flow-profile-min-ms", "25",
    ])

    assert result.exit_code == 0, result.output
    assert fake.performance_profile == {
        "kind": "cumulative_flow",
        "min_total_ms": 25.0,
    }


def test_workspace_ic_horizons_writes_physical_horizons_and_entry_delay(tmp_path, monkeypatch) -> None:
    fake = FakeClient()
    monkeypatch.setenv("FACTORTESTER_HOME", str(tmp_path / "home"))
    monkeypatch.setattr("tools.cli.commands.research.client_from_config", lambda: fake)
    state = load_state()
    state.workspace_id = "workspace-1"
    state.configuration_revision = 1
    save_state(state)

    result = CliRunner().invoke(cli, [
        "workspace", "ic-horizons",
        "--base", "signal", "--base", "1m",
        "--multiple", "1", "--multiple", "5",
        "--entry-delay-bar", "0", "--entry-delay-bar", "1",
    ])

    assert result.exit_code == 0, result.output
    assert fake.payload["analyses"]["ic"] == {
        "forward_return_horizons": {"bases": ["signal", "1m"], "multipliers": [1, 5]},
        "ic_lags": [0, 1],
    }


def test_workspace_ic_horizons_can_select_scale_aware_sampling(tmp_path, monkeypatch) -> None:
    fake = FakeClient()
    monkeypatch.setenv("FACTORTESTER_HOME", str(tmp_path / "home"))
    monkeypatch.setattr("tools.cli.commands.research.client_from_config", lambda: fake)
    state = load_state()
    state.workspace_id = "workspace-1"
    state.configuration_revision = 1
    save_state(state)

    result = CliRunner().invoke(cli, [
        "workspace", "ic-horizons", "--sampling", "scale_aware",
    ])

    assert result.exit_code == 0, result.output
    assert fake.payload["analyses"]["ic"]["forward_return_horizons"] == {
        "sampling": "scale_aware",
    }


def test_workspace_ic_metrics_can_select_and_exclude_groups(tmp_path, monkeypatch) -> None:
    fake = FakeClient()
    monkeypatch.setenv("FACTORTESTER_HOME", str(tmp_path / "home"))
    monkeypatch.setattr("tools.cli.commands.research.client_from_config", lambda: fake)
    state = load_state()
    state.workspace_id = "workspace-1"
    state.configuration_revision = 1
    save_state(state)

    result = CliRunner().invoke(cli, [
        "workspace", "ic-metrics",
        "--metric", "core", "--metric", "holding_half_life",
        "--exclude", "persistence",
    ])

    assert result.exit_code == 0, result.output
    assert fake.payload["analyses"]["ic"]["ic_metric_selection"] == {
        "include": ["core", "holding_half_life"],
        "exclude": ["persistence"],
    }


def test_workspace_ic_rolling_writes_multiple_signal_count_windows(tmp_path, monkeypatch) -> None:
    fake = FakeClient()
    monkeypatch.setenv("FACTORTESTER_HOME", str(tmp_path / "home"))
    monkeypatch.setattr("tools.cli.commands.research.client_from_config", lambda: fake)
    state = load_state()
    state.workspace_id = "workspace-1"
    state.configuration_revision = 1
    save_state(state)

    result = CliRunner().invoke(cli, [
        "workspace", "ic-rolling",
        "--signal-count", "20", "--signal-count", "60",
    ])

    assert result.exit_code == 0, result.output
    assert fake.payload["analyses"]["ic"]["rolling_windows"] == {
        "signal_counts": [20, 60],
    }


def test_workspace_ic_rolling_rejects_clock_duration(tmp_path, monkeypatch) -> None:
    fake = FakeClient()
    monkeypatch.setenv("FACTORTESTER_HOME", str(tmp_path / "home"))
    monkeypatch.setattr("tools.cli.commands.research.client_from_config", lambda: fake)

    result = CliRunner().invoke(cli, [
        "workspace", "ic-rolling", "--duration", "1h",
    ])

    assert result.exit_code != 0
    assert "No such option" in result.output


def test_job_ic_summary_renders_forward_half_life(tmp_path, monkeypatch) -> None:
    fake = FakeClient()
    monkeypatch.setenv("FACTORTESTER_HOME", str(tmp_path / "home"))
    monkeypatch.setattr("tools.cli.commands.research.client_from_config", lambda: fake)

    result = CliRunner().invoke(cli, ["job", "ic-summary", "job-ic-summary", "--json"])

    assert result.exit_code == 0, result.output
    row = json.loads(result.output)["factors"][0]
    assert row["mean_ic"] == 0.03
    assert row["forward_ic_half_life"]["duration"] == "MIN4"


def test_job_continue_until_uses_continue_action(tmp_path, monkeypatch) -> None:
    fake = FakeClient()
    monkeypatch.setenv("FACTORTESTER_HOME", str(tmp_path / "home"))
    monkeypatch.setattr("tools.cli.commands.research.client_from_config", lambda: fake)

    result = CliRunner().invoke(cli, [
        "job", "continue", "job-step", "--until", "2026-01-05T15:00:00",
    ])

    assert result.exit_code == 0, result.output
    assert fake.continue_args == {
        "job_id": "job-step",
        "action": "continue",
        "until": "2026-01-05T15:00:00",
    }
    assert result.output.strip() == (
        "job_id=job-step status=running action=continue until=2026-01-05T15:00:00"
    )


def test_job_watch_renders_step_as_human_readable_tables(tmp_path, monkeypatch) -> None:
    fake = FakeClient()
    monkeypatch.setenv("FACTORTESTER_HOME", str(tmp_path / "home"))
    monkeypatch.setattr("tools.cli.commands.research.client_from_config", lambda: fake)

    result = CliRunner().invoke(cli, ["job", "watch", "job-step", "--after", "7"])

    assert result.exit_code == 0, result.output
    assert "STEP 2026-01-05 09:01:00" in result.output
    assert "CashPoolModule.cash" in result.output
    assert "12345 CNY (minor, scale=2)" in result.output
    assert "LedgerModule.positions" in result.output
    assert "RB.SHF" in result.output
    assert fake.stream_args == {"job_id": "job-step", "after": 7}


def test_job_watch_json_preserves_original_event(tmp_path, monkeypatch) -> None:
    fake = FakeClient()
    monkeypatch.setenv("FACTORTESTER_HOME", str(tmp_path / "home"))
    monkeypatch.setattr("tools.cli.commands.research.client_from_config", lambda: fake)

    result = CliRunner().invoke(cli, ["job", "watch", "job-step", "--json"])

    assert result.exit_code == 0, result.output
    event = json.loads(result.output)
    assert event["event"] == "step"
    assert event["data"]["inputs"][0]["field"] == "CashPoolModule.cash"


def test_job_watch_report_collects_only_after_stream_ends(tmp_path, monkeypatch) -> None:
    fake = FakeClient()
    calls = {}
    monkeypatch.setenv("FACTORTESTER_HOME", str(tmp_path / "home"))
    monkeypatch.setattr("tools.cli.commands.research.client_from_config", lambda: fake)
    monkeypatch.setattr(
        "tools.cli.commands.research.load_profile_root", lambda path: tmp_path,
    )
    monkeypatch.setattr(
        "tools.cli.commands.research.resolve_branch_report_scope",
        lambda **kwargs: {"scope": kwargs},
    )
    monkeypatch.setattr(
        "tools.cli.commands.research.collect_job_report",
        lambda client, *, job_id, scope: (
            calls.update({"client": client, "job_id": job_id, "scope": scope})
            or {"execution_node": "trial_execution"}
        ),
    )

    result = CliRunner().invoke(cli, [
        "job", "watch-report", "job-step", "--profile", "maxa",
        "--report-workspace-id", "package-1", "--branch-id", "branch-1",
    ])

    assert result.exit_code == 0, result.output
    assert calls["client"] is fake
    assert calls["job_id"] == "job-step"
    assert calls["scope"]["scope"]["branch_id"] == "branch-1"
    assert '"execution_node": "trial_execution"' in result.output


def test_job_orders_lists_compact_group_rows(tmp_path, monkeypatch) -> None:
    fake = FakeClient()
    monkeypatch.setenv("FACTORTESTER_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(
        "tools.cli.commands.job_orders.client_from_config", lambda: fake,
    )

    result = CliRunner().invoke(cli, ["job", "orders", "job-orders"])

    assert result.exit_code == 0, result.output
    assert "order_group_id" in result.output
    assert "G1" in result.output
    assert "partially_filled" in result.output
    assert "RB.SHF" in result.output


def test_job_order_json_expands_one_atomic_order(tmp_path, monkeypatch) -> None:
    fake = FakeClient()
    monkeypatch.setenv("FACTORTESTER_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(
        "tools.cli.commands.job_orders.client_from_config", lambda: fake,
    )

    result = CliRunner().invoke(cli, [
        "job", "order", "job-orders", "G1", "--order-id", "C1", "--json",
    ])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert [row["order_id"] for row in payload["orders"]] == ["C1"]
    assert payload["attempts"][0]["attempt_id"] == "C1:attempt:1"
    assert payload["fills"][0]["fill_id"] == "C1:fill:1"
    assert payload["settlements"][0]["margin_after"] == 8.0


def test_job_step_field_prints_exact_serialized_record(tmp_path, monkeypatch) -> None:
    fake = FakeClient()
    monkeypatch.setenv("FACTORTESTER_HOME", str(tmp_path / "home"))
    monkeypatch.setattr("tools.cli.commands.research.client_from_config", lambda: fake)

    result = CliRunner().invoke(cli, [
        "job", "step-field", "job-step", "CashPoolModule.cash", "--after", "3",
    ])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["field"] == "CashPoolModule.cash"
    record = payload["occurrences"][0]["record"]
    assert record["values"][0]["value"]["amount"] == 12345
    assert fake.stream_args == {"job_id": "job-step", "after": 3}


def test_step_complex_change_highlight_excludes_indentation() -> None:
    lines = render_value({"quantity": 2}, indent="    ", highlight=True)

    assert lines[0].startswith("    \x1b[")
    assert not lines[0].startswith("\x1b[")
    assert lines[-1].startswith("    \x1b[")


def test_step_changed_output_is_not_repeated_as_unchanged() -> None:
    from tools.cli.step import render_step_event

    lines = render_step_event({
        "flow_id": "resolve_run_window",
        "inputs": [],
        "outputs": [{
            "field": "RunWindowModule.run_window_envelope",
            "values": [{"scope": "context", "value": [{"ts": "09:00"}, {"ts": "15:00"}]}],
        }],
        "output_changes": [{
            "field": "RunWindowModule.run_window_envelope",
            "scope": "context", "before": None,
            "after": [{"ts": "09:00"}, {"ts": "15:00"}],
        }],
    })

    output = "\n".join(lines)
    assert "未变化输出" not in output
    assert output.count("RunWindowModule.run_window_envelope") == 1
    assert "boundary" in output
    assert "09:00" in output and "15:00" in output


def test_step_groups_identical_product_selection_without_losing_owners() -> None:
    from tools.cli.step import render_step_event

    selection = {
        "product_path_selection_id": "pg-1",
        "label": "日盘",
        "source_type": "manual_selection",
        "selected_paths": ["Product/Futures", "-Product/Futures/_products/BB.DCE"],
    }
    lines = render_step_event({
        "flow_id": "resolve_product_selection",
        "inputs": [{
            "field": "ProductSelectionModule.product_path_selection",
            "values": [
                {"scope": "strategy_config", "strategy": "A1", "value": selection},
                {"scope": "strategy_config", "strategy": "A2", "value": selection},
            ],
        }],
        "outputs": [], "output_changes": [],
    })

    output = "\n".join(lines)
    assert output.count("pg-1") == 1
    assert "A1" in output and "A2" in output
    assert "BB.DCE" in output


def test_step_product_string_uses_counted_product_table_without_ellipsis() -> None:
    from tools.cli.step import render_step_event

    products = "[AP.CZC, CJ.CZC, EC.INE, FB.DCE]"
    lines = render_step_event({
        "flow_id": "resolve_product_selection",
        "inputs": [], "outputs": [],
        "output_changes": [
            {"field": "ProductSelectionModule.products", "strategy": strategy, "before": None, "after": products}
            for strategy in ("A1", "A2")
        ],
    })

    output = "\n".join(lines)
    assert "count" in output and "4" in output
    assert "AP.CZC, CJ.CZC, EC.INE, FB.DCE" in output
    assert "…" not in output


def test_step_product_input_lists_every_product_without_scalar_truncation() -> None:
    from tools.cli.step import render_step_event

    products = "[AP.CZC, CJ.CZC, EC.INE, FB.DCE]"
    lines = render_step_event({
        "flow_id": "validate_ledger_sessions",
        "inputs": [{
            "field": "ProductSelectionModule.products",
            "values": [
                {"scope": "strategy_context", "strategy": strategy, "value": products}
                for strategy in ("A1", "A2")
            ],
        }],
        "outputs": [], "output_changes": [],
    })

    output = "\n".join(lines)
    assert "count" in output and "4" in output
    assert all(product in output for product in ("AP.CZC", "CJ.CZC", "EC.INE", "FB.DCE"))
    assert "…" not in output


def test_market_data_load_plan_and_exclusions_render_as_tables() -> None:
    from tools.cli.step import render_step_event

    lines = render_step_event({
        "flow_id": "check_market_data_coverage", "inputs": [], "outputs": [],
        "output_changes": [
            {"field": "MarketDataModule.market_data_load_plan", "before": None, "after": {
                "type": "MarketDataLoadPlan", "count": 2, "items": {
                    "AP.CZC": {"data_source": "LocalMIN1", "frequency": "MIN1"},
                    "CZCE|F|AP|2605": {"data_source": "ContractMIN1", "frequency": "MIN1"},
                },
            }},
            {"field": "MarketDataModule.excluded_out_of_range_products", "before": None, "after": {
                "type": "MarketDataExcludedProducts", "count": 1, "rows": [{"product": "TC.CZC"}],
            }},
        ],
    })
    output = "\n".join(lines)
    assert "AP.CZC" in output and "LocalMIN1" in output
    assert "TC.CZC" in output
    assert '"items"' not in output


def test_empty_position_book_initialization_is_summarized_per_ledger() -> None:
    from tools.cli.step import render_step_event

    empty_book = {"AP.CZC": {"quantity": 0}, "CJ.CZC": {"quantity": 0}}
    lines = render_step_event({
        "flow_id": "initialize_ledgers", "inputs": [], "outputs": [],
        "output_changes": [
            {
                "field": "LedgerModule.positions", "ledger": ledger, "cash_pool": "P1",
                "before": None, "after": empty_book,
            }
            for ledger in ("L1", "L2")
        ],
    })
    output = "\n".join(lines)
    assert "instruments" in output and "nonzero" in output
    assert "empty" in output
    assert "L1" in output and "L2" in output
    assert '"quantity"' not in output


def test_shadowed_empty_defaults_are_reported_not_repeated() -> None:
    from tools.cli.step import render_step_event

    lines = render_step_event({
        "flow_id": "coverage", "outputs": [], "output_changes": [],
        "inputs": [{
            "field": "MarketDataModule.required_data_source",
            "values": [
                {"scope": "strategy_config", "strategy": "A1", "value": None},
                {"scope": "context", "value": []},
            ],
        }],
    })
    output = "\n".join(lines)
    assert "[]" in output
    assert "已省略 1 条" in output
    assert "strategy_config" not in output


def test_event_drafts_render_as_semantic_rows() -> None:
    from tools.cli.step import render_step_event

    draft = {
        "type": "EventDraft", "timestamp": "2026-01-05 15:00:00", "kind": "ledger",
        "ledger": "L1", "strategy": "", "index_key": None,
        "payload": {"kind": "daily_mark_to_market", "ledger_id": "L1", "trading_day": "2026-01-05"},
    }
    lines = render_step_event({
        "flow_id": "register_dmtm", "inputs": [], "outputs": [],
        "output_changes": [{
            "field": "TradingRuleModule.daily_mark_to_market_events",
            "before": None, "after": [draft],
        }],
    })
    output = "\n".join(lines)
    assert "events=1" in output and "daily_mark_to_market" in output
    assert '"payload"' not in output


def test_sampled_signal_events_render_count_and_rows() -> None:
    from tools.cli.step import render_step_event

    draft = {
        "type": "EventDraft", "timestamp": "2026-01-05 09:01:00", "kind": "signal",
        "strategy": "A1", "ledger": "", "payload": None,
        "index_key": ["2026-01-05", "2026-01-05 09:01:00"],
    }
    lines = render_step_event({
        "flow_id": "signals", "inputs": [], "outputs": [],
        "output_changes": [{
            "field": "FactorSignalModule.signal_value", "before": None,
            "after": {"type": "list", "length": 1800, "truncated": True, "sample": {"head": [draft], "tail": []}},
        }],
    })
    output = "\n".join(lines)
    assert "events=1800" in output and "A1" in output
    assert '"index_key"' not in output


def test_current_market_snapshot_and_constraints_render_semantically() -> None:
    from tools.cli.step import render_step_event

    lines = render_step_event({
        "flow_id": "lookup_prices", "inputs": [], "outputs": [],
        "output_changes": [
            {"field": "MarketDataModule.current_market_snapshot", "before": None, "after": {
                "close": {"AP.CZC": 10}, "volume": {"AP.CZC": 20},
                "upper_limit": {"AP.CZC": 12}, "lower_limit": {"AP.CZC": 8},
            }},
            {"field": "MarketDataModule.current_tradable_status", "before": None, "after": {"AP.CZC": True}},
            {"field": "MarketDataModule.current_order_constraints", "before": None, "after": {
                "AP.CZC": {"tradable": True, "can_buy": True, "can_sell": True, "reason": "", "limit_up_price": 0, "limit_down_price": 0},
            }},
        ],
    })
    output = "\n".join(lines)
    assert "instrument" in output and "close" in output and "volume" in output
    assert "tradable=1, blocked=0" in output
    assert "normal=1, constrained=0" in output
    assert '"can_buy"' not in output


def test_current_market_snapshot_input_is_summarized_by_basis() -> None:
    from tools.cli.step import render_step_event

    lines = render_step_event({
        "flow_id": "margin", "outputs": [], "output_changes": [],
        "inputs": [{"field": "MarketDataModule.current_market_snapshot", "values": [{"value": {
            "close": {"AP.CZC": 10, "CJ.CZC": 20},
            "settlement": {"AP.CZC": 9, "CJ.CZC": 21},
        }}]}],
    })
    output = "\n".join(lines)
    assert "basis" in output and "close" in output and "settlement" in output
    assert "instruments" in output and "逐品种快照" in output
    assert '"AP.CZC"' not in output


def test_current_historical_fields_preserve_accounting_semantics() -> None:
    from tools.cli.step import render_step_event

    lines = render_step_event({
        "flow_id": "historical_fields", "inputs": [], "outputs": [],
        "output_changes": [{
            "field": "MarketDataModule.current_historical_fields", "before": None,
            "after": {"AP.CZC": {
                "CostBasisMethod": "DailyMarkToMarket", "MoneyCalculationPolicy": "aggregate",
                "VolumeMultiple": 10, "OpenRatioByVolume": 5,
            }},
        }],
    })
    output = "\n".join(lines)
    assert "会计语义" in output and "DailyMarkToMarket" in output and "aggregate" in output
    assert "数值规则范围" in output and "VolumeMultiple" in output and "OpenRatioByVolume" in output
    assert '"CostBasisMethod"' not in output


def test_delta_maps_render_compact_owner_summary() -> None:
    from tools.cli.step import render_step_event

    lines = render_step_event({
        "flow_id": "size", "inputs": [], "outputs": [],
        "output_changes": [
            {"field": "OrderConstructModule.raw_deltas", "strategy": strategy, "before": None, "after": {"AP.CZC": value}}
            for strategy, value in (("A1", 2.5), ("A2", -3.0))
        ],
    })
    output = "\n".join(lines)
    assert "owner" in output and "instruments" in output and "gross_abs" in output
    assert "A1" in output and "A2" in output and "AP.CZC" not in output
    assert "step-field" in output
    assert '"AP.CZC"' not in output


def test_delta_maps_omit_only_zero_entries_with_explicit_note() -> None:
    from tools.cli.step import render_step_event

    lines = render_step_event({
        "flow_id": "size", "inputs": [], "outputs": [],
        "output_changes": [{
            "field": "OrderConstructModule.raw_deltas", "strategy": "A1", "before": None,
            "after": {"AP.CZC": 2, "CJ.CZC": 0},
        }],
    })
    output = "\n".join(lines)
    assert "AP.CZC" not in output and "CJ.CZC" not in output
    assert "已省略 1 个零 delta" in output and "step-field" in output


def test_trade_intent_summarizes_weights_without_repeating_map() -> None:
    from tools.cli.step import render_step_event

    lines = render_step_event({
        "flow_id": "group", "inputs": [], "outputs": [],
        "output_changes": [{
            "field": "TargetStrategyModule.trade_intent", "strategy": "A1", "before": None,
            "after": {"type": "rebalance", "reason": "signal", "weights": {"AP.CZC": 0.5, "CJ.CZC": -0.5}},
        }],
    })
    output = "\n".join(lines)
    assert "weight_count" in output and "2" in output
    assert "rebalance" in output and "signal" in output
    assert "AP.CZC" not in output and "target_weights" in output


def test_factor_role_values_render_one_compact_row_per_role() -> None:
    from tools.cli.step import render_step_event

    lines = render_step_event({
        "flow_id": "factor_roles", "inputs": [], "outputs": [],
        "output_changes": [{
            "field": "FactorModule.factor_role_values", "strategy": "A1", "before": None,
            "after": {
                "screen": {"AP.CZC": 1.0, "CJ.CZC": 0.0},
                "sizing": {"AP.CZC": 2.0, "CJ.CZC": 4.0},
            },
        }],
    })
    output = "\n".join(lines)
    assert "role" in output and "screen" in output and "sizing" in output
    assert "count" in output and "finite" in output and "step-field" in output
    assert "AP.CZC" not in output and "CJ.CZC" not in output


def test_margin_budget_step_transposes_one_pool_and_reports_gross_leverage() -> None:
    from tools.cli.step import render_step_event

    output = "\n".join(render_step_event({
        "flow_id": "apply_target_margin_budget", "inputs": [], "outputs": [],
        "output_changes": [{
            "field": "MarginBudgetModule.margin_budget_summary", "before": None,
            "after": {"private:A1": {
                "equity": 100_000_000, "target_margin": 80_000_000,
                "projected_margin": 80_000_000, "weighted_margin_ratio": 0.125,
                "scale": 6.4, "gross_leverage": 6.4,
                "projected_utilization": 0.8, "max_utilization": 0.85,
            }},
        }],
    }))

    assert "指标" in output and "数值" in output
    assert "总名义杠杆" in output and "6.4" in output
    assert "预计保证金利用率" in output and "保证金硬上限" in output
    assert "step-field" in output
    assert '"raw_gross_notional"' not in output


def test_large_target_weight_map_keeps_directional_summary_and_samples() -> None:
    from tools.cli.step import render_step_event

    changes = []
    for strategy in ("A1", "A2"):
        weights = {f"L{i}.{strategy}": 0.05 for i in range(6)}
        weights.update({f"S{i}.{strategy}": -0.05 for i in range(6)})
        changes.append({
            "field": "TargetStrategyModule.target_weights", "strategy": strategy,
            "before": None, "after": weights,
        })
    output = "\n".join(render_step_event({
        "flow_id": "targets", "inputs": [], "outputs": [], "output_changes": changes,
    }))
    assert "long" in output and "short" in output and "gross" in output and "net" in output
    assert "L0.A1" in output and "S0.A2" in output
    assert "L5.A1" not in output and "逐品种目标权重" in output


def test_empty_dmtm_payload_is_not_rendered() -> None:
    from tools.cli.step import render_step_event

    output = "\n".join(render_step_event({
        "flow_id": "signal", "inputs": [], "outputs": [], "output_changes": [],
        "dmtm": {"events": [], "resolved": [], "cash_changes": [], "position_changes": []},
    }))
    assert "DMTM 审计" not in output


def test_orders_render_as_rows_with_rejection_semantics() -> None:
    from tools.cli.step import render_step_event

    order = {
        "instrument": "AP.CZC", "quantity": 2, "intent_quantity": 3,
        "status": "rejected", "reject_reason": "cash", "order_id": "o1",
        "order_group_id": "g1", "offset": "open",
        "requested_quantity": 3, "accepted_quantity": 3, "filled_quantity": 1,
        "fields": {},
    }
    lines = render_step_event({
        "flow_id": "orders", "inputs": [], "outputs": [],
        "output_changes": [{"field": "OrderConstructModule.orders", "strategy": "A1", "before": None, "after": [order]}],
    })
    output = "\n".join(lines)
    assert "orders" in output and "quantity" in output and "intent" in output
    assert "rejected" in output and "cash" in output and "o1" in output
    assert "groups" in output and "g1" in output and "active_leaves" in output
    assert "job orders/order" in output
    assert "step-field" in output
    assert '"reject_reason"' not in output


def test_dmtm_renders_data_money_units_and_position_settlement() -> None:
    from tools.cli.step import render_step_event

    money_before = {"type": "DataMoney", "currency": "CNY", "scale": 100, "minor_units": 1050, "major_units": 10.5}
    money_after = {"type": "DataMoney", "currency": "CNY", "scale": 100, "minor_units": 1250, "major_units": 12.5}
    lines = render_step_event({"flow_id": "dmtm", "inputs": [], "outputs": [], "output_changes": [], "dmtm": {
        "events": [{"ledger": "L1", "trading_day": "2026-01-05"}],
        "resolved": [], "accounting_inputs": [{"field": "accounting_mode", "values": [{"value": "Auto"}]}],
        "market_rule_inputs": [],
        "cash_changes": [{"ledger": "L1", "before": money_before, "after": money_after}],
        "position_changes": [{"ledger": "L1", "changes": [{"instrument": "AP.CZC", "before": {"quantity": 1, "settlement_price": None, "margin_reserved": money_before}, "after": {"quantity": 1, "settlement_price": 10, "margin_reserved": money_after}}]}],
        "margin_changes": [],
    }})
    output = "\n".join(lines)
    assert "before_major" in output and "before_minor" in output
    assert "delta_major" in output and "delta_minor" in output
    assert "settled" in output and "instruments" in output
    assert "margin_before_major" in output and "L1" in output
    assert "AP.CZC" not in output and "step-field" in output


def test_dmtm_deduplicates_fields_represented_by_dedicated_audit() -> None:
    from tools.cli.step import render_step_event

    position_change = {"field": "LedgerModule.positions", "ledger": "L1", "changes": []}
    lines = render_step_event({
        "flow_id": "dmtm", "inputs": [{"field": "MarketDataModule.current_market_snapshot", "values": [{"value": {"close": {"AP.CZC": 10}}}]}],
        "outputs": [], "output_changes": [position_change, {"field": "TradingRuleModule.resolved_daily_mark_to_market", "before": None, "after": {"large": "duplicate"}}],
        "dmtm": {
            "events": [], "accounting_inputs": [],
            "market_rule_inputs": [{"field": "MarketDataModule.current_market_snapshot", "values": [{"value": {"close": {"AP.CZC": 10}}}]}],
            "resolved": [{"value": {"L1": {"AP.CZC": {"enabled": True}}}}],
            "cash_changes": [], "position_changes": [position_change], "margin_changes": [],
        },
    })
    output = "\n".join(lines)
    assert output.count("MarketDataModule.current_market_snapshot") == 1
    assert output.count("LedgerModule.positions") == 0
    assert "large" not in output and "DMTM 解析" in output


def test_margin_only_position_changes_are_summarized_per_ledger() -> None:
    from tools.cli.step import render_step_event

    before = {"type": "DataMoney", "major_units": 10, "minor_units": 1000, "currency": "CNY", "scale": 100}
    after = {"type": "DataMoney", "major_units": 12, "minor_units": 1200, "currency": "CNY", "scale": 100}
    lines = render_step_event({
        "flow_id": "margin", "inputs": [], "outputs": [],
        "output_changes": [{"field": "LedgerModule.positions", "ledger": "L1", "changes": [
            {"instrument": "AP.CZC", "before": {"quantity": 1, "margin_reserved": before},
             "after": {"quantity": 1, "margin_reserved": after}},
        ]}],
    })
    output = "\n".join(lines)
    assert "before_major" in output and "after_major" in output and "L1" in output
    assert "AP.CZC" not in output and "step-field" in output


def test_run_submit_passes_trial_binding_file(tmp_path, monkeypatch) -> None:
    fake = FakeClient()
    monkeypatch.setenv("FACTORTESTER_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(
        "tools.cli.commands.research.client_from_config",
        lambda: fake,
    )
    runner = CliRunner()
    assert runner.invoke(
        cli,
        ["workspace", "create", "--factor-family", "MmRet"],
    ).exit_code == 0
    state = load_state()
    state.configuration_revision = 2
    save_state(state)
    binding = {
        "trial_plan": {"schema_version": 1},
        "trial_plan_hash": "a" * 64,
        "trial_plan_version": 1,
        "trial_role": "main",
        "comparison_id": "comparison-1",
    }
    path = tmp_path / "trial-binding.json"
    path.write_text(json.dumps(binding), encoding="utf-8")

    submitted = runner.invoke(cli, [
        "run",
        "submit",
        "--analysis",
        "ic",
        "--trial-binding-file",
        str(path),
        "--without-report",
    ])

    assert submitted.exit_code == 0, submitted.output
    assert fake.trial_binding == binding


def test_run_submit_requires_explicit_report_intent_for_trial_job(
    tmp_path, monkeypatch,
) -> None:
    fake = FakeClient()
    monkeypatch.setenv("FACTORTESTER_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(
        "tools.cli.commands.research.client_from_config",
        lambda: fake,
    )
    runner = CliRunner()
    assert runner.invoke(
        cli,
        ["workspace", "create", "--factor-family", "MmRet"],
    ).exit_code == 0
    state = load_state()
    state.configuration_revision = 2
    save_state(state)
    path = tmp_path / "trial-binding.json"
    path.write_text(json.dumps({
        "binding_origin": "agent_direct",
        "trial_plan": {"schema_version": 1},
    }), encoding="utf-8")

    submitted = runner.invoke(cli, [
        "run", "submit", "--analysis", "ic",
        "--trial-binding-file", str(path),
    ])

    assert submitted.exit_code != 0
    assert "必须绑定报告范围" in submitted.output


def test_run_submit_freezes_explicit_report_scope(
    tmp_path, monkeypatch,
) -> None:
    fake = FakeClient()
    monkeypatch.setenv("FACTORTESTER_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(
        "tools.cli.commands.research.client_from_config",
        lambda: fake,
    )
    monkeypatch.setattr(
        "tools.cli.commands.research.resolve_branch_report_scope",
        lambda **_kwargs: object(),
    )
    frozen = {
        "profile_ref": "profile:maxa",
        "report_workspace_id": "package-1",
        "branch_id": "branch-1",
        "report_id": "report-package-1-branch-1",
        "report_generation": 7,
        "report_head_hash": "b" * 64,
        "report_parent_id": "direct-trials",
    }

    def _freeze(_scope, *, trial_binding, report_parent_id):
        assert trial_binding["binding_origin"] == "agent_direct"
        assert report_parent_id == "direct-trials"
        return frozen

    monkeypatch.setattr(
        "tools.cli.commands.research.freeze_report_binding",
        _freeze,
    )
    runner = CliRunner()
    assert runner.invoke(
        cli,
        ["workspace", "create", "--factor-family", "MmRet"],
    ).exit_code == 0
    state = load_state()
    state.configuration_revision = 2
    save_state(state)
    path = tmp_path / "trial-binding.json"
    path.write_text(json.dumps({
        "binding_origin": "agent_direct",
        "trial_plan": {"schema_version": 1},
    }), encoding="utf-8")

    submitted = runner.invoke(cli, [
        "run", "submit", "--analysis", "ic",
        "--trial-binding-file", str(path),
        "--profile", "maxa",
        "--report-workspace-id", "package-1",
        "--branch-id", "branch-1",
        "--report-parent-id", "direct-trials",
        "--no-wait-report",
    ])

    assert submitted.exit_code == 0, submitted.output
    assert fake.report_binding == frozen


def test_run_submit_binds_direct_trial_to_explicit_report_parent(
    tmp_path, monkeypatch,
) -> None:
    fake = FakeClient()
    fake.stream_job_id = lambda _job_id, after=0: iter([{
        "event": "result",
        "data": {"status": "succeeded"},
    }])
    monkeypatch.setenv("FACTORTESTER_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(
        "tools.cli.commands.research.client_from_config",
        lambda: fake,
    )
    scope = object()
    monkeypatch.setattr(
        "tools.cli.commands.research.resolve_branch_report_scope",
        lambda **_kwargs: scope,
    )
    frozen = {
        "profile_ref": "profile:maxa",
        "report_workspace_id": "package-1",
        "branch_id": "branch-1",
        "report_id": "report-package-1-branch-1",
        "report_generation": 7,
        "report_head_hash": "b" * 64,
        "report_parent_id": "direct-trials",
    }

    def _freeze(_scope, *, trial_binding, report_parent_id):
        assert trial_binding["binding_origin"] == "agent_direct"
        assert report_parent_id == "direct-trials"
        return frozen

    monkeypatch.setattr(
        "tools.cli.commands.research.freeze_report_binding",
        _freeze,
    )
    collected = []

    def _collect(_client, *, job_id, scope):
        collected.append((job_id, scope))
        return {
            "job_id": job_id,
            "report_follow_up": {
                "status": "analysis_required",
                "parent_id": f"job-{job_id}-result",
            },
        }

    monkeypatch.setattr(
        "tools.cli.commands.research.collect_job_report",
        _collect,
    )
    runner = CliRunner()
    assert runner.invoke(
        cli,
        ["workspace", "create", "--factor-family", "MmRet"],
    ).exit_code == 0
    state = load_state()
    state.configuration_revision = 2
    save_state(state)
    path = tmp_path / "direct-trial-binding.json"
    path.write_text(json.dumps({
        "binding_origin": "agent_direct",
        "trial_plan": {"schema_version": 1},
    }), encoding="utf-8")

    submitted = runner.invoke(cli, [
        "run", "submit", "--analysis", "ic",
        "--trial-binding-file", str(path),
        "--profile", "maxa",
        "--report-workspace-id", "package-1",
        "--branch-id", "branch-1",
        "--report-parent-id", "direct-trials",
        "--json",
    ])

    assert submitted.exit_code == 0, submitted.output
    assert fake.report_binding == frozen
    assert collected == [("job-ic", scope)]
    assert json.loads(submitted.output)["report_collections"][0][
        "report_follow_up"
    ]["parent_id"] == "job-job-ic-result"


def test_report_bound_submit_waits_mounts_and_requests_analysis(
    tmp_path, monkeypatch,
) -> None:
    fake = FakeClient()
    fake.stream_job_id = lambda _job_id, after=0: iter([{
        "event": "result",
        "data": {"status": "succeeded"},
    }])
    monkeypatch.setenv("FACTORTESTER_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(
        "tools.cli.commands.research.client_from_config",
        lambda: fake,
    )
    scope = object()
    monkeypatch.setattr(
        "tools.cli.commands.research.resolve_branch_report_scope",
        lambda **_kwargs: scope,
    )
    monkeypatch.setattr(
        "tools.cli.commands.research.freeze_report_binding",
        lambda _scope, *, trial_binding, report_parent_id: {
            "profile_ref": "profile:maxa",
            "report_workspace_id": "package-1",
            "branch_id": "branch-1",
            "report_id": "report-package-1-branch-1",
            "report_generation": 7,
            "report_head_hash": "b" * 64,
            "report_parent_id": report_parent_id,
        },
    )
    collected = []

    def collect(_client, *, job_id, scope):
        collected.append((job_id, scope))
        return {
            "job_id": job_id,
            "report_follow_up": {
                "status": "analysis_required",
                "parent_id": f"job-{job_id}-result",
                "message": "已添加，请分析",
            },
        }

    monkeypatch.setattr(
        "tools.cli.commands.research.collect_job_report",
        collect,
    )
    runner = CliRunner()
    assert runner.invoke(
        cli,
        ["workspace", "create", "--factor-family", "MmRet"],
    ).exit_code == 0
    state = load_state()
    state.configuration_revision = 2
    save_state(state)
    path = tmp_path / "trial-binding.json"
    path.write_text(json.dumps({
        "binding_origin": "agent_direct",
        "trial_plan": {"schema_version": 1},
    }), encoding="utf-8")

    submitted = runner.invoke(cli, [
        "run", "submit", "--analysis", "ic",
        "--trial-binding-file", str(path),
        "--profile", "maxa",
        "--report-workspace-id", "package-1",
        "--branch-id", "branch-1",
        "--report-parent-id", "direct-trials",
        "--json",
    ])

    assert submitted.exit_code == 0, submitted.output
    payload = json.loads(submitted.output)
    assert collected == [("job-ic", scope)]
    assert payload["report_collections"][0]["report_follow_up"] == {
        "status": "analysis_required",
        "parent_id": "job-job-ic-result",
        "message": "已添加，请分析",
    }


def test_snapshot_cli_creates_lists_and_selects_explicit_snapshot(
    tmp_path,
    monkeypatch,
) -> None:
    fake = FakeClient()
    monkeypatch.setenv("FACTORTESTER_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(
        "tools.cli.commands.research.client_from_config",
        lambda: fake,
    )
    runner = CliRunner()
    assert runner.invoke(
        cli,
        ["workspace", "create", "--factor-family", "MmRet"],
    ).exit_code == 0
    created = runner.invoke(cli, [
        "workspace", "snapshot-create", "Day",
        "--source-workspace-id", "source-workspace",
        "--source-configuration-id", "source-config",
        "--source-revision", "3",
    ])
    listed = runner.invoke(cli, ["workspace", "snapshot-list"])
    submitted = runner.invoke(cli, [
        "run", "submit", "--analysis", "ic",
        "--configuration-snapshot-id", "snapshot-1",
        "--configuration-snapshot-revision", "1",
    ])

    assert created.exit_code == 0, created.output
    assert listed.exit_code == 0, listed.output
    assert submitted.exit_code == 0, submitted.output
    assert fake.snapshot_create == (
        "workspace-1",
        {
            "source_workspace_id": "source-workspace",
            "source_configuration_id": "source-config",
            "source_configuration_revision": 3,
            "name": "Day",
        },
    )
    assert fake.snapshot_selection == ("snapshot-1", 1)


def test_run_submit_rejects_partial_snapshot_identity(
    tmp_path, monkeypatch,
) -> None:
    fake = FakeClient()
    monkeypatch.setenv("FACTORTESTER_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(
        "tools.cli.commands.research.client_from_config", lambda: fake,
    )
    runner = CliRunner()
    assert runner.invoke(
        cli, ["workspace", "create", "--factor-family", "MmRet"],
    ).exit_code == 0

    missing_revision = runner.invoke(cli, [
        "run", "submit", "--analysis", "ic",
        "--configuration-snapshot-id", "snapshot-1",
    ])
    missing_id = runner.invoke(cli, [
        "run", "submit", "--analysis", "ic",
        "--configuration-snapshot-revision", "1",
    ])

    assert missing_revision.exit_code == 1
    assert "requires its frozen revision" in missing_revision.output
    assert missing_id.exit_code == 1
    assert "requires a snapshot id" in missing_id.output


def test_run_submit_json_preserves_server_report_projection(
    tmp_path,
    monkeypatch,
) -> None:
    fake = FakeClient()
    monkeypatch.setenv("FACTORTESTER_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(
        "tools.cli.commands.research.client_from_config",
        lambda: fake,
    )
    runner = CliRunner()
    assert runner.invoke(
        cli,
        ["workspace", "create", "--factor-family", "MmRet"],
    ).exit_code == 0
    state = load_state()
    state.configuration_revision = 2
    save_state(state)

    submitted = runner.invoke(cli, [
        "run", "submit", "--analysis", "ic", "--json",
    ])

    assert submitted.exit_code == 0, submitted.output
    payload = json.loads(submitted.output)
    assert payload["report_projection"]["run_spec"]["alias_zh"] == (
        "截面 IC · 日盘 · SgCPS"
    )


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


def test_job_artifact_writes_binary_file_and_prints_only_receipt(
    tmp_path, monkeypatch,
) -> None:
    fake = FakeClient()
    monkeypatch.setattr(
        "tools.cli.commands.research.client_from_config", lambda: fake
    )
    target = tmp_path / "curve.svg"

    result = CliRunner().invoke(cli, [
        "job", "artifact", "job-curve", "equity_curve_report",
        "--output", str(target),
    ])

    assert result.exit_code == 0, result.output
    receipt = json.loads(result.output)
    assert target.read_bytes() == b"<svg><title>curve</title></svg>"
    assert receipt["content_type"] == "image/svg+xml"
    assert receipt["path"] == str(target.resolve())
    assert "svg" not in receipt


def test_job_download_all_uses_individual_data_plane_transfers(
    tmp_path, monkeypatch,
) -> None:
    fake = FakeClient()
    monkeypatch.setattr(
        "tools.cli.commands.research.client_from_config", lambda: fake
    )
    output = tmp_path / "artifacts"

    result = CliRunner().invoke(cli, [
        "job", "download-all", "job-curve", "--output", str(output),
    ])

    assert result.exit_code == 0, result.output
    receipt = json.loads(result.output)
    assert (output / "curve.svg").read_bytes().startswith(b"<svg>")
    assert receipt["files"] == [str((output / "curve.svg").resolve())]


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
