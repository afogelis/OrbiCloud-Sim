"""Command-line entry point for OrbiCloud-Sim.

Runs a headless simulation, prints the techno-economic summary, and optionally
writes CSV tables plus Plotly HTML visualizations to an output directory.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from .config import default_simulation_config
from .economics import EconomicsModel
from .export import export_results
from .network_router import run_simulation


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run an OrbiCloud-Sim scenario and optionally export results."
    )
    parser.add_argument("--planes", type=int, default=None, help="Override number of orbital planes.")
    parser.add_argument(
        "--per-plane", type=int, default=None, help="Override satellites per plane."
    )
    parser.add_argument("--altitude-km", type=float, default=None, help="Override altitude in km.")
    parser.add_argument(
        "--duration-s", type=float, default=None, help="Override simulated duration in seconds."
    )
    parser.add_argument(
        "--timestep-s", type=float, default=None, help="Override sampling timestep in seconds."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Directory for CSV tables and HTML visualizations.",
    )
    parser.add_argument(
        "--viz-step",
        type=int,
        default=0,
        help="Snapshot step index used for the 3D globe visualization.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = default_simulation_config()

    walker = config.constellation.walker
    if args.planes is not None:
        walker.num_planes = args.planes
    if args.per_plane is not None:
        walker.sats_per_plane = args.per_plane
    if args.altitude_km is not None:
        walker.altitude_km = args.altitude_km
    if args.duration_s is not None:
        config.duration_s = args.duration_s
    if args.timestep_s is not None:
        config.timestep_s = args.timestep_s

    result = run_simulation(config)
    economics = EconomicsModel(config).evaluate(result)

    summary = EconomicsModel(config).constellation_summary(result)
    print("OrbiCloud-Sim run complete")
    print(
        f"  Constellation : {summary['total']} sats "
        f"({summary['compute_nodes']} compute / {summary['relay_nodes']} relay)"
    )
    print(f"  Timesteps     : {len(result.telemetry)}")
    print(f"  Jobs routed   : {economics.jobs_completed}")
    print(f"  Total compute : {economics.total_gflops:,.0f} GFLOP")
    print(f"  Energy saved  : {economics.terrestrial_energy_kwh:,.2f} kWh")
    print(f"  Carbon offset : {economics.carbon_offset_kg:,.2f} kg CO2")
    print(f"  GPU rental $  : ${economics.terrestrial_rental_usd:,.2f}")
    print(f"  Cost / GFLOP  : ${economics.cost_per_gflop_usd:.6g}")
    print(f"  Net value     : ${economics.net_value_usd:,.2f}")
    print(f"  ROI ratio     : {economics.roi_ratio:.3f}")

    if args.output is not None:
        written = export_results(result, economics, args.output, step=args.viz_step)
        print(f"  Outputs       : {args.output.resolve()}")
        for name in written:
            print(f"    - {name}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
