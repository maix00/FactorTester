from click.testing import CliRunner

from tools.cli.commands import server_profile_agent as commands


class _Client:
    def __init__(self) -> None:
        self.action = None

    def profile_agent_page_context(self, profile_id: str):
        assert profile_id == "self-profile"
        return {"page": {
            "tab_id": "factor-new",
            "context": {"sections": [{
                "id": "editor", "page": "factor-create", "section": "source",
                "fields": [{"key": "source", "editable": True, "value": "old"}],
            }]},
        }}

    def apply_profile_agent_page_action(self, profile_id: str, **value):
        self.action = (profile_id, value)
        return {"success": True}


def test_profile_agent_page_commands_read_and_update_registered_fields(monkeypatch) -> None:
    client = _Client()
    monkeypatch.setattr(commands, "client_from_config", lambda: client)
    monkeypatch.setattr(commands, "load_capability", lambda: None)
    runner = CliRunner()

    shown = runner.invoke(commands.profile_agent, [
        "--profile-id", "self-profile", "page", "show",
    ])
    assert shown.exit_code == 0
    assert "factor-create / source" in shown.output
    assert "source (editable)" in shown.output

    updated = runner.invoke(commands.profile_agent, [
        "--profile-id", "self-profile", "page", "set",
        "--tab-id", "factor-new", "--section", "editor",
        "--field", "source", "--value", "new",
    ])
    assert updated.exit_code == 0
    assert client.action == ("self-profile", {
        "tab_id": "factor-new",
        "section_id": "editor",
        "action": {"field": "source", "value": "new"},
    })
