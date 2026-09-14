"""Strict three-way merge of independent research metadata relationships."""
from __future__ import annotations

import copy
import json

RELATION_KEYS = {
    'members': ('research_id', 'principal_ref', 'profile_ref'),
    'workspaces': ('workspace_id',), 'reports': ('report_id',),
    'branches': ('report_id', 'branch_id'), 'evidence_links': ('link_ref',),
}
SCHEMA = '''CREATE TABLE IF NOT EXISTS account_domain_research_bases (
    principal TEXT NOT NULL, entity_id TEXT NOT NULL, revision INTEGER NOT NULL,
    payload_json TEXT NOT NULL, deleted INTEGER NOT NULL,
    PRIMARY KEY(principal, entity_id));'''


def remember_base(conn, *, principal, entity_type, entity_id, revision, payload, deleted=False):
    if entity_type != 'research_catalog' or revision is None:
        return
    conn.execute('''INSERT INTO account_domain_research_bases VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(principal,entity_id) DO UPDATE SET revision=excluded.revision,
        payload_json=excluded.payload_json, deleted=excluded.deleted
        WHERE excluded.revision>=account_domain_research_bases.revision''',
        (principal, entity_id, revision, json.dumps(payload, sort_keys=True), int(deleted)))


def merge_research(base: dict, local: dict, remote: dict) -> dict | None:
    """Never infer missing rows as additions without a common known base."""
    if any(x.get('schema_version') != 2 for x in (base, local, remote)):
        return None
    if set(base) != set(local) or set(base) != set(remote):
        return None
    missing = object()
    def choose(b, l, r):
        if l == r or r == b:
            return l
        if l == b:
            return r
        if isinstance(l, dict) and isinstance(r, dict) and 'updated_at' in l and 'updated_at' in r:
            if {k: v for k, v in l.items() if k != 'updated_at'} == {k: v for k, v in r.items() if k != 'updated_at'}:
                return {**l, 'updated_at': max(l['updated_at'], r['updated_at'])}
        raise ValueError('overlapping research edit')
    result = {}
    try:
        for name in base:
            if name not in RELATION_KEYS:
                result[name] = choose(base[name], local[name], remote[name])
                continue
            fields = RELATION_KEYS[name]
            def indexed(rows):
                if not isinstance(rows, list):
                    raise ValueError('invalid relationships')
                pairs = [(tuple(row[k] for k in fields), row) for row in rows]
                values = dict(pairs)
                if len(values) != len(pairs):
                    raise ValueError('duplicate relationship')
                return values
            b, l, r = (indexed(x[name]) for x in (base, local, remote))
            rows = []
            for key in sorted(b.keys() | l.keys() | r.keys()):
                row = choose(b.get(key, missing), l.get(key, missing), r.get(key, missing))
                if row is not missing:
                    rows.append(row)
            result[name] = rows
        research = result['research']
        if research['owner_ref'] != base['research']['owner_ref']:
            return None
        members = {(x['principal_ref'], x['profile_ref']): x for x in result['members']}
        workspaces = {x['workspace_id']: x for x in result['workspaces']}
        active_keys = [(x['principal_ref'], x['profile_ref']) for x in workspaces.values() if x['status'] == 'active']
        if len(set(active_keys)) != len(active_keys):
            return None
        reports = {x['report_id']: x for x in result['reports']}
        old_branches = {(x['report_id'], x['branch_id']): x for x in base['branches']}
        for branch in result['branches']:
            old = old_branches.get((branch['report_id'], branch['branch_id']))
            if old == branch:
                continue
            if old is not None and any(old[k] != branch[k] for k in (
                'research_id', 'principal_ref', 'profile_ref', 'workspace_id',
                'source_branch_id', 'source_generation', 'source_revision', 'source_publication_id')):
                return None
            member = members.get((branch['principal_ref'], branch['profile_ref']), {})
            workspace = workspaces.get(branch['workspace_id'], {})
            if (research['status'] != 'active' or reports.get(branch['report_id'], {}).get('status') != 'active'
                or member.get('status') != 'active' or member.get('role') not in {'owner', 'editor', 'contributor'}
                or workspace.get('status') != 'active'
                or (workspace.get('principal_ref'), workspace.get('profile_ref')) != (branch['principal_ref'], branch['profile_ref'])):
                return None
        return copy.deepcopy(result)
    except (KeyError, TypeError, ValueError):
        return None
