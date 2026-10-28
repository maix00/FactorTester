"""Freeze the stored T/TL paper-duration family chain without rewriting its source.

Read-only historical SQLite source snapshot; output is an isolated RunSpec input,
not a registry write and not a claim to preserve an older factor:v2 identity.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
from server.modules.shared.factor_param_resolver import _load_factor_family_from_source,_resolve_frozen_factor
from server.modules.shared.factor_param_utils import normalize_factor_param_row,factor_param_value_storage
from tools.factors.factor_param_resolution import factor_param_resolver_scope
from tools.factors.formula_identity import freeze_factor_identity


def freeze(database:Path,window:str):
    records=[];sources={}
    with sqlite3.connect(database.resolve().as_uri()+'?mode=ro',uri=True) as connection:
        def build(name,params):
            rows=connection.execute('select source_code from factor_family_sources where factor_id=?',(name,)).fetchall()
            if len(rows)!=1:raise ValueError(f'expected one unambiguous stored source for {name}')
            source=rows[0][0];sources[name]=hashlib.sha256(source.encode()).hexdigest()
            cls,_=_load_factor_family_from_source(source,name)
            if cls is None:raise ValueError(f'could not load stored source {name}')
            family=cls();normalized=normalize_factor_param_row(family,params)
            refs={r['ref']:r for r in records}
            with factor_param_resolver_scope(lambda value:_resolve_frozen_factor(value,username='alice',frozen_by_ref=refs)):
                factor=family.get_factor(**normalized)
            expr=getattr(factor,'_source_expr',None) or factor.expr
            record=freeze_factor_identity(owner_ref='principal:alice',family_alias=name,factor_alias=str(factor.alias),
                family_formula_fingerprint=family.expr.semantic_fingerprint(),self_formula_fingerprint=expr.semantic_fingerprint(),
                params={p.alias:factor_param_value_storage(p,normalized.get(p.alias)) for p in family.params})
            record.update(source_kind='transient',source_code=source,temporary=True)
            records.append(record);return record
        threshold=build('SgChgPct',{'P':'CA','B':1,'N':'250d','M':.6,'$F':'30m'})
        duration=build('SgChgDurDay',{'P':'CA','Th':threshold,'$F':'30m'})
        deviation=build('TsDurDevDayScope',{'Dur':duration,'V':'C','$F':'30m'})
        signal=build('TsHistCmp',{'X':deviation,'N':window,'$F':'30m'})
    return dict(factors=records,signal_ref=signal['ref'],source_sha256=sources,
        provenance='read-only historical source snapshot; unchanged family sources, freshly frozen identities',
        parameters=dict(window=window,threshold_history='250d',quantile=.6,lag=1,signal_frequency='30m'))


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--database',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path);parser.add_argument('--window',default='20d')
    args=parser.parse_args();payload=freeze(args.database,args.window)
    with args.output.open('x') as handle:json.dump(payload,handle,indent=2)
    print(payload['signal_ref'])

if __name__=='__main__':main()
