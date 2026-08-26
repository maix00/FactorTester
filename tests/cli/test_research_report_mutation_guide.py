from __future__ import annotations

import json

from click.testing import CliRunner

from tools.cli.commands.research_report import report


def _guide(operation: str) -> dict:
    result = CliRunner().invoke(report, [
        "mutation-guide", "--operation", operation, "--json",
    ])
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


def test_move_guide_discloses_complete_batch_contract() -> None:
    value = _guide("move")

    operation = value["operations_file_template"]["operations"][0]
    assert operation == {
        "op": "move",
        "component_id": "<existing-component-id>",
        "parent_id": "<new-parent-component-id>",
        "after_component_id": "<optional-sibling-component-id>",
    }
    assert value["required_fields"] == ["op", "component_id", "parent_id"]
    assert value["next_actions"][0]["action"] == "inspect"
    assert "research reports add-batch" in value["next_actions"][1]["command"]


def test_replace_guide_discloses_full_fields_and_binding_boundary() -> None:
    value = _guide("replace")

    operation = value["operations_file_template"]["operations"][0]
    assert set(operation) == {
        "op", "component_id", "title", "body", "content", "display_kind",
    }
    assert value["forbidden_fields"] == ["bindings", "parent_id"]
    assert "research reports show" in value["inspect_command"]
    assert any("CLI" in rule and "bindings" in rule for rule in value["rules"])
