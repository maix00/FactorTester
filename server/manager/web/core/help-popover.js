(() => {
  const state = {
    stack: [],
    sequence: 0,
    listenersInstalled: false,
  };
  const loaders = new Map();

  function text(value) {
    return value == null ? "" : String(value);
  }

  function isNode(value) {
    return Boolean(value && typeof value === "object" && (
      value.nodeType || typeof value.append === "function"
    ));
  }

  function normalize(help, options = {}) {
    if (typeof help === "string" || help == null) {
      return {mode: options.mode || "bubble", text: text(help).trim()};
    }
    if (isNode(help)) return {mode: "overlay", content: help};
    if (typeof help !== "object") {
      return {mode: options.mode || "bubble", text: text(help).trim()};
    }
    const descriptor = {...help};
    descriptor.mode = descriptor.mode || (
      descriptor.content || typeof descriptor.render === "function"
        ? "overlay" : "bubble"
    );
    descriptor.text = text(
      descriptor.text ?? descriptor.description ?? descriptor.body,
    ).trim();
    return descriptor;
  }

  function closeEntry(entry, options = {}) {
    const index = state.stack.indexOf(entry);
    if (index < 0) return;
    // Nested entries opened from this popup are closed first.
    state.stack.slice(index).reverse().forEach(item => {
      item.button.setAttribute("aria-expanded", "false");
      item.button.removeAttribute?.("aria-controls");
      item.button.removeAttribute?.("aria-describedby");
      if (item.popup?.open && typeof item.popup.close === "function") {
        item.popup.close();
      }
      item.popup?.parentNode?.removeChild(item.popup);
    });
    state.stack = state.stack.slice(0, index);
    if (options.restoreFocus && entry.button.isConnected !== false) {
      entry.button.focus?.();
    }
  }

  function close(options = {}) {
    const top = state.stack[state.stack.length - 1];
    if (!top) return;
    state.stack.slice().forEach(entry => closeEntry(entry));
    if (options.restoreFocus && top.button.isConnected !== false) {
      top.button.focus?.();
    }
  }

  function isInsideAnyPopup(node) {
    return state.stack.some(entry => entry.popup?.contains?.(node));
  }

  function positionBubble(button, popup) {
    if (!button.getBoundingClientRect || !popup.style) return;
    const rect = button.getBoundingClientRect();
    const viewportWidth = Number(window.innerWidth) || 1024;
    const viewportHeight = Number(window.innerHeight) || 768;
    const width = Math.min(360, Math.max(220, viewportWidth - 16));
    popup.style.maxWidth = `${width}px`;
    const measured = popup.getBoundingClientRect?.() || {width, height: 0};
    const gap = 8;
    const measuredWidth = Math.min(width, Number(measured.width) || width);
    const left = Math.max(8, Math.min(
      rect.left + rect.width / 2 - measuredWidth / 2,
      viewportWidth - measuredWidth - 8,
    ));
    const above = rect.top - measured.height - gap;
    const below = rect.bottom + gap;
    const top = above >= 8
      ? above : Math.min(below, viewportHeight - measured.height - 8);
    popup.style.left = `${left}px`;
    popup.style.top = `${top}px`;
  }

  function openBubble(button, descriptor) {
    const popup = document.createElement("div");
    popup.className = "ft-help-bubble";
    popup.id = `ft-help-bubble-${++state.sequence}`;
    popup.setAttribute("role", "tooltip");
    popup.textContent = descriptor.text || "";
    document.body?.append(popup);
    button.setAttribute("aria-controls", popup.id);
    button.setAttribute("aria-describedby", popup.id);
    button.setAttribute("aria-expanded", "true");
    state.stack.push({button, popup, mode: "bubble"});
    positionBubble(button, popup);
  }

  function appendOverlayContent(body, descriptor) {
    if (typeof descriptor.render === "function") {
      const rendered = descriptor.render(body);
      if (rendered && rendered !== body) body.append(rendered);
      return;
    }
    if (isNode(descriptor.content)) {
      body.append(descriptor.content);
      return;
    }
    body.textContent = descriptor.text || text(descriptor.content);
  }

  function appendLoadedContent(body, value) {
    body.replaceChildren?.();
    if (isNode(value)) body.append(value);
    else body.textContent = text(value);
  }

  function isOpen(dialog) {
    return state.stack.some(entry => entry.popup === dialog);
  }

  async function loadOverlayContent(dialog, body, descriptor) {
    const loader = typeof descriptor.load === "function"
      ? descriptor.load
      : loaders.get(descriptor.type);
    if (typeof loader !== "function") {
      appendOverlayContent(body, descriptor);
      return;
    }
    body.textContent = window.FTI18n?.t("正在读取说明…", "正在读取说明…")
      || "正在读取说明…";
    const entry = state.stack.find(item => item.popup === dialog);
    try {
      const value = await loader(descriptor, {dialog, button: entry?.button});
      if (!isOpen(dialog)) return;
      appendLoadedContent(body, value);
    } catch (error) {
      if (!isOpen(dialog)) return;
      body.textContent = error?.message
        || window.FTI18n?.t("读取说明失败", "读取说明失败")
        || "读取说明失败";
    }
  }

  function openOverlay(button, descriptor) {
    const dialog = document.createElement("dialog");
    dialog.className = "ft-help-overlay";
    dialog.id = `ft-help-overlay-${++state.sequence}`;
    dialog.dataset.ftHelp = "true";
    const card = document.createElement("div");
    card.className = "dialog-card ft-help-overlay-card";
    if (descriptor.wide === true) card.classList.add("wide");
    const closeButton = document.createElement("button");
    closeButton.type = "button";
    closeButton.className = "dialog-close";
    closeButton.textContent = "×";
    closeButton.setAttribute(
      "aria-label",
      window.FTI18n?.t("关闭", "关闭") || "关闭",
    );
    closeButton.addEventListener("click", () => {
      closeEntry(state.stack.find(entry => entry.popup === dialog) || {}, {
        restoreFocus: true,
      });
    });
    card.append(closeButton);
    if (descriptor.title) {
      const heading = document.createElement("h2");
      heading.textContent = text(descriptor.title);
      heading.id = `ft-help-overlay-heading-${++state.sequence}`;
      dialog.setAttribute("aria-labelledby", heading.id);
      card.append(heading);
    }
    const body = document.createElement("div");
    body.className = "ft-help-overlay-body";
    body.id = `ft-help-overlay-body-${++state.sequence}`;
    dialog.setAttribute("aria-describedby", body.id);
    card.append(body);
    dialog.append(card);
    dialog.addEventListener("cancel", event => {
      event.preventDefault();
      closeEntry(state.stack.find(entry => entry.popup === dialog) || {}, {
        restoreFocus: true,
      });
    });
    dialog.addEventListener("click", event => {
      if (event.target === dialog) {
        closeEntry(state.stack.find(entry => entry.popup === dialog) || {}, {
          restoreFocus: true,
        });
      }
    });
    document.body?.append(dialog);
    button.setAttribute("aria-controls", dialog.id);
    button.setAttribute("aria-expanded", "true");
    state.stack.push({button, popup: dialog, mode: "overlay"});
    if (typeof dialog.showModal === "function") dialog.showModal();
    else dialog.setAttribute("open", "");
    void loadOverlayContent(dialog, body, descriptor);
  }

  function onPointerDown(event) {
    if (!state.stack.length) return;
    if (state.stack.some(entry => entry.button === event.target)) return;
    if (isInsideAnyPopup(event.target)) return;
    close();
  }

  function onKeyDown(event) {
    if (event.key === "Escape" && state.stack.length) {
      event.preventDefault();
      closeEntry(state.stack[state.stack.length - 1], {restoreFocus: true});
    }
  }

  function reposition() {
    state.stack.forEach(entry => {
      if (entry.mode === "bubble") positionBubble(entry.button, entry.popup);
    });
  }

  function installListeners() {
    if (state.listenersInstalled) return;
    state.listenersInstalled = true;
    document.addEventListener?.("pointerdown", onPointerDown, true);
    document.addEventListener?.("keydown", onKeyDown, true);
    window.addEventListener?.("resize", reposition);
    window.addEventListener?.("scroll", reposition, true);
  }

  function create(help, options = {}) {
    const descriptor = normalize(help, options);
    const button = document.createElement("button");
    button.type = "button";
    button.className = "ft-help-icon";
    button.textContent = "?";
    button.dataset.ftHelp = "true";
    button.setAttribute(
      "aria-label",
      options.ariaLabel
        || window.FTI18n?.t("查看说明", "查看说明")
        || "查看说明",
    );
    button.setAttribute("aria-expanded", "false");
    if (descriptor.mode === "overlay") {
      button.setAttribute("aria-haspopup", "dialog");
    }
    button.addEventListener("click", event => {
      event.preventDefault();
      event.stopPropagation();
      const existing = state.stack.find(entry => entry.button === button);
      if (existing) {
        closeEntry(existing, {restoreFocus: true});
        return;
      }
      // Help icons living inside an open popup open a nested layer; icons
      // outside every popup replace the current stack.
      if (!isInsideAnyPopup(button)) close();
      if (descriptor.mode === "overlay") openOverlay(button, descriptor);
      else if (descriptor.text) openBubble(button, descriptor);
    });
    installListeners();
    return button;
  }

  window.FTHelp = Object.freeze({
    close,
    create,
    registerLoader: (type, loader) => {
      if (!type || typeof loader !== "function") {
        throw new TypeError("help loader requires a type and function");
      }
      loaders.set(String(type), loader);
    },
  });
})();
