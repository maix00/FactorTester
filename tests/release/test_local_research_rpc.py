from concurrent.futures import ThreadPoolExecutor

import pytest

from tools.cli.release.research_reporting.local_rpc import SCHEMA, LocalResearchRPC


def test_rpc_uses_only_native_binding_and_preserves_idempotency(tmp_path):
    rpc = LocalResearchRPC(tmp_path, issuer='https://id.test/realm/', identity_id='stable',
                           profiles=[{'profile_id': 'self', 'display_name': 'Self'}])
    capability = rpc.request({'action': 'capabilities'})
    assert capability['schema'] == SCHEMA
    assert capability['binding'] == {'issuer': 'https://id.test/realm', 'identity_id': 'stable'}
    message = {'action': 'create', 'profile_id': 'self', 'title': ' R ',
               'description': 'a\nb', 'operation_id': 'op-1'}
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: rpc.request(message), range(8)))
    assert len({item['research']['research_id'] for item in results}) == 1
    row = results[0]['research']
    assert row['title'] == 'R' and row['description'] == 'a\nb'
    page = rpc.request({'action': 'list', 'profile_id': 'self', 'limit': 1, 'offset': 0})
    assert page['researches'] == [row] and page['next_offset'] is None
    assert rpc.request({'action': 'get', 'profile_id': 'self', 'research_id': row['research_id']})['research'] == row


def test_rpc_rejects_web_identity_injection_and_unauthorized_profile(tmp_path):
    rpc = LocalResearchRPC(tmp_path, issuer='https://id.test/realm', identity_id='stable',
                           profiles=[{'profile_id': 'self', 'display_name': 'Self'}])
    with pytest.raises(ValueError):
        rpc.request({'action': 'capabilities', 'identity_id': 'other'})
    with pytest.raises(ValueError):
        rpc.request({'action': 'list', 'profile_id': 'self', 'limit': True, 'offset': 0})
    with pytest.raises(PermissionError):
        rpc.request({'action': 'list', 'profile_id': 'other', 'limit': 20, 'offset': 0})
    with pytest.raises(ValueError):
        rpc.request({'action': 'create', 'profile_id': 'self', 'title': 'bad\x00title',
                     'description': '', 'operation_id': 'op-1'})


def test_rpc_rejects_ambiguous_native_profiles(tmp_path):
    with pytest.raises(ValueError):
        LocalResearchRPC(tmp_path, issuer='https://id.test/realm', identity_id='stable',
                         profiles=[{'profile_id': 'self', 'display_name': 'A'},
                                   {'profile_id': 'self', 'display_name': 'B'}])
