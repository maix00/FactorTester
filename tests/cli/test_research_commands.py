from __future__ import annotations

import json

from click.testing import CliRunner

from tools.cli.app import cli
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

    def submit_run(
        self,
        workspace_id,
        configuration_revision,
        *,
        analyses,
        retention_mode,
        step_mode,
        trial_binding=None,
    ):
        assert (workspace_id, configuration_revision) == ("workspace-1", 2)
        self.trial_binding = trial_binding
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
        "instance_id": "instance-1",
        "branch_id": "branch-1",
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
    ])

    assert submitted.exit_code == 0, submitted.output
    assert fake.trial_binding == binding


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
