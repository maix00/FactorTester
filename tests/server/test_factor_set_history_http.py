from types import SimpleNamespace
from urllib.parse import urlencode, urlparse
import pytest

from server.manager.http import catalog_routes as routes
from tools.data.sqlite.account_manager.factor_set import save_factor_set
from tests.data.test_factor_set_history import version, member


class Handler(routes.CatalogRoutesMixin):
    def _session(self): return {'username':'alice'}
    def _visitor_mode(self): return None


@pytest.mark.parametrize('owner,status',[('alice',200),('mallory',403)])
def test_history_endpoint_uses_set_visibility(monkeypatch,tmp_path,owner,status):
    import settings
    monkeypatch.setattr(settings,'CACHE_DB_PATH',tmp_path/'db.sqlite')
    value=version('CA')
    save_factor_set('alice',value)
    handler=Handler()
    handler.state=SimpleNamespace(client_state=SimpleNamespace(factor_set_scopes=lambda _: {}))
    received=[]
    monkeypatch.setattr(routes,'json_response',lambda _,payload,code=200: received.append((payload,code)))
    path='/api/factor-library/factor-sets/history?'+urlencode({'target_ref':value['ref'],'owner_username':owner})
    assert handler._serve_factor_catalog(urlparse(path))
    assert received[0][1]==status


def test_history_factor_rejects_unrelated_ref_without_loading_source(monkeypatch,tmp_path):
    import settings
    monkeypatch.setattr(settings,'CACHE_DB_PATH',tmp_path/'db.sqlite')
    value=version('CA');save_factor_set('alice',value)
    handler=Handler();handler.state=SimpleNamespace(client_state=SimpleNamespace())
    received=[]
    monkeypatch.setattr(routes,'json_response',lambda _,payload,code=200: received.append((payload,code)))
    from server.services.factor_source_catalog import FactorSourceCatalog
    monkeypatch.setattr(FactorSourceCatalog,'version',lambda *a,**k: pytest.fail('unrelated source access'))
    path='/api/factor-library/factor-sets/history-factor?'+urlencode({
        'target_ref':value['ref'],'owner_username':'alice','factor_ref':member('OTHER')['ref']})
    assert handler._serve_factor_catalog(urlparse(path))
    assert received[0][1]==404

def test_removed_member_detail_reads_historical_source_not_current(monkeypatch,tmp_path):
    import settings
    from tools.factors.formula_identity import freeze_factor_identity
    from tools.factors.factor_set_identity import freeze_factor_set_identity
    from tools.data.sqlite.factor_source_versions import record_factor_formula_version
    from tools.data.sqlite.factor_source_store import upsert_factor_source,delete_factor_source
    from server.modules.custom_factors.crud_routes import _family_formula_fingerprint
    from tools.data.sqlite.account_manager.factor_set import delete_factor_set
    monkeypatch.setattr(settings,'CACHE_DB_PATH',tmp_path/'db.sqlite')
    source='from tools.factors import FactorFamily\nfrom tools.factors.expr import OPEN\n\nclass Historical(FactorFamily):\n    @staticmethod\n    def factor_expr():\n        return OPEN\n'
    fp=_family_formula_fingerprint(source,'Historical')
    frozen=freeze_factor_identity(owner_ref='public',family_alias='Historical',factor_alias='Historical',
        family_formula_fingerprint=fp,self_formula_fingerprint='b'*64,params={'$F':'1d','$Rev':0})
    value=freeze_factor_set_identity(owner_ref='principal:alice',set_id='history',alias='集合',members=[frozen])
    upsert_factor_source('public','','Historical','Historical',source,family_formula_fingerprint=fp)
    record_factor_formula_version('public','','Historical',source,family_formula_fingerprint=fp)
    save_factor_set('alice',value);delete_factor_set('alice',value['ref'])
    delete_factor_source('public','','Historical')
    handler=Handler();handler.state=SimpleNamespace(client_state=SimpleNamespace())
    received=[]
    monkeypatch.setattr(routes,'json_response',lambda _,payload,code=200: received.append((payload,code)))
    path='/api/factor-library/factor-sets/history-factor?'+urlencode({
        'target_ref':value['ref'],'owner_username':'alice','factor_ref':frozen['ref']})
    assert handler._serve_factor_catalog(urlparse(path))
    payload,status=received[0]
    assert status==200
    assert payload['factor']['source_code']==source
    assert payload['factor']['resolved_math_expr']
    assert payload['factor']['family_formula_fingerprint']==fp
    assert payload['factor']['can_edit'] is False
