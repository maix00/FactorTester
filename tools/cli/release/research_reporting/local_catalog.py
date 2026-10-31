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

    def page(self, *, profile_id: str, limit: int = 100, offset: int = 0) -> dict:
        profile = self._profile(profile_id)
        if not 1 <= limit <= 200 or not 0 <= offset <= 1_000_000:
            raise ValueError('invalid local Research page')
        with self._connect() as db:
            rows = db.execute('SELECT * FROM researches WHERE profile_id=? ORDER BY created_at DESC, research_id DESC LIMIT ? OFFSET ?',
                              (profile, limit + 1, offset)).fetchall()
            items = [self._public(row) for row in rows[:limit]]
            return {'researches': items, 'next_offset': offset + len(items) if len(rows) > limit else None}

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

    @staticmethod
    def _report_public(row) -> dict:
        return {key: row[key] for key in ('report_id', 'research_id', 'profile_id', 'title', 'created_at')}

    @staticmethod
    def _public(row) -> dict:
        return {key: row[key] for key in ('research_id', 'profile_id', 'title', 'description', 'created_at', 'updated_at')}
