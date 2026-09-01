(() => {
  const el = (tag, className = "", text = "") => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text) node.textContent = text;
    return node;
  };

  function pageLink(context, page, className = "") {
    const link = el("a", className, page.title);
    link.href = `/docs/${page.slug}`;
    link.addEventListener("click", event => {
      event.preventDefault();
      context.navigate(link.getAttribute("href"));
    });
    return link;
  }

  function renderNavigation(context, index, activeSlug) {
    const aside = el("aside", "technical-docs-navigation");
    const search = el("input", "technical-docs-search");
    search.type = "search";
    search.placeholder = context.t("搜索文档");
    aside.append(search);
    const tree = el("div", "technical-docs-tree");
    for (const section of index.sections) {
      const group = el("section", "technical-docs-nav-group");
      group.append(el("h2", "technical-docs-nav-title", section.title));
      for (const page of section.pages) {
        const link = pageLink(context, page, "technical-docs-nav-link");
        if (page.slug === activeSlug) link.classList.add("active");
        group.append(link);
      }
      tree.append(group);
    }
    aside.append(tree);
    search.addEventListener("input", () => {
      const query = search.value.trim().toLocaleLowerCase();
      for (const link of tree.querySelectorAll(".technical-docs-nav-link")) {
        const item = index.search.find(page => link.href.endsWith(`/docs/${page.slug}`));
        const haystack = `${item?.title || ""} ${item?.summary || ""} ${item?.text || ""}`.toLocaleLowerCase();
        link.hidden = Boolean(query && !haystack.includes(query));
      }
      for (const group of tree.children) {
        group.hidden = ![...group.querySelectorAll(".technical-docs-nav-link")].some(link => !link.hidden);
      }
    });
    return aside;
  }

  function bindContentLinks(context, article) {
    for (const link of article.querySelectorAll("a[href]")) {
      const url = new URL(link.href, location.origin);
      if (url.origin !== location.origin) {
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        continue;
      }
      link.addEventListener("click", event => {
        event.preventDefault();
        context.navigate(`${url.pathname}${url.search}${url.hash}`);
      });
    }
  }

  async function render(context, requestedSlug = "") {
    context.activeNav("");
    context.setHeading(context.t("技术文档"));
    const index = await FTDocsSource.index(context);
    if (!context.isRouteCurrent()) return;
    const slug = requestedSlug || index.default_page;
    const page = await FTDocsSource.page(context, slug);
    if (!context.isRouteCurrent()) return;

    const layout = el("div", "technical-docs-layout");
    layout.append(renderNavigation(context, index, slug));
    const main = el("main", "technical-docs-main");
    const header = el("header", "technical-docs-page-header");
    header.append(el("span", "technical-docs-kind", page.section_title));
    header.append(el("h1", "", page.title));
    header.append(el("p", "", page.summary));
    main.append(header);
    const article = el("article", "technical-docs-article");
    article.innerHTML = page.html;
    bindContentLinks(context, article);
    main.append(article);
    if (slug === "test-fields" && window.FTDocsFieldCatalog?.render) {
      window.FTDocsFieldCatalog.render(context, main);
    }
    if (page.related_pages?.length) {
      const related = el("section", "technical-docs-related");
      related.append(el("h2", "", context.t("相关文档")));
      const links = el("div", "technical-docs-related-links");
      for (const item of page.related_pages) links.append(pageLink(context, item));
      related.append(links);
      main.append(related);
    }
    const pager = el("nav", "technical-docs-pager");
    if (page.previous) pager.append(pageLink(context, page.previous, "technical-docs-previous"));
    if (page.next) pager.append(pageLink(context, page.next, "technical-docs-next"));
    main.append(pager);
    const toc = el("aside", "technical-docs-toc");
    toc.append(el("h2", "", context.t("本页目录")));
    for (const heading of page.headings) {
      const link = el("a", heading.level, heading.title);
      link.href = `#${heading.id}`;
      link.addEventListener("click", event => {
        event.preventDefault();
        document.getElementById(heading.id)?.scrollIntoView({behavior: "smooth"});
        history.replaceState(history.state, "", `/docs/${slug}#${heading.id}`);
      });
      toc.append(link);
    }
    layout.append(main, toc);
    context.content.replaceChildren(layout);
    if (location.hash) document.getElementById(location.hash.slice(1))?.scrollIntoView();
  }

  window.FTDocs = Object.freeze({render});
})();
