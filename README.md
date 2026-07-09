# OrbiCloud-Sim: Orbital Data-Center Constellation Optimizer

OrbiCloud-Sim is a Python simulation and techno-economic framework for
space-based data centers. It models a Low Earth Orbit (LEO) constellation that
executes AI compute workloads in orbit and writes CSV tables plus interactive
HTML visualizations for analysis.

The simulator couples four concerns:

- **Orbital mechanics** — Walker-Delta constellation generation and eclipse
  detection via Skyfield's SGP4 propagator.
- **Node state machine** — per-satellite battery and thermodynamic mass
  accumulation driven by sunlight, compute duty, and radiative cooling.
- **Dynamic routing** — a time-varying NetworkX line-of-sight graph with
  Earth-occlusion checks and health-penalized pathfinding.
- **Techno-economics** — CapEx/OpEx TCO with cooling premium, carbon offset,
  cost per GigaFLOP, and break-even horizon.

## High-Fidelity Engineering Constraints

The core engines replace binary academic switches with continuous physical
models:

### Dynamic ECEF Vector Occlusion

Optical inter-satellite links are admitted only when the chord between two
satellite position vectors clears the solid Earth. The closest-approach point
on the segment is found by projecting onto `V = sat2 − sat1`, clamping the
parameter to `[0, 1]`, and rejecting the edge when that point lies inside an
occlusion sphere of radius `R_earth + 100 km`. The **100 km atmospheric
boundary layer** accounts for thermal and signal-distortion altitude above the
mean Earth radius (`6371 km`). Globe snapshots are stored in ECEF so continents
remain fixed under the constellation while physics continues in ECI.

### Thermodynamic Accumulation

Node temperature is not a binary sunlit/eclipse flag. Each timestep integrates
a lumped thermal-mass ODE in kelvin: solar heating while `is_sunlit()` is true
(`+0.5 K/s`), intensive internal heat while AI compute is active (`+2.0 K/s`),
and continuous passive radiative cooling toward deep space
(`−coeff · (T − 3 K)`). Temperature therefore exhibits **continuous thermal
lag**—nodes heat and cool over successive intervals—and is clamped between a
safe storage floor (`250 K`) and a structural maximum (`360 K`). Compute
eligibility still requires temperature below the hardware thermal threshold and
battery above the configured floor.

### Health-Penalized Shortest Path Routing

Valid ISL edges that survive occlusion are not weighted by physical distance
alone. Pathfinding uses NetworkX `shortest_path(..., weight="weight")` where
edge cost scales with node health: if the target's battery falls below **20%**
or its temperature exceeds **90%** of the thermal threshold, the edge weight is
multiplied by **1000×** (distance × health penalty). Critically discharged or
structurally overheated nodes are omitted from the graph entirely
(`weight = ∞`). The resulting routes prefer thermally and electrically healthy
compute nodes rather than the geometrically nearest degraded ones.

## Architecture

```mermaid
flowchart LR
    cfg["config.py<br/>Pydantic models"] --> orb["orbital_engine.py<br/>Walker-Delta + eclipse"]
    cfg --> rt["network_router.py<br/>ISL graph + state machine"]
    orb --> rt
    rt --> econ["economics.py<br/>cost / carbon / ROI"]
    rt --> viz["visualizers.py<br/>Plotly globe + charts"]
    econ --> viz
    rt --> exp["export.py<br/>CSV + HTML outputs"]
    econ --> exp
    viz --> exp
```

Business logic lives in `src/orbicloud_sim/`. Presentation is limited to Plotly
HTML figures written beside the CSV exports.

## Project layout

```text
OrbiCloud-Sim/
├── src/orbicloud_sim/
│   ├── config.py            # Pydantic models: hardware, constellation, sim, economics
│   ├── orbital_engine.py    # Skyfield Walker-Delta TLE synthesis + eclipse detection
│   ├── network_router.py    # NetworkX ISL graph, node state machine, run_simulation
│   ├── economics.py         # Cost-per-GFLOP + carbon-offset model
│   ├── visualizers.py       # Plotly 3D globe and metric charts
│   ├── export.py            # CSV tables + HTML visualization writers
│   └── cli.py               # Headless runner (orbicloud)
├── docs/images/             # README dashboard screenshots
├── tests/test_orbital.py
├── pyproject.toml
└── README.md
```

## Installation

```bash
python -m venv .venv
# Windows PowerShell:  .venv\Scripts\Activate.ps1
# macOS/Linux:         source .venv/bin/activate
pip install -e ".[dev]"
```

Skyfield uses built-in timescale data and a low-precision analytic solar vector,
so no external TLE catalog or JPL ephemeris download is required.

## Usage

Run a scenario and write results:

```bash
orbicloud --planes 8 --per-plane 12 --altitude-km 550 --duration-s 6000 --output output/run
```

Open `output/run/dashboard.html` in a browser for the combined globe, economics,
and telemetry view. Individual charts are also written as `globe.html`,
`telemetry.html`, and `economics.html`, alongside CSV tables for further analysis.

Omit `--output` to print only the console summary:

```bash
orbicloud --planes 8 --per-plane 8 --altitude-km 550 --duration-s 6000
```

## Dashboard screenshots

Combined dashboard (globe, economics, and telemetry):

![OrbiCloud-Sim dashboard](docs/images/dashboard.png)

3D constellation globe with NASA Blue Marble Earth texture (continental US view):

![Constellation globe](docs/images/globe.png)

Telemetry time series:

![Telemetry](docs/images/telemetry.png)

Unit-cost and impact comparison (avoids short-window capex scale distortion):

![Economics](docs/images/economics.png)

## Testing

```bash
pytest
```

## Modeling notes

- **Walker-Delta** patterns are synthesized directly as NORAD TLE strings (mean
  motion derived from altitude), so SGP4 propagation is reused without external
  data files.
- **Eclipse / sunlight** uses a cylindrical Earth-shadow test (`is_sunlit`);
  penumbra is out of scope. Sunlight status feeds the thermal accumulator rather
  than acting as a binary compute switch.
- **ISL geometry** uses the vector occlusion test described above
  (`R_earth + 100 km` atmospheric boundary).
- **Economics** amortizes rideshare launch CapEx (`$1500/kg`) and hardware over
  a 5-year lifetime, credits OpEx savings from avoided grid IT load plus PUE
  cooling premium, and reports break-even months.

All tunable parameters are Pydantic models in `config.py`; there are no hardcoded
magic numbers in the simulation logic.
