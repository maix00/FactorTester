"""Admin-owned identity attributes and their OIDC claim mappings.

Realm Groups/roles remain the authority for permissions. These attributes
only carry stable object-owner and directory references through login.
"""
from __future__ import annotations

CLAIM_ATTRIBUTES = {
    'tr_identity_id': 'tr_identity_id',
    'tr_username': 'legacy_username',
    'tr_organization_id': 'tr_organization_id',
    'tr_organization_name': 'tr_organization_name',
    'tr_level_id': 'tr_level_id',
    'tr_parent_identity_id': 'tr_parent_identity_id',
    'tr_parent_username': 'tr_parent_username',
}


def identity_mappers(client_id: str = 'tr-manager') -> list[dict]:
    return [
        {'name': claim, 'protocol': 'openid-connect',
         'protocolMapper': 'oidc-usermodel-attribute-mapper',
         'config': {'user.attribute': attribute, 'claim.name': claim,
                    'jsonType.label': 'String', 'id.token.claim': 'true',
                    'access.token.claim': 'true', 'userinfo.token.claim': 'true',
                    'introspection.token.claim': 'true'}}
        for claim, attribute in CLAIM_ATTRIBUTES.items()
    ] + [{'name': 'manager-audience', 'protocol': 'openid-connect',
          'protocolMapper': 'oidc-audience-mapper',
          'config': {'included.client.audience': client_id,
                     'access.token.claim': 'true', 'id.token.claim': 'false',
                     'userinfo.token.claim': 'false',
                     'introspection.token.claim': 'true'}}]


def protect_identity_attributes(adapter) -> None:
    """Preserve the realm profile while making ownership labels admin-only."""
    profile = adapter._get('users/profile')
    owned = set(CLAIM_ATTRIBUTES.values())
    attributes = [dict(a) for a in profile.get('attributes', [])
                  if a.get('name') not in owned]
    attributes.extend({'name': name, 'multivalued': False,
                       'permissions': {'view': ['admin'], 'edit': ['admin']}}
                      for name in sorted(owned))
    profile['attributes'] = attributes
    # Unmanaged attributes must not be user-editable ownership claims.
    profile['unmanagedAttributePolicy'] = 'ADMIN_EDIT'
    adapter._put('users/profile', profile)
    verified = adapter._get('users/profile')
    by_name = {a['name']: a for a in verified.get('attributes', [])}
    if any(by_name.get(name, {}).get('permissions') !=
           {'view': ['admin'], 'edit': ['admin']} for name in owned):
        raise RuntimeError('Keycloak identity attribute protection did not verify')


def configure_identity_mappers(adapter, client_id: str) -> None:
    from urllib.parse import quote, urlencode
    rows = adapter._get('clients?' + urlencode({'clientId': client_id}))
    exact = [r for r in rows if r.get('clientId') == client_id]
    if len(exact) != 1:
        raise ValueError('OIDC client is missing or ambiguous')
    path = f"clients/{quote(exact[0]['id'], safe='')}/protocol-mappers/models"
    current = {r['name']: r for r in adapter._get(path)}
    for mapper in identity_mappers(client_id):
        old = current.get(mapper['name'])
        if old is None:
            adapter._post(path, mapper)
        elif any(old.get(k) != mapper[k] for k in ('protocol', 'protocolMapper', 'config')):
            adapter._put(path + '/' + quote(old['id'], safe=''), {**mapper, 'id': old['id']})
    actual = {r['name']: r for r in adapter._get(path)}
    for mapper in identity_mappers(client_id):
        if any(actual.get(mapper['name'], {}).get(k) != mapper[k]
               for k in ('protocol', 'protocolMapper', 'config')):
            raise RuntimeError('Keycloak identity claim mapper did not verify')
