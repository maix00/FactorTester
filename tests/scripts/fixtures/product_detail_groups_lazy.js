window.FTUI = {
  loading(label) {
    const node = document.createElement("div");
    node.className = "test-loading";
    node.textContent = label;
    return node;
  },
  empty(title, detail) {
    const node = document.createElement("div");
    node.className = "test-empty";
    node.textContent = [title, detail].filter(Boolean).join(" ");
    return node;
  },
  table(headers, rows) {
    const shell = document.createElement("table");
    const head = shell.createTHead().insertRow();
    headers.forEach(value => head.insertCell().textContent = value);
    const body = shell.createTBody();
    rows.forEach(values => {
      const row = body.insertRow();
      values.forEach(value => row.insertCell().textContent = value ?? "");
    });
    return {shell, body};
  },
};
window.FTProductPricePanel = {render: async () => {}};

window.startProductDetailFirstPaint = function(productFound) {
  const state = window.__productDetailFirstPaint = {
    requests: [],
    routeCurrent: true,
    completed: false,
    resolveGroups: null,
    rejectGroups: null,
    heading: null,
  };
  const context = {
    content: document.querySelector("main"),
    toolbar: document.querySelector("header"),
    t: value => value,
    activeNav() {},
    setHeading(title, subtitle) { state.heading = {title, subtitle}; },
    updateActiveTab() {},
    navigate() {},
    isRouteCurrent: () => state.routeCurrent,
    api: async url => {
      state.requests.push(url);
      if (url === "/api/product-library/products") {
        return {products: productFound ? [{name: "Product A", desc: "Product details"}] : []};
      }
      if (url.startsWith("/api/product-library/product-groups")) {
        return new Promise((resolve, reject) => {
          state.resolveGroups = resolve;
          state.rejectGroups = reject;
        });
      }
      if (url.startsWith("/api/product-library/product-fields")) return {fields: []};
      if (url.startsWith("/api/product-library/contracts?")) {
        return {contracts: [], supports_term_structure: false};
      }
      return {};
    },
  };
  state.rendering = window.FTProducts.productDetail(
    context, productFound ? "Product A" : "missing-ref",
  ).then(() => { state.completed = true; });
};
