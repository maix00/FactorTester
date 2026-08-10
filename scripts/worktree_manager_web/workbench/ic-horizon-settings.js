(() => {
  function tokens(value) {
    const source = Array.isArray(value) ? value : String(value || "").split(/[\s,，;；]+/);
    return source.map(item => String(item).trim()).filter(Boolean);
  }

  function unique(values) {
    return values.filter((value, index) => values.indexOf(value) === index);
  }

  function normalizeHorizon(value) {
    const raw = value && typeof value === "object" ? value : {};
    const sampling = String(raw.sampling || "").toLowerCase();
    if (sampling === "scale_aware" || sampling === "auto") {
      return {sampling: "scale_aware"};
    }
    const bases = unique(tokens(raw.bases || ["signal"]));
    const multipliers = unique(tokens(raw.multipliers || [1])
      .map(Number).filter(item => Number.isInteger(item) && item > 0));
    return {
      sampling: "explicit",
      bases: bases.length ? bases : ["signal"],
      multipliers: multipliers.length ? multipliers : [1],
    };
  }

  function normalizeDelays(value) {
    const delays = unique(tokens(value).map(Number)
      .filter(item => Number.isInteger(item) && item >= 0));
    return delays.length ? delays : [0];
  }

  function normalizeDecayLags(value) {
    const lags = unique(tokens(value).map(Number)
      .filter(item => Number.isInteger(item) && item > 0));
    return lags.length ? lags : [5];
  }

  function normalizeSettingValues(manifest, values) {
    for (const [key, field] of Object.entries(manifest?.defaults || {})) {
      const target = field?.serialization?.storage_key || key;
      if (!Object.prototype.hasOwnProperty.call(values || {}, target)) continue;
      if (field.control_template === "ic_horizon_grid") {
        values[target] = normalizeHorizon(values[target]);
      } else if (field.control_template === "ic_delay_grid") {
        values[target] = normalizeDelays(values[target]);
      } else if (field.control_template === "ic_decay_grid") {
        values[target] = normalizeDecayLags(values[target]);
      }
    }
    return values;
  }

  function listEditor(options) {
    const {labelText, value, normalize, placeholder, context, disabled, onChange} = options;
    let current = normalize(value);
    const root = document.createElement("div");
    root.className = "ic-grid-editor";
    const title = document.createElement("small");
    title.textContent = labelText;
    const chips = document.createElement("div");
    chips.className = "ic-grid-values";
    const inputRow = document.createElement("div");
    inputRow.className = "ic-grid-add";
    const input = document.createElement("input");
    input.type = "text";
    input.placeholder = placeholder;
    input.disabled = disabled;
    const add = document.createElement("button");
    add.type = "button";
    add.textContent = "+";
    add.title = context.t("添加");
    add.disabled = disabled;

    const commit = next => {
      current = normalize(next);
      draw();
      onChange(current);
    };
    const draw = () => {
      const nodes = current.map((item, index) => {
        const chip = document.createElement("span");
        chip.className = "ic-grid-value";
        const text = document.createElement("span");
        text.textContent = String(item);
        const remove = document.createElement("button");
        remove.type = "button";
        remove.textContent = "×";
        remove.title = context.t("删除");
        remove.disabled = disabled;
        remove.addEventListener("click", () => commit(
          current.filter((_, itemIndex) => itemIndex !== index),
        ));
        chip.append(text, remove);
        return chip;
      });
      chips.replaceChildren(...nodes);
    };
    const append = () => {
      const candidates = tokens(input.value);
      if (!candidates.length) return;
      commit([...current, ...candidates]);
      input.value = "";
      input.focus?.();
    };
    add.addEventListener("click", append);
    input.addEventListener("keydown", event => {
      if (event.key !== "Enter") return;
      event.preventDefault();
      append();
    });
    draw();
    inputRow.append(input, add);
    root.append(title, chips, inputRow);
    return root;
  }

  function renderHorizon({value, context, disabled, onChange}) {
    const normalized = normalizeHorizon(value);
    let explicit = normalized.sampling === "explicit"
      ? normalized : {sampling: "explicit", bases: ["signal"], multipliers: [1]};
    const root = document.createElement("div");
    root.className = "ic-grid-control";
    const mode = document.createElement("select");
    for (const [key, label] of [
      ["scale_aware", context.t("按因子频率自动生成")],
      ["explicit", context.t("手动冻结收益期网格")],
    ]) {
      const option = document.createElement("option");
      option.value = key;
      option.textContent = label;
      mode.append(option);
    }
    mode.value = normalized.sampling;
    mode.disabled = disabled;
    const manual = document.createElement("div");
    manual.className = "ic-grid-manual";
    const bases = listEditor({
      labelText: context.t("收益期基准"), value: explicit.bases,
      normalize: value => normalizeHorizon({...explicit, bases: value}).bases,
      placeholder: context.t("输入 signal、1m 或 1d 后回车"), context, disabled,
      onChange: next => {
        explicit = normalizeHorizon({...explicit, bases: next});
        onChange(explicit);
      },
    });
    const multiples = listEditor({
      labelText: context.t("正整数倍数"), value: explicit.multipliers,
      normalize: value => normalizeHorizon({...explicit, multipliers: value}).multipliers,
      placeholder: context.t("输入 1、5 或 20 后回车"), context, disabled,
      onChange: next => {
        explicit = normalizeHorizon({...explicit, multipliers: next});
        onChange(explicit);
      },
    });
    manual.append(bases, multiples);
    manual.hidden = normalized.sampling !== "explicit";
    mode.addEventListener("change", () => {
      manual.hidden = mode.value !== "explicit";
      onChange(mode.value === "explicit" ? explicit : {sampling: "scale_aware"});
    });
    root.append(mode, manual);
    return root;
  }

  function renderDelays({value, context, disabled, onChange}) {
    const root = document.createElement("div");
    root.className = "ic-grid-control";
    const delays = listEditor({
      labelText: context.t("信号 bar 延迟"), value, normalize: normalizeDelays,
      placeholder: context.t("输入 0、1 或 2 后回车"), context, disabled, onChange,
    });
    const note = document.createElement("small");
    note.textContent = context.t("每个延迟都会与每个收益期组合计算");
    root.append(delays, note);
    return root;
  }

  function renderDecayLags({value, context, disabled, onChange}) {
    const root = document.createElement("div");
    root.className = "ic-grid-control";
    const lags = listEditor({
      labelText: context.t("正整数 Lag"), value, normalize: normalizeDecayLags,
      placeholder: context.t("输入 1、2、5 或 10 后回车"), context, disabled, onChange,
    });
    const note = document.createElement("small");
    note.textContent = context.t("按每 N 个 IC 观测重采样并比较均值、波动、IR 与 t 统计；不改变入场延迟");
    root.append(lags, note);
    return root;
  }

  window.FTICHorizonSettings = Object.freeze({
    normalizeDecayLags, normalizeDelays, normalizeHorizon, normalizeSettingValues,
    renderDecayLags, renderDelays, renderHorizon, tokens,
  });
})();
