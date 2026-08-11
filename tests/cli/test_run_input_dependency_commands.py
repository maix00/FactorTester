from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from tools.cli.app import cli
from tools.cli.state import load_state, save_state


class _RunClient:
    def __init__(self) -> None:
        self.submitted: dict | None = None
        self.previewed: dict | None = None

    def submit_run(
        self,
        workspace_id,
        configuration_revision,
        **kwargs,
    ):
        self.submitted = {
            "workspace_id": workspace_id,
            "configuration_revision": configuration_revision,
            **kwargs,
        }
        return {"run_id": "run-1", "jobs": []}

    def preview_run(
        self,
        workspace_id,
        configuration_revision,
        **kwargs,
    ):
        self.previewed = {
            "workspace_id": workspace_id,
            "configuration_revision": configuration_revision,
            **kwargs,
        }
        return {"run_spec_hash": "a" * 64}


def _configure(tmp_path: Path, monkeypatch) -> _RunClient:
    client = _RunClient()
    monkeypatch.setenv("FACTORTESTER_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(
        "tools.cli.commands.research.client_from_config",
        lambda: client,
    )
    state = load_state()
    state.workspace_id = "workspace-1"
    state.configuration_revision = 7
    save_state(state)
    return client


def test_run_submit_retains_typed_input_dependencies(
    tmp_path,
    monkeypatch,
) -> None:
    client = _configure(tmp_path, monkeypatch)
    strategy = tmp_path / "risk.yaml"
    strategy.write_text("limit: 0.4\n", encoding="utf-8")
    mapping = tmp_path / "symbols.csv"
    mapping.write_text("source,target\nA,DCE\n", encoding="utf-8")

    result = CliRunner().invoke(cli, [
        "run", "submit",
        "--analysis", "backtest",
        "--analysis", "ic",
        "--run-input", f"strategy_configuration={strategy}",
        "--run-input", f"data_mapping={mapping}",
    ])

    assert result.exit_code == 0, result.output
    assert client.submitted is not None
    dependencies = client.submitted["run_input_dependencies"]
    assert dependencies == [
        {
            "path": "strategy-configs/risk.yaml",
            "content": "limit: 0.4\n",
            "content_type": "application/yaml",
            "title_zh": "策略配置：risk.yaml",
            "purpose": "strategy_configuration",
            "analyses": ["backtest", "ic"],
        },
        {
            "path": "data-mappings/symbols.csv",
            "content": "source,target\nA,DCE\n",
            "content_type": "text/csv",
            "title_zh": "数据映射：symbols.csv",
            "purpose": "data_mapping",
            "analyses": ["backtest", "ic"],
        },
    ]


def test_run_preview_uses_the_same_retained_input_contract(
    tmp_path,
    monkeypatch,
) -> None:
    client = _configure(tmp_path, monkeypatch)
    dependency = tmp_path / "commission.py"
    dependency.write_text("RATIO = 0.0001\n", encoding="utf-8")

    result = CliRunner().invoke(cli, [
        "run", "preview",
        "--analysis", "backtest",
        "--run-input", f"strategy_dependency={dependency}",
    ])

    assert result.exit_code == 0, result.output
    assert client.previewed is not None
    assert client.previewed["run_input_dependencies"] == [{
        "path": "strategy-configs/commission.py",
        "content": "RATIO = 0.0001\n",
        "content_type": "text/x-python",
        "title_zh": "策略依赖：commission.py",
        "purpose": "strategy_dependency",
        "analyses": ["backtest"],
    }]
    assert "execution" not in client.previewed["run_input_dependencies"][0]


def test_run_input_rejects_duplicate_logical_names(
    tmp_path,
    monkeypatch,
) -> None:
    _configure(tmp_path, monkeypatch)
    first = tmp_path / "first" / "config.json"
    second = tmp_path / "second" / "config.json"
    first.parent.mkdir()
    second.parent.mkdir()
    first.write_text("{}", encoding="utf-8")
    second.write_text("{}", encoding="utf-8")

    result = CliRunner().invoke(cli, [
        "run", "preview", "--analysis", "backtest",
        "--run-input", f"run_configuration={first}",
        "--run-input", f"run_configuration={second}",
    ])

    assert result.exit_code != 0
    assert "文件名冲突" in result.output


def test_run_input_rejects_unknown_purpose_and_binary_file(
    tmp_path,
    monkeypatch,
) -> None:
    _configure(tmp_path, monkeypatch)
    unsupported = tmp_path / "payload.bin"
    unsupported.write_bytes(b"\x00\x01")
    runner = CliRunner()

    bad_purpose = runner.invoke(cli, [
        "run", "preview", "--analysis", "backtest",
        "--run-input", f"unknown={unsupported}",
    ])
    bad_suffix = runner.invoke(cli, [
        "run", "preview", "--analysis", "backtest",
        "--run-input", str(unsupported),
    ])

    assert bad_purpose.exit_code != 0
    assert "未知的 --run-input PURPOSE" in bad_purpose.output
    assert bad_suffix.exit_code != 0
    assert "受支持的文本文件" in bad_suffix.output


def test_run_help_describes_retained_job_input_lifecycle() -> None:
    runner = CliRunner()
    submit = runner.invoke(cli, ["run", "submit", "--help"])
    preview = runner.invoke(cli, ["run", "preview", "--help"])

    assert submit.exit_code == 0, submit.output
    assert preview.exit_code == 0, preview.output
    assert "--run-input [PURPOSE=]FILE" in submit.output
    assert "--run-input [PURPOSE=]FILE" in preview.output
    assert "任务终止后自动清理" not in submit.output
    assert "清空任务文件时一并删除" in submit.output
