import sqlite3
from scripts.migrations.migrate_strategy_versions_to_couchdb import strategy_documents


def test_strategy_document_includes_current_revision(tmp_path):
    db = tmp_path / "u.db"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE strategy_library_entries (strategy_ref TEXT PRIMARY KEY, owner_ref TEXT, name TEXT, description TEXT, visibility TEXT, current_revision_ref TEXT, created_at REAL, updated_at REAL, deleted_at REAL DEFAULT 0)")
        conn.execute("CREATE TABLE strategy_library_revisions (revision_ref TEXT PRIMARY KEY, strategy_ref TEXT, revision_number INTEGER, source_sha256 TEXT, source_code TEXT, entrypoint TEXT, hooks_json TEXT, requirements_json TEXT, created_by TEXT, created_at REAL)")
        conn.execute("INSERT INTO strategy_library_entries VALUES ('strategy:x','alice','n','d','private','rev:x',0,0,0)")
        conn.execute("INSERT INTO strategy_library_revisions VALUES ('rev:x','strategy:x',1,'s','code','main','{}','[]','alice',0)")
    docs = strategy_documents(db)
    assert docs[0]["ref"] == "strategy:x"
    assert docs[0]["payload"]["revision"]["revision_ref"] == "rev:x"
