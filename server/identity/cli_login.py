"""Public CLI login metadata and its Keycloak-native client definition."""
from __future__ import annotations
import os

DEFAULT_CLIENT_ID = 'traderesearch-cli'

# ``basic`` contributes the standard OIDC ``sub`` claim through Keycloak's sub
# mapper; without it Manager introspection has no subject and rejects an
# otherwise valid CLI token. ``roles`` carries resource_access and ``profile``
# carries preferred_username.
REQUIRED_DEFAULT_CLIENT_SCOPES = ('basic', 'roles', 'profile')


def configuration() -> dict:
    from server.identity.user_session import oidc_settings
    settings = oidc_settings()
    return {'issuer': settings['issuer'], 'client_id': os.environ.get('TR_CLI_OIDC_CLIENT_ID') or DEFAULT_CLIENT_ID}


def client_definition(*, audience: str = 'tr-manager', client_id: str = DEFAULT_CLIENT_ID) -> dict:
    from server.identity.keycloak_profile import identity_mappers
    return {
        'clientId': client_id, 'name': 'TradeResearch CLI', 'protocol': 'openid-connect',
        'enabled': True, 'publicClient': True, 'serviceAccountsEnabled': False,
        'standardFlowEnabled': False, 'implicitFlowEnabled': False,
        'directAccessGrantsEnabled': False, 'fullScopeAllowed': True,
        'attributes': {'oauth2.device.authorization.grant.enabled': 'true'},
        'defaultClientScopes': list(REQUIRED_DEFAULT_CLIENT_SCOPES),
        'optionalClientScopes': [],
        'protocolMappers': identity_mappers(audience),
    }


def _required_scope_ids(adapter) -> dict[str, str]:
    """Resolve this realm's required scope UUIDs without guessing by name order."""
    rows = adapter._get('client-scopes')
    if not isinstance(rows, list):
        raise ValueError('Keycloak client scope lookup failed')
    found: dict[str, list[str]] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('Keycloak client scope lookup returned invalid rows')
        name = str(row.get('name') or '')
        if name not in REQUIRED_DEFAULT_CLIENT_SCOPES:
            continue
        scope_id = str(row.get('id') or '')
        if not scope_id:
            raise ValueError('Keycloak client scope is missing its identifier')
        found.setdefault(name, []).append(scope_id)
    missing = [name for name in REQUIRED_DEFAULT_CLIENT_SCOPES if name not in found]
    if missing:
        raise ValueError('realm is missing required client scopes: ' + ', '.join(missing))
    ambiguous = [name for name, values in found.items() if len(set(values)) != 1]
    if ambiguous:
        raise ValueError('required Keycloak client scope is ambiguous: ' + ', '.join(ambiguous))
    return {name: values[0] for name, values in found.items()}


def _reconcile_default_scopes(adapter, client_uuid: str, *, apply: bool) -> tuple[list[str], bool]:
    """Return required scopes missing from the client and whether apply changed it."""
    ids = _required_scope_ids(adapter)
    current = adapter._get(f'clients/{client_uuid}/default-client-scopes')
    if not isinstance(current, list):
        raise ValueError('Keycloak default client scope lookup failed')
    names = {str(row.get('name') or '') for row in current if isinstance(row, dict)}
    missing = [name for name in REQUIRED_DEFAULT_CLIENT_SCOPES if name not in names]
    if not missing or not apply:
        return missing, False
    for name in missing:
        adapter._put(f'clients/{client_uuid}/default-client-scopes/{ids[name]}', {})
    current = adapter._get(f'clients/{client_uuid}/default-client-scopes')
    if not isinstance(current, list):
        raise ValueError('Keycloak default client scope lookup failed')
    names = {str(row.get('name') or '') for row in current if isinstance(row, dict)}
    still_missing = [name for name in REQUIRED_DEFAULT_CLIENT_SCOPES if name not in names]
    if still_missing:
        raise ValueError('CLI OIDC default scopes did not verify: ' + ', '.join(still_missing))
    return [], True


def provision(adapter, *, apply: bool = False, audience: str = 'tr-manager') -> dict:
    """Create or reconcile the public CLI client; never overwrite an incompatible one."""
    from urllib.parse import urlencode
    desired = client_definition(audience=audience)
    rows = adapter._get('clients?' + urlencode({'clientId': DEFAULT_CLIENT_ID}))
    matches = [row for row in rows if row.get('clientId') == DEFAULT_CLIENT_ID]
    if len(matches) > 1:
        raise ValueError('CLI OIDC client is ambiguous')
    if matches:
        mapper_created = 0
        if apply:
            from server.identity.keycloak_hierarchy_admin import KeycloakHierarchyProvisioner
            mapper_created = KeycloakHierarchyProvisioner(adapter).ensure_group_claim_mapper(
                [DEFAULT_CLIENT_ID],
            )
        actual = adapter._get('clients/' + matches[0]['id'])
        for key in ('protocol', 'enabled', 'publicClient', 'standardFlowEnabled',
                    'implicitFlowEnabled', 'directAccessGrantsEnabled', 'serviceAccountsEnabled',
                    'fullScopeAllowed'):
            if actual.get(key) != desired[key]:
                raise ValueError('existing CLI OIDC client differs: ' + key)
        if actual.get('attributes', {}).get('oauth2.device.authorization.grant.enabled') != 'true':
            raise ValueError('existing CLI OIDC client has device login disabled')
        by_name = {
            str(mapper.get('name') or ''): mapper
            for mapper in actual.get('protocolMappers', [])
            if isinstance(mapper, dict)
        }
        for mapper in desired['protocolMappers']:
            existing = by_name.get(mapper['name'], {})
            if any(existing.get(k) != mapper[k] for k in ('protocol', 'protocolMapper', 'config')):
                raise ValueError('existing CLI OIDC mapper differs: ' + mapper['name'])
        missing, changed = _reconcile_default_scopes(
            adapter, str(matches[0]['id']), apply=apply,
        )
        group_mapper = [
            mapper for mapper in actual.get('protocolMappers', [])
            if isinstance(mapper, dict)
            and str(mapper.get('name') or '') == 'traderesearch-realm-group-paths'
        ]
        group_ok = (
            len(group_mapper) == 1
            and str(group_mapper[0].get('protocolMapper') or '') == 'oidc-group-membership-mapper'
        )
        if not group_ok and apply:
            raise ValueError('CLI OIDC group claim mapper did not verify')
        result = {
            'client_id': DEFAULT_CLIENT_ID,
            'status': 'updated' if (changed or mapper_created) else
                'update' if (missing or not group_ok) else 'verified',
            'default_client_scopes': list(REQUIRED_DEFAULT_CLIENT_SCOPES),
        }
        if missing:
            result['missing_default_scopes'] = missing
        if not group_ok:
            result['missing_protocol_mappers'] = ['traderesearch-realm-group-paths']
        return result
    if apply:
        adapter._post('clients', desired)
        return provision(adapter, apply=True, audience=audience)
    return {'client_id': DEFAULT_CLIENT_ID, 'status': 'create',
            'default_client_scopes': list(REQUIRED_DEFAULT_CLIENT_SCOPES),
            'password_grant': False, 'service_account': False, 'user_grants_changed': False}
