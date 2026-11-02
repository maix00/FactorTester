"""Local business calls retain the exact verified user credential."""
from types import SimpleNamespace
import pytest
from server.manager.state.routing import RoutingStateMixin


def state():
    calls=[]
    return SimpleNamespace(gateway=SimpleNamespace(request=lambda **kwargs:calls.append(kwargs) or 'ok'),
        federation_gateway=SimpleNamespace(request=lambda *a,**kwargs:calls.append(kwargs) or 'remote')),calls


def test_local_user_delegation_reuses_gateway_without_copying_into_payload():
    target,calls=state()
    result=RoutingStateMixin.route_request(target,SimpleNamespace(remote=False,port=8000),
        path='/api/internal/factor-library/families/custom',principal='alice',method='POST',
        body=b'{}',delegated_user_token='verified-access-token')
    assert result=='ok'
    assert calls==[dict(port=8000,path='/api/internal/factor-library/families/custom',
        principal='alice',method='POST',body=b'{}',content_type='application/json',
        delegated_user_token='verified-access-token')]


def test_generic_peer_route_never_forwards_local_user_token():
    target,calls=state()
    with pytest.raises(ValueError,match='local service'):
        RoutingStateMixin.route_request(target,SimpleNamespace(remote=True,port=8000),
            path='/api/internal/factor-library/families/custom',principal='alice',
            delegated_user_token='verified-access-token')
    assert not calls


def test_existing_service_capability_calls_do_not_manufacture_user_tokens():
    target,calls=state()
    RoutingStateMixin.route_request(target,SimpleNamespace(remote=False,port=8000),path='/health',principal='alice')
    assert 'delegated_user_token' not in calls[0]
