(() => {
  function renderDisplayMath(parent, latex) {
    FTRichText.renderMath(parent, String(latex || ""), true);
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
        if (!code && !math && character === "$"
            && !FTRichText.isFactorAliasToken(source, index)
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
          const shell = FTReportTables.render({
            columns: headerCells,
            rows,
            context,
            className: "table-shell markdown-table-shell",
            renderHeader: cell => FTRichText.inline(cell, context),
            renderCell: cell => FTRichText.inline(cell, context),
            values: cells => cells,
          });
          container.append(shell);
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
        item.append(FTRichText.inline((bullet || number)[1], context));
        list.append(item); continue;
      }
      endList();
      if (!trimmed) continue;
      const paragraph = document.createElement("p");
      paragraph.append(FTRichText.inline(raw, context));
      container.append(paragraph);
    }
    return container;
  }

  window.FTRichText.blocks = blocks;
})();
