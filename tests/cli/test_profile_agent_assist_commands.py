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

    def get_profile_agent_assistance_draft(self, profile_id: str, draft_id: str):
        assert profile_id == "self-profile"
        assert draft_id == "a" * 32
        return {
            "success": True,
            "draft": {
                "draft_id": draft_id,
                "status": "draft",
                "document": {"large": "x" * 10000},
            },
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
        return {"success": True, "queued": getattr(self, "queue_apply", False)}


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
    assert json.loads(shown.output)["sections"] == [{
        "id": "section:source",
        "kind": "section",
        "label": "Source",
    }]
    assert "candidates" not in shown.output
    assert len(shown.output) < 1500

    selected = runner.invoke(
        commands.assist,
        [
            "--profile-id", "self-profile", "inspect",
            "--node", "field:source", "--value",
        ],
    )
    assert selected.exit_code == 0
    assert json.loads(selected.output)["value"] == "old"

    contract_only = runner.invoke(
        commands.assist,
        [
            "--profile-id", "self-profile", "inspect",
            "--node", "field:source",
        ],
    )
    assert contract_only.exit_code == 0
    assert "value" not in json.loads(contract_only.output)

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
    assert "applied" in applied.output
    assert client.applied == ("self-profile", {"draft_id": "a" * 32})

    client.queue_apply = True
    queued = runner.invoke(
        commands.assist,
        ["--profile-id", "self-profile", "drafts", "apply", "a" * 32],
    )
    assert queued.exit_code == 0
    assert "queued" in queued.output

    compact = runner.invoke(
        commands.assist,
        ["--profile-id", "self-profile", "drafts", "show", "a" * 32],
    )
    assert compact.exit_code == 0
    assert "document" not in json.loads(compact.output)["draft"]
    assert len(compact.output) < 500

    complete = runner.invoke(
        commands.assist,
        [
            "--profile-id", "self-profile", "drafts", "show", "a" * 32,
            "--document",
        ],
    )
    assert complete.exit_code == 0
    assert json.loads(complete.output)["draft"]["document"]["large"]


def test_inspect_lists_mounted_and_unmounted_tabs_only(monkeypatch) -> None:
    client = _Client()
    page = client.inspect_profile_agent_assistance("self-profile")["page"]
    navigation = page["assistance"]["navigation"]
    navigation["nodes"] = {
        "page": {
            "id": "page", "kind": "page", "label": "IC", "children": [
                "tab:time", "tab:factors", "configurations",
            ],
        },
        "tab:time": {
            "id": "tab:time", "kind": "tab", "label": "Time",
            "mounted": True, "children": ["field:start"],
        },
        "tab:factors": {
            "id": "tab:factors", "kind": "tab", "label": "Factors",
            "mounted": False, "children": ["field:factors"],
        },
        "field:start": {
            "id": "field:start", "kind": "field", "label": "Start",
            "children": [],
        },
        "field:factors": {
            "id": "field:factors", "kind": "field", "label": "Factors",
            "candidate_source": "factortester factors list", "children": [],
        },
        "configurations": {
            "id": "configurations", "kind": "collection", "label": "Groups",
            "summary": "0",
            "collection_path": "configuration.analyses.ic.configuration_groups",
            "required_fields": ["factor_ref", "product_scope_ref"],
            "create_template": {
                "factor_ref": "<factor-ref>",
                "product_scope_ref": "<product-group-ref>",
            },
            "field_sources": {
                "factor_ref": "field:factors",
                "product_scope_ref": "field:products",
            },
            "children": [],
        },
    }
    monkeypatch.setattr(
        commands, "client_from_config",
        lambda: type("Client", (), {
            "inspect_profile_agent_assistance": lambda self, profile_id: {"page": page},
        })(),
    )
    monkeypatch.setattr(commands, "load_capability", lambda: None)
    runner = CliRunner()
    result = runner.invoke(
        commands.assist, ["--profile-id", "self-profile", "inspect"],
    )
    assert result.exit_code == 0
    assert json.loads(result.output)["tabs"] == [
        {"id": "tab:time", "label": "Time", "mounted": True},
        {"id": "tab:factors", "label": "Factors", "mounted": False},
    ]
    assert json.loads(result.output)["configuration_collection"] == {
        "id": "configurations", "kind": "collection",
        "label": "Groups", "summary": "0",
    }

    contract = runner.invoke(
        commands.assist,
        ["--profile-id", "self-profile", "inspect", "--node", "configurations"],
    )
    assert contract.exit_code == 0
    contract_payload = json.loads(contract.output)
    assert contract_payload["create_template"]["factor_ref"] == "<factor-ref>"
    assert contract_payload["field_sources"]["factor_ref"] == "field:factors"

    unmounted = runner.invoke(
        commands.assist,
        ["--profile-id", "self-profile", "inspect", "--node", "tab:factors"],
    )
    assert unmounted.exit_code == 0
    assert json.loads(unmounted.output)["children"] == [
        {"id": "field:factors", "kind": "field", "label": "Factors"},
    ]


def test_assist_subcommand_help_does_not_require_agent_identity(monkeypatch) -> None:
    monkeypatch.setattr(commands, "load_capability", lambda: None)
    result = CliRunner().invoke(commands.assist, ["inspect", "--help"])
    assert result.exit_code == 0
    assert "--profile-id is required" not in result.output
