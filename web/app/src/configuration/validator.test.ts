import assert from "node:assert/strict";
import test from "node:test";
import validator from "./validator.ts";
import type { RJSFSchema } from "@rjsf/utils";

test("dynamic configuration validates under disabled runtime code generation", () => {
  const schema: RJSFSchema = { type: "object", required: ["count"], additionalProperties: false,
    properties: { count: { type: "integer", minimum: 1 }, mode: { enum: ["auto", "manual"] } } };
  assert.equal(validator.validateFormData({ count: 2, mode: "auto" }, schema).errors.length, 0);
  assert.ok(validator.validateFormData({ count: 0, mode: "bad", extra: true }, schema).errors.length >= 3);
  assert.ok(validator.validateFormData({}, schema).errors.length);
  assert.equal(validator.validateFormData({ count: 2 }, schema).errors.length, 0);
  assert.equal(Object.getOwnPropertyNames(schema).some(key => key.startsWith("__absolute")), false);
});

test("root references, union branches and custom field errors retain RJSF semantics", () => {
  const root: RJSFSchema = { $defs: { positive: { type: "integer", minimum: 1 } }, type: "object",
    properties: { count: { $ref: "#/$defs/positive" } } };
  const fragment: RJSFSchema = { $ref: "#/$defs/positive" };
  assert.equal(validator.isValid(fragment, 1, root), true);
  assert.equal(validator.isValid(fragment, 0, root), false);
  assert.ok(validator.validateFormData({count: 0}, root).errors.some(error => error.property === ".count" && error.name === "minimum"));
  const otherRoot: RJSFSchema = { $defs: { positive: { const: 0 } } };
  assert.equal(validator.isValid(fragment, 0, otherRoot), true);
  const union: RJSFSchema = { oneOf: [{type: "string"}, {type: "number"}] };
  assert.equal(validator.isValid(union, 1, union), true);
  assert.equal(validator.isValid(union, true, union), false);
  const result = validator.validateFormData({count: 1}, root, (_data, errors) => { errors.count?.addError("custom"); return errors; });
  assert.deepEqual(result.errorSchema.count?.__errors, ["custom"]);
});
