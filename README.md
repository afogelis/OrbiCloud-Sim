# OrbiCloud-Sim: Orbital Data-Center Constellation Optimizer

OrbiCloud-Sim is a Python simulation and techno-economic framework for
space-based data centers. It models a Low Earth Orbit (LEO) constellation that
executes AI compute workloads in orbit and exports flat CSV tables for analysis
and dashboarding in Tableau.

The simulator couples four concerns:

- **Orbital mechanics** — Walker-Delta constellation generation and eclipse
  detection via Skyfield's SGP4 propagator.
- **Node state machine** — per-satellite battery and thermal evolution driven by
  the sunlight/eclipse cycle and compute duty.
- **Dynamic routing** — a time-varying NetworkX line-of-sight graph plus
  state-aware pathfinding that avoids overheated or battery-starved nodes.
- **Techno-economics** — terrestrial energy and carbon avoided, amortized
  orbital capex, cost per GigaFLOP, and ROI.

## Architecture

```mermaid
flowchart LR
    cfg["config.py<br/>Pydantic models"] --> orb["orbital_engine.py<br/>Walker-Delta + eclipse"]
    cfg --> rt["network_router.py<br/>ISL graph + state machine"]
    orb --> rt
    rt --> econ["economics.py<br/>cost / carbon / ROI"]
    rt --> exp["export.py<br/>Tableau CSV tables"]
    econ --> exp
    exp --> tab["Tableau Desktop<br/>dashboard workbook"]
```

Business logic lives in `src/orbicloud_sim/`. Visualization is performed in
Tableau from the exported CSVs; see `tableau/README.md`.

## Project layout

```text
OrbiCloud-Sim/
├── src/orbicloud_sim/
│   ├── config.py            # Pydantic models: hardware, constellation, sim, economics
│   ├── orbital_engine.py    # Skyfield Walker-Delta TLE synthesis + eclipse detection
│   ├── network_router.py    # NetworkX ISL graph, node state machine, run_simulation
│   ├── economics.py         # Cost-per-GFLOP + carbon-offset model
│   ├── export.py            # Tableau-ready CSV writers
│   └── cli.py               # Headless runner (orbicloud)
├── tableau/
│   └── README.md            # How to connect Tableau to the CSV exports
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

Run a scenario and write Tableau source tables:

```bash
orbicloud --planes 8 --per-plane 12 --altitude-km 550 --duration-s 6000 --output output/tableau
```

Then open Tableau Desktop, connect to the CSVs under `output/tableau/`, and build
the dashboard. Table schemas and suggested sheet layouts are documented in
`tableau/README.md`.

Omit `--output` to print only the console summary:

```bash
orbicloud --planes 8 --per-plane 8 --altitude-km 550 --duration-s 6000
```

## Testing

```bash
pytest
```

## Modeling notes

- **Walker-Delta** patterns are synthesized directly as NORAD TLE strings (mean
  motion derived from altitude), so SGP4 propagation is reused without external
  data files.
- **Eclipse** uses a cylindrical Earth-shadow approximation, standard for LEO
  feasibility studies; penumbra is out of scope.
- **Thermal** state uses a first-order lumped-capacitance model; a compute node
  accepts work only when it is below its thermal threshold and above its battery
  floor.
- **Economics** compares avoided terrestrial GPU energy (with PUE) and cloud GPU
  rental against launch + hardware capex amortized over the satellite lifetime.

All tunable parameters are Pydantic models in `config.py`; there are no hardcoded
magic numbers in the simulation logic.
