(() => {
  function create(options = {}) {
    const current = action => (...args) => {
      if (options.isCurrent?.() === false) return undefined;
      return action?.(...args);
    };
    return Object.freeze({
      activeNav: current(options.activeNav),
      setHeading: current(options.setHeading),
      updateActiveTab: current(options.updateActiveTab),
    });
  }

  function createLifetimes(activeTabID) {
    const rendered = new Map();
    return Object.freeze({
      begin: token => rendered.set(activeTabID(), token),
      current: () => rendered.get(activeTabID()),
      isCurrent: token => rendered.get(activeTabID()) === token,
      discard: tabID => rendered.delete(tabID),
      clear: () => rendered.clear(),
    });
  }

  window.FTRoutePresentation = Object.freeze({create, createLifetimes});
})();
