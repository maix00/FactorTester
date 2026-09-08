(() => {
  // The names in this registry intentionally mirror ClientTab and
  // ResearchDocumentReferenceCatalog.  WebKit cannot load SF Symbols as a
  // browser font, so the browser uses a small inline SVG renderer while
  // keeping the same semantic symbol name and visual metrics as SwiftUI.
  const moduleSymbols = {
    home: "square.grid.2x2",
    research: "lightbulb",
    "research.reports": "doc.text",
    "research.evidence": "doc.text.magnifyingglass",
    "research.graph": "point.3.connected.trianglepath.dotted",
    "research.profiles": "person.2.crop.square.stack",
    "research.agent-models": "server.rack",
    "ic-test": "chart.xyaxis.line",
    "factor-series": "waveform.path.ecg",
    backtest: "chart.line.uptrend.xyaxis",
    jobs: "checklist",
    factors: "function",
    products: "shippingbox",
    strategies: "arrow.triangle.branch",
    profiles: "person.2.crop.square.stack",
    settings: "person.crop.circle",
    manager: "server.rack",
    docs: "book",
    sqlite_web: "cylinder.split.1x2",
    "test-templates": "list.bullet.clipboard",
  };

  const referenceSymbols = {
    evidence: "doc.text.magnifyingglass",
    obligation: "checkmark.seal",
    task: "checklist",
    job: "checklist",
    claim: "quote.bubble",
    artifact: "paperclip",
    report_requirement: "list.bullet.clipboard",
    entry_requirement: "checkmark.square",
    obligation_requirement: "checkmark.square",
    trial_plan: "list.bullet.clipboard",
    graph_reference: "point.3.connected.trianglepath.dotted",
    checkpoint: "flag",
    run: "play.circle",
    run_spec: "slider.horizontal.3",
    delta: "arrow.left.arrow.right",
    factor: "function",
    factor_family: "function",
    factor_set: "square.stack.3d.up",
    profile: "person.crop.rectangle.stack",
    profile_revision: "person.crop.rectangle.stack",
    product_group: "shippingbox.and.arrow.backward",
    product: "shippingbox",
    contract: "doc.text",
    continuous_contract: "chart.line.uptrend.xyaxis",
    file: "doc.text",
    url: "safari",
    reference: "link",
  };

  const shapes = {
    "square.grid.2x2": '<rect x="4" y="4" width="6" height="6" rx="1.2"/><rect x="14" y="4" width="6" height="6" rx="1.2"/><rect x="4" y="14" width="6" height="6" rx="1.2"/><rect x="14" y="14" width="6" height="6" rx="1.2"/>',
    "chart.xyaxis.line": '<path d="M4 20V4M4 20h17"/><path d="m7 15 3-4 3 2 5-7 3 2"/>',
    "lightbulb": '<path d="M9 18h6M10 21h4"/><path d="M8.2 14.5A7 7 0 1 1 15.8 14.5C14.7 15.3 14 16.4 14 18h-4c0-1.6-.7-2.7-1.8-3.5Z"/>',
    "chart.line.uptrend.xyaxis": '<path d="M4 20V4M4 20h17"/><path d="m7 16 4-5 3 2 6-8"/><path d="M17 5h3v3"/>',
    "checklist": '<path d="M8 6h12M8 12h12M8 18h12"/><path d="m3.5 5.8 1.2 1.2 2.2-2.4M3.5 11.8l1.2 1.2 2.2-2.4M3.5 17.8l1.2 1.2 2.2-2.4"/>',
    "function": '<text x="3" y="17" fill="currentColor" stroke="none" font-size="16" font-family="ui-sans-serif, sans-serif" font-weight="650">ƒ(x)</text>',
    "shippingbox": '<path d="m4 8 8-4 8 4-8 4-8-4Z"/><path d="M4 8v9l8 4 8-4V8M12 12v9M8 6l8 4"/>',
    "shippingbox.and.arrow.backward": '<path d="m5 8 7-4 7 4-7 4-7-4Z"/><path d="M5 8v8l7 4 7-4V8M12 12v8"/><path d="M3 13h7m-3-3 3 3-3 3"/>',
    "person.2.crop.square.stack": '<rect x="4" y="4" width="16" height="16" rx="3"/><circle cx="10" cy="10" r="2"/><path d="M7 16c.7-2 1.7-3 3-3s2.3 1 3 3M15 10.5a2 2 0 0 0 0-3"/>',
    "person.crop.rectangle.stack": '<rect x="5" y="4" width="14" height="16" rx="3"/><circle cx="12" cy="10" r="2.3"/><path d="M8 16c.8-2.2 2.1-3.2 4-3.2s3.2 1 4 3.2"/>',
    "person.crop.circle": '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="9" r="2.4"/><path d="M7.5 18c.8-2.7 2.3-4 4.5-4s3.7 1.3 4.5 4"/>',
    "book": '<path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H20v16H6.5A2.5 2.5 0 0 0 4 21.5Z"/><path d="M4 5.5v16M8 7h8M8 11h8"/>',
    "cylinder.split.1x2": '<ellipse cx="12" cy="5" rx="7.5" ry="2.5"/><path d="M4.5 5v9c0 1.4 3.4 2.5 7.5 2.5s7.5-1.1 7.5-2.5V5"/><path d="M12 8v8.5M12 8c0 1.2-1.7 2.1-3.8 2.1S4.5 9.2 4.5 8"/>',
    "server.rack": '<rect x="4" y="4" width="16" height="5" rx="1"/><rect x="4" y="10" width="16" height="5" rx="1"/><rect x="4" y="16" width="16" height="4" rx="1"/><path d="M7 6.5h.1M7 12.5h.1M7 18h.1M10 6.5h7M10 12.5h7M10 18h7"/>',
    "list.bullet.clipboard": '<rect x="7" y="4" width="12" height="16" rx="2"/><path d="M9 4.5V3h5v1.5M10 9h6M10 13h6M10 17h4M4 9h2M4 13h2M4 17h2"/>',
    "sidebar.left": '<rect x="4" y="4" width="16" height="16" rx="2"/><path d="M9 4v16M12.5 9.5 10 12l2.5 2.5"/>',
    "doc.text.magnifyingglass": '<path d="M6 3h8l4 4v7"/><path d="M6 3v18h5M14 3v5h5M9 11h5M9 15h3"/><circle cx="16.5" cy="17" r="3.2"/><path d="m19 19.5 2 2"/>',
    "point.3.connected.trianglepath.dotted": '<circle cx="5" cy="6" r="1.8"/><circle cx="19" cy="6" r="1.8"/><circle cx="12" cy="18" r="1.8"/><path d="m6.5 7.2 4.2 8.3M17.5 7.2l-4.2 8.3M7 6h10"/>',
    "square.stack.3d.up": '<rect x="6" y="8" width="13" height="11" rx="1.5"/><path d="m4 15V5.5C4 4.7 4.7 4 5.5 4H16M8 12h9M8 16h7"/>',
    "checkmark.seal": '<path d="m12 3 2 1 2.2-.2 1.3 1.8 2 .9-.2 2.2 1 2-1 2 .2 2.2-2 .9-1.3 1.8-2.2-.2-2 1-2-1-2.2.2-1.3-1.8-2-.9.2-2.2-1-2 1-2-.2-2.2 2-.9L9.8 4 12 4l2-1Z"/><path d="m8.5 12 2.2 2.2 4.8-5"/>',
    "checkmark.square": '<rect x="4" y="4" width="16" height="16" rx="2"/><path d="m8 12 2.5 2.5L16 9"/>',
    "quote.bubble": '<path d="M5 5h14a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-8l-4 3v-3H5a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2Z"/><path d="M7 10h.1M12 10h.1M17 10h.1"/>',
    "paperclip": '<path d="m8 12 6.5-6.5a3 3 0 0 1 4.2 4.2l-7.8 7.8a4.5 4.5 0 0 1-6.4-6.4l7-7"/>',
    "flag": '<path d="M6 21V4"/><path d="M6 5c3-2 5 2 9 0l3-1v9l-3 1c-4 2-6-2-9 0"/>',
    "play.circle": '<circle cx="12" cy="12" r="9"/><path d="m10 8 6 4-6 4V8Z"/>',
    "slider.horizontal.3": '<path d="M4 6h16M4 12h16M4 18h16"/><circle cx="9" cy="6" r="2"/><circle cx="15" cy="12" r="2"/><circle cx="11" cy="18" r="2"/>',
    "arrow.left.arrow.right": '<path d="M4 8h15m-4-4 4 4-4 4M20 16H5m4-4-4 4 4 4"/>',
    "arrow.triangle.branch": '<path d="M7 5v8a4 4 0 0 0 4 4h6M11 9h6M17 7l2 2-2 2M17 15l2 2-2 2"/><circle cx="7" cy="5" r="2"/>',
    "wrench.and.screwdriver": '<path d="m5 5 5 5M4 4l3-1 2 2-1 3-2 1-2-2 1-3ZM12 12l7 7M15 14l4-4M16 7a4 4 0 0 1 4-4l-2 3 2 2 3-2a4 4 0 0 1-5 5"/>',
    "checkmark.bubble": '<path d="M5 4h14a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-7l-4 3v-3H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2Z"/><path d="m8 10 2.5 2.5L16 7"/>',
    "text.magnifyingglass": '<path d="M4 5h10M4 9h7M4 13h7M4 17h5"/><circle cx="16" cy="16" r="4"/><path d="m19 19 2 2"/>',
    "checkmark.circle": '<circle cx="12" cy="12" r="9"/><path d="m8 12 2.5 2.5L16 9"/>',
    "checkmark.shield": '<path d="M12 3 20 6v5c0 5-3.3 8.3-8 10-4.7-1.7-8-5-8-10V6l8-3Z"/><path d="m8 12 2.5 2.5L16 9"/>',
    "chart.bar.doc.horizontal": '<path d="M5 4h10l4 4v12H5zM15 4v5h5M8 13h8M8 17h5"/><path d="M2 10v8M2 18h2M2 14h2"/>',
    "exclamationmark.triangle": '<path d="m12 4 9 16H3L12 4Z"/><path d="M12 9v5M12 17v.1"/>',
    "doc.text": '<path d="M6 3h8l4 4v14H6zM14 3v5h5M9 12h6M9 16h6"/>',
    "globe": '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c3 2.5 4 5.5 4 9s-1 6.5-4 9c-3-2.5-4-5.5-4-9s1-6.5 4-9Z"/>',
    "arrow.down.circle": '<circle cx="12" cy="12" r="9"/><path d="M12 7v9M8.5 12.5 12 16l3.5-3.5"/>',
    "arrow.up.circle": '<circle cx="12" cy="12" r="9"/><path d="M12 17V8M8.5 11.5 12 8l3.5 3.5"/>',
    "folder": '<path d="M4 7a2 2 0 0 1 2-2h4l2 2h6a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2Z"/><path d="M4 10h16"/>',
    "folder.fill": '<path d="M4 7a2 2 0 0 1 2-2h4l2 2h6a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2Z" fill="currentColor"/>',
    "arrow.clockwise": '<path d="M20 7v5h-5"/><path d="M19 12a7 7 0 1 1-2-5l3 3"/>',
    "gearshape": '<circle cx="12" cy="12" r="3"/><path d="M19 12a7 7 0 0 0-.1-1l2-1.5-2-3.4-2.4 1a7 7 0 0 0-1.8-1L14.4 3h-4.8l-.4 3.1a7 7 0 0 0-1.8 1l-2.4-1-2 3.4L5.1 11a7 7 0 0 0 0 2L3 14.5l2 3.4 2.4-1a7 7 0 0 0 1.8 1l.4 3.1h4.8l.4-3.1a7 7 0 0 0 1.8-1l2.4 1 2-3.4-2.1-1.5a7 7 0 0 0 .1-1Z"/>',
    "eye": '<path d="M3 12s3.2-6 9-6 9 6 9 6-3.2 6-9 6-9-6-9-6Z"/><circle cx="12" cy="12" r="2.5"/>',
    "square.and.pencil": '<rect x="4" y="4" width="14" height="16" rx="2"/><path d="m10 15 1-3 6.8-6.8a1.6 1.6 0 0 1 2.2 2.2L13.2 14l-3.2 1ZM15.8 7.2l2.2 2.2"/>',
    "plus": '<path d="M12 4v16M4 12h16"/>',
    "trash": '<path d="M5 7h14M9 7V4h6v3M7 7l1 13h8l1-13M10 10v7M14 10v7"/>',
    "safari": '<circle cx="12" cy="12" r="9"/><path d="m15.5 8.5-2.3 5.2-4.7 2.3 2.3-5.2 4.7-2.3Z"/>',
    "link": '<path d="M9.5 14.5 8 16a3.5 3.5 0 0 1-5-5l2-2a3.5 3.5 0 0 1 5 0M14.5 9.5 16 8a3.5 3.5 0 0 1 5 5l-2 2a3.5 3.5 0 0 1-5 0M8 12h8"/>',
    "xmark": '<path d="M6 6l12 12M18 6 6 18"/>',
    "chevron.right": '<path d="m9 5 7 7-7 7"/>',
    "chevron.left": '<path d="m15 5-7 7 7 7"/>',
    "triangle.right": '<path d="m9 6 7 6-7 6Z"/>',
    "triangle.down": '<path d="m6 9 6 7 6-7Z"/>',
  };

  const normalize = value => String(value || "").replace(/-/g, "_");

  function fallbackSymbol(name) {
    return shapes[name] || shapes.link;
  }

  function node(symbol, className = "") {
    const host = document.createElement("span");
    host.className = `ft-icon ${className}`.trim();
    host.dataset.symbol = symbol || "link";
    host.setAttribute("aria-hidden", "true");
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.classList.add("ft-icon-svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("focusable", "false");
    svg.setAttribute("aria-hidden", "true");
    svg.innerHTML = `<g fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${fallbackSymbol(symbol)}</g>`;
    host.append(svg);
    return host;
  }

  function module(value) {
    if (value && typeof value === "object") {
      return value.sfSymbol || moduleSymbols[value.id] || module(value.icon);
    }
    const raw = String(value || "");
    return moduleSymbols[raw] || {
      grid: "square.grid.2x2", chart: "chart.xyaxis.line",
      correlation: "chart.xyaxis.line", backtest: "chart.line.uptrend.xyaxis",
      checklist: "checklist", function: "function", box: "shippingbox",
      strategy: "arrow.triangle.branch",
      profiles: "person.2.crop.square.stack", server: "server.rack",
      settings: "person.crop.circle",
    }[raw] || "link";
  }

  function reference(kind, target = "") {
    let value = normalize(kind) || "reference";
    const rawTarget = String(target || "");
    // Swift routes factor-family and factor-set targets through the factor
    // hyperlink kind, so Web follows the same target-aware presentation.
    if (value === "factor" && rawTarget.startsWith("factor-family:")) value = "factor_family";
    if (value === "factor" && rawTarget.startsWith("factor-set:")) value = "factor_set";
    return referenceSymbols[value] || "link";
  }

  function section(kind, displayKind = "") {
    const value = normalize(displayKind || kind);
    return {
      obligation_changes: "exclamationmark.bubble",
      graph_continuation: "arrow.triangle.branch",
      capability_detour: "wrench.and.screwdriver",
      grill_resolution: "checkmark.bubble",
      external_review: "text.magnifyingglass",
      entry_requirements: "checklist",
      obligation_requirement: "checkmark.circle",
      obligation_coverage: "checkmark.shield",
      path_selection: "arrow.triangle.branch",
      test_result: "chart.bar.doc.horizontal",
      research_gap: "exclamationmark.triangle",
    }[value] || "doc.text";
  }

  window.FTIcons = {module, node, reference, section, moduleSymbols, referenceSymbols};
})();
