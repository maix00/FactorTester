"""Write a localhost-only Keycloak realm for isolated execution acceptance."""
from pathlib import Path
import json
import os
import secrets
import sys


def prepare(root):
    root=Path(root);root.mkdir(parents=True,exist_ok=False)
    scopes=[{"name":name,"protocol":"openid-connect"} for name in ["tr:execution:node","tr:market:read","tr:federation:read","tr:federation:submit"]]
    clients=[];credentials={}
    for client_id,node,manager,scope in [
        ('node-a','node-b','','tr:execution:node'),('node-b','node-c','','tr:execution:node'),
        ('manager-api','','manager-a','tr:market:read'),('manager-b-api','','manager-b','tr:market:read'),
        ('node-data','','','tr:market:read')]:
        secret=secrets.token_urlsafe(32);credentials[client_id]=secret
        mappers=[]
        for audience in ['manager-a','manager-b','node-data']:
            mappers.append({'name':'aud-'+audience,'protocol':'openid-connect','protocolMapper':'oidc-audience-mapper',
                'config':{'included.custom.audience':audience,'access.token.claim':'true','introspection.token.claim':'true'}})
        for claim,value in [('tr_node_id',node),('tr_manager_id',manager)]:
            if value:mappers.append({'name':claim,'protocol':'openid-connect','protocolMapper':'oidc-hardcoded-claim-mapper',
                'config':{'claim.name':claim,'claim.value':value,'jsonType.label':'String','access.token.claim':'true','introspection.token.claim':'true'}})
        if manager:
            mappers.append({'name':'delegated-principals','protocol':'openid-connect','protocolMapper':'oidc-hardcoded-claim-mapper',
                'config':{'claim.name':'tr_principals','claim.value':'["alice"]','jsonType.label':'JSON','access.token.claim':'true','introspection.token.claim':'true'}})
        clients.append({'clientId':client_id,'secret':secret,'protocol':'openid-connect','publicClient':False,
            'serviceAccountsEnabled':True,'standardFlowEnabled':False,'directAccessGrantsEnabled':False,
            'defaultClientScopes':[scope,'tr:federation:read','tr:federation:submit'],'protocolMappers':mappers})
    realm={'realm':'tr-node-test','enabled':True,'sslRequired':'none','accessTokenLifespan':60,'clientScopes':scopes,'clients':clients}
    for name,value in [('realm.json',realm),('credentials.json',credentials)]:
        path=root/name;path.write_text(json.dumps(value));path.chmod(0o600)
    for key,value in credentials.items():
        path=root/(key+'.secret');path.write_text(value);path.chmod(0o600)
    print(str(root))


if __name__=='__main__':prepare(sys.argv[1])
