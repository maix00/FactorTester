import test from "node:test";
import assert from "node:assert/strict";
import { versionedAssetURL } from "./assets.ts";
test("shell and workers use per-file content identities without invalidating unchanged editor code",()=>{
 const path='/research-static/vendor/web-app/configuration-code.js';
 const first={'desktop.js':'desktop-one','configuration-code.js':'editor-one'};
 assert.equal(versionedAssetURL(path,first),path+'?v=editor-one');
 assert.equal(versionedAssetURL(path,{...first,'desktop.js':'desktop-two'}),versionedAssetURL(path,first));
 assert.equal(versionedAssetURL('/research-static/vendor/web-app/configuration-json-worker.js',{'configuration-json-worker.js':'worker'}),'/research-static/vendor/web-app/configuration-json-worker.js?v=worker');
});
test("asset versioning preserves explicit identities, other queries, and external URLs",()=>{
 assert.equal(versionedAssetURL('/research-static/core/price-chart.js?feature=1#part',{},'legacy'),'/research-static/core/price-chart.js?feature=1&v=legacy#part');
 assert.equal(versionedAssetURL('/research-static/core/price-chart.js?v=frozen',{},'latest'),'/research-static/core/price-chart.js?v=frozen');
 assert.equal(versionedAssetURL('https://external.invalid/file.js',{},'legacy'),'https://external.invalid/file.js');
 assert.equal(versionedAssetURL('/research-static/vendor/web-app/unknown.js',{},'legacy'),'/research-static/vendor/web-app/unknown.js');
});
