#!/usr/bin/env python3
"""Prepare a new host's protected Keycloak bootstrap files, without changing users."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import secrets
from urllib.parse import urlsplit


def prepare(root: Path, *, public_url: str, network: str, project: str, realm: str, manager_ipv4: str) -> None:
    import re
    import ipaddress
    address = ipaddress.IPv4Address(manager_ipv4)
    if not address.is_private or address.is_loopback or address.is_link_local or address.is_unspecified:
        raise ValueError('reserve a private IPv4 address in the Manager Docker network')
    if any(ord(c) < 33 or ord(c) == 127 for c in public_url):
        raise ValueError('public URL must not contain whitespace or control characters')
    for value in (network, project):
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}', value):
            raise ValueError('invalid Docker project or network name')
    url = urlsplit(public_url)
    if (url.scheme not in {'http', 'https'} or not url.hostname or url.path not in {'', '/'}
            or url.username or url.password or url.query or url.fragment):
        raise ValueError('public URL must be a Manager origin')
    if not re.fullmatch(r'[A-Za-z0-9._-]+', realm):
        raise ValueError('invalid realm')
    if url.scheme == 'http':
        import ipaddress
        try:
            private = ipaddress.ip_address(url.hostname).is_private
        except ValueError:
            private = url.hostname == 'localhost' or url.hostname.endswith('.local')
        if not private:
            raise ValueError('public Manager requires HTTPS')
    if root.exists():
        raise FileExistsError('bootstrap directory already exists; refusing to rotate credentials')
    root.mkdir(parents=True, mode=0o700)
    os.chmod(root, 0o700)
    imports = root / 'import'
    imports.mkdir(mode=0o755)  # parent remains private; container can read bind mount
    manager_secret, migration_secret = secrets.token_urlsafe(48), secrets.token_urlsafe(48)
    directory_secret, visitor_secret = secrets.token_urlsafe(48), secrets.token_urlsafe(48)
    resource_secret = secrets.token_urlsafe(48)
    db_secret, bootstrap_secret = secrets.token_urlsafe(48), secrets.token_urlsafe(48)
    from server.identity.keycloak_profile import identity_mappers, MANAGER_ROLES
    roles = MANAGER_ROLES
    mappers = identity_mappers()
    definition = {'realm': realm, 'enabled': True, 'registrationAllowed': False,
                  'resetPasswordAllowed': False, 'adminPermissionsEnabled': True,
                  'userManagedAccessAllowed': True,
                  'roles': {'client': {'tr-manager': [{'name': role} for role in roles],
                                       'tr-visitor': [{'name': 'access'}]}},
                  'clients': [
                      {'clientId': 'tr-manager', 'enabled': True, 'publicClient': False,
                       'secret': manager_secret, 'standardFlowEnabled': True,
                       'directAccessGrantsEnabled': False, 'serviceAccountsEnabled': True,
                       'redirectUris': [public_url.rstrip('/') + '/auth/oidc/callback'],
                       'webOrigins': [public_url.rstrip('/')],
                       'attributes': {'post.logout.redirect.uris': public_url.rstrip('/') + '/app',
                                      'pkce.code.challenge.method': 'S256'},
                       'protocolMappers': mappers},
                      {'clientId': 'tr-migration', 'enabled': True, 'publicClient': False,
                       'secret': migration_secret, 'standardFlowEnabled': False,
                       'directAccessGrantsEnabled': False, 'serviceAccountsEnabled': True},
                      {'clientId': 'tr-directory', 'enabled': True, 'publicClient': False,
                       'secret': directory_secret, 'standardFlowEnabled': False,
                       'directAccessGrantsEnabled': False, 'serviceAccountsEnabled': True},
                      {'clientId': 'tr-resources', 'enabled': True, 'publicClient': False,
                       'secret': resource_secret, 'standardFlowEnabled': False,
                       'directAccessGrantsEnabled': False, 'serviceAccountsEnabled': True,
                       'authorizationServicesEnabled': True,
                       'authorizationSettings': {'allowRemoteResourceManagement': True,
                           'policyEnforcementMode': 'ENFORCING', 'decisionStrategy': 'UNANIMOUS',
                           'resources': [], 'policies': [], 'scopes': []}},
                      {'clientId': 'tr-visitor', 'enabled': True, 'publicClient': False,
                       'secret': visitor_secret, 'standardFlowEnabled': False,
                       'directAccessGrantsEnabled': False, 'serviceAccountsEnabled': True,
                       'protocolMappers': [identity_mappers('tr-visitor')[-1]]}],
                  'users': [{'username': 'service-account-tr-migration', 'enabled': True,
                             'serviceAccountClientId': 'tr-migration',
                             'clientRoles': {'realm-management': ['realm-admin']}},
                            {'username': 'service-account-tr-directory', 'enabled': True,
                             'serviceAccountClientId': 'tr-directory',
                             'clientRoles': {'realm-management': ['query-users', 'query-groups', 'view-users']}},
                            {'username': 'service-account-tr-visitor', 'enabled': True,
                             'serviceAccountClientId': 'tr-visitor',
                             'clientRoles': {'tr-visitor': ['access']}},
                            {'username': 'service-account-tr-resources', 'enabled': True,
                             'serviceAccountClientId': 'tr-resources',
                             'clientRoles': {'tr-resources': ['uma_protection']}}]}
    (imports / 'realm.json').write_text(json.dumps(definition))
    os.chmod(imports / 'realm.json', 0o644)
    def write(name: str, contents: str) -> None:
        target = root / name
        target.write_text(contents)
        os.chmod(target, 0o600)
    write('identity.env', '\n'.join([
        f'TR_IDENTITY_PROJECT={project}', f'TR_MANAGER_DOCKER_NETWORK={network}',
        f'TR_IDENTITY_MANAGER_IPV4={address}',
        f'TR_IDENTITY_IMPORT_DIR={imports.resolve()}',
        'TR_IDENTITY_DB_URL=jdbc:postgresql://identity-db:5432/tr_identity',
        'TR_IDENTITY_DB_NAME=tr_identity', 'TR_IDENTITY_DB_USER=tr_identity',
        f'TR_IDENTITY_DB_PASSWORD={db_secret}',
        f'TR_IDENTITY_PUBLIC_URL={public_url.rstrip("/")}/identity',
        'TR_IDENTITY_BOOTSTRAP_USER=bootstrap-admin', f'TR_IDENTITY_BOOTSTRAP_PASSWORD={bootstrap_secret}', '']))
    write('manager.env', '\n'.join([
        f'TR_USER_OIDC_ISSUER={public_url.rstrip("/")}/identity/realms/{realm}',
        'TR_USER_OIDC_BACKCHANNEL_URL=http://tr-keycloak:8080/identity',
        'TR_KEYCLOAK_PROXY_BACKEND_URL=http://tr-keycloak:8080',
        'TR_USER_OIDC_CLIENT_ID=tr-manager', 'TR_USER_OIDC_ROLES_CLIENT_ID=tr-manager',
        f'TR_USER_OIDC_CLIENT_SECRET={manager_secret}', '']))
    with (root / 'manager.env').open('a') as output:
        output.write('\n'.join([
            'TRADERESEARCH_KEYCLOAK_ADMIN_CLIENT_ID=tr-directory',
            f'TRADERESEARCH_KEYCLOAK_ADMIN_CLIENT_SECRET={directory_secret}',
            'TR_KEYCLOAK_AUTHZ_CLIENT_ID=tr-resources',
            f'TR_KEYCLOAK_AUTHZ_CLIENT_SECRET={resource_secret}',
            f'TR_KEYCLOAK_VISITOR_ISSUER={public_url.rstrip("/")}/identity/realms/{realm}',
            'TR_KEYCLOAK_VISITOR_CLIENT_ID=tr-visitor',
            f'TR_KEYCLOAK_VISITOR_CLIENT_SECRET={visitor_secret}', '']))
    write('migration.env', '\n'.join([
        'TRADERESEARCH_KEYCLOAK_URL=http://127.0.0.1:8099/identity',
        f'TRADERESEARCH_KEYCLOAK_REALM={realm}',
        'TRADERESEARCH_KEYCLOAK_ADMIN_CLIENT_ID=tr-migration',
        f'TRADERESEARCH_KEYCLOAK_ADMIN_CLIENT_SECRET={migration_secret}',
        'TRADERESEARCH_KEYCLOAK_ROLES_CLIENT_ID=tr-manager',
        'TRADERESEARCH_KEYCLOAK_SESSION_CLIENT_IDS=tr-manager', '']))


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--state-dir', type=Path, required=True)
    p.add_argument('--public-url', required=True)
    p.add_argument('--network', required=True)
    p.add_argument('--manager-ipv4', required=True, help='reserved Keycloak IPv4 on the Manager Docker network')
    p.add_argument('--project', required=True)
    p.add_argument('--realm', default='traderesearch')
    a = p.parse_args()
    prepare(a.state_dir, public_url=a.public_url, network=a.network, project=a.project, realm=a.realm, manager_ipv4=a.manager_ipv4)
    print('Protected bootstrap files prepared; no existing users or credentials modified.')

if __name__ == '__main__':
    main()
