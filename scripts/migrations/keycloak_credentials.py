"""One-time import of existing PBKDF2 credentials into Keycloak's native provider.

Never used for runtime login or identity federation. Source material must come
from a protected pre-cutover backup; neither plaintext nor hash is logged.
"""
from __future__ import annotations

import base64
import json
import re


def legacy_password_credential(salt: str, digest: str) -> dict:
    if not isinstance(salt, str) or not 1 <= len(salt) <= 1024:
        raise ValueError('invalid legacy salt')
    if not isinstance(digest, str) or not re.fullmatch(r'[0-9a-fA-F]{64}', digest):
        raise ValueError('invalid legacy PBKDF2-SHA256 digest')
    return {
        'type': 'password', 'temporary': False,
        'credentialData': json.dumps({'algorithm': 'pbkdf2-sha256', 'hashIterations': 200000}),
        'secretData': json.dumps({
            'salt': base64.b64encode(salt.encode('utf-8')).decode('ascii'),
            'value': base64.b64encode(bytes.fromhex(digest)).decode('ascii'),
        }),
    }


def import_password_credential(adapter, *, subject: str, identity_id: str,
                               salt: str, digest: str) -> bool:
    """Import only into an exact migrated identity with no existing password."""
    from urllib.parse import quote
    path = 'users/' + quote(subject, safe='')
    user = adapter._get(path)
    if not identity_id or user.get('attributes', {}).get('tr_identity_id') != [identity_id]:
        raise ValueError('credential destination identity mismatch')
    existing = adapter._get(path + '/credentials')
    if any(c.get('type') == 'password' for c in existing):
        return False  # Never replace a credential changed at the destination.
    user['credentials'] = [legacy_password_credential(salt, digest)]
    user['requiredActions'] = [v for v in user.get('requiredActions', []) if v != 'UPDATE_PASSWORD']
    adapter._put(path, user)
    if not any(c.get('type') == 'password' for c in adapter._get(path + '/credentials')):
        raise RuntimeError('Keycloak credential import was not confirmed')
    return True
