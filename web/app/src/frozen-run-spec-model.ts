type RecordValue = Record<string, unknown>;

function isRecord(value: unknown): value is RecordValue {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

/** Split the owner-scoped RunSpec response without changing the frozen contract. */
export function frozenRunSpecSections(value: unknown, hash?: string): {
  identity: RecordValue;
  configuration: unknown;
  hasConfiguration: boolean;
  options: unknown;
} {
  const record = isRecord(value) ? value : {};
  const wrapped = isRecord(record.run_spec) &&
    ("run_spec_hash" in record || "configuration_id" in record || "complete_parameters_json" in record);
  const contract = wrapped ? record.run_spec as RecordValue : value;
  const identity: RecordValue = {};
  if (wrapped) {
    for (const [key, item] of Object.entries(record)) {
      // This is the presentation's JSON serialization of run_spec, already shown below.
      if (key !== "run_spec" && key !== "complete_parameters_json") identity[key] = item;
    }
  }
  if (!("run_spec_hash" in identity) && hash) identity.run_spec_hash = hash;

  if (!isRecord(contract)) {
    return { identity, configuration: undefined, hasConfiguration: false, options: contract };
  }
  const hasConfiguration = Object.prototype.hasOwnProperty.call(contract, "configuration");
  const { configuration, ...options } = contract;
  return { identity, configuration, hasConfiguration, options };
}
