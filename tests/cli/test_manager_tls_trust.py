from tools.cli.manager.client import ManagerClient
from tools.cli.manager.config import ManagerConfig
from urllib.request import Request


def test_manager_reuses_only_endpoint_certificate_trust(monkeypatch):
    calls=[];context=object()
    monkeypatch.setattr('tools.cli.native_session.transfer_tls_context',lambda url,authority:calls.append((url,authority)) or context)
    opened=[]
    monkeypatch.setattr('tools.cli.manager.client.urlopen',lambda request,**kwargs:opened.append((request,kwargs)))
    client=ManagerClient(ManagerConfig.from_url('https://manager.example:7998'),token='manager-only')
    request=Request('https://manager.example:7997/capability',headers={'Authorization':'Bearer scoped-capability'})
    client._open(request,timeout=120)
    assert calls==[('https://manager.example:7997/capability','https://manager.example:7998')]
    assert opened[0][1]=={'timeout':120,'context':context}
    assert request.get_header('Authorization')=='Bearer scoped-capability'
    assert client.token=='manager-only'
