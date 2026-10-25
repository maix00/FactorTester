from scripts.migrations.migrate_libraries_to_couchdb import migrate


def test_library_migration_dry_run():
    docs = [{"_id": "factor-family:x"}, {"_id": "factor-family:y"}]
    assert migrate(docs, None, dry_run=True)["written"] == 2
