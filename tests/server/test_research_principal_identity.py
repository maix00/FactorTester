"""Research membership is a principal/Profile pair, never a bare Profile name."""
from server.manager.services.research_catalog import ResearchCatalog


def test_same_named_profiles_keep_distinct_members_and_workspaces(tmp_path):
    catalog = ResearchCatalog(tmp_path / 'research.sqlite')
    research = catalog.create_research(owner_ref='alice', title='Shared research')
    rid = research['research_id']
    catalog.add_membership(rid, actor='alice', principal_ref='bob', profile_ref='self', role='editor')
    members = catalog.list_members(rid, viewer='alice')
    assert {(m['principal_ref'], m['profile_ref'], m['role']) for m in members} == {
        ('alice', 'self', 'owner'), ('bob', 'self', 'editor'),
    }
    alice = catalog.create_workspace(rid, actor='alice', principal_ref='alice', profile_ref='self')
    bob = catalog.create_workspace(rid, actor='alice', principal_ref='bob', profile_ref='self')
    assert alice['workspace_id'] != bob['workspace_id']
    reopened = ResearchCatalog(catalog.db_path)
    assert {(m['principal_ref'], m['profile_ref']) for m in reopened.list_members(rid, viewer='alice')} == {
        ('alice', 'self'), ('bob', 'self'),
    }


def test_removal_requires_principal_when_profile_is_ambiguous(tmp_path):
    import pytest
    catalog = ResearchCatalog(tmp_path / 'research.sqlite')
    rid = catalog.create_research(owner_ref='alice', title='Research')['research_id']
    catalog.add_membership(rid, actor='alice', principal_ref='bob', profile_ref='self', role='editor')
    catalog.create_workspace(rid, actor='alice', principal_ref='bob', profile_ref='self')
    with pytest.raises(ValueError, match='principal_ref'):
        catalog.remove_membership(rid, actor='alice', profile_ref='self')
    removed = catalog.remove_membership(rid, actor='alice', profile_ref='self', principal_ref='bob')
    members = {m['principal_ref']: m for m in catalog.list_members(rid, viewer='alice')}
    assert members['alice']['status'] == 'active'
    assert removed['status'] == 'revoked'
    assert 'bob' not in members
    with pytest.raises(PermissionError, match='required member'):
        catalog.remove_membership(rid, actor='alice', profile_ref='self', principal_ref='alice')


def test_workspace_cannot_borrow_another_principals_membership(tmp_path):
    import pytest
    catalog = ResearchCatalog(tmp_path / 'research.sqlite')
    rid = catalog.create_research(owner_ref='alice', title='Research')['research_id']
    with pytest.raises(ValueError, match='active research member'):
        catalog.create_workspace(rid, actor='alice', principal_ref='mallory', profile_ref='self')


def test_explicit_migration_preserves_rows_and_requires_backup(tmp_path):
    import sqlite3
    import pytest
    from scripts.research.migrate_research_principal_keys import migrate
    database = tmp_path / 'old.sqlite'
    catalog = ResearchCatalog(database)
    rid = catalog.create_research(owner_ref='alice', title='Old research')['research_id']
    # Recreate the former constraints without changing any stored relationships.
    with sqlite3.connect(database) as conn:
        for table in ('research_catalog_memberships', 'research_catalog_workspaces'):
            sql = conn.execute('SELECT sql FROM sqlite_master WHERE name=?', (table,)).fetchone()[0]
            conn.execute(sql.replace(table, table + '_old', 1).replace('research_id, principal_ref, profile_ref)', 'research_id, profile_ref)'))
            conn.execute(f'INSERT INTO {table}_old SELECT * FROM {table}')
            conn.execute(f'DROP TABLE {table}')
            conn.execute(f'ALTER TABLE {table}_old RENAME TO {table}')
    with pytest.raises(RuntimeError, match='explicit principal-key migration'):
        ResearchCatalog(database)
    before = migrate(database)
    assert before['dry_run']
    backup = tmp_path / 'backup.sqlite'
    after = migrate(database, backup=backup)
    assert backup.exists()
    assert backup.stat().st_mode & 0o777 == 0o600
    for table, original in before['tables'].items():
        assert after['tables'][table]['hash'] == original['hash']
        assert not after['tables'][table]['requires_migration']
    restored = ResearchCatalog(database)
    restored.add_membership(rid, actor='alice', principal_ref='bob', profile_ref='self')
    assert len(restored.list_members(rid, viewer='alice')) == 2


def test_report_creation_selects_owner_workspace_among_same_named_profiles(tmp_path):
    catalog = ResearchCatalog(tmp_path / "research.sqlite")
    rid = catalog.create_research(owner_ref="alice", title="Research")["research_id"]
    catalog.add_membership(rid, actor="alice", principal_ref="bob", profile_ref="self", role="editor")
    bob = catalog.create_workspace(rid, actor="alice", principal_ref="bob", profile_ref="self")
    report = catalog.create_report_space(rid, actor="alice", title="Owner report", profile_ref="self")
    assert report["owner_ref"] == "alice"
    assert report["workspace_id"] != bob["workspace_id"]
    owners = {row["workspace_id"]: row["principal_ref"] for row in catalog.list_workspaces(rid, viewer="alice")}
    assert owners[report["workspace_id"]] == "alice"
