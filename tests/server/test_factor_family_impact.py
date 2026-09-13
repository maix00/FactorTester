import json
import sqlite3

from server.modules.custom_factors.family_impact import factor_set_impacts
from tools.factors.formula_identity import freeze_factor_identity
from tools.factors.factor_set_identity import freeze_factor_set_identity


def factor(owner, alias='CA'):
    return freeze_factor_identity(owner_ref=owner, family_alias=alias,
        factor_alias=alias+'|N:1', family_formula_fingerprint='a'*64,
        self_formula_fingerprint='b'*64, params={'N': 1})


def test_sets_match_owner_and_family_and_overlay_received_tombstones():
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    conn.execute('CREATE TABLE account_factor_sets(username,target_ref,payload_json)')
    conn.execute('CREATE TABLE account_domain_entities(principal,entity_type,entity_id,payload_json,deleted)')
    value = freeze_factor_set_identity(owner_ref='principal:alice',set_id='set',alias='组合',
        members=[factor('public'),factor('alice'),factor('public','OTHER')])
    conn.execute('INSERT INTO account_factor_sets VALUES(?,?,?)',('alice',value['ref'],json.dumps(value)))
    impacts = factor_set_impacts(conn,owner_ref='public',family_alias='CA')
    assert impacts[0]['member_count'] == 3
    assert impacts[0]['affected_factor_refs'] == [factor('public')['ref']]
    conn.execute('INSERT INTO account_domain_entities VALUES(?,?,?,?,?)',
        ('alice','factor_set',value['ref'],'{}',1))
    assert factor_set_impacts(conn,owner_ref='public',family_alias='CA') == []
    conn.execute('INSERT INTO account_domain_entities VALUES(?,?,?,?,?)',
        ('bob','factor_set',value['ref'],json.dumps(value),0))
    assert factor_set_impacts(conn,owner_ref='public',family_alias='CA')[0]['username'] == 'bob'
