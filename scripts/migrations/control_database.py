"""Read the selected Manager's control DB configuration without starting it.

Migration commands must explicitly select a Manager state directory when the
connection is persisted there. Never instantiate ManagerState for inventory:
its constructor initializes stores unrelated to the migration.
"""
from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from server.manager.storage.control_db import ControlDatabaseConfig
from server.manager.storage.control_database_settings import ControlDatabaseSettingsStore


def configured_control_database(*, manager_state_root: str | Path | None = None,
                                environ: Mapping[str, str] | None = None) -> ControlDatabaseConfig | None:
    environment = ControlDatabaseConfig.from_env(environ)
    if environment is not None or manager_state_root is None:
        return environment
    root = Path(manager_state_root).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise ValueError('Manager state root must be an existing directory')
    # The runtime uses this exact store and environment-over-file precedence.
    # Its parent already exists, so construction cannot create directories.
    store = ControlDatabaseSettingsStore(root / 'control-database.json', environ=environ)
    return ControlDatabaseConfig.from_env(store.effective_environ())
