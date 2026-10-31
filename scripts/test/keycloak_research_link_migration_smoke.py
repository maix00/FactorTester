#!/usr/bin/env python3
"""Exercise legacy link staging and redemption against disposable Keycloak.

The image must already exist. No existing realm or user is modified. The
local SQLite and Keycloak container are temporary and are removed on exit.
"""
from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path

from scripts.migrations.keycloak_research_stage import build_plan, stage_plan
from scripts.test.keycloak_cross_realm_smoke import Sandbox
from scripts.test.keycloak_research_grant_smoke import NoProfileGrants, run
from server.identity.keycloak import KeycloakAdminAdapter
from server.identity.keycloak_hierarchy_admin import KeycloakHierarchyProvisioner
from server.identity.keycloak_research import KeycloakResearchAuthorization
from server.identity.keycloak_research_cutover import KeycloakResearchPolicyEvaluator
from server.identity.request_context import bind_verified_identity, identity_request
from server.manager.services.research_catalog import ResearchCatalog


def exercise(*, sandbox, realm, settings, sessions, users, manager, issuer, **_unused):
    admin = KeycloakAdminAdapter(sandbox.base, realm)
    admin._token = lambda: sandbox.admin
    provisioner = KeycloakHierarchyProvisioner(admin)
    groups, _ = provisioner.ensure_groups(['/traderesearch', '/traderesearch/organizations',
                                            '/traderesearch/organizations/qa'])
    for user in users.values():
        admin._put('users/' + user['id'] + '/groups/' + groups['/traderesearch/organizations/qa'], {})
    evaluator = KeycloakResearchPolicyEvaluator(adapter=admin, settings=settings,
        request=lambda _adapter, client_uuid, body: sandbox.api('POST', realm,
            f'clients/{client_uuid}/authz/resource-server/policy/evaluate', body))
    accounts = [{'username': name, 'tr_identity_id': 'stable-' + name} for name in users]
    with tempfile.TemporaryDirectory(prefix='tr-link-migration-') as root:
        path, backup = Path(root) / 'legacy.sqlite', Path(root) / 'backup.sqlite'
        old = ResearchCatalog(path)
        research = old.create_research(owner_ref='owner', title='Migration')['research_id']
        used = old.create_share_link(target_kind='research', research_id=research, actor='owner', mode='one_time')
        unused = old.create_share_link(target_kind='research', research_id=research, actor='owner', mode='one_time')
        old.redeem_share_link(used['token'], actor='member')
        with sqlite3.connect(path) as source, sqlite3.connect(backup) as target:
            source.backup(target)
        plan = build_plan(path, accounts, issuer=issuer)
        result = stage_plan(database=path, backup=backup, reviewed_plan=plan, accounts=accounts,
                            adapter=admin, grants=manager, evaluator=evaluator, record=lambda _event: None, issuer=issuer)
        assert result['needs_repair_researches'] == 0 and result['links_bound'] == 2
        strict = ResearchCatalog(path, research_authorizer=KeycloakResearchAuthorization(),
            profile_authorizer=NoProfileGrants(), profile_grant_manager=manager)
        with identity_request():
            bind_verified_identity(*sessions['member'])
            assert strict.redeem_share_link(used['token'], actor='member')['research_id'] == research
        with identity_request():
            bind_verified_identity(*sessions['late'])
            try:
                strict.redeem_share_link(used['token'], actor='late')
            except PermissionError:
                pass
            else:
                raise AssertionError('a migrated one-time link accepted another identity')
            assert strict.redeem_share_link(unused['token'], actor='late')['research_id'] == research
        return {'links_bound': result['links_bound'], 'scope_decisions': result['scope_decisions']}


if __name__ == '__main__':
    with Sandbox() as sandbox:
        result = {}
        def capture(**kwargs):
            result.update(exercise(**kwargs))
        run(sandbox, on_ready=capture)
        print(json.dumps({'real_keycloak': True, **result}, sort_keys=True))
