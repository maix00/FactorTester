"""Real HTTP chart forwarding; deterministic provider and OIDC introspection."""
from dataclasses import asdict
from http.server import ThreadingHTTPServer
from types import SimpleNamespace
import threading
import time
from urllib.error import HTTPError
import pytest

from server.jobs.dispatch.node_market import NodeMarketHandler
from server.jobs.dispatch.node_service import ExecutionNodeService
from server.jobs.repository.sqlite import JobRepository
from server.identity.service_access import ServiceHTTPClient, ServiceTokenVerifier
from server.manager.services.execution_market import read_node_market
from tests.server.test_execution_data_binding import _offer,_target


def read_chart(*,offer,query):
    return {"data":[{"time":123,"close":1}],"product":offer.product_ref}


@pytest.fixture
def node(tmp_path,monkeypatch):
    offer=_offer()
    class Identity:
        manager="manager-a"
        def client_credentials(self,**_):return {"access_token":"test-token","expires_in":60}
        def introspect(self,_):return {"active":True,"iss":"https://identity/realms/test","aud":["market"],"exp":time.time()+60,"sub":"manager", "tr_manager_id":self.manager,"tr_principals":["alice"],"scope":"tr:market:read"}
    identity=Identity()
    descriptor={"target":asdict(_target()),"service_port":8000,"offers":[asdict(offer)],"runtime_adapters":{offer.source_ref:{"member_key":"minute","adapter_id":"v1","frequency":"MIN1","instrument_scope":"physical_contract","clock_policy":"end"}}}
    class Handler(NodeMarketHandler):pass
    Handler.state=SimpleNamespace(session=lambda _:None,descriptors=lambda:[descriptor],provider="tests.server.test_execution_node_market:read_chart",execution_token_verifier=ServiceTokenVerifier(identity,issuer="https://identity/realms/test",audience="market"))
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    descriptor['market_endpoint']=f'http://127.0.0.1:{server.server_port}'
    repo=JobRepository(tmp_path/'manager.sqlite')
    service=ExecutionNodeService(repo,manager_id='manager-a');route=service.register('node-b',descriptor)
    state=SimpleNamespace(server_id='manager-a',job_repository=repo)
    monkeypatch.setattr('server.manager.services.execution_market.configured_client',lambda _:identity)
    yield state,identity,{"route_id":route['route_id'],"source_ref":offer.source_ref,"product_ref":offer.product_ref,"chart_range":"month","max_points":100}
    server.shutdown();server.server_close();thread.join()


def test_manager_forwards_bounded_exact_source_to_node(node):
    state,_,payload=node
    value=read_node_market(state,principal='alice',payload=payload)
    assert len(value['data'])==1 and value['source_ref']==payload['source_ref']
    assert value['node_id']=='node-b'


@pytest.mark.parametrize('change,principal', [({'max_points':5001},'alice'),({'chart_range':'all'},'alice'),({'source_ref':'other'},'alice'),({},'bob')])
def test_invalid_or_unauthorized_requests_never_use_local_fallback(node,change,principal):
    state,_,payload=node
    with pytest.raises((PermissionError,ValueError,HTTPError)):
        read_node_market(state,principal=principal,payload={**payload,**change})
