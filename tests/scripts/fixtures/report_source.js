const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

global.window = {};
vm.runInThisContext(fs.readFileSync(
  "server/manager/web/report/source.js", "utf8",
), {filename: "source.js"});

(async () => {
  const calls = [];
  const responses = {
    "/api/client/research/demo/index": {
      title: "本地",
      assets: [{asset_id: "a", media_type: "text/plain"}],
      local_resources: [{resource_id: "r", content_base64: "cg==", media_type: "text/plain"}],
      related_objects: [], attachments: [],
    },
  };
  const api = async (path, options) => {
    calls.push([path, options]);
    const route = path.split("?", 1)[0];
    if (responses[route]) return structuredClone(responses[route]);
    if (route.endsWith("/chapters/chapter")) return {
      components: [],
      assets: [{asset_id: "b", asset_ref: "b-ref"}],
      local_resources: [{resource_id: "r2", content_base64: "cjI=", media_type: "text/plain"}],
      related_objects: [{object_ref: "object:b"}], attachments: [{attachment_ref: "attachment:b"}],
    };
    throw Object.assign(new Error("missing"), {status: 500});
  };
  const local = window.FTReportSource.create("local:demo", api);
  const value = await local.load();
  assert.equal(value.title, "本地");
  assert.equal(local.chapterLazy, true);
  assert.equal(local.localResourcePath("r"), "/api/client/research/demo/local-resources/r?inline=1");
  assert.equal(local.reportAssetPath("a"), "/api/client/research/demo/assets/a");
  await local.loadChapter("chapter", {signal: "signal"});
  assert.equal(local.localResourceIndex.has("r2"), true);
  assert.equal(local.localResourceIndex.has("r"), false);
  assert.equal(local.value.related_objects[0].object_ref, "object:b");
  assert.deepEqual(calls.map(item => item[0]), [
    "/api/client/research/demo/index",
    "/api/client/research/demo/chapters/chapter?metadata=1",
  ]);

  const remoteApi = async path => {
    if (path.endsWith("/index")) throw Object.assign(new Error("not published"), {status: 404});
    return {title: "共享", assets: [], local_resources: [], related_objects: [], attachments: []};
  };
  const remote = window.FTReportSource.create("publication-1", remoteApi);
  await remote.load();
  assert.equal(remote.chapterLazy, false);
  assert.equal(remote.reportAssetPath("asset-1"), "/api/public-research/publication-1/assets/asset-1");
  assert.equal(remote.localResourcePath("resource-1"), "/api/public-research/publication-1/local-resources/resource-1?inline=1");

  const encoded = window.FTReportSource.create("publication%201", async path => {
    assert.equal(path, "/api/public-research/publication%201/index");
    return {title: "编码报告", assets: [], local_resources: [], related_objects: [], attachments: []};
  });
  await encoded.load();
  assert.equal(encoded.publicationID, "publication 1");
  console.log("ok");
})();
