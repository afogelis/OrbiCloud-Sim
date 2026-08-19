(function () {
  const { dealer, i18n } = window.SHANE;

  const getLang = () => localStorage.getItem("shane-lang") || "en";
  const setLang = (lang) => localStorage.setItem("shane-lang", lang);

  const t = (key) => i18n[getLang()][key] || i18n.en[key] || key;

  const money = (n) =>
    new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: "USD",
      maximumFractionDigits: 0,
    }).format(n);

  const miles = (n) => `${new Intl.NumberFormat("en-US").format(n)} ${t("miles")}`;

  const titleOf = (v) => `${v.year} ${v.make} ${v.model}`;

  function photoFor(v) {
    if (v.image && !String(v.image).startsWith("http")) return v.image;
    const light = ["White", "Silver", "Gold", "Yellow", "Green", "Blue"].includes(v.color);
    if (v.body === "SUV") return light ? "assets/featured-crv.jpg" : "assets/body-suv-dark.jpg";
    if (v.body === "Sedan") return light ? "assets/body-sedan-silver.jpg" : "assets/body-sedan-dark.jpg";
    if (v.body === "Convertible") return "assets/body-convertible.jpg";
    if (v.body === "Truck") return "assets/body-truck.jpg";
    if (v.body === "Hatchback") return "assets/body-hatch.jpg";
    if (v.body === "Coupe") return "assets/body-coupe.jpg";
    if (v.body === "Wagon" || v.body === "Minivan") return "assets/body-van.jpg";
    return "assets/body-sedan-dark.jpg";
  }

  function openStatus() {
    const now = new Date(
      new Date().toLocaleString("en-US", { timeZone: "America/Los_Angeles" })
    );
    const day = now.getDay();
    const hour = now.getHours() + now.getMinutes() / 60;
    const block = dealer.hours.find((h) => h.days.includes(day));
    const isOpen = block && block.open !== null && hour >= block.open && hour < block.close;
    return { isOpen, block };
  }

  function formatHour(h) {
    if (h === null) return getLang() === "es" ? "Cerrado" : "Closed";
    const suffix = h >= 12 ? "PM" : "AM";
    const twelve = ((h + 11) % 12) + 1;
    return `${twelve}:00 ${suffix}`;
  }

  function renderHeader(active) {
    const { isOpen } = openStatus();
    const statusLabel = isOpen ? t("openNow") : t("closedNow");
    document.getElementById("site-header").innerHTML = `
      <a class="skip" href="#content">${t("skip")}</a>
      <div class="topbar">
        <div class="wrap">
          <div>
            <span class="status-dot ${isOpen ? "open" : ""}"></span>
            ${statusLabel} · ${dealer.address}, ${dealer.city}
          </div>
          <div class="hours-mini">${t("hours")}: Mon–Fri 10–7 · Sat 10–6 · ${t("closedSunday")}</div>
        </div>
      </div>
      <header class="site-header">
        <div class="wrap">
          <a class="brand" href="index.html">
            <img src="assets/logo-mark.jpg" alt="" width="40" height="40">
            <span class="brand-text">
              <strong>Shane's</strong>
              <span>Auto Sales</span>
            </span>
          </a>
          <nav class="nav" id="main-nav" aria-label="Primary">
            <a href="inventory.html" ${active === "inventory" ? 'aria-current="page"' : ""}>${t("navInventory")}</a>
            <a href="financing.html" ${active === "financing" ? 'aria-current="page"' : ""}>${t("navFinancing")}</a>
            <a href="about.html" ${active === "about" ? 'aria-current="page"' : ""}>${t("navAbout")}</a>
            <a href="contact.html" ${active === "contact" ? 'aria-current="page"' : ""}>${t("navContact")}</a>
            <a href="request.html" ${active === "request" ? 'aria-current="page"' : ""}>${t("navRequest")}</a>
          </nav>
          <div class="header-actions">
            <button class="lang-btn" type="button" id="lang-toggle" aria-label="Language">${t("lang")}</button>
            <a class="btn btn-copper" href="${dealer.phoneHref}">${t("call")} ${dealer.phone}</a>
            <button class="menu-btn" type="button" id="menu-toggle" aria-expanded="false">Menu</button>
          </div>
        </div>
      </header>
    `;

    document.getElementById("lang-toggle").addEventListener("click", () => {
      setLang(getLang() === "en" ? "es" : "en");
      location.reload();
    });

    const menu = document.getElementById("menu-toggle");
    menu.addEventListener("click", () => {
      const nav = document.getElementById("main-nav");
      const open = nav.classList.toggle("open");
      menu.setAttribute("aria-expanded", String(open));
    });
  }

  function renderFooter() {
    document.getElementById("site-footer").innerHTML = `
      <footer class="site-footer">
        <div class="wrap footer-grid">
          <div>
            <div class="brand" style="margin-bottom:12px">
              <img src="assets/logo-mark.jpg" alt="" width="40" height="40">
              <span class="brand-text">
                <strong>Shane's</strong>
                <span>Auto Sales</span>
              </span>
            </div>
            <p>${t("footerTag")}</p>
            <p style="margin-top:10px"><a href="${dealer.phoneHref}">${dealer.phone}</a><br>
            <a href="mailto:${dealer.email}">${dealer.email}</a></p>
          </div>
          <div>
            <div class="kicker">${t("navInventory")}</div>
            <p style="margin-top:10px">
              <a href="inventory.html">All vehicles</a><br>
              <a href="inventory.html?body=SUV">SUVs</a><br>
              <a href="inventory.html?body=Sedan">Sedans</a><br>
              <a href="inventory.html?body=Convertible">Convertibles</a>
            </p>
          </div>
          <div>
            <div class="kicker">${t("hours")}</div>
            <p style="margin-top:10px">
              Mon–Fri 10:00 AM – 7:00 PM<br>
              Saturday 10:00 AM – 6:00 PM<br>
              Sunday Closed
            </p>
          </div>
          <div>
            <div class="kicker">${dealer.city}</div>
            <p style="margin-top:10px">
              ${dealer.address}<br>
              <a href="${dealer.mapsUrl}">${t("directions")}</a><br>
              <a href="${dealer.facebook}">Facebook</a>
            </p>
          </div>
        </div>
        <div class="wrap legal">
          <span>© ${new Date().getFullYear()} Shane's Auto Sales, Inc.</span>
          <span>${t("privacy")}</span>
        </div>
      </footer>
      <div class="mobile-call">
        <a class="btn btn-copper" href="${dealer.phoneHref}">${t("call")} ${dealer.phone}</a>
      </div>
    `;
  }

  function vehicleCard(v) {
    return `
      <a class="vehicle-card" href="vehicle.html?id=${encodeURIComponent(v.id)}">
        <div class="thumb"><img src="${photoFor(v)}" alt="${titleOf(v)}" loading="lazy"></div>
        <div class="body">
          <div class="meta"><span>${v.body} · ${v.drivetrain}</span><span>${t("stock")} ${v.stock}</span></div>
          <h3>${titleOf(v)}</h3>
          <p class="muted">${v.trim}</p>
          <div class="meta">
            <span class="price">${money(v.price)}</span>
            <span>${miles(v.miles)}</span>
          </div>
        </div>
      </a>
    `;
  }

  function monthlyPayment(principal, down, aprPct, months) {
    const loan = Math.max(principal - down, 0);
    const r = aprPct / 100 / 12;
    if (r === 0) return loan / months;
    return (loan * r) / (1 - Math.pow(1 + r, -months));
  }

  window.ShaneApp = {
    getLang,
    t,
    money,
    miles,
    titleOf,
    photoFor,
    openStatus,
    formatHour,
    renderHeader,
    renderFooter,
    vehicleCard,
    monthlyPayment,
  };

  document.documentElement.lang = getLang();
})();
