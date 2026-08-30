from __future__ import annotations

import json
from types import SimpleNamespace

from click.testing import CliRunner

from tools.cli.app import cli
from tools.cli.commands import strategy_intent as commands


def _manifest():
    return {
        "application": "group_test",
        "defaults": {
            "strategy_intent_mode": {
                "options": [["group", "分组"], ["threshold", "阈值"]],
            },
            "factor_role_bindings": {"serialization": {
                "allowed_roles": ["ranking", "screen", "entry", "exit", "sizing"],
                "roles_by_strategy_kind": {
                    "group": ["ranking", "screen", "sizing"],
                    "threshold": ["entry", "exit"],
                },
            }},
        },
    }


def _configuration():
    return {
        "revision": 4,
        "payload": {
            "schema_version": 1,
            "shared": {"factors": [{"alias": "Rank"}, {"alias": "Gate"}, {"alias": "Size"}]},
            "analyses": {"backtest": {
                "execution": {"settings": {"allocation_policy": "equal_notional"}},
                "groups": [{
                    "id": "A1", "name": "A1", "factorAlias": "Rank",
                    "custom": {"preserved": True},
                }],
            }},
        },
    }


class _FakeClient:
    def __init__(self):
        self.configuration = _configuration()
        self.updated = None

    def manifest(self, application):
        assert application == "group_test"
        return _manifest()

    def get_workspace_configuration(self, workspace_id):
        assert workspace_id == "workspace-1"
        return self.configuration

    def update_workspace_configuration(self, workspace_id, *, expected_revision, payload):
        assert (workspace_id, expected_revision) == ("workspace-1", 4)
        self.updated = payload
        return {"revision": 5, "payload": payload}


def _install(monkeypatch):
    fake = _FakeClient()
    state = SimpleNamespace(workspace_id="workspace-1", configuration_revision=4)
    monkeypatch.setattr(commands, "client_from_config", lambda: fake)
    monkeypatch.setattr(commands, "load_state", lambda: state)
    monkeypatch.setattr(commands, "save_state", lambda value: None)
    return fake


def test_describe_and_show_have_stable_json(monkeypatch):
    _install(monkeypatch)
    runner = CliRunner()

    described = runner.invoke(cli, ["strategy", "intent", "describe", "--json"])
    shown = runner.invoke(cli, ["strategy", "intent", "show", "--json"])

    assert described.exit_code == 0, described.output
    assert json.loads(described.output)["roles_by_strategy_kind"]["group"] == [
        "ranking", "screen", "sizing",
    ]
    assert shown.exit_code == 0, shown.output
    assert json.loads(shown.output)["strategies"][0]["group_id"] == "A1"


def test_configure_updates_real_workspace_payload_and_preserves_fields(monkeypatch):
    fake = _install(monkeypatch)

    result = CliRunner().invoke(cli, [
        "strategy", "intent", "configure", "A1",
        "--role", "screen=Gate", "--screen-rule", "gte", "--screen-lower", "1.5",
        "--role", "sizing=Size", "--allocation-policy", "factor_sizing", "--json",
    ])

    assert result.exit_code == 0, result.output
    group = fake.updated["analyses"]["backtest"]["groups"][0]
    assert group["factorRoleBindings"] == {"screen": "Gate", "sizing": "Size"}
    assert group["custom"] == {"preserved": True}
    assert json.loads(result.output)["revision"] == 5


def test_configure_rejects_noop_and_incompatible_role_without_mutation(monkeypatch):
    fake = _install(monkeypatch)
    runner = CliRunner()

    noop = runner.invoke(cli, ["strategy", "intent", "configure", "A1", "--role", "screen=Gate"])
    invalid_role = runner.invoke(cli, [
        "strategy", "intent", "configure", "A1", "--role", "entry=Unknown",
    ])

    assert noop.exit_code != 0 and "screen-rule" in noop.output
    assert invalid_role.exit_code != 0 and "incompatible" in invalid_role.output
    assert fake.updated is None


def test_configure_accepts_deferred_profile_role_factor(monkeypatch):
    fake = _install(monkeypatch)

    result = CliRunner().invoke(cli, [
        "strategy", "intent", "configure", "A1",
        "--role", "screen=StTurnoverOrdinalRank|N:20d",
        "--screen-rule", "lte", "--screen-upper", "12", "--json",
    ])

    assert result.exit_code == 0, result.output
    assert fake.updated["shared"]["factors"] == [
        {"alias": "Rank"}, {"alias": "Gate"}, {"alias": "Size"},
    ]
    group = fake.updated["analyses"]["backtest"]["groups"][0]
    assert group["factorRoleBindings"] == {
        "screen": "StTurnoverOrdinalRank|N:20d",
    }
