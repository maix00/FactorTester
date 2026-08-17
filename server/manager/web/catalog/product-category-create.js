(() => {
  // Kept as a public compatibility entry for older callers.  Creation now
  // uses the same detail layout as viewing and editing a Category.
  function render(context, helpers, options = {}) {
    return window.FTProductCategoryDetails.render(
      context, "", options.mode || "create", helpers,
    );
  }

  window.FTProductCategoryCreate = Object.freeze({open: render, render});
})();
