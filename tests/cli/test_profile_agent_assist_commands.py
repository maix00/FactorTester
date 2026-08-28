import json

from click.testing import CliRunner

from tools.cli.commands import assist as commands


class _Client:
    def __init__(self) -> None:
        self.applied = None
        self.document = None

    def inspect_profile_agent_assistance(self, profile_id: str):
        assert profile_id == "self-profile"
        return {
            "page": {
                "tab_id": "factor-new",
                "assistance": {
                    "page_kind": "factor-create",
                    "revision": 7,
                    "document": {
                        "source": "old",
                        "candidates": [
                            {"id": index, "details": {"large": "x" * 1000}}
                            for index in range(100)
                        ],
                    },
                    "document_schema": {"type": "object"},
                },
            }
        }

    def create_profile_agent_assistance_draft(self, profile_id: str, document: dict):
        assert profile_id == "self-profile"
        assert document == {"source": "new"}
        self.document = document
        return {"draft": {"draft_id": "a" * 32, "status": "draft"}}

    def validate_profile_agent_assistance(self, profile_id: str, draft_id: str):
        assert profile_id == "self-profile"
        assert draft_id == "a" * 32
        return {"success": True, "valid": True}

    def apply_profile_agent_assistance(self, profile_id: str, **value):
        self.applied = (profile_id, value)
        return {"success": True}


def test_profile_agent_assist_commands_use_one_structured_document(monkeypatch) -> None:
    client = _Client()
    monkeypatch.setattr(commands, "client_from_config", lambda: client)
    monkeypatch.setattr(commands, "load_capability", lambda: None)
    runner = CliRunner()

    shown = runner.invoke(
        commands.assist,
        [
            "--profile-id",
            "self-profile",
            "inspect",
        ],
    )
    assert shown.exit_code == 0
    assert json.loads(shown.output)["assistance"]["revision"] == 7
    assert "old" not in shown.output
    assert len(shown.output) < 1500

    selected = runner.invoke(
        commands.assist,
        [
            "--profile-id", "self-profile", "inspect",
            "--path", "/assistance/document/source",
        ],
    )
    assert selected.exit_code == 0
    assert json.loads(selected.output) == "old"

    paged = runner.invoke(
        commands.assist,
        [
            "--profile-id", "self-profile", "inspect",
            "--path", "/assistance/document/candidates",
            "--offset", "20", "--limit", "2", "--depth", "0",
        ],
    )
    assert paged.exit_code == 0
    page = json.loads(paged.output)
    assert page["count"] == 100
    assert page["offset"] == 20
    assert page["has_more"] is True
    assert [item["path"] for item in page["items"]] == [
        "/assistance/document/candidates/20",
        "/assistance/document/candidates/21",
    ]
    assert "x" * 100 not in paged.output

    missing = runner.invoke(
        commands.assist,
        [
            "--profile-id", "self-profile", "inspect",
            "--path", "/assistance/document/missing",
        ],
    )
    assert missing.exit_code != 0
    assert "path does not exist" in missing.output

    created = runner.invoke(
        commands.assist,
        [
            "--profile-id",
            "self-profile",
            "drafts",
            "create",
            "--stdin",
        ],
        input='{"source":"new"}',
    )
    assert created.exit_code == 0
    assert json.loads(created.output)["draft_id"] == "a" * 32

    validated = runner.invoke(
        commands.assist,
        [
            "--profile-id",
            "self-profile",
            "drafts",
            "validate",
            "a" * 32,
        ],
    )
    assert validated.exit_code == 0

    applied = runner.invoke(
        commands.assist,
        [
            "--profile-id",
            "self-profile",
            "drafts",
            "apply",
            "a" * 32,
        ],
    )
    assert applied.exit_code == 0
    assert client.applied == ("self-profile", {"draft_id": "a" * 32})


def test_assist_subcommand_help_does_not_require_agent_identity(monkeypatch) -> None:
    monkeypatch.setattr(commands, "load_capability", lambda: None)
    result = CliRunner().invoke(commands.assist, ["inspect", "--help"])
    assert result.exit_code == 0
    assert "--profile-id is required" not in result.output
