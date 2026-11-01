"""Prepare or stage one principal's device grants from a restored PostgreSQL backup.

The restored database URL is read from TR_DEVICE_RESTORED_DB_URL, never from
the command line. Before stage, operators must quiesce device writes and
independently back up and restore-test both PostgreSQL and Keycloak. Staging
does not change the Manager's authority or remove old records.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat

from scripts.migrations.keycloak_device_inventory import read_keycloak_directory, read_postgres_snapshot
from scripts.migrations.keycloak_device_stage import KeycloakDeviceStageBackend, review, stage


def _read_private_json(path: str) -> dict:
    flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0)
    fd = os.open(Path(path).expanduser(), flags)
    with os.fdopen(fd, 'rb') as source:
        info = os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
            raise PermissionError('reviewed plan must be an owner-only regular file')
        if info.st_size > 1024 * 1024:
            raise ValueError('reviewed plan exceeds size budget')
        value = json.load(source)
    if not isinstance(value, dict):
        raise ValueError('reviewed plan must be an object')
    return value


def _check_private_backup(path: str, expected: str, *, label: str) -> None:
    if not re.fullmatch(r'[0-9a-f]{64}', expected):
        raise ValueError(f'{label} backup SHA-256 is invalid')
    flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0)
    fd = os.open(Path(path).expanduser(), flags)
    digest = hashlib.sha256()
    with os.fdopen(fd, 'rb') as source:
        info = os.fstat(source.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or info.st_mode & 0o077 or info.st_size <= 0):
            raise PermissionError(f'{label} backup must be an owner-only regular file')
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    if digest.hexdigest() != expected:
        raise ValueError(f'{label} backup checksum mismatch')


def _check_keycloak_backup(path: str, expected: str) -> None:
    _check_private_backup(path, expected, label='Keycloak')


def _snapshot(config, *, manager_id: str, principal: str) -> dict:
    from server.manager.storage.control_db import PostgresControlStore
    connection = PostgresControlStore(config)._connect()
    try:
        return read_postgres_snapshot(connection, manager_id=manager_id, principal=principal)
    finally:
        connection.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('review', 'stage'))
    parser.add_argument('--manager-id', required=True)
    parser.add_argument('--principal', required=True)
    parser.add_argument('--plan', required=True, help='owner-only review file')
    parser.add_argument('--journal', help='new owner-only write-ahead journal; stage only')
    parser.add_argument('--keycloak-backup', help='restore-tested Keycloak backup; stage only')
    parser.add_argument('--keycloak-backup-sha256', help='SHA-256 of the Keycloak backup; stage only')
    parser.add_argument('--device-writes-quiesced', action='store_true',
                        help='confirm device enrollment and revocation are stopped for the entire staging')
    args = parser.parse_args()
    from server.manager.storage.control_db import ControlDatabaseConfig
    from server.identity.user_session import oidc_settings
    from server.identity.keycloak_policy_evaluation import KeycloakPolicyEvaluator

    live = ControlDatabaseConfig.from_env()
    restored = ControlDatabaseConfig.from_url(os.environ.get('TR_DEVICE_RESTORED_DB_URL', ''))
    if live is None:
        parser.error('live PostgreSQL control database is not configured')
    # Host aliases can point at the same cluster. Require a differently named
    # restored database even when the configured hosts appear distinct.
    if live.database == restored.database:
        parser.error('restored backup must have a distinct database name')
    settings = oidc_settings()
    issuer = str(settings.get('issuer') or '').rstrip('/')
    backup = _snapshot(restored, manager_id=args.manager_id, principal=args.principal)
    directory = read_keycloak_directory(args.principal)
    prepared = review(backup, directory, manager_id=args.manager_id, issuer=issuer)
    path = Path(args.plan).expanduser()
    if args.action == 'review':
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        with os.fdopen(fd, 'w') as output:
            json.dump(prepared, output, sort_keys=True)
            output.flush()
            os.fsync(output.fileno())
        print(json.dumps({'sha256': prepared['sha256'], 'statuses': prepared['statuses']}, sort_keys=True))
        return
    if not args.device_writes_quiesced or not args.journal or not args.keycloak_backup or not args.keycloak_backup_sha256:
        parser.error('stage requires quiesced device writes, a journal and a checksummed Keycloak backup')
    _check_keycloak_backup(args.keycloak_backup, args.keycloak_backup_sha256)
    reviewed = _read_private_json(args.plan)
    evaluator = KeycloakPolicyEvaluator(allowed_kinds=('device',), allowed_scopes=('use',), settings=settings)
    backend = KeycloakDeviceStageBackend(settings=settings, evaluator=evaluator, issuer=issuer)
    result = stage(reviewed=reviewed, backup_snapshot=backup, backup_directory=directory,
        live_snapshot=lambda: _snapshot(live, manager_id=args.manager_id, principal=args.principal),
        live_directory=lambda: read_keycloak_directory(args.principal), manager_id=args.manager_id,
        issuer=issuer, journal=Path(args.journal), resource_absent=backend.resource_absent,
        create=backend.create, verify=backend.verify)
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
