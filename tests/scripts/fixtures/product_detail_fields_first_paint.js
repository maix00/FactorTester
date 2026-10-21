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
      values.forEach(value => {
        const cell = row.insertCell();
        if (value instanceof Node) cell.append(value);
        else cell.textContent = value ?? "";
      });
    });
    return {shell, body};
  },
  pagedTable(headers, rows, options) {
    const start = ((options.page || 1) - 1) * options.pageSize;
    return {...this.table(headers, rows.slice(start, start + options.pageSize)
      .map(options.renderRow)), start};
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
