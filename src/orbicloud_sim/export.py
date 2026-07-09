"""CSV and HTML exporters for OrbiCloud-Sim.

Simulation and economics results are written as flat tables plus Plotly HTML
charts. No physics or routing logic lives here.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from .economics import EconomicsResult
from .network_router import GROUND_NODE_ID, SimulationResult
from .visualizers import write_visualizations


def satellites_frame(result: SimulationResult) -> pd.DataFrame:
    """Static constellation membership (one row per satellite)."""

    rows = [
        {
            "sat_id": sat.sat_id,
            "name": sat.name,
            "role": sat.role.value,
            "plane": sat.plane,
            "slot": sat.slot,
            "compute_power_tflops": sat.profile.compute_power_tflops,
            "battery_capacity_wh": sat.profile.battery_capacity_wh,
            "thermal_threshold_c": sat.profile.thermal_threshold_c,
            "hardware_cost_usd": sat.profile.hardware_cost_usd,
            "mass_kg": sat.profile.mass_kg,
        }
        for sat in result.satellites
    ]
    return pd.DataFrame(rows)


def telemetry_frame(result: SimulationResult) -> pd.DataFrame:
    """Per-timestep aggregate telemetry (already tabular from the router)."""

    return result.telemetry.copy()


def node_states_frame(result: SimulationResult) -> pd.DataFrame:
    """Per-timestep, per-satellite state for spatial and thermal analysis."""

    rows: list[dict] = []
    for snapshot in result.snapshots:
        step = snapshot["step"]
        time_s = snapshot["time_s"]
        for sat in result.satellites:
            node = snapshot["nodes"][sat.sat_id]
            pos = node["position_km"]
            rows.append(
                {
                    "step": step,
                    "time_s": time_s,
                    "sat_id": sat.sat_id,
                    "name": sat.name,
                    "role": node["role"].value,
                    "x_km": float(pos[0]),
                    "y_km": float(pos[1]),
                    "z_km": float(pos[2]),
                    "battery_fraction": float(node["battery_fraction"]),
                    "temperature_c": float(node["temperature_c"]),
                    "in_eclipse": bool(node["in_eclipse"]),
                    "eligible": bool(node["eligible"]),
                }
            )
    return pd.DataFrame(rows)


def routes_frame(result: SimulationResult) -> pd.DataFrame:
    """Active route hops per timestep (ground node id is ``GROUND_NODE_ID``)."""

    rows: list[dict] = []
    for snapshot in result.snapshots:
        path = snapshot["route_path"]
        if len(path) < 2:
            continue
        for hop_index, node_id in enumerate(path):
            rows.append(
                {
                    "step": snapshot["step"],
                    "time_s": snapshot["time_s"],
                    "hop_index": hop_index,
                    "node_id": node_id,
                    "is_ground": node_id == GROUND_NODE_ID,
                }
            )
    return pd.DataFrame(rows)


def economics_summary_frame(economics: EconomicsResult) -> pd.DataFrame:
    """Single-row summary of techno-economic metrics."""

    return pd.DataFrame([economics.as_dict()])


def economics_breakdown_frame(economics: EconomicsResult) -> pd.DataFrame:
    """Long-form value comparison for bar charts."""

    return pd.DataFrame(
        [
            {"metric": "grid_cost_saved_usd", "label": "Grid cost saved", "value_usd": economics.grid_cost_saved_usd},
            {"metric": "carbon_value_usd", "label": "Carbon value", "value_usd": economics.carbon_value_usd},
            {
                "metric": "terrestrial_rental_usd",
                "label": "GPU rental avoided",
                "value_usd": economics.terrestrial_rental_usd,
            },
            {
                "metric": "space_compute_cost_usd",
                "label": "Space compute cost",
                "value_usd": economics.space_compute_cost_usd,
            },
            {"metric": "net_value_usd", "label": "Net value", "value_usd": economics.net_value_usd},
        ]
    )


def scenario_frame(result: SimulationResult) -> pd.DataFrame:
    """Scenario parameters for captions and reproducibility."""

    config = result.config
    walker = config.constellation.walker
    return pd.DataFrame(
        [
            {
                "epoch_utc": config.epoch.isoformat(),
                "duration_s": config.duration_s,
                "timestep_s": config.timestep_s,
                "num_steps": config.num_steps,
                "workload_gflops": config.workload_gflops,
                "num_planes": walker.num_planes,
                "sats_per_plane": walker.sats_per_plane,
                "altitude_km": walker.altitude_km,
                "inclination_deg": walker.inclination_deg,
                "phasing_f": walker.phasing_f,
                "compute_fraction": config.constellation.compute_fraction,
                "ground_station": config.ground_station.name,
                "ground_latitude_deg": config.ground_station.latitude_deg,
                "ground_longitude_deg": config.ground_station.longitude_deg,
            }
        ]
    )


def export_results(
    result: SimulationResult,
    economics: EconomicsResult,
    output_dir: str | Path,
    step: int = 0,
) -> dict[str, Path]:
    """Write CSV tables and HTML visualizations to ``output_dir``."""

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    tables = {
        "scenario.csv": scenario_frame(result),
        "satellites.csv": satellites_frame(result),
        "telemetry.csv": telemetry_frame(result),
        "node_states.csv": node_states_frame(result),
        "routes.csv": routes_frame(result),
        "economics_summary.csv": economics_summary_frame(economics),
        "economics_breakdown.csv": economics_breakdown_frame(economics),
    }

    written: dict[str, Path] = {}
    for filename, frame in tables.items():
        path = out / filename
        frame.to_csv(path, index=False)
        written[filename] = path

    written.update(write_visualizations(result, economics, out, step=step))
    return written
