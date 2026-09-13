"""Read-only dependency planning for family deletion and ownership changes."""
from __future__ import annotations

import json

from tools.factors.factor_set_identity import require_frozen_factor_set


def _owner(value: str) -> str:
    value = str(value or '').removeprefix('principal:')
    return 'public' if value in {'public', '__public__', '__public_jobs__'} else value


def factor_matches_family(value: dict, *, owner_ref: str, family_alias: str) -> bool:
    """A matching alias under another owner is a different family."""
    identity = value.get('identity') or {}
    return (_owner(value.get('owner_ref')) == _owner(owner_ref)
            and identity.get('family_alias') == family_alias)


def factor_set_impacts(conn, *, owner_ref: str, family_alias: str) -> list[dict]:
    """Overlay received registrations/tombstones before examining frozen members.

    No source is evaluated, no network is contacted and historical job artifacts
    are never included. The caller must establish synchronization completeness.
    """
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    sets = {}
    if 'account_factor_sets' in tables:
        for row in conn.execute('SELECT username,target_ref,payload_json FROM account_factor_sets'):
            sets[(row['username'], row['target_ref'])] = json.loads(row['payload_json'])
    if 'account_domain_entities' in tables:
        for row in conn.execute("SELECT principal,entity_id,payload_json,deleted FROM account_domain_entities WHERE entity_type='factor_set'"):
            key = (row['principal'], row['entity_id'])
            if row['deleted']:
                sets.pop(key, None)
            else:
                sets[key] = json.loads(row['payload_json'])
    result = []
    for (principal, ref), value in sorted(sets.items()):
        if not value.get('registration_active', True):
            continue
        frozen = require_frozen_factor_set(value)
        members = frozen['identity']['members']
        affected = [member['ref'] for member in members if factor_matches_family(
            member, owner_ref=owner_ref, family_alias=family_alias)]
        if affected:
            result.append({'username': principal, 'ref': ref, 'alias': frozen['alias'],
                           'member_count': len(members), 'affected_factor_refs': affected})
    return result

def apply_set_family_change(conn, mirror, *, owner_ref, family_alias, replacements=None, reason='family_deleted'):
    """Version affected active sets within the caller's transaction."""
    import time
    from tools.data.sqlite.account_manager.factor_set import _visible_sets, _persist, _events, _set_head, ensure_factor_set_schema
    from tools.factors.factor_set_identity import freeze_factor_set_identity
    ensure_factor_set_schema(conn)
    impacts = factor_set_impacts(conn, owner_ref=owner_ref, family_alias=family_alias)
    replacements = replacements or {}
    for impact in impacts:
        principal = impact['username']
        value = _visible_sets(conn, principal)[impact['ref']]
        old_members = value['identity']['members']
        affected = set(impact['affected_factor_refs'])
        mapping = replacements.get(principal, {})
        members = [mapping.get(member['ref'], member) for member in old_members
                   if member['ref'] not in affected or member['ref'] in mapping]
        members = list({member['ref']: member for member in members}.values())
        _persist(conn, mirror, principal, {**value, 'registration_active': False, 'updated_at': time.time()})
        if members:
            frozen = freeze_factor_set_identity(owner_ref=value['owner_ref'],
                set_id=value['identity']['set_id'], alias=value['alias'], members=members)
            updated = {**value, **frozen, 'registration_active': True, 'updated_at': time.time()}
            _persist(conn, mirror, principal, updated)
        else:
            updated = value
        _set_head(conn, mirror, principal, updated, active=bool(members))
        _events(conn, mirror, principal, updated, old_members, members, reason)
    return impacts
