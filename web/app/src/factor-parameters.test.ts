import assert from 'node:assert/strict';
import {test} from 'node:test';
import {factorParameterValues,parameterDefaults,factorSourceKey,parameterLabel} from './factor-parameters.ts';
test('typed and JSON parameter views preserve nested frozen identities and falsy values',()=>{
 const nested={ref:'factor:v2:inner',params:{N:'250d'}};
 const values=factorParameterValues([{alias:'N',value:0},{alias:'reverse',value:false},{alias:'Child',value:nested}]);
 assert.deepEqual(values,{N:0,reverse:false,Child:nested});
 assert.equal(values.Child,nested);
 assert.deepEqual(factorParameterValues(JSON.parse(JSON.stringify(values))),values);
});
test('only declared defaults are filled; no invented parameters',()=>{
 assert.deepEqual(parameterDefaults([{alias:'N',default_value:'20d'},{alias:'Child',default_value:null},{alias:'B',default_value:false}]),{N:'20d',B:false});
});
test('editing uses the family source owner instead of the factor registration owner',()=>{
 assert.equal(factorSourceKey({factor_family_alias:'Alpha',source:'public',owner_username:'alice'}),'public:Alpha');
 assert.equal(factorSourceKey({factor_family_alias:'Alpha',factor_owner_ref:'principal:bob',owner_username:'alice'}),'bob:Alpha');
});

test('old runtime parameter names never expose UUIDs as field labels',()=>{
 assert.equal(parameterLabel({alias:'N',name:'N:'+'a'.repeat(32)}),'N');
 assert.equal(parameterLabel({alias:'N',name:'Window'}),'Window');
});
