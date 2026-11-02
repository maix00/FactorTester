import {familyConfigurationKey} from './catalog-search.ts';
type Row=Record<string,any>;
/** Adapt presentation rows only. Values and frozen nested records stay intact. */
export function factorParameterValues(value:unknown):Row {
 if(Array.isArray(value))return Object.fromEntries(value.filter(row=>row&&typeof row.alias==='string').map(row=>[row.alias,row.value]));
 return value&&typeof value==='object'?{...value}:{};
}
export function parameterDefaults(definitions:Row[]):Row {
 return Object.fromEntries(definitions.filter(row=>row.alias&&row.default_value!==null&&row.default_value!==undefined).map(row=>[row.alias,row.default_value]));
}
export function factorSourceKey(factor:Row):string {
 const alias=String(factor.factor_family_alias||factor.family_alias||factor.identity?.family_alias||'');
 const rawOwner=String(factor.family_owner_username||factor.factor_owner_ref||factor.owner_username||'').replace(/^principal:/,'');
 return familyConfigurationKey({factor_family_alias:alias,source:factor.source,factor_kind:factor.factor_kind,owner_username:rawOwner==='public'?'__public__':rawOwner});
}

/** Old metadata used runtime UniqueNameObject names; do not display their UUIDs. */
export function parameterLabel(definition:Row):string {
 const alias=String(definition.alias||''),name=String(definition.name||'');
 return !name||(name.startsWith(alias+':')&&/:[0-9a-f]{32}$/i.test(name))?alias:name;
}
