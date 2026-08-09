(() => {
  // One report owns one observer.  Components only register a mount callback;
  // they do not create observers or retain visibility bookkeeping themselves.
  function observerFor(context) {
    if (
      context.lazyRendering === false
      || typeof IntersectionObserver !== "function"
    ) return null;
    if (context.lazyObserver) return context.lazyObserver;

    const callbacks = new Map();
    const observer = new IntersectionObserver(entries => {
      entries.forEach(entry => {
        if (!entry.isIntersecting) return;
        const mount = callbacks.get(entry.target);
        if (!mount) return;
        callbacks.delete(entry.target);
        observer.unobserve(entry.target);
        mount();
      });
    }, {rootMargin: context.lazyRootMargin || "600px 0px"});
    context.lazyObserver = observer;
    context.lazyCallbacks = callbacks;
    context.lazyObservers?.add(observer);
    return observer;
  }

  function observe(element, context, mount) {
    const observer = observerFor(context);
    if (!observer) return null;
    context.lazyCallbacks.set(element, mount);
    observer.observe(element);
    return () => {
      context.lazyCallbacks.delete(element);
      observer.unobserve(element);
    };
  }

  window.FTReportLazyRuntime = Object.freeze({observe});
})();
