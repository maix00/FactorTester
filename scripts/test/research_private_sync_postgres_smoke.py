"""Exercise Research outbox privacy against an isolated real PostgreSQL.

This tests the legacy account-domain metadata path, not CouchDB publication or
Keycloak policy. It never connects to an existing server or downloads an image.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from urllib.parse import quote

import psycopg

from scripts.test.postgres_sandbox import postgres_sandbox
from scripts.test.historical_research_catalog import HistoricalResearchCatalog as ResearchCatalog
from server.manager.storage.account_domain import AccountDomainSyncService
from server.manager.storage.account_domain.research_sync import snapshot
from server.manager.storage.control_db import ControlDatabaseConfig, PostgresControlStore
from tools.data.sqlite.db import connect_sqlite


def main():
    with postgres_sandbox("tr-research-outbox") as settings, tempfile.TemporaryDirectory(
            prefix="tr-research-outbox-") as tmp:
        url = (f"postgresql://{settings['user']}:{quote(settings['password'], safe='')}@"
               f"{settings['host']}:{settings['port']}/{settings['dbname']}?sslmode=disable")
        control = PostgresControlStore(ControlDatabaseConfig.from_url(url))
        author_path, mirror_path = Path(tmp) / "author.sqlite", Path(tmp) / "mirror.sqlite"
        author, mirror = ResearchCatalog(author_path), ResearchCatalog(mirror_path)
        outgoing = AccountDomainSyncService(sqlite_path=author_path, control_store=control, manager_id="author")
        incoming = AccountDomainSyncService(sqlite_path=mirror_path, control_store=control, manager_id="mirror")
        author.set_synchronizer(outgoing)
        mirror.set_synchronizer(incoming)

        private = author.create_research(owner_ref="alice", title="private sentinel")['research_id']
        author.register_report(private, actor="alice", report_id="private-report", title="private report sentinel")
        safe_default = author.create_research(owner_ref="alice", title="shared default", visibility="public")['research_id']
        author.register_report(safe_default, actor="alice", report_id="default-report")
        assert not outgoing.local.pending(principal="alice")
        # Exercise historical migration compatibility only after verifying the
        # real runtime default never auto-uploads a full Research graph.
        outgoing.research_legacy_sharing = True
        # Queue a private projection produced by the former implementation.
        with connect_sqlite(author_path, readonly=True) as conn:
            old = snapshot(conn, private)
        outgoing.local.upsert_local(principal="alice", entity_type="research_catalog", entity_id=private,
            payload={"schema_version": 2, "visibility": "public", "replication_scope": "trusted_managers",
                     "storage_server_id": "author", **old}, manager_id="author")

        shared = author.create_research(owner_ref="alice", title="shared", visibility="authorized",
                                        authorized_users=["bob"])['research_id']
        author.register_report(shared, actor="alice", report_id="shared-report", title="shared report")
        sent = outgoing.flush(principal="alice", limit=1)
        assert sent['sent'] == 1 and sent['blocked'] == 1
        assert incoming.pull(principal="bob")['applied'] == 1
        assert mirror.get_research_summary(shared, viewer="bob")['research_id'] == shared
        author.update_research(shared, actor="alice", visibility="private", authorized_users=[])
        assert outgoing.flush(principal="alice")['sent'] == 1
        incoming.pull(principal="bob")
        assert not mirror.list_researches(viewer="bob")

        with psycopg.connect(**settings) as db:
            rows = db.execute("""SELECT entity_id,payload::text,deleted FROM control_account_domain_entities
                WHERE principal=%s AND entity_type=%s""", ("alice", "research_catalog")).fetchall()
        assert len(rows) == 1 and rows[0][0] == shared and not rows[0][2]
        assert "private sentinel" not in rows[0][1] and "private report sentinel" not in rows[0][1]
        retained = outgoing.local.pending(principal="alice", include_blocked=True)
        assert len(retained) == 1 and retained[0]['entity_id'] == private
        assert retained[0]['last_error'] == 'research_sync_needs_review'
        print(json.dumps({"real_postgres": True, "default_graph_upload_disabled": True,
            "legacy_compatibility_test_only": True, "private_not_transmitted": True,
            "old_private_retained_for_review": True, "shared_metadata_and_revocation": True,
            "keycloak_tested": False, "couchdb_tested": False}, sort_keys=True))


if __name__ == "__main__":
    main()
