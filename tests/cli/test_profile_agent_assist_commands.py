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
                    "navigation": {
                        "schema_version": 1,
                        "root_id": "page",
                        "nodes": {
                            "page": {
                                "id": "page",
                                "kind": "page",
                                "label": "Factor",
                                "children": ["section:source"],
                            },
                            "section:source": {
                                "id": "section:source",
                                "kind": "section",
                                "label": "Source",
                                "summary": "2 fields",
                                "children": ["field:source"],
                            },
                            "field:source": {
                                "id": "field:source",
                                "kind": "field",
                                "label": "Source code",
                                "value": "old",
                                "children": [],
                            },
                        },
                    },
                },
            }
        }

    def create_profile_agent_assistance_draft(
        self, profile_id: str, document: dict | None, *, from_current: bool = False,
    ):
        assert profile_id == "self-profile"
        assert document == {"source": "new"} or (document is None and from_current)
        self.document = document
        return {"draft": {"draft_id": "a" * 32, "status": "draft"}}

    def patch_profile_agent_assistance_draft(
        self, profile_id: str, draft_id: str, patch: dict,
    ):
        assert profile_id == "self-profile"
        assert draft_id == "a" * 32
        assert patch == {"source": "patched"}
        return {"draft": {"draft_id": draft_id, "status": "draft"}}

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
    assert json.loads(shown.output)["navigation"]["children"] == [{
        "id": "section:source",
        "kind": "section",
        "label": "Source",
        "summary": "2 fields",
    }]
    assert "candidates" not in shown.output
    assert len(shown.output) < 1500

    selected = runner.invoke(
        commands.assist,
        [
            "--profile-id", "self-profile", "inspect",
            "--node", "field:source",
        ],
    )
    assert selected.exit_code == 0
    assert json.loads(selected.output)["value"] == "old"

    missing = runner.invoke(
        commands.assist,
        [
            "--profile-id", "self-profile", "inspect",
            "--node", "field:missing",
        ],
    )
    assert missing.exit_code != 0
    assert "node was not found" in missing.output

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

    based = runner.invoke(
        commands.assist,
        ["--profile-id", "self-profile", "drafts", "create", "--from-current"],
    )
    assert based.exit_code == 0

    patched = runner.invoke(
        commands.assist,
        [
            "--profile-id", "self-profile", "drafts", "patch", "a" * 32,
            "--stdin",
        ],
        input='{"source":"patched"}',
    )
    assert patched.exit_code == 0

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
