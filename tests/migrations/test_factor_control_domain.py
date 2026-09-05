from __future__ import annotations

import copy
import json
import pytest
from tools.migrations import migrate_factor_control_domain as migration


class Connection:
    def __init__(self, current):
        self.current = current
        self.sequence = 1000
        self.calls = []
    def __enter__(self):
        self.before = copy.deepcopy(self.current)
        return self
    def __exit__(self, kind, *_args):
        if kind: self.current = self.before
    def execute(self, statement, parameters=()):
        self.calls.append((statement, parameters))
        value = None
        if statement.startswith("SELECT payload"):
            value = self.current
        elif statement.startswith("SELECT nextval"):
            self.sequence += 1
            value = (self.sequence,)
        elif statement.startswith("INSERT"):
            self.current = (parameters[3].obj, parameters[4], parameters[5])
        return type("Cursor", (), {"fetchone": lambda _self: value})()


def plan_files(tmp_path):
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps({"rows": [{
        "principal": "alice", "entity_type": "factor_param_config",
        "entity_id": "default:F", "expected_revision": 3,
        "old_payload": {"schema_version": 1}, "old_deleted": False,
        "new_payload": {"schema_version": 2}, "new_deleted": False,
    }]}))
    environment = tmp_path / "control.env"
    environment.write_text("FACTORTESTER_CONTROL_DATABASE_URL=postgresql://example\n")
    return plan, environment


def test_apply_and_restore_both_advance_global_cursor(tmp_path, monkeypatch):
    plan, environment = plan_files(tmp_path)
    connection = Connection(({"schema_version": 1}, False, 3))
    monkeypatch.setattr(migration.psycopg, "connect", lambda url: connection)
    assert migration.apply_plan(plan_path=plan, environment_path=environment) == 1
    assert connection.current == ({"schema_version": 2}, False, 1001)
    receipt = json.loads(plan.with_suffix(".json.receipt.json").read_text())
    assert receipt["rows"][0]["revision"] == 1001
    assert migration.apply_plan(plan_path=plan, environment_path=environment, restore=True) == 1
    assert connection.current == ({"schema_version": 1}, False, 1002)


def test_replay_is_idempotent_and_intervening_edits_are_preserved(tmp_path, monkeypatch):
    plan, environment = plan_files(tmp_path)
    connection = Connection(({"schema_version": 2}, False, 99))
    monkeypatch.setattr(migration.psycopg, "connect", lambda url: connection)
    assert migration.apply_plan(plan_path=plan, environment_path=environment) == 1
    assert connection.sequence == 1000
    connection.current = ({"schema_version": 2, "user_edit": True}, False, 100)
    with pytest.raises(RuntimeError, match="precondition"):
        migration.apply_plan(plan_path=plan, environment_path=environment, restore=True)
    assert connection.current[0]["user_edit"] is True
