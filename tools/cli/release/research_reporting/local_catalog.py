"""Client-owned private Research metadata; this store never synchronizes.

Callers must derive the binding and allowed Profiles from the native verified
session, not from embedded web content. Sharing is a separate explicit action.
"""
from __future__ import annotations

import json
import secrets
import sqlite3
import time
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
from urllib.parse import urlsplit

from tools.cli.release.local_profile_contracts import validate_local_identifier
from tools.cli.release.locations import validate_client_root


class LocalResearchListingChanged(ValueError):
    """A multi-page local listing was changed between requests."""


class LocalResearchCatalog:
    def __init__(self, root: Path, *, issuer: str, identity_id: str, profiles: set[str]) -> None:
        issuer = str(issuer or '').strip().rstrip('/')
        stable = str(identity_id or '').strip()
        parsed = urlsplit(issuer)
        if (parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username
                or parsed.password or parsed.query or parsed.fragment or not stable or len(stable) > 128):
            raise ValueError('verified local identity is required')
        self.profiles = frozenset(validate_local_identifier(p, 'profile_id') for p in profiles)
        if not self.profiles:
            raise ValueError('verified local Profile is required')
        identity_hash = sha256(json.dumps([issuer, stable], ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()
        base = validate_client_root(root) / 'local-research'
        if base.is_symlink():
            raise ValueError('local research directory cannot be a symlink')
        base.mkdir(parents=True, mode=0o700, exist_ok=True)
        base.chmod(0o700)
        self.path = base / (identity_hash + '.sqlite3')
        self.workspace_root = base / (identity_hash + '.reports')
        if self.path.is_symlink():
            raise ValueError('local research database cannot be a symlink')
        with self._connect() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS researches (
                research_id TEXT PRIMARY KEY, profile_id TEXT NOT NULL, title TEXT NOT NULL,
                description TEXT NOT NULL, operation_id TEXT NOT NULL UNIQUE,
                created_at REAL NOT NULL, updated_at REAL NOT NULL)''')
            db.execute('''CREATE TABLE IF NOT EXISTS reports (
                report_id TEXT PRIMARY KEY, research_id TEXT NOT NULL, profile_id TEXT NOT NULL,
                title TEXT NOT NULL, operation_id TEXT NOT NULL UNIQUE,
                created_at REAL NOT NULL, ready INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY(research_id) REFERENCES researches(research_id))''')
            db.execute('''CREATE INDEX IF NOT EXISTS researches_profile_page
                ON researches(profile_id, created_at DESC, research_id DESC)''')
            db.execute('''CREATE TABLE IF NOT EXISTS server_research_origins (
                research_id TEXT PRIMARY KEY, manager_hash TEXT NOT NULL, profile_id TEXT NOT NULL,
                title TEXT NOT NULL, description TEXT NOT NULL, updated_at REAL NOT NULL)''')
            db.execute('''CREATE TABLE IF NOT EXISTS server_report_scans (
                research_id TEXT NOT NULL, manager_hash TEXT NOT NULL, profile_id TEXT NOT NULL,
                cursor TEXT NOT NULL DEFAULT '', last_attempt REAL NOT NULL DEFAULT 0,
                PRIMARY KEY(research_id, manager_hash, profile_id))''')
            db.execute('''CREATE INDEX IF NOT EXISTS server_report_scans_page
                ON server_report_scans(manager_hash, profile_id, last_attempt, research_id)''')
            db.execute('''CREATE TABLE IF NOT EXISTS server_report_pending (
                research_id TEXT NOT NULL, report_id TEXT NOT NULL, manager_hash TEXT NOT NULL,
                profile_id TEXT NOT NULL, last_attempt REAL NOT NULL DEFAULT 0,
                PRIMARY KEY(report_id, manager_hash, profile_id))''')
            db.execute('''CREATE INDEX IF NOT EXISTS server_report_pending_page
                ON server_report_pending(manager_hash, profile_id, last_attempt, report_id)''')
            db.execute('''CREATE TABLE IF NOT EXISTS server_research_pending (
                research_id TEXT NOT NULL, manager_hash TEXT NOT NULL, profile_id TEXT NOT NULL,
                last_attempt REAL NOT NULL DEFAULT 0, PRIMARY KEY(research_id, manager_hash, profile_id))''')
            db.execute('''CREATE INDEX IF NOT EXISTS server_research_pending_page
                ON server_research_pending(manager_hash, profile_id, last_attempt, research_id)''')
            db.execute('''CREATE INDEX IF NOT EXISTS reports_profile_page
                ON reports(profile_id, ready, created_at DESC, report_id DESC)''')
            db.execute('''CREATE TABLE IF NOT EXISTS local_directory_revision (
                id INTEGER PRIMARY KEY CHECK (id=1), revision INTEGER NOT NULL)''')
            db.execute('INSERT OR IGNORE INTO local_directory_revision VALUES (1,0)')
            for table in ('researches', 'reports'):
                for operation in ('INSERT', 'UPDATE', 'DELETE'):
                    db.execute(f'''CREATE TRIGGER IF NOT EXISTS local_directory_{table}_{operation.lower()}
                        AFTER {operation} ON {table} BEGIN
                          UPDATE local_directory_revision SET revision=revision+1 WHERE id=1;
                        END''')

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        try:
            self.path.chmod(0o600)
            db.row_factory = sqlite3.Row
            with db:
                yield db
        finally:
            db.close()

    def _profile(self, profile_id: str) -> str:
        value = validate_local_identifier(profile_id, 'profile_id')
        if value not in self.profiles:
            raise PermissionError('Profile is outside the native session')
        return value

    def create(self, *, profile_id: str, title: str, description: str, operation_id: str) -> dict:
        profile = self._profile(profile_id)
        title = str(title or '').strip()
        if not title or len(title) > 256 or not isinstance(description, str) or len(description) > 10000:
            raise ValueError('invalid Research title or description')
        operation = validate_local_identifier(operation_id, 'operation_id')
        now = time.time()
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            existing = db.execute('SELECT * FROM researches WHERE operation_id=?', (operation,)).fetchone()
            if existing:
                if (existing['profile_id'], existing['title'], existing['description']) != (profile, title, description):
                    raise ValueError('operation_id was already used for another Research')
                return self._public(existing)
            identifier = 'research:v1:' + secrets.token_urlsafe(18)
            db.execute('INSERT INTO researches VALUES (?, ?, ?, ?, ?, ?, ?)',
                       (identifier, profile, title, description, operation, now, now))
            return self._public(db.execute('SELECT * FROM researches WHERE research_id=?', (identifier,)).fetchone())

    def list(self, *, profile_id: str, limit: int = 200, offset: int = 0) -> list[dict]:
        return self.page(profile_id=profile_id, limit=limit, offset=offset)['researches']

    def page(self, *, profile_id: str, limit: int = 100, offset: int = 0,
             expected_revision: int | None = None, consistent: bool = False) -> dict:
        profile = self._profile(profile_id)
        if not 1 <= limit <= 200 or not 0 <= offset <= 1_000_000:
            raise ValueError('invalid local Research page')
        with self._connect() as db:
            if consistent:
                db.execute('BEGIN')
                revision = db.execute('SELECT revision FROM local_directory_revision WHERE id=1').fetchone()['revision']
                if expected_revision is not None and expected_revision != revision:
                    raise LocalResearchListingChanged('local research directory changed during pagination')
            rows = db.execute('SELECT * FROM researches WHERE profile_id=? ORDER BY created_at DESC, research_id DESC LIMIT ? OFFSET ?',
                              (profile, limit + 1, offset)).fetchall()
            items = [self._public(row) for row in rows[:limit]]
            result = {'researches': items, 'next_offset': offset + len(items) if len(rows) > limit else None}
            if consistent:
                result['revision'] = revision
            return result

    def consistent_page(self, *, profile_id: str, limit: int, offset: int, expected_revision: int | None) -> dict:
        """Read a directory page and its revision from the same SQLite snapshot."""
        return self.page(profile_id=profile_id, limit=limit, offset=offset,
                         expected_revision=expected_revision, consistent=True)

    def get(self, *, profile_id: str, research_id: str) -> dict | None:
        profile = self._profile(profile_id)
        with self._connect() as db:
            row = db.execute('SELECT * FROM researches WHERE profile_id=? AND research_id=?', (profile, str(research_id))).fetchone()
            return self._public(row) if row else None

    def create_report(self, *, profile_id: str, research_id: str, title: str, operation_id: str) -> dict:
        """Reserve one report identity and initialize the shared report-tree format.

        The reservation survives an interrupted initialization; retrying the
        same operation completes the same report rather than creating another.
        """
        from .generation import report_workspace_lock
        from .report_workspace_identity import report_workspace_id_for
        from .workspace import initialize_report_workspace

        profile = self._profile(profile_id)
        title = str(title or '').strip()
        if not title or len(title) > 256:
            raise ValueError('invalid report title')
        operation = validate_local_identifier(operation_id, 'operation_id')
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if not db.execute('SELECT 1 FROM researches WHERE profile_id=? AND research_id=?',
                              (profile, research_id)).fetchone():
                raise ValueError('research is unavailable')
            row = db.execute('SELECT * FROM reports WHERE operation_id=?', (operation,)).fetchone()
            if row:
                if (row['profile_id'], row['research_id'], row['title']) != (profile, research_id, title):
                    raise ValueError('operation_id was already used for another report')
            else:
                identifier = 'report:v1:' + secrets.token_urlsafe(18)
                db.execute('INSERT INTO reports (report_id, research_id, profile_id, title, operation_id, created_at) VALUES (?, ?, ?, ?, ?, ?)',
                           (identifier, research_id, profile, title, operation, time.time()))
                row = db.execute('SELECT * FROM reports WHERE report_id=?', (identifier,)).fetchone()
            report = dict(row)
        if self.workspace_root.is_symlink():
            raise ValueError('local report directory cannot be a symlink')
        self.workspace_root.mkdir(mode=0o700, exist_ok=True)
        self.workspace_root.chmod(0o700)
        workspace_id = report_workspace_id_for(report['report_id'])
        with report_workspace_lock(self.workspace_root / '.locks' / workspace_id):
            with self._connect() as db:
                current = db.execute('SELECT ready FROM reports WHERE report_id=?', (report['report_id'],)).fetchone()
            if not current:
                raise ValueError('report reservation is unavailable')
            if not current['ready']:
                initialize_report_workspace(workspace_root=self.workspace_root, report_workspace_id=workspace_id,
                    report_id=report['report_id'], branch_id='main', workspace_id=research_id,
                    title=title, branch_ref='report-branch:main')
                with self._connect() as db:
                    db.execute('UPDATE reports SET ready=1 WHERE report_id=?', (report['report_id'],))
        return self._report_public(report)

    def list_reports(self, *, profile_id: str, research_id: str, limit: int, offset: int) -> dict:
        profile = self._profile(profile_id)
        if not 1 <= limit <= 200 or not 0 <= offset <= 1_000_000:
            raise ValueError('invalid local report page')
        with self._connect() as db:
            if not db.execute('SELECT 1 FROM researches WHERE profile_id=? AND research_id=?',
                              (profile, research_id)).fetchone():
                raise ValueError('research is unavailable')
            rows = db.execute('''SELECT * FROM reports WHERE profile_id=? AND research_id=? AND ready=1
                ORDER BY created_at DESC, report_id DESC LIMIT ? OFFSET ?''',
                (profile, research_id, limit + 1, offset)).fetchall()
            items = [self._report_public(row) for row in rows[:limit]]
            return {'reports': items, 'next_offset': offset + len(items) if len(rows) > limit else None}

    def list_profile_reports(self, *, profile_id: str, limit: int, offset: int, expected_revision: int | None) -> dict:
        """List one verified Profile's report metadata without opening report trees."""
        profile = self._profile(profile_id)
        if not 1 <= limit <= 200 or not 0 <= offset <= 1_000_000:
            raise ValueError('invalid local report page')
        with self._connect() as db:
            db.execute('BEGIN')
            revision = db.execute('SELECT revision FROM local_directory_revision WHERE id=1').fetchone()['revision']
            if expected_revision is not None and expected_revision != revision:
                raise LocalResearchListingChanged('local report directory changed during pagination')
            rows = db.execute('''SELECT report.report_id, report.research_id, report.profile_id,
                    report.title, report.created_at, research.title AS research_title,
                    research.profile_id AS research_profile_id,
                    research.created_at AS research_created_at,
                    research.updated_at AS research_updated_at
                FROM reports AS report LEFT JOIN researches AS research
                  ON research.research_id=report.research_id
                WHERE report.profile_id=? AND report.ready=1
                ORDER BY report.created_at DESC, report.report_id DESC LIMIT ? OFFSET ?''',
                (profile, limit + 1, offset)).fetchall()
            if any(row['research_profile_id'] != profile for row in rows):
                raise ValueError('local report has a missing or mismatched Research identity')
            items = [{**self._report_public(row), 'research': {
                'research_id': row['research_id'], 'profile_id': row['profile_id'],
                'title': row['research_title'],
                'created_at': row['research_created_at'], 'updated_at': row['research_updated_at'],
            }} for row in rows[:limit]]
            return {'reports': items, 'next_offset': offset + len(items) if len(rows) > limit else None,
                    'revision': revision}

    def get_report_index(self, *, profile_id: str, research_id: str, report_id: str) -> dict:
        from .authoring.tree_projection import load_report_index
        from .public_research.projection import build_upload_index
        report, root = self._report_root(profile_id, research_id, report_id)
        snapshot = load_report_index(package_root=root, branch_id='main')
        index = build_upload_index(snapshot)
        if index.get('report_id') != report_id:
            raise ValueError('local report identity is invalid')
        return {'report': report, 'index': index,
                'version': {'generation': snapshot['head']['generation'], 'root_ref': snapshot['head']['root_ref']}}

    def _report_root(self, profile_id: str, research_id: str, report_id: str):
        from .report_workspace_identity import report_workspace_id_for
        profile = self._profile(profile_id)
        with self._connect() as db:
            row = db.execute('''SELECT * FROM reports WHERE profile_id=? AND research_id=?
                AND report_id=? AND ready=1''', (profile, research_id, report_id)).fetchone()
            if row is None:
                raise ValueError('report is unavailable')
            report = self._report_public(row)
        if self.workspace_root.is_symlink():
            raise ValueError('local report directory cannot be a symlink')
        root = self.workspace_root / 'research' / report_workspace_id_for(report_id)
        if root.is_symlink() or root.parent.is_symlink():
            raise ValueError('local report workspace cannot be a symlink')
        return report, root

    def get_report_chapter(self, *, profile_id: str, research_id: str, report_id: str, chapter_id: str) -> dict:
        from .authoring.tree_projection import load_chapter_snapshot
        from .authoring.tree_schema import identifier
        from .public_research.projection import build_upload_projection

        _report, root = self._report_root(profile_id, research_id, report_id)
        snapshot = load_chapter_snapshot(package_root=root, branch_id='main', chapter_id=identifier(chapter_id, 'chapter_id'))
        if snapshot['head']['report_id'] != report_id:
            raise ValueError('local report identity is invalid')
        projection = build_upload_projection(snapshot, include_asset_bytes=False, include_local_resource_bytes=False)
        return {'chapter': {'chapter_id': chapter_id, 'components': projection['components']},
                'version': {'generation': snapshot['head']['generation'], 'root_ref': snapshot['head']['root_ref']}}

    def add_report_component(self, *, profile_id: str, research_id: str, report_id: str,
                             component_id: str, kind: str, parent_id: str, title: str, body: str,
                             generation: int, root_ref: str) -> dict:
        """Apply one bounded additive edit through the shared versioned tree transaction."""
        from .authoring.tree_operations import apply_operation
        from .authoring.tree_paths import report_tree_paths
        from .authoring.tree_schema import identifier, node_reference
        from .authoring.tree_transactions import mutate_batch
        from .generation import report_workspace_lock
        from .git import commit_report_workspace
        from .report_workspace_identity import report_workspace_id_for

        _report, root = self._report_root(profile_id, research_id, report_id)
        if kind not in {'chapter', 'entry'} or type(generation) is not int or generation < 0:
            raise ValueError('invalid report edit')
        identifier(component_id, 'component_id')
        node_reference(root_ref)
        if kind == 'chapter':
            if parent_id or body or not title.strip():
                raise ValueError('invalid chapter')
            parent = None
        else:
            parent = identifier(parent_id, 'parent_id')
            if not body.strip():
                raise ValueError('invalid paragraph')
        operation = {'op': 'add', 'component_id': component_id, 'kind': kind,
                     'title': title, 'body': body, 'parent_id': parent, 'content': None,
                     'display_kind': '', 'bindings': []}
        expected = {'report_id': report_id, 'generation': generation, 'root_ref': root_ref}
        lock = self.workspace_root / '.locks' / report_workspace_id_for(report_id)
        with report_workspace_lock(lock):
            head = mutate_batch(report_tree_paths(root, 'main'), [operation], apply_operation,
                                expected_head=expected)
            commit_report_workspace(root, message='Edit report')
        return {'version': {'generation': head['generation'], 'root_ref': head['root_ref']}}

    @staticmethod
    def _report_public(row) -> dict:
        return {key: row[key] for key in ('report_id', 'research_id', 'profile_id', 'title', 'created_at')}

    @staticmethod
    def _public(row) -> dict:
        return {key: row[key] for key in ('research_id', 'profile_id', 'title', 'description', 'created_at', 'updated_at')}
