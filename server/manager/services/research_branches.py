"""Metadata-only branch identities; report bytes remain owned by their executor."""
from __future__ import annotations

import re
import time
from tools.data.sqlite.db import connect_sqlite


def publication_source_kind(publication_id: str) -> str:
    """Disjoint, formal publication namespaces; never infer authority from labels."""
    if isinstance(publication_id, str):
        if re.fullmatch(r'p-[0-9a-f]{64}', publication_id):
            return 'couchdb'
        if re.fullmatch(r'[A-Za-z0-9_-]{20,64}', publication_id):
            return 'publication'
    raise ValueError('published branch reference is invalid')

BRANCH_SCHEMA = '''
CREATE TABLE IF NOT EXISTS research_catalog_branches (
    report_id TEXT NOT NULL,
    branch_id TEXT NOT NULL,
    research_id TEXT NOT NULL,
    principal_ref TEXT NOT NULL,
    profile_ref TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    title TEXT NOT NULL,
    status TEXT NOT NULL,
    source_branch_id TEXT NOT NULL,
    source_generation INTEGER NOT NULL,
    source_revision TEXT NOT NULL,
    source_publication_id TEXT NOT NULL,
    generation INTEGER NOT NULL,
    revision TEXT NOT NULL,
    publication_id TEXT NOT NULL,
    storage_server_id TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    PRIMARY KEY(report_id, branch_id),
    FOREIGN KEY(report_id) REFERENCES research_catalog_reports(report_id)
);
CREATE INDEX IF NOT EXISTS idx_research_branch_research ON research_catalog_branches(research_id);
'''


def _identifier(value, field):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9._-]{1,128}', value):
        raise ValueError(f'{field} must be a safe identifier')
    return value


class ResearchBranchesMixin:
    def _branch_profile_decision(self, report, actor: str, profile_ref: str):
        """Ask Keycloak before acquiring SQLite's writer lock, when enabled."""
        authorizer = self._profile_authorizer
        if authorizer is None:
            return None
        with connect_sqlite(self.db_path, readonly=True) as conn:
            if self._profile_policy_pending(conn, str(report['research_id']), actor, profile_ref):
                raise PermissionError('Profile authorization update is pending')
            version = self._profile_policy_version(conn, str(report['research_id']), actor, profile_ref)
        allowed = bool(authorizer.may_write_profile(
            research_id=str(report['research_id']), viewer=actor, profile_ref=profile_ref,
        ))
        return allowed, version

    def _branch_member(self, conn, report, actor: str, profile_ref: str, profile_decision=None):
        current = conn.execute('SELECT status FROM research_catalog_reports WHERE report_id=?',
                               (report['report_id'],)).fetchone()
        research = conn.execute('SELECT status FROM research_catalog_researches WHERE research_id=?',
                                (report['research_id'],)).fetchone()
        if self._profile_authorizer is None:
            member = conn.execute('''SELECT role FROM research_catalog_memberships
                WHERE research_id=? AND principal_ref=? AND profile_ref=? AND status='active' ''',
                (report['research_id'], actor, profile_ref)).fetchone()
            profile_decision = member is not None and member['role'] in {'owner', 'editor', 'contributor'}
        else:
            pending = conn.execute('''SELECT 1 FROM research_profile_policy_pending
                WHERE research_id=? AND principal_ref=? AND profile_ref=?''',
                (report['research_id'], actor, profile_ref)).fetchone()
            if pending is not None:
                raise PermissionError('Profile authorization update is pending')
            if (not isinstance(profile_decision, tuple) or len(profile_decision) != 2
                    or self._profile_policy_version(conn, str(report['research_id']), actor, profile_ref)
                    != profile_decision[1]):
                raise PermissionError('Profile authorization changed; retry')
            profile_decision = profile_decision[0]
        if (current is None or current['status'] != 'active' or research is None or research['status'] != 'active'
                or profile_decision is not True):
            raise PermissionError('this exact Profile is not an active report editor')
        workspace = conn.execute('''SELECT workspace_id FROM research_catalog_workspaces
            WHERE research_id=? AND principal_ref=? AND profile_ref=? AND status='active' ''',
            (report['research_id'], actor, profile_ref)).fetchone()
        if workspace is None:
            raise ValueError('create the Profile research workspace before reserving a branch')
        return workspace['workspace_id']

    def reserve_report_branch(self, report_id: str, *, actor: str, profile_ref: str,
                              branch_id: str, title: str = '', source_branch_id: str = '',
                              source_generation: int = 0, source_revision: str = '') -> dict:
        """Reserve one writer identity idempotently, without claiming byte availability."""
        branch_id = _identifier(branch_id, 'branch_id')
        profile_ref = _identifier(profile_ref, 'profile_ref')
        if not isinstance(title, str) or len(title) > 256:
            raise ValueError('branch title is invalid')
        report = self._report_row(report_id)
        profile_decision = self._branch_profile_decision(report, actor, profile_ref)
        with self._write(report['research_id']) as conn:
            workspace = self._branch_member(conn, report, actor, profile_ref, profile_decision)
            previous = conn.execute('SELECT * FROM research_catalog_branches WHERE report_id=? AND branch_id=?',
                                    (report_id, branch_id)).fetchone()
            identity = (actor, profile_ref, workspace, source_branch_id, source_generation, source_revision)
            if previous is not None:
                if tuple(previous[k] for k in ('principal_ref', 'profile_ref', 'workspace_id',
                                               'source_branch_id', 'source_generation', 'source_revision')) != identity:
                    raise ValueError('branch identity already belongs to another writer or fork source')
                return dict(previous)
            source_publication_id = ''
            if source_branch_id:
                source = conn.execute('''SELECT * FROM research_catalog_branches
                    WHERE report_id=? AND branch_id=? AND status='active' ''',
                    (report_id, source_branch_id)).fetchone()
                if source is None or (source['generation'], source['revision']) != (source_generation, source_revision):
                    raise ValueError('fork source branch version is unavailable or changed')
                source_publication_id = source['publication_id']
            elif source_generation or source_revision:
                raise ValueError('source version requires a source branch')
            now = time.time()
            conn.execute('''INSERT INTO research_catalog_branches VALUES
                (?, ?, ?, ?, ?, ?, ?, 'reserved', ?, ?, ?, ?, 0, '', '', '', ?, ?)''',
                (report_id, branch_id, report['research_id'], actor, profile_ref, workspace, title or branch_id,
                 source_branch_id, source_generation, source_revision, source_publication_id, now, now))
            return dict(conn.execute('SELECT * FROM research_catalog_branches WHERE report_id=? AND branch_id=?',
                                     (report_id, branch_id)).fetchone())

    def publish_report_branch(self, report_id: str, branch_id: str, *, actor: str, profile_ref: str,
                              expected_generation: int, expected_revision: str, generation: int,
                              revision: str, publication_id: str, storage_server_id: str) -> dict:
        """Advance only the reserved writer's exact version after byte publication."""
        if (not isinstance(generation, int) or isinstance(generation, bool) or generation < 0
                or not isinstance(revision, str) or not re.fullmatch('[0-9a-f]{64}', revision)
                or not isinstance(publication_id, str)
                or not isinstance(storage_server_id, str) or not storage_server_id.strip()):
            raise ValueError('published branch version or byte location is invalid')
        publication_source_kind(publication_id)
        report = self._report_row(report_id)
        profile_decision = self._branch_profile_decision(report, actor, profile_ref)
        with self._write(report['research_id']) as conn:
            self._branch_member(conn, report, actor, profile_ref, profile_decision)
            row = conn.execute('SELECT * FROM research_catalog_branches WHERE report_id=? AND branch_id=?',
                               (report_id, branch_id)).fetchone()
            if row is None:
                raise KeyError('report branch is not reserved')
            if (row['principal_ref'], row['profile_ref']) != (actor, profile_ref):
                raise PermissionError('only the branch writer Profile may advance it')
            if (row['generation'], row['revision'], row['publication_id'], row['storage_server_id']) == (
                    generation, revision, publication_id, storage_server_id):
                return dict(row)
            if ((row['generation'], row['revision']) != (expected_generation, expected_revision)
                    or (row['status'] == 'active' and generation <= row['generation'])):
                raise ValueError('branch version conflict; refresh before publishing')
            conn.execute('''UPDATE research_catalog_branches SET generation=?, revision=?, publication_id=?,
                storage_server_id=?, status='active', updated_at=? WHERE report_id=? AND branch_id=?''',
                (generation, revision, publication_id, storage_server_id, time.time(), report_id, branch_id))
            return dict(conn.execute('SELECT * FROM research_catalog_branches WHERE report_id=? AND branch_id=?',
                                    (report_id, branch_id)).fetchone())

    def list_report_branches(self, report_id: str, *, viewer: str) -> list[dict]:
        report = self._report_row(report_id)
        if not self._report_access(report, viewer)['can_view']:
            raise PermissionError('report branch access is not authorized')
        with connect_sqlite(self.db_path, readonly=True) as conn:
            rows = conn.execute('''SELECT * FROM research_catalog_branches WHERE report_id=?
                AND (status='active' OR principal_ref=?) ORDER BY created_at, branch_id''', (report_id, viewer)).fetchall()
        return [dict(row) for row in rows]

    def _registered_branch_choices(self, report_id: str) -> list[dict]:
        return self._registered_branch_choices_many([report_id])[report_id]

    def _registered_branch_choices_many(self, report_ids) -> dict[str, list[dict]]:
        """Read heads only for already-authorized Reports in bounded SQL batches."""
        ids = list(dict.fromkeys(report_ids))
        result = {report_id: [] for report_id in ids}
        if not ids:
            return result
        with connect_sqlite(self.db_path, readonly=True) as conn:
            for start in range(0, len(ids), 200):
                batch = ids[start:start + 200]
                placeholders = ','.join('?' for _ in batch)
                rows = conn.execute("SELECT * FROM research_catalog_branches WHERE status='active' AND report_id IN ("
                                    + placeholders + ") ORDER BY created_at, branch_id", batch).fetchall()
                for row in rows:
                    result[row['report_id']].append({**dict(row), 'branch_ref': row['branch_id'],
                        'source_kind': publication_source_kind(row['publication_id']),
                        'source_ref': row['publication_id'], 'selected': False})
        return result

    def report_branch_identity(self, publication_id: str) -> dict:
        """Return the branch one publication belongs to.

        The publication store holds the report bytes; the catalog knows which
        branch produced that publication, who wrote the branch and at which
        revision.  A publication key without a registration is reported as
        unknown instead of inventing an author.
        """
        key = str(publication_id or '').strip()
        if not key:
            return {}
        with connect_sqlite(self.db_path, readonly=True) as conn:
            row = conn.execute(
                "SELECT * FROM research_catalog_branches WHERE publication_id=?"
                " AND status='active' ORDER BY created_at LIMIT 1",
                (key,),
            ).fetchone()
        return dict(row) if row else {}
