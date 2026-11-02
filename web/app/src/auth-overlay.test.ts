import test from "node:test";
import { build } from "esbuild";
import { mkdtemp, writeFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { execFileSync } from "node:child_process";

test("rendered sign-in cannot expose password or registration fallback", async () => {
  const temporary = await mkdtemp(join(tmpdir(), "tr-auth-dom-"));
  try {
    const result = await build({
      stdin: { resolveDir: fileURLToPath(new URL("..", import.meta.url)), loader: "tsx", contents: `
        import React from 'react';
        import {renderToStaticMarkup} from 'react-dom/server';
        import assert from 'node:assert/strict';
        import {AuthOverlay} from './src/auth.tsx';
        globalThis.location={pathname:'/app',search:''};
        for(const provider of ['keycloak','manager',undefined]) {
          const html=renderToStaticMarkup(React.createElement(AuthOverlay,{
            entry:{authentication_provider:provider,public_registration_enabled:true},
            unavailable:false,authError:''}));
          assert(!html.includes('<input'));
          assert(!html.includes('<form'));
          assert(!html.includes('/auth/login'));
          assert(!html.includes('/auth/register'));
          assert.equal(html.includes('disabled=""'),provider!=='keycloak');
        }
      ` }, bundle: true, platform: "node", format: "cjs", write: false,
      loader: { ".css": "empty" }, logLevel: "silent",
    });
    const output = join(temporary, "render.cjs");
    await writeFile(output, result.outputFiles[0].contents);
    execFileSync(process.execPath, [output], {stdio:"pipe"});
  } finally {
    await rm(temporary, { recursive: true, force: true });
  }
});
