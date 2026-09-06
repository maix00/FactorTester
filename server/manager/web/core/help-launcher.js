(() => {
  let loading = null;
  let generation = 0;
  const loaders = new Map();
  const facade = {
    close(options) {
      generation += 1;
      if (window.FTHelp !== facade) window.FTHelp.close(options);
    },
    registerLoader(type, loader) {
      if (!type || typeof loader !== "function") throw new TypeError("help loader requires a type and function");
      loaders.set(String(type), loader);
    },
    create(help, options = {}) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "ft-help-icon";
      button.textContent = "?";
      button.dataset.ftHelp = "true";
      button.setAttribute("aria-label", options.ariaLabel || window.FTI18n?.t("查看说明") || "查看说明");
      button.setAttribute("aria-expanded", "false");
      button.addEventListener("click", async event => {
        event.preventDefault();
        event.stopPropagation();
        if (button.disabled) return;
        button.disabled = true;
        const started = generation;
        try {
          loading ||= window.FTStaticLoader.loadGroups(["help-popover"]).then(() => {
            if (window.FTHelp === facade) throw new Error("说明面板加载失败");
            for (const [type, loader] of loaders) window.FTHelp.registerLoader(type, loader);
          }).catch(error => { loading = null; throw error; });
          await loading;
          if (button.isConnected === false || started !== generation) return;
          const ready = window.FTHelp.create(help, options);
          button.replaceWith(ready);
          ready.focus?.();
          ready.click();
        } catch (error) {
          button.title = error.message || "说明面板加载失败";
        } finally {
          button.disabled = false;
        }
      });
      return button;
    },
  };
  window.FTHelp = Object.freeze(facade);
})();
