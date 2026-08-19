(function () {
  const { t } = window.ShaneApp;
  const stock = new URLSearchParams(location.search).get("stock");

  document.querySelectorAll("form[data-demo]").forEach((form) => {
    if (stock && form.elements.stock) {
      form.elements.stock.value = stock;
    }

    form.addEventListener("submit", (event) => {
      event.preventDefault();
      let valid = true;
      form.querySelectorAll("[required]").forEach((field) => {
        const error = field.parentElement.querySelector(".error");
        if (!field.value.trim()) {
          valid = false;
          if (error) error.textContent = t("required");
        } else if (error) {
          error.textContent = "";
        }
      });
      if (!valid) return;
      const box = form.querySelector(".form-success");
      box.hidden = false;
      box.textContent = t("formSuccess");
      form.querySelector("button[type=submit]").disabled = true;
    });
  });
})();
