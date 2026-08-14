"""Public facade for the account-identity migration helpers.

The implementation is split by persistence boundary. Existing callers keep
using this module while SQLite, PostgreSQL, and filesystem state remain
independently testable.
"""

from server.manager.storage.identity_migration_common import (
    POSTGRES_USER_REFERENCES,
    SQLITE_USER_REFERENCES,
    SYSTEM_OWNER_VALUES,
    backup_sqlite,
    choose_canonical_username,
    cursor_rows_as_dicts,
    sqlite_integrity_check,
)
from server.manager.storage.identity_migration_files import (
    apply_user_root_identity_migration,
    backup_json,
    migrate_local_device_json,
    migrate_local_session_json,
    user_root_identity_plan,
)
from server.manager.storage.identity_migration_postgres import (
    apply_postgres_identity_migration,
    postgres_identity_plan,
)
from server.manager.storage.identity_migration_sqlite import (
    apply_sqlite_identity_migration,
    sqlite_identity_plan,
)

__all__ = [
    "POSTGRES_USER_REFERENCES",
    "SQLITE_USER_REFERENCES",
    "SYSTEM_OWNER_VALUES",
    "apply_postgres_identity_migration",
    "apply_sqlite_identity_migration",
    "apply_user_root_identity_migration",
    "backup_json",
    "backup_sqlite",
    "choose_canonical_username",
    "cursor_rows_as_dicts",
    "migrate_local_device_json",
    "migrate_local_session_json",
    "postgres_identity_plan",
    "sqlite_identity_plan",
    "sqlite_integrity_check",
    "user_root_identity_plan",
]
