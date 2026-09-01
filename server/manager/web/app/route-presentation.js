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

  window.FTRoutePresentation = Object.freeze({create});
})();
