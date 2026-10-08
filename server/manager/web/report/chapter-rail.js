(() => {
  const markerScale = distance => {
    const progress = distance === 0 ? 1 : distance === 1 ? .7 : distance === 2 ? .4 : distance === 3 ? .2 : 0;
    return .2308 + (.7692 * progress);
  };

  function setup(rail, roots, context, controls) {
    if (!rail) return {refresh() {}};
    rail.__ftChapterRailCleanup?.();
    const selected = controls.getSelected;
    const activate = controls.activate;
    rail.hidden = roots.length === 0;
    rail.setAttribute("aria-label", context.t?.("章节导航") || "章节导航");
    const tooltip = document.createElement("div");
    tooltip.className = "chapter-rail-tooltip";
    tooltip.hidden = true;
    tooltip.setAttribute("role", "tooltip");
    tooltip.innerHTML = `<div class="chapter-rail-tooltip-title"></div><div class="chapter-rail-tooltip-preview"></div><div class="chapter-rail-tooltip-meta"></div>`;
    const titleNode = tooltip.querySelector(".chapter-rail-tooltip-title");
    const previewNode = tooltip.querySelector(".chapter-rail-tooltip-preview");
    const metaNode = tooltip.querySelector(".chapter-rail-tooltip-meta");
    let interactionIndex = selected();
    let tooltipTimer = null;
    let hideTimer = null;
    const updateMarkerTarget = target => {
      interactionIndex = Number.isInteger(target) ? target : selected();
      rail.querySelectorAll(".chapter-rail-item").forEach((markerItem, markerIndex) => {
        const distance = Math.abs(markerIndex - interactionIndex);
        const fill = markerItem.querySelector(".chapter-rail-marker-fill");
        markerItem.classList.toggle("active", markerIndex === selected());
        markerItem.classList.toggle("interaction-target", markerIndex === interactionIndex);
        markerItem.classList.toggle("nearby", distance === 1);
        markerItem.classList.toggle("far", distance > 1);
        if (fill) fill.style.transform = `scaleX(${markerScale(distance).toFixed(4)})`;
      });
    };
    const hideTooltip = () => {
      if (tooltipTimer) window.clearTimeout(tooltipTimer);
      if (hideTimer) window.clearTimeout(hideTimer);
      tooltip.classList.remove("visible");
      hideTimer = window.setTimeout(() => { tooltip.hidden = true; }, 160);
    };
    const showTooltip = (item, node, index) => {
      updateMarkerTarget(index);
      if (hideTimer) window.clearTimeout(hideTimer);
      if (tooltipTimer) window.clearTimeout(tooltipTimer);
      tooltipTimer = window.setTimeout(() => {
        titleNode.textContent = node.component.title || `${context.t?.("章节") || "章节"} ${index + 1}`;
        // Swift's timeline outline uses the first child title as the chapter
        // preview. Public projections do not need to duplicate that derived
        // field: derive it from the same tree and keep any explicit preview
        // supplied by a newer projection as the first choice. Do not fall
        // back to the chapter body: that makes the callout much larger than
        // the Swift preview and leaks arbitrary report content into it.
        const firstChildTitle = node.children?.[0]?.component?.title || "";
        const preview = node.component.preview || (
          firstChildTitle !== (node.component.title || "") ? firstChildTitle : ""
        );
        previewNode.textContent = String(preview).replace(/\s+/g, " ").trim().slice(0, 240);
        const rawDate = node.component.created_at;
        const timestamp = typeof rawDate === "number"
          ? rawDate > 1e12 ? rawDate : rawDate * 1000
          : null;
        const date = timestamp != null
          ? new Date(timestamp)
          : new Date(String(rawDate || ""));
        const dateText = Number.isNaN(date.getTime()) ? "" : date.toLocaleString();
        metaNode.textContent = dateText;
        previewNode.hidden = !previewNode.textContent;
        metaNode.hidden = !metaNode.textContent;
        const itemBox = item.getBoundingClientRect();
        const panelWidth = Math.min(320, Math.max(0, window.innerWidth - 16));
        tooltip.style.left = `${Math.max(8, Math.min(itemBox.right + 4, window.innerWidth - panelWidth - 8))}px`;
        tooltip.style.top = `${Math.max(8, Math.min(itemBox.top + itemBox.height / 2 - 46, window.innerHeight - 126))}px`;
        tooltip.hidden = false;
        requestAnimationFrame(() => tooltip.classList.add("visible"));
      }, 80);
    };
    rail.replaceChildren(...roots.map((node, index) => {
      const item = document.createElement("button");
      item.type = "button";
      item.className = "chapter-rail-item";
      item.dataset.index = String(index);
      item.setAttribute("aria-current", index === selected() ? "true" : "false");
      item.setAttribute("aria-label", `${context.t?.("跳转到章节") || "跳转到章节"} ${node.component.title || index + 1}`);
      item.innerHTML = `<span class="chapter-rail-marker" aria-hidden="true"><span class="chapter-rail-marker-fill"></span></span>`;
      item.addEventListener("pointerenter", () => showTooltip(item, node, index));
      item.addEventListener("pointerleave", () => { updateMarkerTarget(selected()); hideTooltip(); });
      item.addEventListener("focus", () => showTooltip(item, node, index));
      item.addEventListener("blur", () => { updateMarkerTarget(selected()); hideTooltip(); });
      item.addEventListener("click", () => {
        activate(index);
        item.scrollIntoView({block: "center", behavior: "smooth"});
      });
      return item;
    }));
    // Pointer scrubbing used to call getBoundingClientRect for every marker
    // on every pointermove.  Keep the measured centers for the current rail
    // layout instead; invalidate them only when the rail can have moved.
    let markerCenters = [];
    let markerCentersDirty = true;
    const invalidateMarkerCenters = () => { markerCentersDirty = true; };
    const measureMarkerCenters = () => {
      markerCenters = [...rail.querySelectorAll(".chapter-rail-item")]
        .map(item => {
          const box = item.getBoundingClientRect();
          return box.top + box.height / 2;
        });
      markerCentersDirty = false;
    };
    // Keep the tooltip outside the scrollable rail. This is the same sibling
    // overlay used by SwiftUI; otherwise overflow-y would clip it at the rail edge.
    document.querySelectorAll(".chapter-rail-tooltip").forEach(item => item.remove());
    document.body.append(tooltip);
    const itemAt = index => rail.querySelector(`[data-index="${index}"]`);
    let scrubbing = false;
    const nearestIndex = clientY => {
      if (markerCentersDirty) measureMarkerCenters();
      if (!markerCenters.length) return selected();
      let low = 0;
      let high = markerCenters.length - 1;
      while (low <= high) {
        const middle = Math.floor((low + high) / 2);
        if (markerCenters[middle] < clientY) low = middle + 1;
        else high = middle - 1;
      }
      const candidates = [
        Math.max(0, Math.min(markerCenters.length - 1, low)),
        Math.max(0, Math.min(markerCenters.length - 1, high)),
      ];
      return candidates.reduce((best, index) =>
        Math.abs(markerCenters[index] - clientY)
          < Math.abs(markerCenters[best] - clientY) ? index : best,
      candidates[0]);
    };
    const pointerDown = event => {
      if (event.button !== 0 || event.target.closest(".chapter-rail-tooltip")) return;
      scrubbing = true;
      rail.setPointerCapture?.(event.pointerId);
      const index = nearestIndex(event.clientY);
      if (Number.isInteger(index)) {
        activate(index);
        updateMarkerTarget(index);
        showTooltip(itemAt(index), roots[index], index);
      }
    };
    const pointerMove = event => {
      if (!scrubbing) return;
      const index = nearestIndex(event.clientY);
      if (Number.isInteger(index) && index !== selected()) {
        activate(index);
        updateMarkerTarget(index);
        showTooltip(itemAt(index), roots[index], index);
      }
    };
    const stopScrubbing = event => {
      if (!scrubbing) return;
      scrubbing = false;
      updateMarkerTarget(selected());
      if (!event.target.closest?.(".chapter-rail-item")) hideTooltip();
      rail.releasePointerCapture?.(event.pointerId);
    };
    rail.addEventListener("pointerdown", pointerDown);
    rail.addEventListener("pointermove", pointerMove);
    rail.addEventListener("pointerup", stopScrubbing);
    rail.addEventListener("pointercancel", stopScrubbing);
    const updateOverflow = () => {
      if (!rail.isConnected) {
        window.removeEventListener("resize", updateOverflow);
        return;
      }
      invalidateMarkerCenters();
      const maximumHeight = Math.min(window.innerHeight * .7, 640);
      rail.classList.toggle("overflow", roots.length * 14 > maximumHeight);
    };
    updateOverflow();
    window.addEventListener("resize", updateOverflow, {passive: true});
    rail.addEventListener("scroll", invalidateMarkerCenters, {passive: true});

    const refresh = () => rail.querySelectorAll(".chapter-rail-item").forEach((item, index) => {
      item.classList.toggle("active", index === selected());
      item.setAttribute("aria-current", index === selected() ? "true" : "false");
      const distance = Math.abs(index - selected());
      item.classList.toggle("nearby", distance === 1);
      item.classList.toggle("far", distance > 1);
      const fill = item.querySelector(".chapter-rail-marker-fill");
      if (fill) fill.style.transform = `scaleX(${markerScale(distance).toFixed(4)})`;
    });
    refresh();
    const cleanup = () => {
      rail.removeEventListener("pointerdown", pointerDown);
      rail.removeEventListener("pointermove", pointerMove);
      rail.removeEventListener("pointerup", stopScrubbing);
      rail.removeEventListener("pointercancel", stopScrubbing);
      window.removeEventListener("resize", updateOverflow);
      rail.removeEventListener("scroll", invalidateMarkerCenters);
      if (tooltipTimer) window.clearTimeout(tooltipTimer);
      if (hideTimer) window.clearTimeout(hideTimer);
      tooltip.remove();
      if (rail.__ftChapterRailCleanup === cleanup) delete rail.__ftChapterRailCleanup;
    };
    rail.__ftChapterRailCleanup = cleanup;
    return {refresh, cleanup};
  }

  window.FTReportChapterRail = Object.freeze({setup});
})();
