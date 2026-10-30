from pathlib import Path
import pytest
from scripts.migrations.keycloak_execution_client import provision, SCOPE

class Adapter:
    def __init__(self): self.scopes=[]; self.clients=[]
    def _get(self,path):
        return self.scopes if path == 'client-scopes' else []
    def _post(self,path,payload):
        (self.scopes if path=='client-scopes' else self.clients).append(payload)


def test_service_clients_have_no_human_admin_or_federation_grants(tmp_path):
    a=Adapter(); root=tmp_path/'credentials'
    receipt=provision(a,manager_id='manager-a',node_id='node-a',output=root)
    assert receipt['scope']==SCOPE
    node, verifier=a.clients
    assert node['defaultClientScopes']==[SCOPE]
    assert verifier['defaultClientScopes']==[]
    for client in a.clients:
        assert not client['fullScopeAllowed']
        assert not client['standardFlowEnabled']
        assert not client['directAccessGrantsEnabled']
        assert 'authorizationServicesEnabled' not in client
    assert node['protocolMappers'][0]['config']['included.custom.audience']=='manager-a'
    assert node['protocolMappers'][1]['config']['claim.value']=='node-a'
    assert node['protocolMappers'][2]['config']['included.custom.audience']==receipt['clients']['verifier']
    assert all((p.stat().st_mode & 0o777)==0o600 for p in root.iterdir())
    with pytest.raises(FileExistsError):provision(a,manager_id='manager-a',node_id='node-a',output=root)


def test_refuses_existing_client_without_rotating_or_rebinding(tmp_path):
    a=Adapter(); a._get=lambda path: [{'id':'existing'}] if path.startswith('clients?') else []
    with pytest.raises(ValueError,match='already exists'):
        provision(a,manager_id='manager-a',node_id='node-a',output=tmp_path/'credentials')
    assert not a.clients
    assert not (tmp_path/'credentials').exists()
