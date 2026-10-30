import base64
import hashlib
import json
import pytest
from scripts.migrations.keycloak_credentials import legacy_password_credential, import_password_credential


def test_native_pbkdf2_encoding_preserves_existing_password():
    salt = 'legacy-random-salt'
    digest = hashlib.pbkdf2_hmac('sha256', b'test-only', salt.encode(), 200000)
    c = legacy_password_credential(salt, digest.hex())
    data, secret = json.loads(c['credentialData']), json.loads(c['secretData'])
    assert data == {'algorithm': 'pbkdf2-sha256', 'hashIterations': 200000}
    assert hashlib.pbkdf2_hmac('sha256', b'test-only', base64.b64decode(secret['salt']), data['hashIterations']) == base64.b64decode(secret['value'])


@pytest.mark.parametrize('salt,digest', [('', 'a'*64), ('salt', 'bad'), ('salt', 'g'*64)])
def test_reject_invalid_legacy_material(salt, digest):
    with pytest.raises(ValueError): legacy_password_credential(salt, digest)


def test_does_not_overwrite_destination_password():
    class Adapter:
        def _get(self, path):
            return [{'type': 'password'}] if path.endswith('/credentials') else {'attributes': {'tr_identity_id': ['stable']}}
        def _put(self, *args): raise AssertionError('must not overwrite')
    assert not import_password_credential(Adapter(), subject='id', identity_id='stable', salt='salt', digest='a'*64)
    with pytest.raises(ValueError):
        import_password_credential(Adapter(), subject='id', identity_id='other', salt='salt', digest='a'*64)
