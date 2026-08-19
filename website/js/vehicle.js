(function () {
  const { vehicles } = window.SHANE;
  const { t, money, miles, titleOf, photoFor, vehicleCard, monthlyPayment } = window.ShaneApp;
  const id = new URLSearchParams(location.search).get("id");
  const vehicle = vehicles.find((v) => v.id === id) || vehicles[0];

  document.title = `${titleOf(vehicle)} · Shane's Auto Sales`;
  document.getElementById("vehicle-root").innerHTML = `
    <div class="gallery">
      <img src="${photoFor(vehicle)}" alt="${titleOf(vehicle)}">
    </div>
    <div>
      <p class="kicker">${vehicle.body} · ${t("stock")} ${vehicle.stock}</p>
      <h1 style="font-size:clamp(2rem,4vw,3.4rem);margin:8px 0 4px">${titleOf(vehicle)}</h1>
      <p class="paper-dim">${vehicle.trim}</p>
      <p style="margin:16px 0 0;max-width:60ch">${vehicle.blurb}</p>
      <dl class="specs">
        <div><dt>${t("price")}</dt><dd>${money(vehicle.price)}</dd></div>
        <div><dt>${t("miles")}</dt><dd>${miles(vehicle.miles)}</dd></div>
        <div><dt>${t("drivetrain")}</dt><dd>${vehicle.drivetrain}</dd></div>
        <div><dt>${t("trans")}</dt><dd>${vehicle.transmission}</dd></div>
        <div><dt>${t("engine")}</dt><dd>${vehicle.engine}</dd></div>
        <div><dt>${t("fuel")}</dt><dd>${vehicle.fuel}</dd></div>
        <div><dt>${t("mpg")}</dt><dd>${vehicle.mpg}</dd></div>
        <div><dt>${t("color")}</dt><dd>${vehicle.color}</dd></div>
        <div><dt>${t("vin")}</dt><dd>${vehicle.vin}</dd></div>
        <div><dt>${t("stock")}</dt><dd>${vehicle.stock}</dd></div>
      </dl>
    </div>
  `;

  const downEl = document.getElementById("est-down");
  const termEl = document.getElementById("est-term");
  const rateEl = document.getElementById("est-rate");
  const payEl = document.getElementById("est-pay");
  const downVal = document.getElementById("est-down-val");

  downEl.max = vehicle.price;
  downEl.value = Math.min(2000, Math.round(vehicle.price * 0.1));

  function updatePay() {
    const down = Number(downEl.value);
    const months = Number(termEl.value);
    const apr = Number(rateEl.value);
    downVal.textContent = money(down);
    payEl.textContent = money(Math.round(monthlyPayment(vehicle.price, down, apr, months)));
  }

  [downEl, termEl, rateEl].forEach((el) => el.addEventListener("input", updatePay));
  updatePay();

  document.getElementById("apply-link").href = `financing.html?stock=${vehicle.stock}`;
  document.getElementById("want-link").href = `request.html?stock=${vehicle.stock}`;
  document.getElementById("detail-price").textContent = money(vehicle.price);

  const similar = vehicles
    .filter((v) => v.id !== vehicle.id && (v.body === vehicle.body || v.make === vehicle.make))
    .slice(0, 3);
  document.getElementById("similar-grid").innerHTML = similar.map(vehicleCard).join("");
})();
