import json

from click.testing import CliRunner

from tools.cli.commands import assist as commands


class _Client:
    def __init__(self) -> None:
        self.applied = None

    def inspect_profile_agent_assistance(self, profile_id: str):
        assert profile_id == "self-profile"
        return {"page": {"tab_id": "factor-new", "assistance": {
            "page_kind": "factor-create", "revision": 7,
            "document": {"source": "old"}, "document_schema": {"type": "object"},
        }}}

    def validate_profile_agent_assistance(self, profile_id: str, document: dict):
        assert profile_id == "self-profile"
        assert document == {"source": "new"}
        return {"success": True, "valid": True}

    def apply_profile_agent_assistance(self, profile_id: str, **value):
        self.applied = (profile_id, value)
        return {"success": True}


def test_profile_agent_assist_commands_use_one_structured_document(monkeypatch) -> None:
    client = _Client()
    monkeypatch.setattr(commands, "client_from_config", lambda: client)
    monkeypatch.setattr(commands, "load_capability", lambda: None)
    runner = CliRunner()

    shown = runner.invoke(commands.assist, [
        "--profile-id", "self-profile", "inspect",
    ])
    assert shown.exit_code == 0
    assert json.loads(shown.output)["assistance"]["revision"] == 7

    validated = runner.invoke(commands.assist, [
        "--profile-id", "self-profile", "validate", "--stdin",
    ], input='{"source":"new"}')
    assert validated.exit_code == 0

    applied = runner.invoke(commands.assist, [
        "--profile-id", "self-profile", "apply", "--stdin",
        "--tab-id", "factor-new", "--expected-revision", "7",
    ], input='{"source":"new"}')
    assert applied.exit_code == 0
    assert client.applied == ("self-profile", {
        "tab_id": "factor-new", "expected_revision": 7,
        "document": {"source": "new"},
    })


def test_assist_subcommand_help_does_not_require_agent_identity(monkeypatch) -> None:
    monkeypatch.setattr(commands, "load_capability", lambda: None)
    result = CliRunner().invoke(commands.assist, ["inspect", "--help"])
    assert result.exit_code == 0
    assert "--profile-id is required" not in result.output
