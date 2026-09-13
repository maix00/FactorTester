"""Atomic family ownership changes using existing immutable identities/outbox."""
from __future__ import annotations
import hashlib
import json
import os
import time

import settings
from tools.data.sqlite.db import connect_sqlite
from tools.data.sqlite.factor_source_store import get_factor_source_record, upsert_factor_source, delete_factor_source
from tools.data.sqlite.factor_source_versions import record_factor_formula_version, _ensure_schema as ensure_versions
from tools.data.sqlite.account_manager.factor_param_config import ensure_factor_param_config_schema
from tools.factors.formula_identity import freeze_factor_identity, require_frozen_factor
from server.manager.storage.account_domain.local import LocalAccountDomainStore
from server.manager.storage.account_domain.payloads import public_payload
from server.modules.custom_factors.family_impact import factor_set_impacts, factor_matches_family, apply_set_family_change


def _configs(conn, alias):
    suffix=':'+alias
    values={(r['username'],r['scope_key']+suffix):json.loads(r['payload_json']) for r in conn.execute(
        'SELECT username,scope_key,payload_json FROM account_factor_param_configs WHERE ff_alias=?',(alias,))}
    for row in conn.execute("SELECT principal,entity_id,payload_json,deleted FROM account_domain_entities WHERE entity_type='factor_param_config' AND substr(entity_id,-?)=?",(len(suffix),suffix)):
        key=(row['principal'],row['entity_id'])
        if row['deleted']: values.pop(key,None)
        else: values[key]=json.loads(row['payload_json'])
    return values


def _plan(conn, kind, principal, alias):
    owner=principal if kind=='custom' else 'public'
    configs=[]
    for (user,identifier),payload in _configs(conn,alias).items():
        rows=payload.get('resolved_factors') or []
        for row in rows:
            require_frozen_factor(row)
        matches=[r for r in rows if factor_matches_family(r,owner_ref=owner,family_alias=alias)]
        if not rows and payload.get('params_list') and (kind=='public' or user==principal):
            raise ValueError('存在尚未冻结的旧因子登记，请先保存这些因子配置再转换')
        if matches:
            if len(matches)!=len(rows):
                raise ValueError('同一登记混有不同归属的因子，请先拆分登记')
            configs.append((user,identifier,payload))
    sets=factor_set_impacts(conn,owner_ref=owner,family_alias=alias)
    rows=conn.execute("SELECT payload_json,deleted FROM account_domain_entities WHERE entity_type='factor_family' AND entity_id=? AND principal=?",(kind+':'+alias,principal if kind=='custom' else '__public__')).fetchone()
    source=conn.execute('SELECT source_code,updated_at FROM factor_family_sources WHERE source_kind=? AND owner_username=? AND factor_id=?',
        (kind,principal if kind=='custom' else '',alias)).fetchone()
    digest=hashlib.sha256(json.dumps([configs,sets,tuple(rows) if rows else None,tuple(source) if source else None],sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    return configs,sets,digest


def family_change_impact(kind,principal,alias):
    LocalAccountDomainStore(settings.CACHE_DB_PATH)
    with connect_sqlite(settings.CACHE_DB_PATH) as conn:
        ensure_factor_param_config_schema(conn)
        configs,sets,digest=_plan(conn,kind,principal,alias)
    return {'revision':digest,'registrations':[{'username':u,'scope_key':p.get('scope_key'),
        'factor_count':len(p.get('resolved_factors') or [])} for u,_,p in configs], 'factor_sets':sets,
        'factor_count':sum(len(p.get('resolved_factors') or []) for _,_,p in configs)}


def transfer_family(kind,principal,alias,*,expected_revision):
    if kind not in {'custom','public'}: raise ValueError('因子家族类别无效')
    source=get_factor_source_record(kind,principal if kind=='custom' else '',alias)
    if source is None: raise FileNotFoundError('因子家族源码不存在')
    target_kind='public' if kind=='custom' else 'custom'
    target_owner='' if target_kind=='public' else principal
    new_owner='public' if target_kind=='public' else principal
    from server.modules.custom_factors.crud_routes import _family_formula_fingerprint
    fingerprint=_family_formula_fingerprint(source['source_code'],alias)
    mirror=LocalAccountDomainStore(settings.CACHE_DB_PATH)
    with connect_sqlite(settings.CACHE_DB_PATH) as conn:
        ensure_factor_param_config_schema(conn);ensure_versions(conn)
        conn.execute('BEGIN IMMEDIATE')
        configs,sets,revision=_plan(conn,kind,principal,alias)
        current = conn.execute('SELECT updated_at FROM factor_family_sources WHERE source_kind=? AND owner_username=? AND factor_id=?',
            (kind,principal if kind=='custom' else '',alias)).fetchone()
        if source and (current is None or current['updated_at'] != source['updated_at']):
            raise ValueError('源码已变化，请重新确认')
        if not expected_revision or revision!=expected_revision:
            raise ValueError('依赖已变化，请重新查看影响并确认转换')
        if conn.execute('SELECT 1 FROM factor_family_sources WHERE source_kind=? AND owner_username=? AND factor_id=?',
                        (target_kind,target_owner,alias)).fetchone() or conn.execute(
            "SELECT 1 FROM account_domain_entities WHERE entity_type='factor_family' AND principal=? AND entity_id=? AND NOT deleted",
            (target_owner or '__public__',target_kind+':'+alias)).fetchone():
            raise ValueError('目标类别已有同名因子家族，不能覆盖')
        replacements={principal:{}}
        old_owner=principal if kind=='custom' else 'public'
        # Sets can retain a version that has no current parameter registration.
        frozen=[]
        for user,_,payload in configs:
            if user==principal: frozen.extend(payload.get('resolved_factors') or [])
        from tools.data.sqlite.account_manager.factor_set import _visible_sets
        for impact in sets:
            if impact['username']==principal:
                frozen.extend(m for m in _visible_sets(conn,principal)[impact['ref']]['identity']['members']
                    if factor_matches_family(m,owner_ref=old_owner,family_alias=alias))
        for factor in frozen:
            identity=factor['identity']
            replacement=freeze_factor_identity(owner_ref=new_owner,family_alias=alias,
                factor_alias=factor.get('factor_alias') or factor['alias'],
                family_formula_fingerprint=identity['family_formula_fingerprint'],
                self_formula_fingerprint=identity['self_formula_fingerprint'],params=identity.get('params',{}))
            replacements[principal][factor.get('factor_ref') or factor['ref']]=replacement
        required={f['identity']['family_formula_fingerprint'] for f in frozen}
        versions={r['family_formula_fingerprint']:dict(r) for r in conn.execute(
            'SELECT * FROM factor_family_formula_versions WHERE source_kind=? AND owner_username=? AND factor_id=?',
            (kind,principal if kind=='custom' else '',alias))}
        versions[fingerprint]={'source_code':source['source_code']}
        if required-versions.keys():
            raise ValueError('保留因子所需的历史源码尚未同步，不能转换')
        upsert_factor_source(target_kind,target_owner,alias,source['factor_name'],source['source_code'],
            chinese_name=source['chinese_name'],description=source['description'],category=source['category'],
            family_formula_fingerprint=fingerprint,connection=conn,mirror=mirror)
        for fp,version in versions.items():
            record_factor_formula_version(target_kind,target_owner,alias,version['source_code'],
                family_formula_fingerprint=fp,subject='归属转换保留版本',connection=conn,mirror=mirror)
        for user,identifier,payload in configs:
            scope=identifier[:-len(alias)-1]
            if user==principal:
                updated=[]
                for factor in payload['resolved_factors']:
                    item=replacements[principal][factor.get('factor_ref') or factor['ref']]
                    updated.append({**factor,**item,'factor_ref':item['ref'],'factor_owner_ref':new_owner,
                        'factor_kind':target_kind,'source':target_kind})
                payload={**payload,'resolved_factors':updated,
                    'metadata':{**payload.get('metadata',{}),'factor_owner_ref':new_owner}}
                conn.execute('''INSERT INTO account_factor_param_configs(username,scope_key,ff_alias,payload_json,updated_at)
                    VALUES(?,?,?,?,?) ON CONFLICT(username,scope_key,ff_alias) DO UPDATE SET
                    payload_json=excluded.payload_json,updated_at=excluded.updated_at''',
                    (user,scope,alias,json.dumps(payload,ensure_ascii=False),time.time()))
                mirror.upsert_local(principal=user,entity_type='factor_param_config',entity_id=identifier,
                    payload=public_payload(payload),connection=conn,manager_id=os.environ.get('FACTORTESTER_SERVER_ID') or 'local')
            else:
                conn.execute('DELETE FROM account_factor_param_configs WHERE username=? AND scope_key=? AND ff_alias=?',(user,scope,alias))
                mirror.upsert_local(principal=user,entity_type='factor_param_config',entity_id=identifier,payload={},deleted=True,
                    connection=conn,manager_id=os.environ.get('FACTORTESTER_SERVER_ID') or 'local')
        apply_set_family_change(conn,mirror,owner_ref=old_owner,family_alias=alias,
            replacements=replacements,reason='family_transferred')
        # Preserve the old source snapshots; only retire current source/head.
        record_factor_formula_version(kind,principal if kind=='custom' else '',alias,source['source_code'],
            family_formula_fingerprint=fingerprint,connection=conn,mirror=mirror)
        delete_factor_source(kind,principal if kind=='custom' else '',alias,connection=conn,mirror=mirror)
    from server.services.factor_registry import invalidate_custom_factor_cache, invalidate_factor_family_cache
    invalidate_custom_factor_cache(principal,alias);invalidate_factor_family_cache(alias)
    return {'success':True,'target_kind':target_kind,'preserved_factors':len(replacements[principal]),
            'affected_factor_sets':len(sets),'affected_users':sorted({u for u,_,_ in configs}|{s['username'] for s in sets}|{'__public__'})}

def delete_family(kind,principal,alias,*,expected_revision):
    source=get_factor_source_record(kind,principal if kind=='custom' else '',alias)
    from server.modules.custom_factors.crud_routes import _family_formula_fingerprint
    fingerprint=_family_formula_fingerprint(source['source_code'],alias) if source else ''
    mirror=LocalAccountDomainStore(settings.CACHE_DB_PATH)
    with connect_sqlite(settings.CACHE_DB_PATH) as conn:
        ensure_factor_param_config_schema(conn);ensure_versions(conn)
        conn.execute('BEGIN IMMEDIATE')
        configs,sets,revision=_plan(conn,kind,principal,alias)
        current = conn.execute('SELECT updated_at FROM factor_family_sources WHERE source_kind=? AND owner_username=? AND factor_id=?',
            (kind,principal if kind=='custom' else '',alias)).fetchone()
        if source and (current is None or current['updated_at'] != source['updated_at']):
            raise ValueError('源码已变化，请重新确认')
        if not expected_revision or revision!=expected_revision:
            raise ValueError('依赖已变化，请重新查看影响并确认删除')
        if source:
            record_factor_formula_version(kind,principal if kind=='custom' else '',alias,source['source_code'],
                family_formula_fingerprint=fingerprint,connection=conn,mirror=mirror)
        for user,identifier,payload in configs:
            conn.execute('DELETE FROM account_factor_param_configs WHERE username=? AND scope_key=? AND ff_alias=?',
                         (user,identifier[:-len(alias)-1],alias))
            mirror.upsert_local(principal=user,entity_type='factor_param_config',entity_id=identifier,payload={},
                deleted=True,connection=conn,manager_id=os.environ.get('FACTORTESTER_SERVER_ID') or 'local')
        apply_set_family_change(conn,mirror,owner_ref=principal if kind=='custom' else 'public',family_alias=alias)
        if source:
            delete_factor_source(kind,principal if kind=='custom' else '',alias,connection=conn,mirror=mirror)
    from server.services.factor_registry import invalidate_custom_factor_cache,invalidate_factor_family_cache
    invalidate_custom_factor_cache(principal,alias);invalidate_factor_family_cache(alias)
    return {'success':True,'affected_users':sorted({u for u,_,_ in configs}|{s['username'] for s in sets}|{'__public__'})}
