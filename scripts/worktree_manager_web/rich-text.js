(() => {
  const appendText = (parent, value) => {
    if (value) parent.append(document.createTextNode(value));
  };

  function referenceKind(target, context) {
    const raw = String(target || "");
    if (context.referenceMeta?.[raw]?.kind) return context.referenceMeta[raw].kind;
    if (/^(?:factortester-local|file):\/\//i.test(raw)
        || /^factortester:\/\/file(?:[/?#]|$)/i.test(raw)) return "file";
    if (raw.startsWith("factortester://")) {
      return raw.slice("factortester://".length).split(/[/?]/)[0].replace(/-/g, "_");
    }
    if (/^https?:/i.test(raw)) return "url";
    // Local report trees may still expose a relative path before publication
    // projection has rewritten it to factortester-local://.  Render it with
    // the same file icon instead of the generic link icon.
    if (raw && !/^[a-z][a-z0-9+.-]*:/i.test(raw) && !raw.startsWith("#")) {
      return "file";
    }
    return "reference";
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
    if (/^factortester-local:\/\//i.test(target)) {
      chip.href = "#";
      chip.dataset.localResource = target.slice("factortester-local://".length);
      chip.addEventListener("click", event => {
        event.preventDefault();
        context?.openLocalResource?.(chip.dataset.localResource, label);
      });
      parent.append(chip);
      return;
    }
    if (/^(?:file):\/\//i.test(target)
        || /^factortester:\/\/file(?:[/?#]|$)/i.test(target)) {
      chip.href = "#";
      chip.dataset.localResource = target;
      chip.addEventListener("click", event => {
        event.preventDefault();
        context?.openLocalResource?.(target, label);
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
    // Older reports may still contain a relative local path.  The public
    // projection normally converts it to factortester-local://, but keeping
    // this fallback prevents silently dropping the labelled link.
    if (!/^[a-z][a-z0-9+.-]*:/i.test(target) && !target.startsWith("#")) {
      chip.href = "#";
      chip.addEventListener("click", event => {
        event.preventDefault();
        context?.openLocalResource?.(target, label);
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
    if (/^factortester-local:\/\//i.test(target) && context.localResourcePath) {
      image.src = context.localResourcePath(target.slice("factortester-local://".length));
    } else if (/^(?:https?:|data:|blob:)/i.test(target)) {
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

  function matchingDelimiter(source, start, open, close) {
    let depth = 0;
    let escaped = false;
    for (let index = start; index < source.length; index += 1) {
      const character = source[index];
      if (escaped) {
        escaped = false;
        continue;
      }
      if (character === "\\") {
        escaped = true;
        continue;
      }
      if (character === open) depth += 1;
      if (character === close) {
        depth -= 1;
        if (depth === 0) return index;
      }
    }
    return -1;
  }

  function markdownLinkAt(source, start) {
    const image = source.startsWith("![", start);
    const labelStart = image ? start + 1 : start;
    if (source[labelStart] !== "[") return null;
    const labelEnd = matchingDelimiter(source, labelStart, "[", "]");
    if (labelEnd < 0 || source[labelEnd + 1] !== "(") return null;
    const targetEnd = matchingDelimiter(source, labelEnd + 1, "(", ")");
    if (targetEnd < 0) return null;
    return {
      end: targetEnd + 1,
      image,
      label: source.slice(labelStart + 1, labelEnd),
      target: source.slice(labelEnd + 2, targetEnd),
    };
  }

  function unescapedDelimiter(source, start, delimiter) {
    let escaped = false;
    for (let index = start; index < source.length; index += 1) {
      if (!escaped && source.startsWith(delimiter, index)) return index;
      const character = source[index];
      if (escaped) {
        escaped = false;
        continue;
      }
      if (character === "\\") {
        escaped = true;
        continue;
      }
    }
    return -1;
  }

  // `$F`, `$Rev`, and the other `$...` pieces are FactorExpr metadata, not
  // TeX.  Keep them as identifiers when they are not already inside a link.
  function isFactorAliasToken(source, index) {
    return /^\$(?:F|Rev|RF|COMMON)(?::|=|_|\b)/i.test(source.slice(index));
  }

  function inline(value, context = {}) {
    const source = String(value ?? "");
    const fragment = document.createDocumentFragment();
    let plain = "";
    const flushPlain = () => {
      appendText(fragment, plain);
      plain = "";
    };
    let index = 0;
    while (index < source.length) {
      const link = (source[index] === "[" || source.startsWith("![", index))
        ? markdownLinkAt(source, index) : null;
      if (link) {
        flushPlain();
        if (link.image) appendImage(fragment, link.label, link.target, context);
        else appendLink(fragment, link.label, link.target, context);
        index = link.end;
        continue;
      }
      if (source[index] === "`") {
        const end = unescapedDelimiter(source, index + 1, "`");
        if (end >= 0) {
          flushPlain();
          const code = document.createElement("code");
          code.className = "inline";
          code.textContent = source.slice(index + 1, end);
          fragment.append(code);
          index = end + 1;
          continue;
        }
      }
      if (source.startsWith("\\(", index)) {
        const end = unescapedDelimiter(source, index + 2, "\\)");
        if (end >= 0) {
          flushPlain();
          renderMath(fragment, source.slice(index + 2, end));
          index = end + 2;
          continue;
        }
      }
      if (source[index] === "$" && !isFactorAliasToken(source, index)
          && !/\s/.test(source[index + 1] || "")) {
        const end = unescapedDelimiter(source, index + 1, "$");
        if (end > index + 1) {
          flushPlain();
          renderMath(fragment, source.slice(index + 1, end));
          index = end + 1;
          continue;
        }
      }
      const emphasis = source.startsWith("**", index) || source.startsWith("__", index)
        ? source.slice(index, index + 2) : "";
      if (emphasis) {
        const end = unescapedDelimiter(source, index + 2, emphasis);
        if (end > index + 2) {
          flushPlain();
          const strong = document.createElement("strong");
          strong.append(inline(source.slice(index + 2, end), context));
          fragment.append(strong);
          index = end + 2;
          continue;
        }
      }
      plain += source[index];
      index += 1;
    }
    flushPlain();
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
    const parseTableCells = line => {
      const source = line.trim();
      const start = source.startsWith("|") ? 1 : 0;
      const end = source.endsWith("|") ? source.length - 1 : source.length;
      const cells = [];
      let cell = "";
      let code = false;
      let bracketDepth = 0;
      let parenDepth = 0;
      let math = null;
      let escaped = false;
      for (let index = start; index < end; index += 1) {
        const character = source[index];
        if (escaped) {
          cell += character;
          escaped = false;
          continue;
        }
        if (character === "\\") {
          if (source.startsWith("\\(", index) && !code && !math) math = "paren";
          else if (source.startsWith("\\)", index) && math === "paren") math = null;
          else {
            cell += character;
            escaped = true;
            continue;
          }
          cell += character;
          if (source[index + 1] === "(" || source[index + 1] === ")") {
            cell += source[index + 1]; index += 1;
          }
          continue;
        }
        if (character === "`") {
          code = !code;
          cell += character;
          continue;
        }
        if (!code && source.startsWith("$$", index)) {
          math = math === "dollar" ? null : "dollar";
          cell += "$$"; index += 1;
          continue;
        }
        if (!code && !math && character === "$" && !isFactorAliasToken(source, index)
            && !/\s/.test(source[index + 1] || "")) {
          math = "single-dollar";
          cell += character;
          continue;
        }
        if (!code && math === "single-dollar" && character === "$") {
          math = null;
          cell += character;
          continue;
        }
        if (!code && !math && character === "[") bracketDepth += 1;
        if (!code && !math && character === "]" && bracketDepth > 0) bracketDepth -= 1;
        if (!code && !math && bracketDepth === 0 && character === "(") parenDepth += 1;
        if (!code && !math && bracketDepth === 0 && character === ")" && parenDepth > 0) parenDepth -= 1;
        const factorAliasPipe = character === "|"
          && /\$F(?::|=|\b)/i.test(cell)
          && /^\|\$(?:Rev|RF|COMMON)(?::|=|_|\b)/i.test(source.slice(index));
        if (character === "|" && !factorAliasPipe && !code && !math
            && bracketDepth === 0 && parenDepth === 0) {
          cells.push(cell.trim());
          cell = "";
        } else {
          cell += character;
        }
      }
      cells.push(cell.trim());
      return cells;
    };
    const isTableDivider = (cells, count) => cells.length > 0 && cells.length <= count
      && cells.every(cell => /^:?-+:?$/.test(cell.trim()));
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
      if (raw.includes("|") && lines[lineIndex + 1]?.includes("|")) {
        const headerCells = parseTableCells(raw);
        const dividerCells = parseTableCells(lines[lineIndex + 1]);
        if (headerCells.length > 0 && isTableDivider(dividerCells, headerCells.length)) {
          const rows = [];
          let cursor = lineIndex + 2;
          while (cursor < lines.length && lines[cursor].includes("|")) {
            const row = parseTableCells(lines[cursor]);
            if (row.length !== headerCells.length) break;
            rows.push(row);
            cursor += 1;
          }
          endList();
          const shell = document.createElement("div");
          shell.className = "table-shell markdown-table-shell";
          const table = document.createElement("table");
          const head = table.createTHead().insertRow();
          headerCells.forEach(cell => {
            const th = document.createElement("th"); th.append(inline(cell, context)); head.append(th);
          });
          const body = table.createTBody();
          rows.forEach(cells => {
            const row = body.insertRow();
            cells.forEach(cell => { const td = row.insertCell(); td.append(inline(cell, context)); });
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

  window.FTRichText = {inline, blocks, appendLink};
})();
