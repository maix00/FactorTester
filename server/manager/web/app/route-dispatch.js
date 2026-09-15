(() => {
  // Route dispatch is intentionally boring: URL classification lives in
  // FTNavigation, while this seam only applies the existing auth and page
  // handlers. Keeping it dependency-injected makes the shell testable without
  // constructing a browser or duplicating page routing in each module.
  function create({content, t, context, jobsContext, requireLogin, handlers}) {
    const pages = handlers || {};
    // Presentation follows the route.  It is deliberately separate from the
    // login guard so a public route (the test workbench feed) still gets the
    // same feature-entry highlight and heading as the other pages.
    const present = (pageContext, shell) => {
      pageContext.activeNav?.(shell.nav || "");
      pageContext.setHeading?.(t(shell.title));
    };
    const guarded = (pageContext, shell, handler, ...args) => {
      present(pageContext, shell);
      if (!shell.allowVisitor && requireLogin()) return undefined;
      return handler?.(pageContext, ...args);
    };

    async function render(route, routeToken) {
      switch (route.kind) {
        case "home": return pages.home?.();
        case "public-reference": return pages.publicReference?.(route.id);
        case "reference": return pages.reference?.(context(routeToken), route);
        case "report": return pages.report?.(route.id, routeToken);
        case "research": return pages.research?.(routeToken);
        case "strategy-library": return guarded(
          context(routeToken), {nav: "strategies", title: "策略库"},
          pages.strategyLibrary, route.scope || "mine",
        );
        case "strategy": return guarded(
          context(routeToken), {nav: "strategies", title: "策略库"},
          pages.strategy, route.id || "", route.mode || "view", route,
        );
        case "research-detail": return guarded(
          context(routeToken), {nav: "research", title: "研究"},
          pages.researchDetail, route.id,
        );
        case "evidence-detail": return guarded(
          context(routeToken), {nav: "research", title: "证据"},
          pages.evidenceDetail, route.id,
        );
        case "docs": return guarded(
          context(routeToken), {nav: "", title: "技术文档", allowVisitor: true},
          pages.docs, route.slug,
        );
        case "research-graph": return guarded(
          context(routeToken), {nav: "research", title: "研究图"},
          pages.researchGraph, route.id,
        );
        case "remote-module": {
          if (route.module === "sqlite-web") {
            const pageContext = context(routeToken);
            pageContext.activeNav?.("");
            pageContext.setHeading?.(t("数据库"));
            if (requireLogin()) return undefined;
          }
          return pages.remoteModule?.(route, routeToken);
        }
        case "mihomo": {
          const pageContext = context(routeToken);
          pageContext.activeNav?.("mihomo");
          pageContext.setHeading?.(t("Mihomo Dashboard"), "Mihomo");
          if (requireLogin()) return undefined;
          return pages.mihomo?.(pageContext);
        }
        // The server task feed is intentionally public.  The jobs page
        // selects the public server scope when there is no session and lets
        // the API decide which rows/details are visible.  Guarding it here
        // prevented that scope from ever rendering and left the previous
        // page header in place because the list handler never ran.  The
        // feature-entry presentation is applied separately so the 测试台 entry
        // is highlighted exactly like the other feature-entry pages.
        case "jobs": {
          present(context(routeToken), {nav: "jobs", title: "测试台"});
          return pages.jobs?.(
            jobsContext(routeToken), route.section || "types",
          );
        }
        case "job": return pages.job?.(
          jobsContext(routeToken), route.port, route.id, route.serverID,
        );
        case "job-configuration": return pages.jobConfiguration?.(
          jobsContext(routeToken), route.port, route.id, route.serverID,
        );
        case "job-input": return pages.jobInput?.(
          jobsContext(routeToken), route.port, route.id, route.inputName, route.serverID,
        );
        case "ic-test": return guarded(
          context(routeToken), {nav: "", title: "IC 测试", allowVisitor: true},
          pages.icTest, route,
        );
        case "backtest": return guarded(
          context(routeToken), {nav: "", title: "回测", allowVisitor: true},
          pages.backtest, route,
        );
        case "factor-series": return guarded(
          context(routeToken), {nav: "jobs", title: "查看因子序列", allowVisitor: true},
          pages.factorSeries, route.factorRef, route.groupRef,
        );
        case "test-template": return guarded(
          context(routeToken), {nav: "", title: "测试模板", allowVisitor: true}, pages.testTemplate, route.id,
        );
        case "factor-families": return guarded(
          context(routeToken), {nav: "factors", title: "因子库", allowVisitor: true}, pages.factorFamilies, route,
        );
        case "factor-sets": return guarded(
          context(routeToken), {nav: "factors", title: "因子库"}, pages.factorSets, route,
        );
        case "factor-family": return guarded(
          context(routeToken), {nav: "factors", title: "因子库", allowVisitor: true}, pages.factorFamily, route.id,
          route.mode || "view", {publicMode: route.publicMode === true},
        );
        case "factor": return guarded(
          context(routeToken), {nav: "factors", title: "因子库", allowVisitor: true},
          pages.factor, route.id, route.mode || "view", route,
        );
        case "factor-set": return guarded(
          context(routeToken), {nav: "factors", title: "因子库"},
          pages.factorSet, route.id, route.mode || "view", route,
        );
        case "factors": return guarded(
          context(routeToken), {nav: "factors", title: "因子库", allowVisitor: true}, pages.factors, route,
        );
        case "product-group": return guarded(
          context(routeToken), {nav: "products", title: "产品库", allowVisitor: true}, pages.productGroup, route.id,
        );
        case "product": return guarded(
          context(routeToken), {nav: "products", title: "产品库", allowVisitor: true}, pages.product, route.id,
        );
        case "product-reference": return guarded(
          context(routeToken), {nav: "products", title: "产品库", allowVisitor: true},
          pages.productReference, route.referenceKind, route.id,
        );
        case "product-sources": return guarded(
          context(routeToken), {nav: "products", title: "产品库", allowVisitor: true}, pages.productSources, route,
        );
        case "product-source-family": return guarded(
          context(routeToken), {nav: "products", title: "数据源族", allowVisitor: true},
          pages.productSourceFamily, route.id,
        );
        case "product-groups": return guarded(
          context(routeToken), {nav: "products", title: "产品库", allowVisitor: true}, pages.productGroups, route,
        );
        case "product-categories": return guarded(
          context(routeToken), {nav: "products", title: "产品库", allowVisitor: true}, pages.productCategories, route,
        );
        case "product-category": return guarded(
          context(routeToken), {nav: "products", title: "产品分类", allowVisitor: true},
          pages.productCategory, route,
        );
        case "products": return guarded(
          context(routeToken), {nav: "products", title: "产品库", allowVisitor: true}, pages.products,
        );
        case "profile": return guarded(
          context(routeToken), {nav: "research", title: "研究身份"}, pages.profile, route.id,
        );
        case "profiles": return guarded(
          context(routeToken), {nav: "research", title: "研究身份"}, pages.profiles,
        );
        case "settings": return pages.settings?.(context(routeToken), route.section);
        case "manager": return guarded(
          context(routeToken), {nav: "", title: "服务器"}, pages.manager, route,
        );
        default:
          if (requireLogin()) return undefined;
          throw new Error(t("该模块尚未注册"));
      }
    }

    return Object.freeze({render});
  }

  window.FTAppRouteDispatch = Object.freeze({create});
})();
