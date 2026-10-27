import test from "node:test";
import assert from "node:assert/strict";
import { productFieldRows } from "./product-fields.ts";

test("product rows preserve native keys, precision, unknowns and future fields", () => {
  const info = { currency: "CNY" };
  const rows = productFieldRows({
    margin_init: { value: "0.0200", type: "Decimal" },
    margin_maint: { value: "0.0150" },
    multiplier: { value: 0 },
    is_inverse: { value: false },
    price_increment: { value: null },
    info: { value: info },
    future_native_field: { value: "005" },
  });
  assert.deepEqual(rows.map(row => row.key), ["margin_init", "margin_maint", "multiplier", "is_inverse", "price_increment", "info", "future_native_field"]);
  assert.deepEqual(rows.map(row => row.value), ["0.0200", "0.0150", 0, false, null, info, "005"]);
  assert.equal(rows[5].value, info);
  assert.equal(rows[0].type, "Decimal");
});

test("field identity comes from the response key and raw values are supported", () => {
  assert.deepEqual(productFieldRows({ margin_init: { key: "other", value: 1 }, raw: "0.0100" }), [
    { key: "margin_init", value: 1 }, { key: "raw", value: "0.0100" },
  ]);
  assert.deepEqual(productFieldRows(null), []);
});
