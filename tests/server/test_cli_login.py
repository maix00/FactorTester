import pytest

from server.identity.cli_login import (
    DEFAULT_CLIENT_ID,
    REQUIRED_DEFAULT_CLIENT_SCOPES,
    client_definition,
    provision,
)

SCOPE_IDS = {'basic': 'scope-basic', 'roles': 'scope-roles', 'profile': 'scope-profile'}
_GROUP_MAPPER = {
    'name': 'traderesearch-realm-group-paths',
    'protocol': 'openid-connect',
    'protocolMapper': 'oidc-group-membership-mapper',
    'config': {
        'claim.name': 'groups', 'full.path': 'true',
        'id.token.claim': 'true', 'access.token.claim': 'true',
        'userinfo.token.claim': 'true', 'introspection.token.claim': 'true',
    },
}


class FakeAdapter:
    def __init__(self, *, exists=True, default_scopes=('roles', 'profile'), group_mapper=True):
        self.exists = exists
        self.default_scopes = {name: SCOPE_IDS[name] for name in default_scopes}
        self.mappers = list(client_definition()['protocolMappers'])
        if group_mapper:
            self.mappers.append(dict(_GROUP_MAPPER))
        self.calls = []
        self.posted = []

    def _get(self, path):
        if path.startswith('clients?'):
            return [{'clientId': DEFAULT_CLIENT_ID, 'id': 'cli-uuid'}] if self.exists else []
        if path == 'clients/cli-uuid':
            return {
                **client_definition(),
                'id': 'cli-uuid',
                'protocolMappers': list(self.mappers),
            }
        if path == 'client-scopes':
            return [{'name': name, 'id': scope} for name, scope in SCOPE_IDS.items()]
        if path == 'clients/cli-uuid/default-client-scopes':
            return [{'name': name} for name in self.default_scopes]
        if path == 'clients/cli-uuid/protocol-mappers/models':
            return list(self.mappers)
        raise AssertionError('unexpected GET ' + path)

    def _post(self, path, payload):
        self.posted.append((path, payload))
        if path == 'clients/cli-uuid/protocol-mappers/models':
            self.mappers.append(dict(payload))
        else:
            self.exists = True
        return 201, ''

    def _put(self, path, payload):
        self.calls.append((path, payload))
        prefix = 'clients/cli-uuid/default-client-scopes/'
        if path.startswith(prefix):
            scope_id = path[len(prefix):]
            name = {value: key for key, value in SCOPE_IDS.items()}[scope_id]
            self.default_scopes[name] = scope_id
            return 204
        raise AssertionError('unexpected PUT ' + path)


def test_cli_client_requests_the_scope_that_carries_the_subject():
    definition = client_definition()
    assert set(definition['defaultClientScopes']) == set(REQUIRED_DEFAULT_CLIENT_SCOPES)
    assert 'basic' in definition['defaultClientScopes']
    assert definition['attributes']['oauth2.device.authorization.grant.enabled'] == 'true'


def test_dry_run_reports_a_client_that_cannot_carry_sub():
    adapter = FakeAdapter(default_scopes=('roles', 'profile'))

    result = provision(adapter)

    assert result['status'] == 'update'
    assert result['missing_default_scopes'] == ['basic']
    assert adapter.calls == [], 'dry-run must not change Keycloak'


def test_apply_adds_missing_default_scope_and_verifies():
    adapter = FakeAdapter(default_scopes=('roles', 'profile'))

    result = provision(adapter, apply=True)

    assert result['status'] == 'updated'
    assert adapter.calls == [
        ('clients/cli-uuid/default-client-scopes/scope-basic', {}),
    ]
    assert set(adapter.default_scopes) == set(REQUIRED_DEFAULT_CLIENT_SCOPES)


def test_complete_client_is_verified_without_writes():
    adapter = FakeAdapter(default_scopes=REQUIRED_DEFAULT_CLIENT_SCOPES,
                          group_mapper=True)

    result = provision(adapter)

    assert result['status'] == 'verified'
    assert adapter.calls == []


def test_dry_run_reports_missing_group_claim_mapper():
    adapter = FakeAdapter(default_scopes=REQUIRED_DEFAULT_CLIENT_SCOPES,
                          group_mapper=False)

    result = provision(adapter)

    assert result['status'] == 'update'
    assert result['missing_protocol_mappers'] == ['traderesearch-realm-group-paths']


def test_apply_adds_missing_group_claim_mapper():
    adapter = FakeAdapter(default_scopes=REQUIRED_DEFAULT_CLIENT_SCOPES,
                          group_mapper=False)

    result = provision(adapter, apply=True)

    assert result['status'] == 'updated'
    assert adapter.posted == [('clients/cli-uuid/protocol-mappers/models', _GROUP_MAPPER)]


def test_missing_realm_scope_blocks_provisioning():
    adapter = FakeAdapter(default_scopes=REQUIRED_DEFAULT_CLIENT_SCOPES)
    original = adapter._get

    def get(path):
        if path == 'client-scopes':
            return [row for row in original(path) if row['name'] != 'basic']
        return original(path)

    adapter._get = get
    with pytest.raises(ValueError, match='missing required client scopes: basic'):
        provision(adapter)


def test_device_configuration_is_served_as_an_entry_route(monkeypatch):
    from types import SimpleNamespace

    from server.identity import cli_login
    from server.manager.http import core_get_routes

    responses = []

    class Handler(core_get_routes.CoreGetRoutesMixin):
        state = SimpleNamespace(public_server=True, require_login_for_ui=True)

        def _public_login_gate(self, *_args, **_kwargs):
            raise AssertionError('confirmation must not run before CLI discovery')

    monkeypatch.setattr(
        core_get_routes, 'json_response',
        lambda _handler, body, status=200: responses.append((body, status)),
    )
    monkeypatch.setattr(
        cli_login, 'configuration',
        lambda: {'issuer': 'https://id.example/realms/research',
                 'client_id': DEFAULT_CLIENT_ID},
    )

    handled = Handler()._get_entry_routes(
        SimpleNamespace(path='/auth/oidc/device-configuration', query=''),
    )

    assert handled is True
    assert responses == [
        ({'issuer': 'https://id.example/realms/research',
          'client_id': DEFAULT_CLIENT_ID}, 200),
    ]


def test_device_configuration_fails_closed_without_oidc_configuration(monkeypatch):
    from types import SimpleNamespace

    from server.identity import cli_login
    from server.manager.http import core_get_routes

    responses = []

    class Handler(core_get_routes.CoreGetRoutesMixin):
        state = SimpleNamespace(public_server=False, require_login_for_ui=False)

    monkeypatch.setattr(
        core_get_routes, 'json_response',
        lambda _handler, body, status=200: responses.append((body, status)),
    )

    def unavailable():
        raise ValueError('Keycloak OIDC client is not configured')

    monkeypatch.setattr(cli_login, 'configuration', unavailable)

    assert Handler()._get_entry_routes(
        SimpleNamespace(path='/auth/oidc/device-configuration', query=''),
    ) is True
    assert responses[0][1] == 503
