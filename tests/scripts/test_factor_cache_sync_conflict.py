from contextlib import contextmanager
from copy import deepcopy
from server.manager.storage.account_domain.remote import AccountDomainControlMixin

class Store(AccountDomainControlMixin):
    def __init__(self, payload, deleted=False):
        self.payload, self.deleted, self.writes = payload, deleted, 0
    @contextmanager
    def _connection(self):
        yield self
    def execute(self, sql, args=()):
        self.sql = sql
        if 'INSERT INTO' in sql: self.writes += 1
        return self
    def fetchone(self):
        if 'nextval' in self.sql: return {'revision': 11}
        return {'payload': self.payload, 'deleted': self.deleted, 'revision': 10}

def test_concurrent_render_refresh_preserves_authoring_cas():
    current = {'params_list': [{'N': '1m'}], 'resolved_factors': [
        {'identity': {'params': {'N': '1m'}, 'family_ref': 'fixed'},
         'resolved_math_expr_version': 5, 'name': 'random-a'}]}
    incoming = deepcopy(current)
    incoming['resolved_factors'][0]['name'] = 'random-b'
    store = Store(current)
    def push(payload=incoming, deleted=False):
        return store.push_account_domain_entity(principal='alice', entity_type='factor_param_config',
            entity_id='default:F', payload=payload, base_revision=9, deleted=deleted)
    assert push()['status'] == 'synced'
    assert store.writes == 0
    incoming['resolved_factors'][0]['resolved_math_expr_version'] = 6
    assert push()['status'] == 'synced'
    assert store.writes == 1
    incoming['params_list'] = [{'N': '5m'}]
    assert push()['status'] == 'conflict'
    assert push(current, deleted=True)['status'] == 'conflict'
    incoming = deepcopy(current)
    incoming['resolved_factors'][0]['identity']['family_ref'] = 'different'
    assert push(incoming)['status'] == 'conflict'
