(() => {
  function componentTree(components) {
    const nodes = new Map(
      (components || []).map(component => [
        component.component_id,
        {component, children: []},
      ]),
    );
    const roots = [];
    for (const node of nodes.values()) {
      const parent = nodes.get(node.component.parent_id);
      (parent ? parent.children : roots).push(node);
    }
    return roots;
  }

  function chapterRoots(report) {
    const descriptors = Array.isArray(report?.chapters) ? report.chapters : [];
    if (descriptors.length) {
      return descriptors.map(chapter => ({
        component: {
          component_id: chapter.component_id,
          kind: "chapter",
          parent_id: null,
          title: chapter.title || "",
          created_at: chapter.created_at,
          preview: chapter.preview || "",
        },
        children: [],
      }));
    }
    return componentTree(report?.components).filter(
      node => node.component.kind === "chapter",
    );
  }

  window.FTReportTree = Object.freeze({componentTree, chapterRoots});
})();
