"""Thin service access adapter: Keycloak authenticates, platform maps claims.

No new signatures, enrollment registry, JWT parser or token authority. Keys,
revocation and grants remain Keycloak responsibilities. Transfer-node key
protocols remain separate from execution API authentication.
"""
from __future__ import annotations
from dataclasses import dataclass
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import threading
import time
from urllib.parse import urlparse
from urllib.request import Request

from server.identity.keycloak import ServiceOIDCClient
from server.manager.domain.federation_transport import FederationTransport


@dataclass(frozen=True, slots=True)
class ServiceIdentity:
    subject: str
    node_id: str
    manager_id: str
    scopes: frozenset[str]
    principals: frozenset[str] = frozenset()


def configured_client(prefix="TR_OIDC"):
    issuer=os.environ[prefix+"_ISSUER"].rstrip("/")
    base, separator, realm=issuer.rpartition("/realms/")
    if not separator or not realm or "/" in realm:
        raise ValueError("explicit Keycloak realm issuer is required")
    parsed=urlparse(issuer)
    if parsed.scheme not in {"https","http"} or not parsed.hostname or parsed.username:
        raise ValueError("invalid OIDC issuer")
    secret=Path(os.environ[prefix+"_CLIENT_SECRET_FILE"]).read_text().strip()
    if not secret:raise ValueError("OIDC service credential is missing")
    return ServiceOIDCClient(base,realm,os.environ[prefix+"_CLIENT_ID"],client_secret=secret)


class ServiceTokenVerifier:
    def __init__(self, client, *, issuer, audience):
        self.client,self.issuer,self.audience=client,issuer.rstrip("/"),audience
        self._cache={};self._lock=threading.Lock()

    def verify(self, token, *, required_scope):
        digest=hashlib.sha256(token.encode()).hexdigest();now=time.time()
        with self._lock:
            cached=self._cache.get(digest)
            if cached and cached[0]>now:claims=cached[1]
            else:
                claims=self.client.introspect(token)
                if not isinstance(claims,dict) or claims.get("active") is not True:
                    raise PermissionError("inactive service token")
                audience=claims.get("aud",[])
                if isinstance(audience,str):audience=[audience]
                if claims.get("iss")!=self.issuer or self.audience not in audience:
                    raise PermissionError("service token issuer/audience mismatch")
                expires=float(claims.get("exp") or 0)
                if expires<=now:raise PermissionError("expired service token")
                if len(self._cache)>=256:self._cache.clear()
                self._cache[digest]=(min(expires,now+5),claims)
        scopes=frozenset(str(claims.get("scope") or "").split())
        if required_scope not in scopes:raise PermissionError("service scope is missing")
        return ServiceIdentity(str(claims.get("sub") or ""),str(claims.get("tr_node_id") or ""),
                               str(claims.get("tr_manager_id") or ""),scopes,
                               frozenset(claims.get("tr_principals") or []) if isinstance(claims.get("tr_principals"), list) else frozenset())


@lru_cache(maxsize=8)
def _verifier(issuer,client_id,secret_file,secret_mtime,audience):
    del secret_mtime
    base,_,realm=issuer.rstrip("/").rpartition("/realms/")
    client=ServiceOIDCClient(base,realm,client_id,client_secret=Path(secret_file).read_text().strip())
    return ServiceTokenVerifier(client,issuer=issuer,audience=audience)


def authenticate_service(handler, *, required_scope):
    scheme,_,token=str(handler.headers.get("Authorization") or "").partition(" ")
    if scheme.lower()!="bearer" or not token:raise PermissionError("OIDC service token is required")
    verifier=getattr(handler.state,"execution_token_verifier",None)
    if verifier is None:
        try:
            path=Path(os.environ["TR_OIDC_CLIENT_SECRET_FILE"])
            verifier=_verifier(os.environ["TR_OIDC_ISSUER"],os.environ["TR_OIDC_CLIENT_ID"],
                str(path),path.stat().st_mtime_ns,os.environ["TR_OIDC_AUDIENCE"])
        except (KeyError,OSError,ValueError) as exc:
            raise PermissionError("OIDC execution authentication is not configured") from exc
    return verifier.verify(token,required_scope=required_scope)


class ServiceHTTPClient:
    """Use existing OIDC client grants and TLS transport for JSON business APIs."""
    def __init__(self,endpoint,*,oidc,response_limit=1024*1024,scope=""):
        self.endpoint,self.oidc=endpoint.rstrip("/"),oidc
        self.response_limit,self.scope=response_limit,scope
        self._token="";self._expires=0;self._lock=threading.Lock()
        self.transport=FederationTransport()

    def post_json(self,path,payload):
        with self._lock:
            if time.monotonic()>=self._expires:
                result=self.oidc.client_credentials(scope=self.scope)
                self._token=result["access_token"]
                self._expires=time.monotonic()+max(1,float(result.get("expires_in",30))-10)
            token=self._token
        request=Request(self.endpoint+path,data=json.dumps(payload,separators=(",",":"),sort_keys=True).encode(),
            method="POST",headers={"Content-Type":"application/json","Authorization":"Bearer "+token})
        with self.transport.open(request,timeout=15) as response:
            raw=response.read(self.response_limit+1)
        if len(raw)>self.response_limit:raise ValueError("node response exceeds byte budget")
        result=json.loads(raw)
        if not isinstance(result,dict) or result.get("success") is False:raise ValueError("invalid service response")
        return result
