/** CSP-safe schema validation for dynamic server/strategy contracts. No code generation. */
import { Validator, type Schema, type SchemaDraft } from "@cfworker/json-schema";
import { ROOT_SCHEMA_PREFIX, withIdRefPrefix, type RJSFSchema, type ValidatorType } from "@rjsf/utils";
import processRawValidationErrors from "@rjsf/validator-ajv8/lib/processRawValidationErrors.js";
import type { ErrorObject } from "ajv";

let cache = new WeakMap<RJSFSchema, Validator>();
let fragments = new WeakMap<RJSFSchema, WeakMap<RJSFSchema, Validator>>();
const draftOf = (schema: RJSFSchema): SchemaDraft => String(schema.$schema).includes("2020-12") ? "2020-12"
  : String(schema.$schema).includes("2019-09") ? "2019-09" : "7";
function interpreter(schema: RJSFSchema): Validator {
  let result = cache.get(schema);
  // The interpreter attaches resolution metadata. Keep the server contract immutable.
  if (!result) { result = new Validator(structuredClone(schema) as Schema, draftOf(schema), false); cache.set(schema, result); }
  return result;
}
const validator: ValidatorType = {
  rawValidation<Result>(schema: RJSFSchema, data?: unknown) {
    try {
      const result = interpreter(schema).validate(data);
      const errors: ErrorObject[] = result.errors.map(error => ({ keyword: error.keyword,
        instancePath: error.instanceLocation.replace(/^#/, ""), schemaPath: error.keywordLocation,
        message: error.error, params: {} }));
      return { errors: errors as Result[] };
    } catch (reason) { return { validationError: reason instanceof Error ? reason : new Error(String(reason)) }; }
  },
  validateFormData(data, schema, customValidate, transformErrors, uiSchema) {
    return processRawValidationErrors(validator, validator.rawValidation<ErrorObject>(schema, data), data,
      schema, customValidate, transformErrors, uiSchema);
  },
  isValid(schema, data, rootSchema) {
    try {
      if (schema === rootSchema) return interpreter(schema).validate(data).valid;
      let byRoot = fragments.get(schema);
      if (!byRoot) { byRoot = new WeakMap(); fragments.set(schema, byRoot); }
      let check = byRoot.get(rootSchema);
      if (!check) {
        check = new Validator(withIdRefPrefix(schema) as Schema, draftOf(rootSchema), false);
        check.addSchema(structuredClone(rootSchema) as Schema, ROOT_SCHEMA_PREFIX);
        byRoot.set(rootSchema, check);
      }
      return check.validate(data).valid;
    } catch { return false; }
  },
  reset() { cache = new WeakMap(); fragments = new WeakMap(); },
};
export default validator;
