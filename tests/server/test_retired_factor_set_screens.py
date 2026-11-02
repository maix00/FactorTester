from types import SimpleNamespace
from urllib.parse import urlparse,parse_qs
import pytest
from server.manager.http.core_get_routes import CoreGetRoutesMixin

@pytest.mark.parametrize('path,expected',[
 ('/factors/sets',{'page':['factors'],'section':['sets']}),
 ('/factors/set/new',{'page':['factors'],'section':['sets'],'mode':['create']}),
 ('/factors/set/factor-set%3Av2%3Aabc?mode=edit&owner_username=alice',
  {'page':['factors'],'section':['sets'],'object_ref':['factor-set:v2:abc'],'mode':['edit'],'owner_username':['alice']}),
])
def test_retired_set_screen_redirects_without_serving_the_old_shell(path,expected):
    headers={};status=[]
    handler=SimpleNamespace(_get_manager_identity_route=lambda parsed:False,
        send_response=status.append,send_header=lambda key,value:headers.__setitem__(key,value),end_headers=lambda:None)
    assert CoreGetRoutesMixin._get_session_and_shell_routes(handler,urlparse(path))
    assert status==[302]
    assert urlparse(headers['Location']).path=='/app'
    assert parse_qs(urlparse(headers['Location']).query)==expected
    assert headers['Cache-Control']=='no-store'
