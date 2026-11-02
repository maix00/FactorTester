"""Acknowledged mutations invalidate cached lists without accepting late old reads."""
from types import SimpleNamespace
import threading
from server.manager.services import federated_public_data as module


def test_factor_generation_prevents_an_old_read_from_repopulating_current_cache(monkeypatch):
    service=object.__new__(module.FederatedPublicDataService)
    service._lock=threading.RLock();service._cache={};service._factor_cache_revision=0;service.cache_seconds=60
    calls=[]
    service.client_state=SimpleNamespace(factor_library=lambda principal: calls.append(principal) or {'families':[],'factors':[]})
    monkeypatch.setattr(module,'public_factor_library',lambda:{'families':[],'factors':[]})
    first=service.factor_library('alice')
    service.factor_library('alice')
    assert calls==['alice']
    old_key=('factors','alice',0)
    service.invalidate_factor_cache()
    service._store(old_key,{**first,'stale_marker':True})
    current=service.factor_library('alice')
    assert 'stale_marker' not in current
    assert calls==['alice','alice']
    service.factor_library('alice')
    assert calls==['alice','alice']
