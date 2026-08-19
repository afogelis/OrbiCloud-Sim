# Shane's Auto Sales website redesign

Static HTML/CSS/JS prototype of a shanecars.com redesign. It is a front-end mock, not a live CRM replacement. Inventory is a representative snapshot compiled from public listings and will not match the dealership's current stock.

## Run locally

```bash
cd website
python3 -m http.server 4173
```

Open `http://localhost:4173`.

## Pages

| File | Role |
|------|------|
| `index.html` | Home: search, featured vehicles, hours, map |
| `inventory.html` | Filterable inventory grid |
| `vehicle.html` | Detail + payment sketch (`?id=`) |
| `financing.html` | Pre-approval form (demo submit) |
| `about.html` | Address, hours, how the lot operates |
| `contact.html` | Contact form, hours, map |
| `request.html` | Request-a-car form |

English/Spanish copy is toggled from the header (`localStorage` key `shane-lang`). Forms validate in the browser and do not post to Shane's Auto Sales.

## Source facts used

- Shane's Auto Sales, Inc., 13526 Ventura Blvd, Sherman Oaks, CA 91423
- Phone `(818) 451-9099`, email `info@shanecars.com`
- Hours: Mon–Fri 10:00 AM–7:00 PM, Sat 10:00 AM–6:00 PM, Sunday closed
- Facebook: [Shanes Auto](https://www.facebook.com/people/Shanes-Auto/61565567445845/)
