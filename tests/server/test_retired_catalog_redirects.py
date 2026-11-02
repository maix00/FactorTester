"""Retired URLs select React views without reading a catalog or executing source."""
from urllib.parse import urlparse,parse_qs
import pytest
from server.manager.http.core_get_routes import CoreGetRoutesMixin

@pytest.mark.parametrize('path,section,target,mode',[
 ('/factors','factors','',''),('/factors/families','families','',''),
 ('/factors/family/new?mode=create&visibility=public','families','','create'),
 ('/factors/factor/factor%3Av2%3Afrozen?mode=edit&owner_username=alice','factors','factor:v2:frozen','edit'),
 ('/factors/set/factor-set%3Av2%3Afrozen','sets','factor-set:v2:frozen',''),
])
def test_retired_urls_redirect_without_loading_domain_objects(path,section,target,mode):
 class Handler(CoreGetRoutesMixin):
  def _get_manager_identity_route(self,parsed):return False
  def send_response(self,status):self.status=status
  def send_header(self,key,value):self.headers[key]=value
  def end_headers(self):pass
 h=Handler();h.headers={}
 assert h._get_session_and_shell_routes(urlparse(path)) is True
 assert h.status==302
 parsed=urlparse(h.headers['Location']);assert parsed.path=='/app'
 query=parse_qs(parsed.query)
 assert query['page']==['factors'] and query['section']==[section]
 assert query.get('object_ref',[''])[0]==target
 assert query.get('mode',[''])[0]==mode
 if 'visibility=public' in path:assert query['source']==['public']
 if 'owner_username' in path:assert query['owner_username']==['alice']
