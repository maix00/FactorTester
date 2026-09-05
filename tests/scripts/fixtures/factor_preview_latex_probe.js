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
if (!shared || typeof shared.previewExpression !== "function") {
  process.stderr.write("FTFactorDetailShared.previewExpression not found\n");
  process.exit(3);
}

const results = input.map(entry => {
  const factor = entry.factor;
  const values = entry.values || {};
  const expression = shared.previewExpression(factor, values);
  return { expression };
});

process.stdout.write(JSON.stringify(results));
