"""Keep immutable revision identity independent of a node's display counter."""

REVISION_COLUMNS = (
    'revision_ref TEXT PRIMARY KEY, strategy_ref TEXT NOT NULL, '
    'revision_number INTEGER NOT NULL, source_sha256 TEXT NOT NULL, '
    'source_code TEXT NOT NULL, entrypoint TEXT NOT NULL, '
    'hooks_json TEXT NOT NULL, requirements_json TEXT NOT NULL, '
    'created_by TEXT NOT NULL, created_at REAL NOT NULL'
)


def migrate_revision_identity(db):
    # Two disconnected nodes may both author revision 2. Their immutable UUIDs
    # are distinct; the account-domain entry CAS decides which becomes current.
    # Preserve both histories rather than blocking the entire pull cursor.
    indexes = db.execute('PRAGMA index_list(strategy_library_revisions)').fetchall()
    legacy = any(
        row['unique'] and [column['name'] for column in db.execute(
            'SELECT name FROM pragma_index_info(?) ORDER BY seqno', (row['name'],)
        )] == ['strategy_ref', 'revision_number']
        for row in indexes
    )
    if not legacy:
        return
    db.execute('BEGIN IMMEDIATE')
    db.execute(f'CREATE TABLE strategy_library_revisions_migrating ({REVISION_COLUMNS})')
    db.execute('INSERT INTO strategy_library_revisions_migrating SELECT * FROM strategy_library_revisions')
    db.execute('DROP TABLE strategy_library_revisions')
    db.execute('ALTER TABLE strategy_library_revisions_migrating RENAME TO strategy_library_revisions')
    db.execute('CREATE INDEX idx_strategy_library_revision ON strategy_library_revisions(strategy_ref, revision_number)')
