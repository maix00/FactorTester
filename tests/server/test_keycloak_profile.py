from copy import deepcopy
from server.identity.keycloak_profile import (
    CLAIM_ATTRIBUTES, configure_identity_mappers, protect_identity_attributes,
)


class Adapter:
    def __init__(self):
        self.profile = {'attributes': [{'name': 'email'}], 'groups': [{'name': 'custom'}]}
        self.mappers = []
        self.writes = 0

    def _get(self, path):
        if path == 'users/profile':
            return deepcopy(self.profile)
        if path.startswith('clients?'):
            return [{'clientId': 'manager', 'id': 'c'}]
        return deepcopy(self.mappers)

    def _put(self, path, value):
        self.writes += 1
        if path == 'users/profile':
            self.profile = deepcopy(value)
        else:
            i = next(i for i, r in enumerate(self.mappers) if r['id'] == value['id'])
            self.mappers[i] = deepcopy(value)

    def _post(self, path, value):
        self.writes += 1
        self.mappers.append({**deepcopy(value), 'id': str(len(self.mappers))})


def test_identity_attributes_cannot_be_edited_by_users_and_preserve_profile():
    a = Adapter()
    protect_identity_attributes(a)
    assert a.profile['groups'] == [{'name': 'custom'}]
    assert {'name': 'email'} in a.profile['attributes']
    for attr in a.profile['attributes'][1:]:
        assert attr['permissions'] == {'view': ['admin'], 'edit': ['admin']}
    assert a.profile['unmanagedAttributePolicy'] == 'ADMIN_EDIT'


def test_claims_use_imported_attribute_names_and_do_not_duplicate_mappers():
    a = Adapter()
    configure_identity_mappers(a, 'manager')
    n = a.writes
    configure_identity_mappers(a, 'manager')
    assert a.writes == n
    assert len(a.mappers) == len(CLAIM_ATTRIBUTES)
    assert next(r for r in a.mappers if r['name'] == 'tr_organization_id')['config']['user.attribute'] == 'organization_id'
