const assert = require('assert');
const path = require('path');

global.window = global;
delete global.MoneyDisplay;

require(path.resolve(__dirname, '../../static/js/modules/shared/money_display.js'));

assert.strictEqual(MoneyDisplay.formatMajor(1234.5, { currency: 'CNY' }), 'CNY 1,234.50');
assert.strictEqual(MoneyDisplay.formatSignedMajor(12.3, { currency: 'USD' }), '+USD 12.30');
assert.strictEqual(MoneyDisplay.formatSignedMajor(-12.3, { currency: 'USD' }), '-USD 12.30');
assert.strictEqual(MoneyDisplay.formatMajor(12.345, { currency: '', decimals: 2 }), '12.35');

console.log('PASS: money display formats major-unit amounts with currency codes');
