"""Read-only allow/deny parity for reviewed device grants on one Manager.

Run with device and Keycloak policy writes quiesced. This verifies the scoped
device inventory, not browser login, device proof-of-possession or Research.
It never creates resources or repairs/regrants revoked permissions.
"""
from __future__ import annotations

from typing import Callable

from scripts.migrations.keycloak_device_inventory import plan
from scripts.migrations.keycloak_device_stage import review
from server.identity.keycloak_authorization import AuthorizationUnavailable
from server.identity.keycloak_migration_directory import verified_migration_subjects


def verify_device_policy_parity(*, reviewed: dict, live_snapshot: Callable[[], dict],
                               live_directory: Callable[[], dict], manager_id: str,
                               issuer: str, evaluator, resource_absent: Callable[[str], bool]) -> dict:
    """Compare owners and every active human, including disabled-device denials.

    Missing resources count as denial only for reviewed denied entries. Mirror
    records from another Manager are counted separately and never authorized
    under this Manager. Input/subject/presence changes invalidate the receipt.
    Keycloak evaluation already batches requests; memory is O(device count),
    not the cross-product of devices and users.
    """
    def evidence():
        snapshot, directory = live_snapshot(), live_directory()
        if review(snapshot, directory, manager_id=manager_id, issuer=issuer) != reviewed:
            raise AuthorizationUnavailable('device evidence changed after review')
        inventory = plan(snapshot, directory, manager_id=manager_id)
        if set(inventory['summary']['statuses']) - {'grant', 'denied', 'outside_manager'}:
            raise AuthorizationUnavailable('unresolved device entries block parity')
        mapping = {row['username']: row['tr_identity_id'] for row in directory['accounts']}
        subjects = verified_migration_subjects(evaluator.adapter, mapping)
        if any(subjects.get(row['tr_identity_id']) != row['keycloak_subject']
               for row in directory['accounts']):
            raise AuthorizationUnavailable('device owner subject differs from reviewed directory')
        return inventory, mapping, subjects

    inventory, mapping, subjects = evidence()
    entries = [row for row in inventory['entries'] if row['status'] != 'outside_manager']
    if len(entries) > 10_000 or len(entries) * len(subjects) > 1_000_000:
        raise AuthorizationUnavailable('device parity exceeds its decision budget')
    presence = {}
    expected_owner = {}
    for row in entries:
        ref = row['resource_ref']
        absent = resource_absent(ref)
        if type(absent) is not bool:
            raise AuthorizationUnavailable('device resource presence is invalid')
        if row['status'] == 'grant' and absent:
            raise AuthorizationUnavailable('reviewed device grant is missing in Keycloak')
        presence[ref] = not absent
        expected_owner[ref] = mapping[row['username']] if row['status'] == 'grant' else None
    candidates = [('device', ref, ('use',)) for ref, exists in presence.items() if exists]
    keys = {('device', ref, 'use') for _kind, ref, _scopes in candidates}
    allows = 0
    for identity in subjects:
        decisions = evaluator.evaluate(identity, candidates=candidates)
        if set(decisions) != keys or any(type(value) is not bool for value in decisions.values()):
            raise AuthorizationUnavailable('device authorization decision coverage differs')
        for (_kind, ref, _scope), actual in decisions.items():
            expected = expected_owner[ref] == identity
            if actual != expected:
                raise AuthorizationUnavailable('device authorization decisions differ')
            allows += int(actual)
    after_inventory, after_mapping, after_subjects = evidence()
    if (after_inventory != inventory or after_mapping != mapping or after_subjects != subjects
            or any(resource_absent(ref) is not (not exists) for ref, exists in presence.items())):
        raise AuthorizationUnavailable('device evidence changed during parity')
    total = len(entries) * len(subjects)
    return {'schema': 'tr-device-parity-v1', 'plan_sha256': reviewed['sha256'],
            'manager_id': manager_id, 'users': len(subjects), 'devices': len(entries),
            'outside_manager': inventory['summary']['statuses'].get('outside_manager', 0),
            'decisions': total, 'allowed': allows, 'denied': total - allows,
            'missing_denied_resources': sum(not exists for exists in presence.values()),
            'cutover_ready': False}
