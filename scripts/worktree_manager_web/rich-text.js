(() => {
  const appendText = (parent, value) => {
    if (value) parent.append(document.createTextNode(value));
  };

  function referenceKind(target, context) {
    const raw = String(target || "");
    if (context.referenceMeta?.[raw]?.kind) return context.referenceMeta[raw].kind;
    if (raw.startsWith("factortester://")) {
      return raw.slice("factortester://".length).split(/[/?]/)[0].replace(/-/g, "_");
    }
    return /^https?:/i.test(raw) ? "url" : "reference";
  }

  function appendLink(parent, label, target, context) {
    const kind = referenceKind(target, context);
    const chip = document.createElement("a");
    chip.className = `reference-chip reference-${kind.replace(/-/g, "_").replace(/[^a-z0-9_]/gi, "")}`;
    chip.dataset.referenceKind = kind;
    chip.dataset.referenceTarget = target;
    const icon = FTIcons.node(FTIcons.reference(kind, target), "reference-icon");
    icon.dataset.referenceKind = kind;
    const text = document.createElement("span");
    text.className = "reference-title";
    text.textContent = context.referenceMeta?.[target]?.label || label;
    chip.append(icon, text);
    // A browser may scroll a link into view before dispatching `click`.
    // Capture the report viewport during pointerdown so opening a detail tab
    // never replaces the user's original reading position with that interim
    // scroll position.
    chip.addEventListener("pointerdown", () => context?.captureScrollPosition?.());
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

  function appendImage(parent, alt, target, context) {
    const image = document.createElement("img");
    image.className = "report-image inline-report-image";
    image.alt = alt || "";
    image.loading = "lazy";
    if (/^(?:https?:|data:|blob:)/i.test(target)) {
      image.src = target;
    } else if (context.reportAssetPath) {
      image.src = context.reportAssetPath(target);
    } else {
      image.alt = alt || target;
    }
    parent.append(image);
  }

  function renderMath(parent, latex, display = false) {
    const element = document.createElement(display ? "div" : "span");
    element.className = display ? "display-math" : "inline-math";
    try {
      katex.render(latex, element, {displayMode: display, throwOnError: false});
    } catch (_) {
      element.textContent = latex;
    }
    parent.append(element);
  }

  function inline(value, context = {}) {
    const source = String(value ?? "");
    const fragment = document.createDocumentFragment();
    // Images and links are first-class tokens. Dollar math is deliberately
    // bounded by a closing dollar, so identifiers such as `$F=1d` remain text.
    const pattern = /(!\[[^\]\n]*\]\([^)]+\)|\[[^\]\n]+\]\([^)]+\)|`[^`\n]+`|\\\([^\n]+?\\\)|\$(?!\s)(?:\\.|[^$\n])+?\$|\*\*(?:\\.|[^*\n])+?\*\*|__(?:\\.|[^_\n])+?__)/g;
    let index = 0;
    for (const match of source.matchAll(pattern)) {
      appendText(fragment, source.slice(index, match.index));
      const token = match[0];
      if (token.startsWith("![")) {
        const parts = /^!\[([^\]]*)\]\(([^)]+)\)$/.exec(token);
        if (parts) appendImage(fragment, parts[1], parts[2], context);
      } else if (token.startsWith("`")) {
        const code = document.createElement("code");
        code.className = "inline";
        code.textContent = token.slice(1, -1);
        fragment.append(code);
      } else if (token.startsWith("\\(")) {
        renderMath(fragment, token.slice(2, -2));
      } else if (token.startsWith("$") && token.endsWith("$")) {
        renderMath(fragment, token.slice(1, -1));
      } else if (token.startsWith("**") || token.startsWith("__")) {
        const strong = document.createElement("strong");
        strong.append(inline(token.slice(2, -2), context));
        fragment.append(strong);
      } else {
        const parts = /^\[([^\]]+)\]\(([^)]+)\)$/.exec(token);
        if (parts) appendLink(fragment, parts[1], parts[2], context);
      }
      index = match.index + token.length;
    }
    appendText(fragment, source.slice(index));
    return fragment;
  }

  function renderDisplayMath(parent, latex) {
    renderMath(parent, String(latex || ""), true);
  }

  function blocks(value, context = {}) {
    const container = document.createDocumentFragment();
    const lines = String(value ?? "").split(/\r?\n/);
    let list = null;
    let ordered = false;
    const endList = () => { list = null; };
    const parseTableCells = line => line.trim().replace(/^\|/, "").replace(/\|$/, "").split(/\s*\|\s*/);
    for (let lineIndex = 0; lineIndex < lines.length; lineIndex += 1) {
      const raw = lines[lineIndex];
      const trimmed = raw.trim();
      if (trimmed === "$$" || trimmed === "\\[") {
        endList();
        const close = trimmed === "$$" ? "$$" : "\\]";
        const formula = [];
        lineIndex += 1;
        while (lineIndex < lines.length && lines[lineIndex].trim() !== close) {
          formula.push(lines[lineIndex]); lineIndex += 1;
        }
        renderDisplayMath(container, formula.join("\n"));
        continue;
      }
      if (raw.includes("|") && lines[lineIndex + 1]?.includes("|")
          && /^\s*\|?\s*:?-{2,}/.test(lines[lineIndex + 1])) {
        const tableLines = [];
        let cursor = lineIndex;
        while (cursor < lines.length && lines[cursor].includes("|")) tableLines.push(lines[cursor++]);
        if (tableLines.length >= 2) {
          endList();
          const shell = document.createElement("div");
          shell.className = "table-shell markdown-table-shell";
          const table = document.createElement("table");
          const head = table.createTHead().insertRow();
          parseTableCells(tableLines[0]).forEach(cell => {
            const th = document.createElement("th"); th.append(inline(cell, context)); head.append(th);
          });
          const body = table.createTBody();
          tableLines.slice(2).forEach(line => {
            const row = body.insertRow();
            parseTableCells(line).forEach(cell => { const td = row.insertCell(); td.append(inline(cell, context)); });
          });
          shell.append(table); container.append(shell);
          lineIndex = cursor - 1;
          continue;
        }
      }
      const display = /^\s*(?:\$\$(.+)\$\$|\\\[(.+)\\\])\s*$/.exec(raw);
      if (display) {
        endList(); renderDisplayMath(container, display[1] || display[2]); continue;
      }
      const bullet = /^\s*[-*]\s+(.+)$/.exec(raw);
      const number = /^\s*\d+[.)]\s+(.+)$/.exec(raw);
      if (bullet || number) {
        const wantsOrdered = Boolean(number);
        if (!list || ordered !== wantsOrdered) {
          list = document.createElement(wantsOrdered ? "ol" : "ul");
          ordered = wantsOrdered; container.append(list);
        }
        const item = document.createElement("li");
        item.append(inline((bullet || number)[1], context)); list.append(item); continue;
      }
      endList();
      if (!trimmed) continue;
      const paragraph = document.createElement("p"); paragraph.append(inline(raw, context)); container.append(paragraph);
    }
    return container;
  }

  window.FTRichText = {inline, blocks};
})();
