import os
from concurrent.futures import ThreadPoolExecutor

import pytest

from tools.cli.release.research_reporting.local_catalog import LocalResearchCatalog


def catalog(root, issuer='https://example.test/realms/a', identity='stable', profiles=None):
    return LocalResearchCatalog(root, issuer=issuer, identity_id=identity, profiles=profiles or {'self'})


def test_local_create_is_private_scoped_and_persistent(tmp_path):
    store = catalog(tmp_path)
    record = store.create(profile_id='self', title='  Research  ', description='one\ntwo', operation_id='op-1')
    assert record['title'] == 'Research'
    assert record['description'] == 'one\ntwo'
    assert record['research_id'].startswith('research:v1:')
    assert catalog(tmp_path).list(profile_id='self') == [record]
    assert catalog(tmp_path, identity='other').list(profile_id='self') == []
    assert catalog(tmp_path, issuer='https://example.test/realms/b').list(profile_id='self') == []
    assert store.path.stat().st_mode & 0o777 == 0o600
    with pytest.raises(PermissionError):
        store.list(profile_id='other')


def test_concurrent_retry_is_idempotent_and_does_not_allow_reuse(tmp_path):
    store = catalog(tmp_path)
    def create():
        return store.create(profile_id='self', title='R', description='', operation_id='op-1')
    with ThreadPoolExecutor(max_workers=4) as executor:
        rows = list(executor.map(lambda _: create(), range(8)))
    assert len({row['research_id'] for row in rows}) == 1
    with pytest.raises(ValueError):
        store.create(profile_id='self', title='Different', description='', operation_id='op-1')
    assert len(store.list(profile_id='self')) == 1


def test_pagination_reports_next_page_without_exposing_other_profiles(tmp_path):
    store = catalog(tmp_path, profiles={'self', 'other'})
    for index in range(3):
        store.create(profile_id='self', title=str(index), description='', operation_id=f'op-{index}')
    store.create(profile_id='other', title='hidden', description='', operation_id='other-1')
    first = store.page(profile_id='self', limit=2)
    assert len(first['researches']) == 2 and first['next_offset'] == 2
    last = store.page(profile_id='self', limit=2, offset=2)
    assert len(last['researches']) == 1 and last['next_offset'] is None


def test_invalid_identity_and_symlink_are_rejected(tmp_path):
    with pytest.raises(ValueError):
        catalog(tmp_path, issuer='file:///etc')
    with pytest.raises(ValueError):
        catalog(tmp_path, identity='')
    target = tmp_path / 'target'
    target.mkdir()
    os.symlink(target, tmp_path / 'local-research')
    with pytest.raises(ValueError):
        catalog(tmp_path)
