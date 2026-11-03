import assert from "node:assert/strict";
import test from "node:test";
import {clientInstallerHref} from "./client-release.ts";
const sha256="a".repeat(64),path=`/api/client/releases/assets/beta/${sha256}.dmg`;
test("verified installers stay on the selected Manager despite advertised host aliases",()=>{
  for(const host of ["http://localhost:7998","https://public.example:7998"]){
    assert.equal(clientInstallerHref({sha256,dmg_url:host+path},"http://127.0.0.1:7998/app"),"http://127.0.0.1:7998"+path);
  }
});
test("invalid or mismatched installers never become download links",()=>{
  for(const dmg_url of ["javascript:alert(1)","https://user:secret@example.test"+path,"https://example.test"+path+"?redirect=1",path.replace(sha256,"b".repeat(64)),"/other.dmg"]){
    assert.equal(clientInstallerHref({sha256,dmg_url},"https://manager.example/app"),undefined);
  }
  assert.equal(clientInstallerHref({dmg_url:path},"https://manager.example/app"),undefined);
});
