from __future__ import annotations

import json

from tools.migrations import migrate_factor_control_domain as migration


class _Cursor:
    rowcount = 1

    def fetchone(self):
        return None


class _Connection:
    def __init__(self) -> None:
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, statement, parameters):
        self.calls.append((statement, parameters))
        return _Cursor()


def test_control_domain_plan_applies_and_restores_expected_revision(
    tmp_path, monkeypatch,
) -> None:
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps({"rows": [{
        "principal": "alice",
        "entity_type": "factor_param_config",
        "entity_id": "default:Momentum",
        "expected_revision": 3,
        "old_payload": {"schema_version": 1},
        "old_deleted": False,
        "new_payload": {"schema_version": 2},
        "new_deleted": False,
    }]}), encoding="utf-8")
    environment = tmp_path / "control.env"
    environment.write_text(
        "FACTORTESTER_CONTROL_DATABASE_URL=postgresql://example\n",
        encoding="utf-8",
    )
    connections: list[_Connection] = []

    def connect(_url):
        connection = _Connection()
        connections.append(connection)
        return connection

    monkeypatch.setattr(migration.psycopg, "connect", connect)

    assert migration.apply_plan(
        plan_path=plan, environment_path=environment,
    ) == 1
    assert migration.apply_plan(
        plan_path=plan, environment_path=environment, restore=True,
    ) == 1

    applied = connections[0].calls[0][1]
    restored = connections[1].calls[0][1]
    assert applied[2] == 4
    assert applied[-1] == 3
    assert restored[2] == 3
    assert restored[-1] == 4


def test_control_domain_plan_is_idempotent_when_target_is_already_present(
    tmp_path, monkeypatch,
) -> None:
    plan = tmp_path / "plan.json"
    target = {"schema_version": 2}
    plan.write_text(json.dumps({"rows": [{
        "principal": "alice", "entity_type": "factor_param_config",
        "entity_id": "default:Momentum", "expected_revision": 3,
        "old_payload": {"schema_version": 1}, "old_deleted": False,
        "new_payload": target, "new_deleted": False,
    }]}), encoding="utf-8")
    environment = tmp_path / "control.env"
    environment.write_text(
        "FACTORTESTER_CONTROL_DATABASE_URL=postgresql://example\n", encoding="utf-8",
    )

    class Connection(_Connection):
        def execute(self, statement, parameters):
            self.calls.append((statement, parameters))
            if statement.startswith("UPDATE"):
                return type("Cursor", (), {"rowcount": 0})()
            return type("Cursor", (), {"fetchone": lambda _self: (target, False)})()

    monkeypatch.setattr(migration.psycopg, "connect", lambda _url: Connection())
    assert migration.apply_plan(plan_path=plan, environment_path=environment) == 1
