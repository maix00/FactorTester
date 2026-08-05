(() => {
  const appendText = (parent, value) => parent.append(document.createTextNode(value));

  function appendLink(parent, label, target, context) {
    if (target.startsWith("factortester-local://")) {
      const button = document.createElement("a");
      button.href = "#";
      button.textContent = label;
      button.dataset.localResource = target.slice("factortester-local://".length);
      button.addEventListener("click", event => {
        event.preventDefault();
        context?.openLocalResource?.(button.dataset.localResource, label);
      });
      parent.append(button);
      return;
    }
    if (/^https?:\/\//i.test(target)) {
      const anchor = document.createElement("a");
      anchor.href = target;
      anchor.target = "_blank";
      anchor.rel = "noopener noreferrer";
      anchor.textContent = label;
      parent.append(anchor);
      return;
    }
    if (target.startsWith("factortester://")) {
      const anchor = document.createElement("a");
      anchor.href = "#";
      anchor.textContent = label;
      anchor.addEventListener("click", event => {
        event.preventDefault();
        context?.openReference?.(target, label);
      });
      parent.append(anchor);
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
    for (const raw of lines) {
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
