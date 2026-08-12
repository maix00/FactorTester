from __future__ import annotations

import datetime as dt
import ipaddress
import json
import socket
import ssl
import threading
from http.client import HTTPConnection, HTTPSConnection
from urllib.request import Request

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from server.manager import runtime as manager
from server.manager.domain.federation_transport import FederationTransport


def _self_signed_certificate(tmp_path):
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1"),
    ])
    now = dt.datetime.now(dt.timezone.utc)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=1))
        .not_valid_after(now + dt.timedelta(hours=1))
        .add_extension(
            x509.SubjectAlternativeName([
                x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
            ]),
            critical=False,
        )
        .sign(private_key, hashes.SHA256())
    )
    certificate_path = tmp_path / "manager.crt"
    private_key_path = tmp_path / "manager.key"
    certificate_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    private_key_path.write_bytes(private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ))
    return certificate_path, private_key_path


def test_manager_tls_listener_redirects_plain_http_on_the_same_port(
    tmp_path, monkeypatch,
) -> None:
    monkeypatch.setenv("FACTORTESTER_REQUIRE_LOGIN_FOR_UI", "1")
    monkeypatch.setenv("FACTORTESTER_REQUIRE_DEVICE_AUTH", "1")
    monkeypatch.setenv("FACTORTESTER_PUBLIC_SERVER", "1")
    state = manager.ManagerState(tmp_path, "python", server_id="public-main")
    manager.Handler.state = state
    server = manager.ThreadingHTTPServer(("127.0.0.1", 0), manager.Handler)
    certificate, private_key = _self_signed_certificate(tmp_path)
    manager.enable_server_tls(
        server,
        manager.server_tls_context(certificate, private_key),
        allow_plain_http=True,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_port
    idle = socket.create_connection(("127.0.0.1", port), timeout=3)
    try:
        plain = HTTPConnection("127.0.0.1", port, timeout=3)
        plain.request("GET", "/jobs?scope=all")
        redirected = plain.getresponse()
        assert redirected.status == 308
        assert redirected.getheader("Location") == (
            f"https://127.0.0.1:{port}/jobs?scope=all"
        )
        redirected.read()
        plain.close()

        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        secure = HTTPSConnection("127.0.0.1", port, context=context, timeout=3)
        secure.request("GET", "/")
        protected = secure.getresponse()
        assert protected.status == 303
        assert protected.getheader("Location") == "/compliance?next=/"
        protected.read()
        secure.close()
    finally:
        idle.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_federation_transport_trusts_an_explicit_private_ca(tmp_path) -> None:
    state = manager.ManagerState(tmp_path, "python", server_id="private-peer")
    manager.Handler.state = state
    server = manager.ThreadingHTTPServer(("127.0.0.1", 0), manager.Handler)
    certificate, private_key = _self_signed_certificate(tmp_path)
    manager.enable_server_tls(
        server,
        manager.server_tls_context(certificate, private_key),
        allow_plain_http=True,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        request = Request(
            f"https://127.0.0.1:{server.server_port}/api/server/network-info",
        )
        with FederationTransport(ca_file=certificate).open(
            request,
            timeout=3,
        ) as response:
            payload = json.loads(response.read())
        assert payload["server_id"] == "private-peer"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
