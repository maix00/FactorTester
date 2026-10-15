(() => {
  // Browser title bubbles cannot be themed. Keep the original value on the
  // element only while it is not hovered, so dynamic title updates still work.
  const EXCLUDED = ".ft-help-icon, .chapter-rail-tooltip, .ft-help-bubble, .highcharts-tooltip, [role='tooltip']";
  const tooltip = document.createElement("div");
  tooltip.id = "ft-hover-tooltip";
  tooltip.className = "ft-hover-tooltip";
  tooltip.setAttribute("role", "tooltip");
  tooltip.hidden = true;
  document.body.append(tooltip);

  let active = null;
  let timer = null;
  let titleObserver = null;
  let originalTitle = null;
  let described = false;

  function labelFor(element) {
    if (!element || element.matches(EXCLUDED) || element.closest(EXCLUDED)) return "";
    if (element.hasAttribute("title")) return element.getAttribute("title")?.trim() || "";
    return "";
  }

  function targetFor(node) {
    for (let element = node?.nodeType === 1 ? node : node?.parentElement;
      element && element !== document.body; element = element.parentElement) {
      if (element.matches(EXCLUDED)) return null;
      if (element.hasAttribute("title")) {
        if (labelFor(element)) return element;
      }
    }
    return null;
  }

  function position() {
    if (!active || tooltip.hidden) return;
    const box = active.getBoundingClientRect();
    const tip = tooltip.getBoundingClientRect();
    const inset = 8;
    const gap = 13;
    const below = box.bottom + gap + tip.height <= window.innerHeight - inset;
    const top = below ? box.bottom + gap : Math.max(inset, box.top - gap - tip.height);
    const left = Math.max(inset, Math.min(
      box.left + box.width / 2 - tip.width / 2,
      window.innerWidth - tip.width - inset,
    ));
    tooltip.style.top = `${top}px`;
    tooltip.style.left = `${left}px`;
    tooltip.style.setProperty("--ft-tooltip-arrow-x", `${Math.max(12, Math.min(
      tip.width - 12, box.left + box.width / 2 - left,
    ))}px`);
    tooltip.dataset.placement = below ? "below" : "above";
  }

  function hide() {
    clearTimeout(timer);
    timer = null;
    titleObserver?.disconnect();
    titleObserver = null;
    if (active) {
      if (originalTitle !== null && !active.hasAttribute("title")) {
        active.setAttribute("title", originalTitle);
      }
      if (described) active.removeAttribute("aria-describedby");
    }
    active = null;
    originalTitle = null;
    described = false;
    tooltip.hidden = true;
  }

  function show() {
    if (!active || !active.isConnected) return hide();
    const label = originalTitle !== null ? originalTitle : labelFor(active);
    if (!label) return hide();
    tooltip.textContent = label;
    tooltip.hidden = false;
    // Dialogs live in the top layer; a tooltip outside them would be obscured.
    const host = active.closest("[popover], dialog[open]") || document.body;
    if (tooltip.parentElement !== host) host.append(tooltip);
    if (!active.hasAttribute("aria-describedby")) {
      active.setAttribute("aria-describedby", tooltip.id);
      described = true;
    }
    position();
  }

  function activate(element, immediate = false) {
    if (!element || (element === active && !tooltip.hidden)) return;
    hide();
    active = element;
    originalTitle = element.getAttribute("title");
    if (originalTitle !== null) {
      element.removeAttribute("title");
      titleObserver = new MutationObserver(() => {
        if (!active?.hasAttribute("title")) return;
        originalTitle = active.getAttribute("title");
        active.removeAttribute("title");
        if (!tooltip.hidden) {
          tooltip.textContent = originalTitle;
          position();
        }
      });
      titleObserver.observe(element, {attributes: true, attributeFilter: ["title"]});
    }
    timer = window.setTimeout(show, immediate ? 0 : 220);
  }

  document.addEventListener("pointerover", event => {
    if (event.pointerType === "touch") return;
    if (active?.contains(event.target)) return;
    activate(targetFor(event.target));
  });
  document.addEventListener("pointerout", event => {
    if (active && !active.contains(event.relatedTarget)) hide();
  });
  document.addEventListener("focusin", event => activate(targetFor(event.target), true));
  document.addEventListener("focusout", event => {
    if (active && !active.contains(event.relatedTarget)) hide();
  });
  document.addEventListener("pointerdown", hide, true);
  document.addEventListener("keydown", event => { if (event.key === "Escape") hide(); });
  document.addEventListener("scroll", hide, true);
  window.addEventListener("resize", hide);
})();
