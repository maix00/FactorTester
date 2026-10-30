import time
from server.identity.user_session import UserSessionVerifier


class Client:
    def __init__(self):
        self.calls = 0
        self.claims = dict(active=True, iss='https://id/realms/tr', aud=['manager'],
                           exp=time.time()+60, sub='uid', preferred_username='alice',
                           resource_access={'other': {'roles': ['admin_console:manage']},
                                            'manager': {'roles': ['agent_assistant:use']}})

    def introspect(self, token):
        self.calls += 1
        return self.claims


def test_verified_client_roles_and_cache():
    client = Client()
    verifier = UserSessionVerifier(client, issuer='https://id/realms/tr', audience='manager')
    result = verifier.session('token')
    assert result['keycloak_roles'] == ('agent_assistant:use',)
    assert result['admin_capabilities'] == []
    assert verifier.session('token') == result
    assert client.calls == 1


def test_oidc_settings_keep_public_issuer_separate_from_private_backchannel(monkeypatch, tmp_path):
    import server.identity.user_session as user_session

    secret_file = tmp_path / "manager-client"
    secret_file.write_text("manager-secret")
    authz_secret_file = tmp_path / "authz-client"
    authz_secret_file.write_text("authz-secret")
    monkeypatch.setenv(
        "TRADERESEARCH_USER_OIDC_ISSUER",
        "https://101.133.144.27/realms/traderesearch",
    )
    monkeypatch.setenv("TRADERESEARCH_USER_OIDC_CLIENT_ID", "manager-web")
    monkeypatch.setenv("TRADERESEARCH_USER_OIDC_AUDIENCE", "manager-web")
    monkeypatch.setenv("TRADERESEARCH_USER_OIDC_ROLES_CLIENT_ID", "manager-api")
    monkeypatch.setenv("TRADERESEARCH_USER_OIDC_CLIENT_SECRET_FILE", str(secret_file))
    monkeypatch.setenv(
        "TRADERESEARCH_USER_OIDC_BACKCHANNEL_URL", "http://keycloak:8080",
    )
    monkeypatch.setenv("TRADERESEARCH_KEYCLOAK_AUTHZ_CLIENT_ID", "manager-authz")
    monkeypatch.setenv(
        "TRADERESEARCH_KEYCLOAK_AUTHZ_CLIENT_SECRET_FILE", str(authz_secret_file),
    )

    settings = user_session.oidc_settings()
    assert settings["issuer"] == "https://101.133.144.27/realms/traderesearch"
    assert settings["base_url"] == "https://101.133.144.27"
    assert settings["backchannel_base_url"] == "http://keycloak:8080"
    assert settings["authz_client_secret"] == "authz-secret"


def test_http_keycloak_backchannel_rejects_public_host():
    import pytest
    import server.identity.user_session as user_session

    with pytest.raises(ValueError, match="private endpoint"):
        user_session._backchannel_base_url(
            "https://id.example", "http://id.example",
        )


def test_keycloak_backchannel_preserves_the_same_origin_context_path():
    import server.identity.user_session as user_session

    assert user_session._backchannel_base_url(
        "https://101.133.144.27:7998/identity",
        "http://keycloak:8080/identity",
    ) == "http://keycloak:8080/identity"


def test_keycloak_backchannel_rejects_a_different_context_path():
    import pytest
    import server.identity.user_session as user_session

    with pytest.raises(ValueError, match="invalid Keycloak backchannel"):
        user_session._backchannel_base_url(
            "https://101.133.144.27:7998/identity",
            "http://keycloak:8080/",
        )


def test_roles_can_come_from_the_manager_authorization_client():
    client = Client()
    client.claims['resource_access']['tr-manager-api'] = {
        'roles': ['admin_console:manage'],
    }
    verifier = UserSessionVerifier(
        client, issuer='https://id/realms/tr', audience='manager',
        roles_client_id='tr-manager-api',
    )
    assert verifier.session('token')['keycloak_roles'] == ('admin_console:manage',)


def test_organization_admin_group_receives_scoped_federation_capability():
    from server.identity.realm_groups import organization_admin_group_path

    client = Client()
    client.claims['resource_access']['manager']['roles'] = []
    client.claims['groups'] = [organization_admin_group_path('org-a')]
    verifier = UserSessionVerifier(
        client, issuer='https://id/realms/tr', audience='manager',
    )

    session = verifier.session('organization-admin')
    assert session['role'] == 'org_admin'
    assert session['admin_capabilities'] == [
        'identity:manage', 'federation:manage',
    ]
    assert 'admin_console:manage' not in session['admin_capabilities']


def test_reject_wrong_audience_and_revoked_token():
    client = Client()
    verifier = UserSessionVerifier(client, issuer='https://id/realms/tr', audience='manager')
    client.claims['aud'] = ['other']
    assert verifier.session('wrong') is None
    client.claims['aud'] = ['manager']
    client.claims['active'] = False
    assert verifier.session('revoked') is None


def test_keycloak_permission_does_not_use_local_super_admin(monkeypatch):
    from server.permissions.agent_assistant import can_use_agent_assistant
    monkeypatch.setenv('TRADERESEARCH_AUTH_MODE', 'keycloak')
    assert not can_use_agent_assistant('alice', 'super_admin')
    assert can_use_agent_assistant('alice', 'user', ('agent_assistant:use',))


def test_manager_keycloak_mode_uses_verified_session(monkeypatch):
    from server.manager.state.sessions import SessionStateMixin
    import server.identity.user_session as user_session
    monkeypatch.setenv('TRADERESEARCH_AUTH_MODE', 'keycloak')
    monkeypatch.setattr(user_session, 'keycloak_session', lambda token: {'username': 'alice'} if token == 'trusted' else None)
    state = SessionStateMixin()
    assert state.session('trusted') == {'username': 'alice'}
    assert state.session('local-super-admin') is None


def test_manager_dual_mode_prefers_a_verified_keycloak_session(monkeypatch):
    from server.manager.state.sessions import SessionStateMixin
    import server.identity.user_session as user_session
    monkeypatch.setenv('TRADERESEARCH_AUTH_MODE', 'dual')
    monkeypatch.setattr(user_session, 'keycloak_session', lambda token: {
        'username': 'alice', 'keycloak_roles': ('admin_console:manage',),
    } if token == 'kc-token' else None)
    state = SessionStateMixin()
    assert state.session('kc-token')['keycloak_roles'] == ('admin_console:manage',)
    assert state.session('legacy-token') is None


def test_dual_mode_never_falls_back_to_a_preexisting_local_session(monkeypatch):
    from server.manager.state.sessions import SessionStateMixin
    import server.identity.user_session as user_session
    monkeypatch.setenv('TRADERESEARCH_AUTH_MODE', 'dual')
    monkeypatch.setattr(user_session, 'keycloak_session', lambda _token: None)
    state = SessionStateMixin()
    token = 'local-super-admin'
    state._sessions = {
        state._token_hash(token): (
            'alice', 'super_admin', time.time() + 60, 'password', '', '',
            time.time(), time.time(),
        ),
    }
    assert state.session(token) is None


def test_keycloak_roles_override_stale_local_admin_flags(monkeypatch):
    from flask import Flask, g
    from tools.data.account_manage import is_super_admin_account, get_account

    monkeypatch.setenv('TRADERESEARCH_AUTH_MODE', 'keycloak')
    app = Flask(__name__)
    with app.test_request_context('/'):
        g.keycloak_user_session = {
            'username': 'alice', 'keycloak_roles': ('admin_console:manage',),
        }
        stale_local_admin = {'username': 'bob', 'role': 'super_admin', 'is_admin': True}
        assert is_super_admin_account(get_account('alice'))
        assert not is_super_admin_account(stale_local_admin)
    with app.test_request_context('/'):
        g.keycloak_user_session = {'username': 'alice', 'keycloak_roles': ()}
        projected = get_account('alice')
        assert projected['role'] == 'user'
        assert projected['is_admin'] is False
        assert not is_super_admin_account(projected)


def test_keycloak_scoped_admin_roles_do_not_use_legacy_hierarchy(monkeypatch):
    from flask import Flask, g
    from tools.data.account_manage import (
        get_account, is_any_admin_account, is_org_admin_account,
    )

    monkeypatch.setenv('TRADERESEARCH_AUTH_MODE', 'keycloak')
    app = Flask(__name__)
    with app.test_request_context('/'):
        g.keycloak_user_session = {
            'username': 'manager', 'keycloak_roles': (),
            'keycloak_groups': ('/traderesearch/admin-scopes/organizations/org-a/organization-admins',),
        }
        manager = get_account('manager')
        assert manager['role'] == 'org_admin'
        assert is_org_admin_account(manager)
        assert not is_any_admin_account(manager)
