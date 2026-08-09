(() => {
  // Route dispatch is intentionally boring: URL classification lives in
  // FTNavigation, while this seam only applies the existing auth and page
  // handlers. Keeping it dependency-injected makes the shell testable without
  // constructing a browser or duplicating page routing in each module.
  function create({content, t, context, jobsContext, requireLogin, handlers}) {
    const pages = handlers || {};
    const guarded = (handler, ...args) => {
      if (requireLogin()) return undefined;
      return handler?.(...args);
    };

    async function render(route, routeToken) {
      switch (route.kind) {
        case "home": return pages.home?.();
        case "public-reference": return pages.publicReference?.(route.id);
        case "reference": return pages.reference?.(context(routeToken), route);
        case "report": return pages.report?.(route.id, routeToken);
        case "research": return pages.research?.(routeToken);
        case "remote-module": {
          if (route.module === "sqlite-web" && requireLogin()) return undefined;
          return pages.remoteModule?.(route, routeToken);
        }
        // The server task feed is intentionally public.  The jobs page
        // selects the public server scope when there is no session and lets
        // the API decide which rows/details are visible.  Guarding it here
        // prevented that scope from ever rendering and left the previous
        // page header in place because the list handler never ran.
        case "jobs": return pages.jobs?.(jobsContext(routeToken));
        case "job": return pages.job?.(jobsContext(routeToken), route.port, route.id);
        case "ic-test": return guarded(pages.icTest, context(routeToken));
        case "backtest": return guarded(pages.backtest, context(routeToken));
        case "test-template": return guarded(pages.testTemplate, context(routeToken), route.id);
        case "factor-families": return guarded(pages.factorFamilies, context(routeToken), route);
        case "factor-sets": return guarded(pages.factorSets, context(routeToken), route);
        case "factor-family": return guarded(pages.factorFamily, context(routeToken), route.id);
        case "factor": return guarded(pages.factor, context(routeToken), route.id);
        case "factor-set": return guarded(pages.factorSet, context(routeToken), route.id);
        case "factors": return guarded(pages.factors, context(routeToken));
        case "product-group": return guarded(pages.productGroup, context(routeToken), route.id);
        case "product": return guarded(pages.product, context(routeToken), route.id);
        case "product-reference": return guarded(
          pages.productReference, context(routeToken), route.referenceKind, route.id,
        );
        case "product-sources": return guarded(pages.productSources, context(routeToken), route);
        case "product-groups": return guarded(pages.productGroups, context(routeToken), route);
        case "products": return guarded(pages.products, context(routeToken));
        case "profile": return guarded(pages.profile, context(routeToken), route.id);
        case "profiles": return guarded(pages.profiles, context(routeToken));
        case "settings": return pages.settings?.(context(routeToken), route.section);
        case "manager": return guarded(pages.manager, routeToken, context(routeToken));
        default:
          if (requireLogin()) return undefined;
          throw new Error(t("该模块尚未注册"));
      }
    }

    return Object.freeze({render});
  }

  window.FTAppRouteDispatch = Object.freeze({create});
})();
