# Tableau Dashboard Guide

Simulation outputs are flat CSV tables written by the OrbiCloud-Sim CLI. Tableau
Desktop (or Tableau Prep) is used to build the interactive dashboard from those
files; the Python package does not embed a web UI.

## Generate source data

From the repository root, after installing the package:

```bash
orbicloud --planes 8 --per-plane 12 --altitude-km 550 --duration-s 6000 --output output/tableau
```

This creates the following files under `output/tableau/`:

| File | Grain | Typical Tableau use |
|------|-------|---------------------|
| `scenario.csv` | one row | captions, parameter labels |
| `satellites.csv` | one row per satellite | role filters, constellation size |
| `telemetry.csv` | one row per timestep | latency, SoC, eligible-node time series |
| `node_states.csv` | one row per satellite × timestep | spatial scatter, thermal/battery color |
| `routes.csv` | one row per hop × timestep | active path overlays |
| `economics_summary.csv` | one row | KPI cards (cost/GFLOP, ROI, carbon) |
| `economics_breakdown.csv` | one row per metric | Space vs Terrestrial bar chart |

## Suggested workbook structure

1. Connect Tableau to the `output/tableau` folder (Text file / CSV).
2. Relate `node_states.csv` to `satellites.csv` on `sat_id`.
3. Relate `telemetry.csv` to `scenario.csv` (cross-join or blend on a constant).
4. Use `economics_summary.csv` for KPI cards and `economics_breakdown.csv` for
   the cost comparison bar chart.
5. For a 3D-style globe approximation, plot `x_km`, `y_km`, `z_km` from
   `node_states.csv` with color on `eligible` / `temperature_c` / `battery_fraction`,
   and filter by `step` with a parameter or page shelf.

Generated CSVs under `output/` are not committed to git; regenerate them after
changing scenario parameters.
