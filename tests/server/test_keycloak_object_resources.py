import pytest
from scripts.migrations.keycloak_object_resources import plan_resources, apply_resources


def test_placeholder_requires_exact_job_owner_and_never_defaults():
    rows = [{'_id': 'report:a:1', 'kind': 'report', 'job_id': 'a',
             'owner': '__legacy_report_migration__'}]
    denied = plan_resources(rows, {'alice': 'subject'})
    with pytest.raises(ValueError, match='unresolved'):
        apply_resources(denied, register=lambda **_: pytest.fail('must not write'))
    result = plan_resources(rows, {'alice': 'subject'}, jobs={'a': {'owner': 'alice'}})
    assert result['resources'][0]['owner_subject'] == 'subject'
    assert result['resources'][0]['resource_type'] == 'job_test_report'


def test_factor_head_and_revision_share_one_permission_and_public_is_not_reowned():
    rows = [{'_id': name, 'kind': kind, 'source_kind': 'custom',
             'owner_ref': 'alice', 'factor_id': 'A'} for name, kind in [
                 ('head', 'factor_family_head'), ('version', 'factor_family')]]
    rows.append({'_id': 'public', 'kind': 'factor_family', 'source_kind': 'public'})
    result = plan_resources(rows, {'alice': 'subject'})
    assert result['summary']['resources'] == 1
    assert len(result['resources'][0]['documents']) == 2
    assert result['public_documents'] == ['public']
    calls = []
    applied = apply_resources(result, register=lambda **kw: calls.append(kw) or 'resource-id')
    assert len(calls) == 1 and applied[0]['resource_id'] == 'resource-id'


def test_unknown_kind_and_removed_owner_are_blockers_not_deletions():
    result = plan_resources([{'_id': 'a', 'kind': 'unexpected'},
        {'_id': 'b', 'kind': 'product_group', 'owner_ref': 'removed'}], {})
    assert result['summary']['unresolved'] == 2
    assert not result['resources']


def test_binding_preserves_content_and_attachment_stubs_and_rejects_concurrent_writes():
    import json
    from scripts.migrations.keycloak_object_resources import bind_document
    original = {'_id': 'report:a:1', '_rev': '1-a', 'owner': '__legacy_report_migration__',
                'content_sha256': 'frozen-hash', '_attachments': {'x': {'stub': True}}}
    class Store:
        writes = []
        def _request(self, method, path, body=None):
            if method == 'GET':
                return 200, json.dumps(original).encode()
            self.writes.append(json.loads(body))
            return 201, b'{}'
    store = Store()
    record = {'resource_type': 'job_test_report', 'owner': 'alice', 'resource_id': 'id'}
    doc = {'document_id': 'report:a:1', 'expected_rev': '1-a',
           'previous_owner': '__legacy_report_migration__'}
    bind_document(store, record, doc)
    assert store.writes[0] == {**original, 'owner': 'alice', 'keycloak_resource_id': 'id'}
    with pytest.raises(ValueError, match='changed'):
        bind_document(store, record, {**doc, 'expected_rev': '0-old'})
    assert len(store.writes) == 1
