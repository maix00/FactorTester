import json

from click.testing import CliRunner

from tools.cli.app import cli
from tools.cli.commands import workspace_strategy
from tools.cli.core.strategy_spec import StrategySpec, template_for
from tools.cli.state import CliState


def test_strategy_template_catalog_has_user_facing_sources():
    assert template_for("group_quantile").label == "分组多空"
    assert StrategySpec.from_mapping({"source": "profile:demo/strategy.py"}).source_kind == "profile"


def test_strategy_list_json_does_not_expose_internal_objects():
    result = CliRunner().invoke(cli, ["strategy", "list", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert any(item["source"] == "profile:<path>" for item in payload)
    assert all("StrategyBook" not in json.dumps(item) for item in payload)


def test_strategy_validate_json_normalizes_spec(tmp_path):
    path = tmp_path / "strategy.json"
    path.write_text(
        json.dumps({
            "source": "builtin:group_quantile",
            "parameters": {"groups": 5},
            "execution": {"liquidity": "infinite"},
        }),
        encoding="utf-8",
    )

    result = CliRunner().invoke(cli, ["strategy", "validate", "--spec", str(path), "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["valid"] is True
    assert payload["strategy"]["source_name"] == "group_quantile"
    assert payload["strategy"]["parameters"] == {"groups": 5}


def test_strategy_validate_rejects_unknown_template(tmp_path):
    path = tmp_path / "strategy.json"
    path.write_text(json.dumps({"source": "builtin:missing"}), encoding="utf-8")

    result = CliRunner().invoke(cli, ["strategy", "validate", "--spec", str(path)])

    assert result.exit_code != 0
    assert "unknown strategy template" in result.output


def test_custom_strategy_source_stays_relative_to_its_workspace():
    spec = StrategySpec.from_mapping({
        "source": "profile:strategies/demo/actor.py",
        "workspace": "profile:demo",
        "entrypoint": "Demo",
    })
    assert spec.normalized()["entrypoint"] == "Demo"
    assert spec.dependencies()["source_kind"] == "profile"


def test_strategy_library_and_workspace_strategy_commands_are_registered():
    runner = CliRunner()

    library = runner.invoke(cli, ["strategy-library", "--help"])
    assert library.exit_code == 0
    assert "revisions" in library.output
    assert "share" in library.output

    workspace = runner.invoke(cli, ["workspace", "strategy", "--help"])
    assert workspace.exit_code == 0
    assert "add-inline" in workspace.output
    assert "update-inline" in workspace.output
    assert "bind-library" in workspace.output
    assert "show" in workspace.output


def test_workspace_strategy_show_is_concise_and_reads_source_on_request(monkeypatch):
    state = CliState(workspace_id="workspace-one", configuration_revision=4)

    class FakeClient:
        def list_configuration_strategies(self, workspace_id, *, include_source=False):
            assert workspace_id == "workspace-one"
            strategies = [{
                "temp_ref": "temporary-strategy:one",
                "name": "临时策略",
                "entrypoint": "Demo",
                "source_sha256": "a" * 64,
            }]
            if include_source:
                strategies[0]["source_code"] = "class Demo: pass\n"
            return {
                "bindings": [{
                    "binding_id": "binding-one",
                    "target_strategy_id": "group-1",
                    "source": {"kind": "inline", "temp_ref": "temporary-strategy:one"},
                }],
                "strategies": strategies,
            }

    monkeypatch.setattr(workspace_strategy, "load_state", lambda: state)
    monkeypatch.setattr(workspace_strategy, "client_from_config", lambda: FakeClient())
    runner = CliRunner()

    metadata = runner.invoke(cli, ["workspace", "strategy", "show", "binding-one"])
    assert metadata.exit_code == 0, metadata.output
    assert "binding=binding-one" in metadata.output
    assert "source_code" not in metadata.output

    source = runner.invoke(cli, [
        "workspace", "strategy", "show", "binding-one", "--with-source",
    ])
    assert source.exit_code == 0, source.output
    assert "source_code:" in source.output
    assert "class Demo: pass" in source.output


def test_workspace_strategy_list_is_concise_by_default(monkeypatch):
    state = CliState(workspace_id="workspace-one", configuration_revision=4)

    class FakeClient:
        def list_configuration_strategies(self, workspace_id, *, include_source=False):
            assert workspace_id == "workspace-one"
            strategy = {
                "temp_ref": "temporary-strategy:one",
                "name": "临时策略",
                "entrypoint": "Demo",
                "source_sha256": "a" * 64,
            }
            if include_source:
                strategy["source_code"] = "class Demo: pass\n"
            return {
                "configuration_id": workspace_id,
                "revision": 4,
                "bindings": [{
                    "binding_id": "binding-one",
                    "target_strategy_id": "group-1",
                    "source": {
                        "kind": "inline",
                        "temp_ref": "temporary-strategy:one",
                    },
                }],
                "strategies": [strategy],
            }

    monkeypatch.setattr(workspace_strategy, "load_state", lambda: state)
    monkeypatch.setattr(workspace_strategy, "client_from_config", lambda: FakeClient())
    runner = CliRunner()

    metadata = runner.invoke(cli, ["workspace", "strategy", "list"])
    assert metadata.exit_code == 0, metadata.output
    assert "configuration_id=workspace-one" in metadata.output
    assert "strategy=临时策略" in metadata.output
    assert "source_code" not in metadata.output

    source = runner.invoke(cli, [
        "workspace", "strategy", "list", "--with-source",
    ])
    assert source.exit_code == 0, source.output
    assert "source_code:" in source.output
    assert "class Demo: pass" in source.output
