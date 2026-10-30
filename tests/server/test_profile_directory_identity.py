from flask import Flask, g

from server.identity.request_context import bind_verified_identity, identity_request
from server.manager.services.profile_directory import _verified_request_username


def test_profile_directory_reads_verified_manager_request_identity_only():
    assert _verified_request_username() == ""
    with identity_request():
        bind_verified_identity("verified-token", {"username": "manager-user", "keycloak_subject": "subject",
                                                 "keycloak_issuer": "https://issuer.test/realm"})
        assert _verified_request_username() == "manager-user"
    assert _verified_request_username() == ""


def test_profile_directory_never_trusts_flask_session_without_verified_token():
    with Flask(__name__).test_request_context():
        g.keycloak_user_session = {"username": "flask-user", "keycloak_subject": "subject",
                                   "keycloak_issuer": "https://issuer.test/realm"}
        assert _verified_request_username() == ""
        g.keycloak_access_token = "verified-token"
        assert _verified_request_username() == "flask-user"
