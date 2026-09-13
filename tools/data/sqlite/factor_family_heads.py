"""Current family metadata, separate from immutable source providers."""
import json
import settings
from tools.data.sqlite.db import connect_sqlite


def family_heads(source_kind, owner=None):
    with connect_sqlite(settings.CACHE_DB_PATH, readonly=True) as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='account_domain_entities'").fetchone():
            return []
        query = "SELECT principal,entity_id,payload_json,deleted FROM account_domain_entities WHERE entity_type='factor_family'"
        args = ()
        if owner is not None:
            query += ' AND principal=?'
            args = (owner or '__public__',)
        rows = db.execute(query, args).fetchall()
    return [{'payload': json.loads(row['payload_json']), 'deleted': bool(row['deleted']),
             'owner': '' if row['principal'] == '__public__' else row['principal'],
             'factor_id': row['entity_id'].split(':', 1)[1]}
            for row in rows if row['entity_id'].startswith(source_kind + ':')]


def family_head(source_kind, owner, factor_id):
    return next((row for row in family_heads(source_kind, owner)
                 if row['factor_id'] == factor_id), None)


def project_family_heads(values, source_kind, owner):
    merged = {(value.get('owner_username') or '', value['factor_id']): value for value in values}
    for row in family_heads(source_kind, owner):
        key = (row['owner'], row['factor_id'])
        if row['deleted']:
            merged.pop(key, None)
        else:
            payload = row['payload']
            merged[key] = {**(payload.get('catalog') or {}), **payload,
                           'owner_username': row['owner'], 'factor_id': row['factor_id']}
    return list(merged.values())


def legacy_source_manifests(rows, source_kind, owner):
    """Yield scoped provider metadata only where no current family head exists.

    Providers retain bytes for frozen history. Neither a live provider nor a
    newer provider revision can override a current head or its tombstone.
    Public and private catalogs must share this rule.
    """
    principal = owner or '__public__'
    current_ids = {row['factor_id'] for row in family_heads(source_kind, owner)}
    for row in rows:
        if not isinstance(row, dict) or row.get('deleted'):
            continue
        payload = row.get('payload')
        if not isinstance(payload, dict):
            continue
        kind = str(payload.get('source_kind') or source_kind).strip().lower()
        payload_owner = str(payload.get('owner_username') or row.get('principal') or '').strip()
        if kind != source_kind or payload_owner != principal:
            continue
        alias = str(payload.get('factor_id') or '').strip()
        if alias and alias not in current_ids:
            yield payload
