(function () {
  const { vehicles } = window.SHANE;
  const { t, vehicleCard, money } = window.ShaneApp;

  const params = new URLSearchParams(location.search);
  const els = {
    make: document.getElementById("filter-make"),
    body: document.getElementById("filter-body"),
    price: document.getElementById("filter-price"),
    sort: document.getElementById("filter-sort"),
    grid: document.getElementById("inventory-grid"),
    count: document.getElementById("inventory-count"),
    reset: document.getElementById("filter-reset"),
  };

  const makes = [...new Set(vehicles.map((v) => v.make))].sort();
  const bodies = [...new Set(vehicles.map((v) => v.body))].sort();

  function optionList(values, selected) {
    return [`<option value="">${t("any")}</option>`]
      .concat(values.map((v) => `<option value="${v}" ${v === selected ? "selected" : ""}>${v}</option>`))
      .join("");
  }

  els.make.innerHTML = optionList(makes, params.get("make") || "");
  els.body.innerHTML = optionList(bodies, params.get("body") || "");
  if (params.get("price")) els.price.value = params.get("price");
  if (params.get("sort")) els.sort.value = params.get("sort");

  function apply() {
    let list = vehicles.slice();
    const make = els.make.value;
    const body = els.body.value;
    const price = els.price.value;
    const sort = els.sort.value;

    if (make) list = list.filter((v) => v.make === make);
    if (body) list = list.filter((v) => v.body === body);
    if (price) list = list.filter((v) => v.price <= Number(price));

    if (sort === "price-asc") list.sort((a, b) => a.price - b.price);
    else if (sort === "price-desc") list.sort((a, b) => b.price - a.price);
    else if (sort === "miles") list.sort((a, b) => a.miles - b.miles);
    else if (sort === "year") list.sort((a, b) => b.year - a.year);
    else list.sort((a, b) => Number(Boolean(b.featured)) - Number(Boolean(a.featured)) || a.price - b.price);

    els.count.textContent = `${list.length} ${t("results")}`;
    els.grid.innerHTML = list.length
      ? list.map(vehicleCard).join("")
      : `<div class="empty">${t("noResults")}</div>`;
  }

  ["make", "body", "price", "sort"].forEach((key) => {
    els[key].addEventListener("change", apply);
  });

  els.reset.addEventListener("click", () => {
    els.make.value = "";
    els.body.value = "";
    els.price.value = "";
    els.sort.value = "featured";
    apply();
  });

  apply();
  window.ShaneMoney = money;
})();
