// The JS hook must resolve the API bundled with the GTHT Python Playwright pin.
const assert = require('node:assert/strict');
const {chromium, webkit} = require('playwright');

assert.equal(typeof chromium.launch, 'function');
assert.equal(typeof webkit.launch, 'function');
console.log('PLAYWRIGHT RUNTIME: GTHT-bundled Node driver exposes Chromium and WebKit APIs');
