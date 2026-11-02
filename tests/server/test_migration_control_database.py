"""Migration reads the same persisted control endpoint as Manager, without schema writes."""
import json

import pytest

from scripts.migrations.control_database import configured_control_database
from server.manager.storage.control_db import CONTROL_DATABASE_ENV


def test_persisted_manager_configuration_is_read_without_changes(tmp_path):
    path = tmp_path / 'control-database.json'
    path.write_text(json.dumps({'url': 'postgresql://operator:secret@db.internal/manager'}))
    before = path.read_bytes()
    config = configured_control_database(manager_state_root=tmp_path, environ={})
    assert config.host == 'db.internal' and config.database == 'manager'
    assert path.read_bytes() == before
    assert {file.name for file in tmp_path.iterdir()} == {'control-database.json'}


def test_environment_precedence_matches_manager_without_reading_stale_file(tmp_path):
    (tmp_path / 'control-database.json').write_text('not valid JSON')
    config = configured_control_database(manager_state_root=tmp_path,
        environ={CONTROL_DATABASE_ENV: 'postgresql://operator:secret@current.internal/active'})
    assert config.host == 'current.internal' and config.database == 'active'


def test_inventory_never_creates_missing_state_or_chooses_another_manager(tmp_path):
    missing = tmp_path / 'wrong-manager'
    with pytest.raises(FileNotFoundError):
        configured_control_database(manager_state_root=missing, environ={})
    assert not missing.exists()
    assert configured_control_database(environ={}) is None
    assert configured_control_database(manager_state_root=tmp_path, environ={}) is None
    assert list(tmp_path.iterdir()) == []
