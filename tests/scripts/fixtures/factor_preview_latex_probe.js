"use strict";
// Cross-end probe: loads factor-detail-shared.js and computes the frontend
// previewExpression for each factor object passed as JSON on stdin.
//
// argv[2] = path to factor-detail-shared.js (the module to load)
// stdin   = JSON: [{ "factor": {...}, "values": {...} }, ...]
// stdout  = JSON: [ { "expression": "<string>" }, ... ]
const fs = require("fs");
const vm = require("vm");
const path = require("path");

const sharedPath = process.argv[2];
if (!sharedPath) {
  process.stderr.write("usage: node probe.js <factor-detail-shared.js>\n");
  process.exit(2);
}

const input = JSON.parse(fs.readFileSync(0, "utf8"));

// Minimal browser globals so the IIFE can install window.FTFactorDetailShared.
global.window = {};
// Prevent any accidental document usage during load (none should happen here).
const code = fs.readFileSync(sharedPath, "utf8");
vm.runInThisContext(code, { filename: sharedPath });

const shared = global.window.FTFactorDetailShared;
const katex = require(path.resolve(path.dirname(sharedPath),
  "../../../../apple/Resources/ThirdParty/KaTeX/katex.min.js"));
if (!shared || typeof shared.previewExpression !== "function") {
  process.stderr.write("FTFactorDetailShared.previewExpression not found\n");
  process.exit(3);
}

async function main() {
  const results = [];
  for (const entry of input) {
    const factor = entry.factor;
    const values = entry.values || {};
    const api = async (_path, options) => ({success: true,
      latex: JSON.parse(options.body).include_nested_definitions === false ? entry.flat : entry.rendered});
    const expression = await shared.previewExpression(factor, values, {api});
    katex.renderToString(expression, {throwOnError: true, strict: "ignore", displayMode: true});
    global.document = {createElement: () => ({
      children: [], handlers: {}, append(...nodes) { this.children.push(...nodes); },
      addEventListener(type, handler) { this.handlers[type] = handler; },
      replaceChildren() {},
    })};
    let localExpression;
    window.katex = {};
    window.FTUI = {renderMath(_target, source) { localExpression = source; }};
    const local = shared.localFormula({t: x => x, api}, factor, values);
    await local.root.children[0].children[1].handlers.click();
    results.push({expression, localExpression});
  }
  process.stdout.write(JSON.stringify(results));
}
main().catch(error => { process.stderr.write(String(error.stack)); process.exit(1); });
