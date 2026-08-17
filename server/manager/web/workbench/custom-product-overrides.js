(() => {
  function definitions(field) {
    const all = field?.serialization?.fields || [];
    const filter = String(field?.serialization?.module_filter || "");
    return filter ? all.filter(item => String(item.module || "") === filter) : all;
  }

  function fieldMeta(field, value) {
    return definitions(field).find(item => String(item.value) === String(value)) || {};
  }

  function belongs(field, row) {
    const filter = String(field?.serialization?.module_filter || "");
    if (!filter) return true;
    return String(fieldMeta(field, row?.field).module || "") === filter;
  }

  function scopedRows(field, rows) {
    return (Array.isArray(rows) ? rows : []).filter(row => row && belongs(field, row));
  }

  function replaceScopedRows(field, allRows, nextRows) {
    const retained = (Array.isArray(allRows) ? allRows : []).filter(row => !belongs(field, row));
    const meaningful = nextRows.filter(row => (
      row && (String(row.product || "").trim() || String(row.field || "").trim()
        || row.value !== "" && row.value != null)
    ));
    return [...retained, ...meaningful];
  }

  function input(type, value, placeholder, disabled, onChange) {
    const control = document.createElement("input");
    control.type = type;
    control.value = value ?? "";
    control.placeholder = placeholder || "";
    control.disabled = Boolean(disabled);
    control.addEventListener("change", () => onChange(control.value));
    return control;
  }

  function valueControl(meta, value, disabled, onChange, context, name = "custom-product-value") {
    if (meta.value_type === "select") {
      const picker = FTTestChoicePicker.create(context, {
        className: "test-choice-picker",
        compact: true,
        name,
        multi: false,
        disabled,
        items: (meta.value_options || []).map(raw => {
          const optionValue = String(Array.isArray(raw) ? raw[0] : raw.value ?? "");
          const label = String(Array.isArray(raw) ? raw[1] : raw.label ?? optionValue);
          return {value: optionValue, label, description: raw.description || label};
        }),
        selected: [String(value ?? "")],
        onChange: next => onChange(next[0] ?? ""),
      });
      return picker.element;
    }
    if (meta.value_type === "boolean") {
      const picker = FTTestChoicePicker.create(context, {
        className: "test-choice-picker",
        compact: true,
        name,
        multi: false,
        disabled,
        items: [
          {value: "true", label: context.t("是"), description: context.t("启用")},
          {value: "false", label: context.t("否"), description: context.t("停用")},
        ],
        selected: [String(Boolean(value))],
        onChange: next => onChange(next[0] === "true"),
      });
      return picker.element;
    }
    return input(meta.value_type === "number" ? "number" : "text", value, "值", disabled, raw => {
      onChange(meta.value_type === "number" && raw !== "" ? Number(raw) : raw);
    });
  }

  function activationPatch(manifest, field, rows) {
    if (field?.serialization?.module_filter) return {};
    const modules = new Set(rows.map(row => fieldMeta(field, row.field).module).filter(Boolean));
    const patch = {};
    for (const editor of Object.values(manifest?.defaults || {})) {
      const serialization = editor?.serialization || {};
      if (serialization.kind !== "custom_product_overrides"
        || !modules.has(serialization.module_filter)) continue;
      for (const [key, values] of Object.entries(serialization.module_editor?.mode_when || {})) {
        if (Array.isArray(values) && values.length) patch[key] = values[0];
      }
    }
    return patch;
  }

  function render(options) {
    const {key, field, manifest, values, context, disabled, onPatch} = options;
    const storageKey = field?.serialization?.storage_key || key;
    const root = document.createElement("div");
    root.className = "custom-product-overrides";
    const table = document.createElement("div");
    table.className = "custom-product-rows";
    const add = document.createElement("button");
    add.type = "button"; add.textContent = context.t("添加字段");
    add.disabled = Boolean(disabled || !definitions(field).length);

    const commit = rows => {
      const all = replaceScopedRows(field, values[storageKey], rows);
      onPatch({[storageKey]: all, ...activationPatch(manifest, field, all)});
    };
    const rows = scopedRows(field, values[storageKey]).map(row => ({...row}));
    if (!rows.length) {
      const empty = document.createElement("small");
      empty.textContent = disabled
        ? context.t("当前模式使用自动字段") : context.t("尚未覆盖产品字段");
      table.append(empty);
    }
    rows.forEach((row, index) => {
      const line = document.createElement("div");
      line.className = "custom-product-row";
      line.append(input("text", row.product, context.t("产品/合约代码"), disabled, value => {
        rows[index] = {...rows[index], product: value}; commit(rows);
      }));
      const fieldPicker = FTTestChoicePicker.create(context, {
        className: "test-choice-picker",
        compact: true,
        name: `custom-product-field-${index}`,
        multi: false,
        disabled,
        items: definitions(field).map(meta => ({
          value: meta.value,
          label: meta.label || meta.value,
          description: meta.unit || meta.label || meta.value,
        })),
        selected: [row.field || definitions(field)[0]?.value || ""],
        onChange: next => {
          const selectedField = next[0] || "";
          rows[index] = {...rows[index], field: selectedField, value: "", start: "", end: ""};
          commit(rows);
        },
      });
      line.append(fieldPicker.element);
      const selectedField = fieldPicker.values[0] || definitions(field)[0]?.value || "";
      const meta = fieldMeta(field, selectedField);
      line.append(valueControl(meta, row.value, disabled, value => {
        rows[index] = {...rows[index], value}; commit(rows);
      }, context, `custom-product-value-${index}`));
      const rangeDisabled = Boolean(disabled || meta.allow_time_range === false);
      line.append(
        input("datetime-local", row.start, context.t("开始时间"), rangeDisabled, value => {
          rows[index] = {...rows[index], start: value}; commit(rows);
        }),
        input("datetime-local", row.end, context.t("结束时间"), rangeDisabled, value => {
          rows[index] = {...rows[index], end: value}; commit(rows);
        }),
      );
      const remove = document.createElement("button");
      remove.type = "button"; remove.textContent = "×"; remove.title = context.t("删除");
      remove.disabled = Boolean(disabled);
      remove.addEventListener("click", () => { rows.splice(index, 1); commit(rows); });
      line.append(remove); table.append(line);
    });
    add.addEventListener("click", () => {
      rows.push({product: "", field: definitions(field)[0]?.value || "", value: ""});
      commit(rows);
    });
    root.append(table, add);
    return root;
  }

  window.FTCustomProductOverrides = Object.freeze({
    definitions, fieldMeta, scopedRows, replaceScopedRows, activationPatch, render,
  });
})();
