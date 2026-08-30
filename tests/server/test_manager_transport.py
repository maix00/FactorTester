from __future__ import annotations

import datetime as dt
import ipaddress
import json
import socket
import ssl
import threading
from contextlib import contextmanager
from http.client import HTTPConnection, HTTPSConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from server.manager import runtime as manager
from server.manager.domain.federation_transport import FederationTransport


@contextmanager
def _redirect_servers():
    leaked: list[str] = []

    class Target(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            leaked.append(self.headers.get("Authorization", ""))
            self.send_response(200)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, _format, *_args):
            pass

    target = ThreadingHTTPServer(("127.0.0.1", 0), Target)

    class Redirect(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            self.send_response(302)
            self.send_header(
                "Location",
                f"http://127.0.0.1:{target.server_port}/stolen",
            )
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, _format, *_args):
            pass

    redirect = ThreadingHTTPServer(("127.0.0.1", 0), Redirect)
    threads = [
        threading.Thread(target=value.serve_forever, daemon=True)
        for value in (target, redirect)
    ]
    for thread in threads:
        thread.start()
    try:
        yield redirect.server_port, leaked
    finally:
        for value in (target, redirect):
            value.shutdown()
            value.server_close()
        for thread in threads:
            thread.join(timeout=2)


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
        tls_socket = secure.sock
        assert tls_socket is not None
        secure.request("GET", "/compliance")
        compliance = secure.getresponse()
        assert compliance.status == 200
        compliance.read()
        assert secure.sock is tls_socket
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


def test_federation_transport_never_redirects_node_credentials() -> None:
    with _redirect_servers() as (port, leaked):
        request = Request(
            f"http://127.0.0.1:{port}/peer",
            headers={"Authorization": "Bearer peer-secret"},
        )
        try:
            FederationTransport().open(request, timeout=3)
        except HTTPError as exc:
            assert exc.code == 302
        else:  # pragma: no cover - security invariant
            raise AssertionError("peer redirect was unexpectedly followed")

    assert leaked == []
