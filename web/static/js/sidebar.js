(function () {
  const storageKey = "sidebarCollapsed";
  const toggle = document.querySelector("[data-sidebar-toggle]");

  function collapsed() {
    return localStorage.getItem(storageKey) === "true";
  }

  function applyState(isCollapsed) {
    document.body.classList.toggle("sidebar-collapsed", isCollapsed);
    document.documentElement.classList.toggle("sidebar-collapsed-initial", isCollapsed);
    if (toggle) {
      toggle.setAttribute("aria-expanded", String(!isCollapsed));
      toggle.setAttribute("aria-label", isCollapsed ? "Expandir menu lateral" : "Recolher menu lateral");
      toggle.title = isCollapsed ? "Expandir menu lateral" : "Recolher menu lateral";
    }
  }

  applyState(collapsed());

  if (toggle) {
    toggle.addEventListener("click", () => {
      const next = !document.body.classList.contains("sidebar-collapsed");
      localStorage.setItem(storageKey, String(next));
      applyState(next);
    });
  }
})();
