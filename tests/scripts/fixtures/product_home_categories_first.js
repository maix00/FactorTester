const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

class FakeElement {
  constructor(tag = "div") {
    this.tagName = tag;
    this.children = [];
    this.attributes = {};
    this.listeners = {};
    this.dataset = {};
    this.className = "";
    this.textContent = "";
    this.value = "";
    this.style = {setProperty() {}};
    this.isConnected = true;
  }

  append(...items) { this.children.push(...items); }
  replaceChildren(...items) { this.children = [...items]; }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  addEventListener(name, callback) { this.listeners[name] = callback; }
}

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return {promise, resolve, reject};
}

const settle = () => new Promise(resolve => setTimeout(resolve, 0));
const until = async predicate => {
  for (let attempt = 0; attempt < 100; attempt += 1) {
    if (predicate()) return;
    await settle();
  }
  assert.fail("timed out waiting for deferred catalog work");
};

async function runScenario(sourceFailure = false) {
  const toolbar = new FakeElement("header");
  const content = new FakeElement("main");
  const apiCalls = [];
  const categoryRequest = deferred();
  const sourceRequest = deferred();
  let treeResponse = {tree: []};
  const document = {
    documentElement: {classList: {contains: () => false}},
    createElement: tag => new FakeElement(tag),
    querySelector: selector => selector === "header" ? toolbar : content,
  };
  const window = {
    FTAppRuntime: {hasLocalCatalog: () => false},
    requestAnimationFrame: callback => setTimeout(callback, 0),
  };
  const FTUI = {
    loading: label => Object.assign(new FakeElement(), {textContent: label}),
    empty: (title, body = "") => Object.assign(new FakeElement(), {
      textContent: `${title} ${body}`,
    }),
    refreshButton: () => new FakeElement("button"),
  };
  const FTProductCategoryModel = {
    availableSourceIDs: definitions => definitions.map(item => item.id),
    treeNodeInitiallyOpen: () => false,
  };
  const FTMultiSelectFilter = {
    create: () => ({element: Object.assign(new FakeElement(), {
      className: "product-category-filter-ready",
    })}),
  };
  window.FTMultiSelectFilter = FTMultiSelectFilter;
  const localStorageValues = new Map();
  const localStorage = {
    getItem: key => localStorageValues.get(key) || null,
    setItem: (key, value) => localStorageValues.set(key, String(value)),
  };
  const context = {
    activeNav() {},
    setHeading() {},
    t: value => value,
    session: {username: "test"},
    toolbar,
    content,
    navigate() {},
    showNotice() {},
    isRouteCurrent: () => true,
    api: async path => {
      apiCalls.push(path);
      if (path === "/api/product-library/categories") return categoryRequest.promise;
      if (path === "/api/product-library/data-sources") return sourceRequest.promise;
      if (path.startsWith("/api/product-library/tree?")) return treeResponse;
      throw new Error(`unexpected catalog request: ${path}`);
    },
  };
  const sandbox = {
    window, document, location: {search: ""}, localStorage,
    URLSearchParams, AbortController, setTimeout, clearTimeout, Promise,
    FTUI, FTProductCategoryModel, FTMultiSelectFilter, context,
    console,
  };
  vm.createContext(sandbox);
  vm.runInContext(
    fs.readFileSync("server/manager/web/catalog/product-tree.js", "utf8"),
    sandbox,
    {filename: "product-tree.js"},
  );
  sandbox.FTProductTree = window.FTProductTree;
  vm.runInContext(
    fs.readFileSync("server/manager/web/catalog/products.js", "utf8"),
    sandbox,
    {filename: "products.js"},
  );

  const renderPromise = window.FTProducts.list(context, "products");
  await settle();
  assert.ok(apiCalls.includes("/api/product-library/categories"));
  assert.ok(apiCalls.includes("/api/product-library/data-sources"));
  categoryRequest.resolve({categories: [{id: "category-1", alias: "Rates"}]});

  const renderedBeforeSources = await Promise.race([
    renderPromise.then(() => true),
    new Promise(resolve => setTimeout(() => resolve(false), 100)),
  ]);
  assert.strictEqual(
    renderedBeforeSources,
    true,
    "category controls must render without waiting for source descriptors",
  );
  const page = content.children[0];
  const results = page.children.find(item => item.className === "library-results");
  const categoryMount = results.children[0];
  const treeMount = results.children[1];
  assert.strictEqual(categoryMount.children[0].className, "product-category-filter-ready");
  assert.ok(treeMount.children[0].children[0].textContent.includes("正在读取产品目录"));
  assert.ok(!apiCalls.some(path => path.startsWith("/api/product-library/tree?")));

  if (sourceFailure) {
    await settle();
    sourceRequest.reject(new Error("source descriptors unavailable"));
    await until(() => treeMount.children[0].children[0]?.textContent.includes(
      "source descriptors unavailable",
    ));
    assert.strictEqual(categoryMount.children[0].className, "product-category-filter-ready");
    assert.ok(!apiCalls.some(path => path.startsWith("/api/product-library/tree?")));
    return;
  }

  sourceRequest.resolve({sources: [{id: "family-1", family_id: "family-1"}]});
  await until(() => apiCalls.some(path => path.startsWith("/api/product-library/tree?")));
  const treePath = apiCalls.find(path => path.startsWith("/api/product-library/tree?"));
  assert.ok(
    new URL(treePath, "http://manager").searchParams
      .getAll("data_source").includes("family-1"),
    "tree requests must remain scoped to resolved source descriptors",
  );
}

async function main() {
  await runScenario(false);
  await runScenario(true);
  console.log("ok");
}

main().catch(error => {
  console.error(error.stack || error);
  process.exitCode = 1;
});
