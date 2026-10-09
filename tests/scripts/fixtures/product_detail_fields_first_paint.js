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

window.startProductDetailFieldsFirstPaint = function(options = {}) {
  const state = window.__productDetailFieldsFirstPaint = {
    requests: [],
    routeCurrent: true,
    completed: false,
    resolveFields: null,
    rejectFields: null,
    resolvePrice: null,
    priceStarted: false,
    heading: null,
  };
  window.FTProductPricePanel = {
    render(_context, mount) {
      state.priceStarted = true;
      mount.textContent = "价格正在读取";
      if (options.deferPrice) {
        return new Promise(resolve => {
          state.resolvePrice = () => {
            mount.textContent = "价格已读取";
            resolve();
          };
        });
      }
      mount.textContent = "价格已读取";
      return Promise.resolve();
    },
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
    api: url => {
      state.requests.push(url);
      if (url === "/api/product-library/products") {
        return Promise.resolve({products: [{name: "Product A", desc: "Product details"}]});
      }
      if (url.startsWith("/api/product-library/product-fields")) {
        return new Promise((resolve, reject) => {
          state.resolveFields = resolve;
          state.rejectFields = reject;
        });
      }
      if (url.startsWith("/api/product-library/contracts?")) {
        state.contractsStarted = true;
        return Promise.resolve({
          supports_term_structure: true,
          contracts: [{uid: "A1", contract: "A1", has_data: true}],
        });
      }
      return Promise.resolve({});
    },
  };
  state.rendering = window.FTProducts.productDetail(context, "Product A")
    .then(() => { state.completed = true; });
};
