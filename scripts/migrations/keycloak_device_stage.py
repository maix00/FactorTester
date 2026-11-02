"""Stage reviewed device grants, without switching the authorization source.

Callers must independently back up the control database and Keycloak, quiesce
device writes, and supply a fresh scoped snapshot and Keycloak directory. An
interrupted journal is evidence for manual reconciliation, never a retry token.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Callable

from scripts.migrations.keycloak_device_inventory import plan


def _digest(value: object) -> str:
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False,
                      separators=(',', ':')).encode()
    return hashlib.sha256(data).hexdigest()


def review(snapshot: dict, directory: dict, *, manager_id: str, issuer: str) -> dict:
    """Bind the exact device inventory, identity subjects and target issuer."""
    from urllib.parse import urlsplit
    issuer = str(issuer or '').strip().rstrip('/')
    url = urlsplit(issuer)
    if (url.scheme not in {'http', 'https'} or not url.hostname or url.username is not None
            or url.password is not None or url.query or url.fragment):
        raise ValueError('an exact Keycloak issuer is required')
    inventory = plan(snapshot, directory, manager_id=manager_id)
    payload = {'schema': 'tr-device-stage-v1', 'manager_id': manager_id,
               'issuer': issuer, 'inventory_sha256': inventory['summary']['sha256'],
               'statuses': inventory['summary']['statuses']}
    return {**payload, 'sha256': _digest(payload)}


class KeycloakDeviceStageBackend:
    """Use the existing Protection API and admin policy evaluator."""

    def __init__(self, *, settings: dict, evaluator, issuer: str) -> None:
        from server.identity.keycloak_authorization import protection_token
        if str(settings.get('issuer') or '').rstrip('/') != issuer.rstrip('/'):
            raise ValueError('Keycloak backend belongs to another issuer')
        self.settings, self.evaluator = dict(settings), evaluator
        self._check_settings()
        self.token = protection_token(settings)

    def _check_settings(self) -> None:
        from server.identity.user_session import oidc_settings
        current = oidc_settings()
        for key in ('issuer', 'base_url', 'backchannel_base_url', 'realm',
                    'authz_client_id', 'authz_client_secret'):
            if current.get(key) != self.settings.get(key):
                raise ValueError('Keycloak backend configuration changed during staging')

    def resource_absent(self, ref: str) -> bool:
        from urllib.parse import urlencode
        from server.identity.keycloak_authorization import (
            AuthorizationUnavailable, _protection_request, keycloak_resource_name,
        )
        self._check_settings()
        name = keycloak_resource_name('device', ref)
        query = urlencode({'name': name, 'first': 0, 'max': 10, 'deep': 'true'})
        _, result, _ = _protection_request(self.settings, self.token, 'GET', 'resource_set?' + query)
        rows = result if isinstance(result, list) else result.get('resources') if isinstance(result, dict) else None
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise AuthorizationUnavailable('invalid Keycloak resource search')
        matches = [row for row in rows if row.get('name') == name]
        if len(matches) > 1:
            raise AuthorizationUnavailable('duplicate Keycloak device resources')
        return not matches

    def create(self, ref: str, subject: str, intent: str) -> str:
        from server.identity.keycloak_authorization import ensure_keycloak_resource
        self._check_settings()
        return ensure_keycloak_resource(resource_type='device', resource_ref=ref, owner_subject=subject,
                                        owner_scopes=('use',), creation_intent=intent, create_only=True)

    def verify(self, identity: str, ref: str) -> bool:
        self._check_settings()
        return self.evaluator.evaluate(identity, candidates=[('device', ref, ('use',))]).get(
            ('device', ref, 'use')) is True


def stage(*, reviewed: dict, backup_snapshot: dict, live_snapshot: Callable[[], dict],
          backup_directory: dict, live_directory: Callable[[], dict], manager_id: str,
          issuer: str, journal: Path, resource_absent: Callable[[str], bool],
          create: Callable[[str, str, str], str], verify: Callable[[str, str], bool]) -> dict:
    """Create only absent, reviewed grants; stop on ambiguity or partial failure.

    ``verify`` must perform an independent fresh Keycloak policy decision for
    the exact stable identity and resource. The result is a staging receipt,
    not proof that all legacy permissions or cross-user denials are equivalent.
    """
    expected = review(backup_snapshot, backup_directory, manager_id=manager_id, issuer=issuer)
    if reviewed != expected:
        raise ValueError('reviewed device plan does not match backup')
    if set(expected['statuses']) - {'grant', 'denied', 'outside_manager'}:
        raise ValueError('unresolved device entries block staging')

    def refresh() -> tuple[dict, dict, dict]:
        snapshot, directory = live_snapshot(), live_directory()
        if review(snapshot, directory, manager_id=manager_id, issuer=issuer) != expected:
            raise ValueError('device inventory or Keycloak identity changed after review')
        return snapshot, directory, plan(snapshot, directory, manager_id=manager_id)

    _snapshot, directory, inventory = refresh()
    grants = [item for item in inventory['entries'] if item['status'] == 'grant']
    if len(grants) > 10000:
        raise ValueError('device staging exceeds its grant budget')
    for item in grants:
        if resource_absent(item['resource_ref']) is not True:
            raise ValueError('existing device resource requires manual authorization review')

    path = Path(journal).expanduser()
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, 'O_NOFOLLOW'):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as output:
        def record(value: dict) -> None:
            output.write(json.dumps(value, sort_keys=True, separators=(',', ':')) + '\n')
            output.flush()
            os.fsync(output.fileno())

        record({'event': 'begin', 'plan_sha256': expected['sha256'], 'grants': len(grants)})
        for item in grants:
            # Recheck the full frozen evidence before every mutation. Device
            # writes must also be quiesced; this check alone is not a lock.
            _snapshot, directory, _inventory = refresh()
            accounts = {row['username']: row for row in directory['accounts']}
            owner = accounts[item['username']]
            ref = item['resource_ref']
            ref_hash = _digest(ref)
            intent = _digest({'plan': expected['sha256'], 'source': item['source_sha256'],
                              'identity': item['identity_sha256'], 'ref': ref_hash})
            record({'event': 'intent', 'ref_sha256': ref_hash, 'intent': intent})
            try:
                # The implementation must use Keycloak's create-only path;
                # it must never repair an existing or revoked grant.
                create(ref, owner['keycloak_subject'], intent)
                if verify(owner['tr_identity_id'], ref) is not True:
                    raise ValueError('created device grant did not verify')
            except Exception:
                record({'event': 'unresolved', 'ref_sha256': ref_hash, 'intent': intent})
                raise
            record({'event': 'verified', 'ref_sha256': ref_hash, 'intent': intent})
        record({'event': 'complete', 'plan_sha256': expected['sha256'], 'grants': len(grants)})
    return {'staged': len(grants), 'plan_sha256': expected['sha256'], 'cutover_ready': False}
