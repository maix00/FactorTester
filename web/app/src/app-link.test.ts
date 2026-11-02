import assert from 'node:assert/strict';
import {test} from 'node:test';
import {appCatalogLink} from './app-link.ts';
test('catalog links retain immutable identity and scoped owner without treating them as URLs',()=>{
 assert.deepEqual(appCatalogLink('?page=factors&section=sets&object_ref=factor-set%3Av2%3Ax&owner_username=alice&mode=edit'),{pageId:'factors',args:{section:'sets',catalogRef:'factor-set:v2:x',catalogOwner:'alice',catalogMode:'edit'}});
 assert.equal(appCatalogLink('?page=https://other.invalid'),null);
 assert.equal(appCatalogLink('?page=admin'),null);
 assert.deepEqual(appCatalogLink('?page=factors&mode=delete'),{pageId:'factors',args:{}});
});
