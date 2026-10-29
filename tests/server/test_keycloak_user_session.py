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
