"""Service grants never confer arbitrary node/Manager/principal authority."""
from types import SimpleNamespace
import time
import pytest

from server.identity.service_access import ServiceTokenVerifier
from server.manager.http.federation.public_data import FederationPublicDataRoutesMixin


def claims(**changes):
    return {"active":True,"iss":"https://id/realms/tr","aud":["manager-b"],
            "exp":time.time()+60,"sub":"service","scope":"tr:federation:read tr:federation:submit",
            "tr_manager_id":"manager-a","tr_principals":["alice"],**changes}


@pytest.mark.parametrize("change", [{"active":False},{"iss":"https://other"},{"aud":["other"]},{"exp":0}])
def test_invalid_service_authority_rejected(change):
    verifier=ServiceTokenVerifier(SimpleNamespace(introspect=lambda _:claims(**change)),issuer="https://id/realms/tr",audience="manager-b")
    with pytest.raises(PermissionError):verifier.verify("token",required_scope="tr:federation:read")


def test_introspection_cached_but_scope_checked_on_every_call():
    calls=[]
    verifier=ServiceTokenVerifier(SimpleNamespace(introspect=lambda _:calls.append(1) or claims()),issuer="https://id/realms/tr",audience="manager-b")
    assert verifier.verify("token",required_scope="tr:federation:read").principals==frozenset({"alice"})
    with pytest.raises(PermissionError):verifier.verify("token",required_scope="tr:execution:node")
    assert len(calls)==1


@pytest.mark.parametrize("principal,peer,status", [("alice","manager-a",200),("bob","manager-a",403),("alice","unknown",403)])
def test_federation_requires_registered_peer_and_delegated_principal(monkeypatch,principal,peer,status):
    import server.manager.http.federation.public_data as module
    responses=[]
    monkeypatch.setattr(module,"json_response",lambda _,value,code=200:responses.append((code,value)))
    verifier=ServiceTokenVerifier(SimpleNamespace(introspect=lambda _:claims(tr_manager_id=peer)),issuer="https://id/realms/tr",audience="manager-b")
    class Handler(FederationPublicDataRoutesMixin):
        headers={"Authorization":"Bearer token"}
        state=SimpleNamespace(execution_token_verifier=verifier,
            federation_registry=SimpleNamespace(servers=lambda **_: [{"server_id":"manager-a"}]))
        def _json_body(self,_):return {"kind":"execution","operation":"targets","principal":principal,"payload":{}}
        def _public_data_value(self,**_):return {"targets":[]}
        def _has_federation_proxy_token(self):raise AssertionError("execution must not fall back to old proxy token")
    Handler()._federation_public_data()
    assert responses[0][0]==status


def test_service_backchannel_preserves_canonical_token_issuer(tmp_path, monkeypatch):
    from server.identity import service_access as module
    secret = tmp_path / "secret"
    secret.write_text("fixture")
    for key, value in {"ISSUER": "https://public.example/identity/realms/tr",
                       "CLIENT_ID": "node", "CLIENT_SECRET_FILE": str(secret),
                       "BACKCHANNEL_URL": "http://keycloak:8080/identity"}.items():
        monkeypatch.setenv("TR_OIDC_" + key, value)
    calls = []
    monkeypatch.setattr(module, "ServiceOIDCClient",
                        lambda base, realm, client, **kw: calls.append((base, realm, client)) or object())
    module.configured_client()
    verifier = module._verifier("https://public.example/identity/realms/tr", "node",
                                str(secret), 1, "manager", "http://keycloak:8080/identity")
    assert calls == [("http://keycloak:8080/identity", "tr", "node")] * 2
    assert verifier.issuer == "https://public.example/identity/realms/tr"
    monkeypatch.setenv("TR_OIDC_BACKCHANNEL_URL", "http://untrusted.example/identity")
    with pytest.raises(ValueError):
        module.configured_client()
    module._verifier.cache_clear()
