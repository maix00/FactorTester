(() => {
  const appendText = (parent, value) => parent.append(document.createTextNode(value));

  function referenceKind(target, context) {
    const raw = String(target || "");
    if (context.referenceMeta?.[raw]?.kind) return context.referenceMeta[raw].kind;
    if (raw.startsWith("factortester://")) return raw.slice("factortester://".length).split(/[/?]/)[0];
    return /^https?:/i.test(raw) ? "url" : "reference";
  }

  function appendLink(parent, label, target, context) {
    const kind = referenceKind(target, context);
    const chip = document.createElement("a");
    chip.className = `reference-chip reference-${kind.replace(/[^a-z0-9_-]/gi, "")}`;
    chip.dataset.referenceKind = kind;
    chip.dataset.referenceTarget = target;
    const icon = document.createElement("span");
    icon.className = "reference-icon";
    icon.textContent = ({factor:"ƒ", factor_set:"ƒ", factor_family:"ƒ", evidence:"▧", job:"▧", product:"◇", contract:"◇", profile:"♙", trial_plan:"▤", run_spec:"▤", obligation:"✓", requirement:"✓", url:"↗"})[kind] || "•";
    const text = document.createElement("span");
    text.className = "reference-title";
    text.textContent = context.referenceMeta?.[target]?.label || label;
    chip.append(icon, text);
    if (target.startsWith("factortester-local://")) {
      chip.href = "#";
      chip.dataset.localResource = target.slice("factortester-local://".length);
      chip.addEventListener("click", event => {
        event.preventDefault();
        context?.openLocalResource?.(chip.dataset.localResource, label);
      });
      parent.append(chip);
      return;
    }
    if (/^https?:\/\//i.test(target)) {
      chip.href = target; chip.target = "_blank"; chip.rel = "noopener noreferrer";
      parent.append(chip);
      return;
    }
    if (target.startsWith("factortester://")) {
      chip.href = "#";
      chip.addEventListener("click", event => {
        event.preventDefault();
        context?.openReference?.(target, label);
      });
      parent.append(chip);
      return;
    }
    appendText(parent, label);
  }

  function inline(value, context = {}) {
    const fragment = document.createDocumentFragment();
    const pattern = /(\[[^\]]+\]\([^)]+\)|`[^`\n]+`|\\\([^\n]+?\\\))/g;
    let index = 0;
    for (const match of value.matchAll(pattern)) {
      appendText(fragment, value.slice(index, match.index));
      const token = match[0];
      if (token.startsWith("`")) {
        const code = document.createElement("code");
        code.className = "inline";
        code.textContent = token.slice(1, -1);
        fragment.append(code);
      } else if (token.startsWith("\\(")) {
        const span = document.createElement("span");
        span.className = "inline-math";
        try {
          katex.render(token.slice(2, -2), span, {throwOnError: false});
        } catch (_) {
          span.textContent = token;
        }
        fragment.append(span);
      } else {
        const parts = /^\[([^\]]+)\]\(([^)]+)\)$/.exec(token);
        if (parts) appendLink(fragment, parts[1], parts[2], context);
      }
      index = match.index + token.length;
    }
    appendText(fragment, value.slice(index));
    return fragment;
  }

  function blocks(value, context = {}) {
    const container = document.createDocumentFragment();
    const lines = String(value || "").split(/\r?\n/);
    let list = null;
    let ordered = false;
    const endList = () => { list = null; };
    for (let lineIndex = 0; lineIndex < lines.length; lineIndex += 1) {
      const raw = lines[lineIndex];
      if (raw.includes("|") && lines[lineIndex + 1]?.includes("|") && /^\s*\|?\s*:?-{2,}/.test(lines[lineIndex + 1])) {
        // Markdown tables are parsed as one report component so links and
        // formulas in cells use the same inline renderer.
        const tableLines = [];
        let cursor = lineIndex;
        while (cursor < lines.length && lines[cursor].includes("|")) tableLines.push(lines[cursor++]);
        if (tableLines.length >= 2) {
          endList();
          const shell = document.createElement("div"); shell.className = "table-shell markdown-table-shell";
          const table = document.createElement("table");
          const parse = line => line.trim().replace(/^\|/, "").replace(/\|$/, "").split(/\s*\|\s*/);
          const head = table.createTHead().insertRow(); parse(tableLines[0]).forEach(cell => { const th = document.createElement("th"); th.append(inline(cell, context)); head.append(th); });
          const body = table.createTBody(); tableLines.slice(2).forEach(line => { const tr = body.insertRow(); parse(line).forEach(cell => { const td = tr.insertCell(); td.append(inline(cell, context)); }); });
          shell.append(table); container.append(shell);
          lineIndex = cursor - 1;
          continue;
        }
      }
      const display = /^\s*(?:\$\$(.+)\$\$|\\\[(.+)\\\])\s*$/.exec(raw);
      if (display) {
        endList();
        const math = document.createElement("div");
        math.className = "display-math";
        try { katex.render(display[1] || display[2], math, {displayMode: true, throwOnError: false}); }
        catch (_) { math.textContent = display[1] || display[2]; }
        container.append(math);
        continue;
      }
      const bullet = /^\s*[-*]\s+(.+)$/.exec(raw);
      const number = /^\s*\d+[.)]\s+(.+)$/.exec(raw);
      if (bullet || number) {
        const wantsOrdered = Boolean(number);
        if (!list || ordered !== wantsOrdered) {
          list = document.createElement(wantsOrdered ? "ol" : "ul");
          ordered = wantsOrdered;
          container.append(list);
        }
        const item = document.createElement("li");
        item.append(inline((bullet || number)[1], context));
        list.append(item);
        continue;
      }
      endList();
      if (!raw.trim()) continue;
      const paragraph = document.createElement("p");
      paragraph.append(inline(raw, context));
      container.append(paragraph);
    }
    return container;
  }

  window.FTRichText = {inline, blocks};
})();
