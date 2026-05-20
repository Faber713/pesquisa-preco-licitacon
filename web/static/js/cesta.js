(function () {
  const storageKey = "pesquisa-cesta-collapsed";
  const collapsedClass = "basket-collapsed";
  const drawerClass = "basket-drawer-open";

  function basket() {
    return document.querySelector("#basket-sidebar");
  }

  function counter() {
    return document.querySelector("[data-basket-counter]");
  }

  function setCollapsed(collapsed) {
    document.body.classList.toggle(collapsedClass, collapsed);
    localStorage.setItem(storageKey, collapsed ? "1" : "0");
    const toggle = document.querySelector("[data-basket-toggle]");
    if (toggle) {
      toggle.textContent = collapsed ? "Mostrar" : "Ocultar";
    }
  }

  function openDrawer() {
    document.body.classList.remove(collapsedClass);
    document.body.classList.add(drawerClass);
    localStorage.setItem(storageKey, "0");
  }

  function closeDrawer() {
    document.body.classList.remove(drawerClass);
  }

  function refreshCounter(count) {
    const target = counter();
    if (target) {
      target.textContent = String(count || 0);
    }
  }

  function replaceBasket(html) {
    const current = basket();
    if (!current) {
      return;
    }
    current.outerHTML = html;
    const next = basket();
    refreshCounter(Number(next?.dataset.basketCount || 0));
    setCollapsed(localStorage.getItem(storageKey) === "1");
  }

  function markLoading(form, loading) {
    form.classList.toggle("is-loading", loading);
    form.querySelectorAll("button, select, input").forEach((input) => {
      if (input.type !== "hidden") {
        input.disabled = loading;
      }
    });
  }

  async function submitBasketForm(form) {
    const data = new FormData(form);
    markLoading(form, true);
    try {
      const response = await fetch(form.action, {
        method: form.method || "POST",
        body: data,
        headers: {
          Accept: "application/json",
          "X-Requested-With": "fetch",
        },
      });

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }

      const payload = await response.json();
      if (payload.basket_html) {
        replaceBasket(payload.basket_html);
      }
      refreshCounter(payload.count);
    } catch (error) {
      form.submit();
    } finally {
      markLoading(form, false);
    }
  }

  document.addEventListener("submit", (event) => {
    const form = event.target;
    if (!(form instanceof HTMLFormElement) || !form.action.includes("/cesta/")) {
      return;
    }

    event.preventDefault();
    submitBasketForm(form);
  });

  document.addEventListener("click", (event) => {
    if (event.target.closest("[data-basket-toggle]")) {
      setCollapsed(!document.body.classList.contains(collapsedClass));
      closeDrawer();
    }

    if (event.target.closest("[data-basket-open]")) {
      openDrawer();
    }

    if (event.target.closest("[data-basket-backdrop]")) {
      closeDrawer();
      setCollapsed(true);
    }
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      closeDrawer();
    }
  });

  const saved = localStorage.getItem(storageKey);
  const currentCount = Number(basket()?.dataset.basketCount || 0);
  setCollapsed(saved === null ? currentCount === 0 : saved === "1");
  refreshCounter(currentCount);
})();
