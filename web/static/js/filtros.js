(function () {
  document.querySelectorAll('input[name="desconsiderar_orgao_origem"]').forEach((checkbox) => {
    const form = checkbox.closest("form");
    const input = form?.querySelector('input[name="orgao_origem"]');
    function sync() {
      if (!input) {
        return;
      }
      input.closest(".field")?.classList.toggle("is-muted", !checkbox.checked);
    }
    checkbox.addEventListener("change", sync);
    sync();
  });

  document.querySelectorAll('input[name="periodo_pesquisa"]').forEach((radio) => {
    const form = radio.closest("form");
    const fields = form ? [...form.querySelectorAll(".period-custom")] : [];
    function syncPeriod() {
      const selected = form?.querySelector('input[name="periodo_pesquisa"]:checked')?.value;
      fields.forEach((field) => field.classList.toggle("is-hidden", selected !== "personalizado"));
    }
    radio.addEventListener("change", syncPeriod);
    syncPeriod();
  });
})();
