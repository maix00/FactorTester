import hashlib
import io
import pytest
from server.manager.services import research_object_transfer as module


def test_research_internal_download_uses_existing_verified_local_data_path(monkeypatch):
    raw = b'complete research bundle'
    digest = hashlib.sha256(raw).hexdigest()
    tls = object()
    monkeypatch.setattr(module, 'loopback_client_access',
                        lambda url: ('https://localhost:7997/v1/test', tls))
    def open_request(request, *, timeout, context):
        assert request.full_url == 'https://localhost:7997/v1/test'
        assert request.headers['Authorization'] == 'Bearer ticket'
        assert context is tls and timeout == 120
        return io.BytesIO(raw)
    monkeypatch.setattr(module, 'urlopen', open_request)
    transfer = module.ResearchObjectTransfer(
        server_id='requesting-manager',
        metadata_reader=lambda *args, **kwargs: {'value': {
            'kind': 'object', 'size_bytes': len(raw), 'content_hash': digest,
            'storage_server_id': 'source-manager'}},
        access_provider=lambda **kwargs: {'url': 'https://public.example:7997/v1/test',
                                         'bearer': 'ticket'})
    result = transfer.read('abcdefghijklmnopqrstuv', 'alice',
                           object_kind='research_local_resource', item_id='bundle')
    assert result[0] == raw
    monkeypatch.setattr(module, 'urlopen', lambda *args, **kwargs: io.BytesIO(b'wrong'))
    with pytest.raises(ValueError, match='size'):
        transfer.read('abcdefghijklmnopqrstuv', 'alice',
                      object_kind='research_local_resource', item_id='bundle')
