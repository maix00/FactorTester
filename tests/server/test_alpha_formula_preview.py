import pytest
from flask import Flask
from server.modules.custom_factors import factor_library_internal_bp
from server.modules.factors import factors_bp
from server.modules.factors import formula  # register the real endpoint
from alpha.factor.serialized_formula import preview_expression


@pytest.fixture(autouse=True)
def principal(monkeypatch):
    monkeypatch.setattr("server.services.http_auth.current_user", lambda: "alice")


def client():
    app=Flask(__name__);app.register_blueprint(factors_bp);app.register_blueprint(factor_library_internal_bp)
    return app.test_client()


def test_preview_uses_alpha_without_source_loading_or_computation():
    factor={'factor_family_alias':'Example','math_expr':r'X_t:=\textcolor{red}{N}',
            'parameter_definitions':[{'alias':'N','type':'WindowParam','value':'2d'}]}
    response=client().post('/api/factor-library/families/formula-preview',json={'factor':factor,'parameter_values':{'N':'3d'}})
    assert response.status_code==200
    assert response.json['latex']==preview_expression(factor,{'N':'3d'})
    assert response.json['renderer_version']==7


def test_preview_bounds_input_and_expansion_before_large_allocations():
    c=client()
    assert c.post('/api/factor-library/families/formula-preview',data='x'*(1024*1024+1)).status_code==413
    nested={}
    for _ in range(50):nested={'child':nested}
    assert c.post('/api/factor-library/families/formula-preview',json={'factor':nested}).status_code==400
    factor={'math_expr':r'\textcolor{red}{N}'*1000,
            'parameter_definitions':[{'alias':'N','type':'TypeParam','value':'a'*5000}]}
    response=c.post('/api/factor-library/families/formula-preview',json={'factor':factor})
    assert response.status_code==400 and 'too large' in response.json['error']
    assert c.post('/api/factor-library/families/formula-preview',json={'factor':{},'parameter_values':[]}).status_code==400


def test_internal_preview_uses_same_authenticated_handler(monkeypatch):
    c=client()
    payload={"factor":{"math_expr":"X_t"}}
    assert c.post('/api/internal/factor-library/formula-preview',json=payload).status_code==200
    monkeypatch.setattr("server.services.http_auth.current_user",lambda:None)
    assert c.post('/api/internal/factor-library/formula-preview',json=payload).status_code==401


def test_manager_forwards_preview_json_without_synchronization(monkeypatch):
    import io
    from types import SimpleNamespace
    from urllib.parse import urlparse
    from server.manager.http import job_proxy_routes
    from server.manager.http.gateway import GatewayResponse

    body=b'{"factor":{"math_expr":"X_t"}}'
    calls=[]
    state=SimpleNamespace(server_id='local',route_for=lambda **kw:'route',
        route_request=lambda *a,**kw:calls.append(kw) or GatewayResponse(200,b'{"success":true}', 'application/json'),
        client_state=SimpleNamespace(_refresh_account_domain_async=lambda *a,**kw:pytest.fail('preview must not synchronize')))
    handler=SimpleNamespace(state=state,headers={'Content-Type':'application/json','Content-Length':str(len(body))},
        rfile=io.BytesIO(body),_session=lambda:{'username':'alice'},
        _is_local_agent_request=lambda:False,_send_gateway_response=lambda *a,**kw:None)
    assert job_proxy_routes.JobProxyRoutesMixin._proxy_authenticated_local_service(
        handler,urlparse('/api/factor-library/families/formula-preview'),method='POST')
    assert calls==[dict(path='/api/internal/factor-library/formula-preview',principal='alice',
        method='POST',body=body,content_type='application/json')]
