import json

from click.testing import CliRunner

from tools.cli.app import cli
from tools.cli.core.strategy_spec import StrategySpec, template_for


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
