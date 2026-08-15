(() => {
  const sections = [
    {id: "types", title: "测试类型", path: "/jobs?section=types"},
    {id: "tasks", title: "测试任务", path: "/jobs?section=tasks"},
  ];

  function render(context, selected) {
    const root = document.createElement("div");
    root.className = "job-scope-tabs test-page-tabs";
    sections.forEach(section => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "job-scope-tab test-page-tab";
      button.classList.toggle("selected", section.id === selected);
      button.textContent = context.t(section.title);
      button.title = button.textContent;
      button.addEventListener("click", () => context.navigate(section.path));
      root.append(button);
    });
    return root;
  }

  window.FTTestPageTabs = Object.freeze({render});
})();
