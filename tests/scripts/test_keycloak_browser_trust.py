import base64
import hashlib
import os
from datetime import datetime, timedelta, timezone

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from scripts.test.keycloak_browser_oidc import browser_certificate_trust


def test_explicit_ca_pins_only_its_key_and_restores_driver_environment(tmp_path, monkeypatch):
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'isolated-test')])
    now = datetime.now(timezone.utc)
    certificate = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
        .serial_number(x509.random_serial_number()).not_valid_before(now).not_valid_after(now+timedelta(days=1))
        .sign(key, hashes.SHA256()))
    path = tmp_path/'public.pem'; path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    monkeypatch.setenv('KEYCLOAK_BROWSER_CA_FILE', str(path))
    monkeypatch.setenv('NODE_EXTRA_CA_CERTS', 'previous-ca')
    expected = base64.b64encode(hashlib.sha256(key.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)).digest()).decode()
    with browser_certificate_trust() as options:
        assert options == {'args': ['--ignore-certificate-errors-spki-list='+expected]}
        assert os.environ['NODE_EXTRA_CA_CERTS'] == str(path)
    assert os.environ['NODE_EXTRA_CA_CERTS'] == 'previous-ca'
    path.write_text('-----BEGIN PRIVATE KEY-----')
    with pytest.raises(ValueError, match='public certificates only'):
        with browser_certificate_trust(): pass
    assert os.environ['NODE_EXTRA_CA_CERTS'] == 'previous-ca'


def test_no_explicit_ca_leaves_normal_tls_unchanged(monkeypatch):
    monkeypatch.delenv('KEYCLOAK_BROWSER_CA_FILE', raising=False)
    monkeypatch.delenv('NODE_EXTRA_CA_CERTS', raising=False)
    with browser_certificate_trust() as options:
        assert options == {} and 'NODE_EXTRA_CA_CERTS' not in os.environ
