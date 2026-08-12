import json

from click.testing import CliRunner

from tools.cli.commands import research_graph as command_module
from tools.cli.commands.research_graph import research_graph


def test_cycle_object_command_forwards_type_identity_and_trace(
    monkeypatch,
) -> None:
    class Client:
        def get_research_cycle_object(
            self,
            instance_id,
            branch_id,
            object_type,
            object_id,
            *,
            trace_id=None,
        ):
            assert (instance_id, branch_id) == ("instance-1", "branch-1")
            assert object_type == "run_spec"
            assert object_id == "sha256:" + "a" * 64
            assert trace_id == "trace-1"
            return {
                "object_kind": "run_spec",
                "run_spec_hash": "a" * 64,
            }

    monkeypatch.setattr(
        command_module,
        "client_from_config",
        lambda: Client(),
    )

    result = CliRunner().invoke(research_graph, [
        "cycle-object",
        "instance-1",
        "branch-1",
        "run_spec",
        "sha256:" + "a" * 64,
        "--trace-id",
        "trace-1",
    ])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["object_kind"] == "run_spec"
