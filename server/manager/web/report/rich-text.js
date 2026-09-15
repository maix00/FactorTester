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
    const legacyFactorSnapshot = /^factortester:\/\/factor\/(?:factor|factor-family|factor-set)%3Av1%3A/i
      .test(String(target || ""));
    if (legacyFactorSnapshot) {
      const value = document.createElement("span");
      value.className = "reference-chip reference-factor reference-legacy";
      value.dataset.referenceKind = kind;
      value.dataset.referenceTarget = target;
      const icon = FTIcons.node(FTIcons.reference(kind, target), "reference-icon");
      const text = document.createElement("span");
      text.className = "reference-title";
      text.textContent = context.referenceMeta?.[target]?.label || label;
      value.append(icon, text);
      parent.append(value);
      return;
    }
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
        if (context.nativeReference) {
          context?.openReference?.(
            `factortester://file/${encodeURIComponent(chip.dataset.localResource)}`,
            label,
          );
        } else {
          context?.openLocalResource?.(chip.dataset.localResource, label);
        }
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
        if (context.nativeReference && /^factortester:\/\/file(?:[/?#]|$)/i.test(target)) {
          context?.openReference?.(target, label);
        } else {
          context?.openLocalResource?.(target, label);
        }
      });
      parent.append(chip);
      return;
    }
    if (/^https?:\/\//i.test(target)) {
      // Web URLs are browser navigation, not FactorTester object references.
      // Keep the real href even when a WebKit object-reference bridge exists.
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
    const setBlob = blob => {
      if (!blob || !image.isConnected) return;
      const url = URL.createObjectURL(blob);
      image.src = url;
      image.addEventListener("load", () => URL.revokeObjectURL(url), {once: true});
    };
    if (/^factortester-local:\/\//i.test(target) && context.loadLocalResource) {
      parent.append(image);
      Promise.resolve(context.loadLocalResource(
        target.slice("factortester-local://".length),
      )).then(setBlob).catch(() => {
        image.alt = `${alt || target} (${context.t?.("读取失败") || "读取失败"})`;
      });
      return;
    }
    if (/^factortester-local:\/\//i.test(target) && context.localResourcePath) {
      image.src = context.localResourcePath(target.slice("factortester-local://".length));
    } else if (/^(?:https?:|data:|blob:)/i.test(target)) {
      image.src = target;
    } else if (context.loadReportAsset) {
      parent.append(image);
      Promise.resolve(context.loadReportAsset(target)).then(setBlob).catch(() => {
        image.alt = `${alt || target} (${context.t?.("读取失败") || "读取失败"})`;
      });
      return;
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
      window.FTUI?.renderMath?.(element, latex, {display: display === true});
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

  window.FTRichText = {inline, appendLink, renderMath, isFactorAliasToken};
})();
