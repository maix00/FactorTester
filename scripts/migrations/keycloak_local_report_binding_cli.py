"""Review or stage one old report binding, never changing its Keycloak grants.

Provide a restored CouchDB via TR_REPORT_RESTORED_COUCHDB_URL and
TR_REPORT_RESTORED_COUCHDB_DB (plus optional USER/PASSWORD). The restored
database must have a different name from the live database. Staging requires
quiesced authorization writes and independently restore-tested backups.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from types import SimpleNamespace

from scripts.migrations.keycloak_device_stage_cli import _check_private_backup, _read_private_json
from scripts.migrations.keycloak_local_report_binding import BindingBackend, review, stage


def _restored_store(live):
    from server.jobs.storage.couchdb_reports import CouchDBObjectStore
    url = os.environ.get('TR_REPORT_RESTORED_COUCHDB_URL', '').strip()
    database = os.environ.get('TR_REPORT_RESTORED_COUCHDB_DB', '').strip()
    if not url or not database or database == live.database:
        raise ValueError('a separately restored CouchDB database is required')
    return CouchDBObjectStore(url, database,
        username=os.environ.get('TR_REPORT_RESTORED_COUCHDB_USER', ''),
        password=os.environ.get('TR_REPORT_RESTORED_COUCHDB_PASSWORD', ''))


def _verify_restored(evidence, restored) -> None:
    for key in ('receipt', 'publication'):
        expected = evidence[key]
        status, raw = restored._request('GET', expected['_id'])
        if status != 200 or json.loads(raw) != expected:
            raise ValueError(f'restored {key} differs from the reviewed live record')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('review', 'stage'))
    parser.add_argument('--manager-id', required=True)
    parser.add_argument('--owner-id', required=True)
    parser.add_argument('--research-id', required=True)
    parser.add_argument('--report-id', required=True)
    parser.add_argument('--plan', required=True)
    parser.add_argument('--journal')
    parser.add_argument('--keycloak-backup')
    parser.add_argument('--keycloak-backup-sha256')
    parser.add_argument('--couch-backup')
    parser.add_argument('--couch-backup-sha256')
    parser.add_argument('--authorization-writes-quiesced', action='store_true')
    parser.add_argument('--keycloak-restore-verified', action='store_true')
    args = parser.parse_args()

    from server.identity.federation_identity_sync import manager_keycloak_admin_adapter
    from server.identity.keycloak_research import KeycloakResearchGrantManager
    from server.identity.server_admission import _context
    from server.manager.services.research_couchdb_publication import report_store_from_environment
    _public, configured_manager, _organizations = _context(None)
    if not configured_manager or configured_manager != args.manager_id:
        parser.error('manager identity differs from this deployment')
    live = report_store_from_environment()
    restored = _restored_store(live)
    backend = BindingBackend(state=SimpleNamespace(server_id=args.manager_id), store=live,
        manager=KeycloakResearchGrantManager(), adapter=manager_keycloak_admin_adapter(),
        research_id=args.research_id, report_id=args.report_id, owner_id=args.owner_id)
    evidence = backend.read_evidence()
    _verify_restored(evidence, restored)
    decisions = backend.read_decisions(evidence['directory'], args.report_id)
    prepared = review(**evidence, decisions=decisions)
    path = Path(args.plan).expanduser()
    if args.action == 'review':
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        with os.fdopen(fd, 'w') as output:
            json.dump(prepared, output, sort_keys=True)
            output.flush()
            os.fsync(output.fileno())
        print(json.dumps({'sha256': prepared['sha256'], 'status': prepared['status']}, sort_keys=True))
        return
    if (not args.authorization_writes_quiesced or not args.keycloak_restore_verified or not args.journal
            or not args.keycloak_backup or not args.keycloak_backup_sha256
            or not args.couch_backup or not args.couch_backup_sha256):
        parser.error('stage requires quiesced writes, restore verification, both checksummed backups and a journal')
    _check_private_backup(args.keycloak_backup, args.keycloak_backup_sha256, label='Keycloak')
    _check_private_backup(args.couch_backup, args.couch_backup_sha256, label='CouchDB')
    approved = _read_private_json(args.plan)
    if approved != prepared:
        raise ValueError('report binding changed after review')
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0)
    fd = os.open(Path(args.journal).expanduser(), flags, 0o600)
    with os.fdopen(fd, 'w') as output:
        def record(value):
            output.write(json.dumps(value, sort_keys=True, separators=(',', ':')) + '\n')
            output.flush()
            os.fsync(output.fileno())
        result = stage(approved=approved, read_evidence=backend.read_evidence,
            read_decisions=backend.read_decisions, update_resource=backend.update_resource, record=record)
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
