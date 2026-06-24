"""Command-line entry point for OrbiCloud-Sim.

Runs a headless simulation with the default (or lightly overridden) scenario and
prints the techno-economic summary. Useful for smoke-testing the core without
launching the Streamlit dashboard.
"""

from __future__ import annotations

import argparse

from .config import default_simulation_config
from .economics import EconomicsModel
from .network_router import run_simulation


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run an OrbiCloud-Sim scenario headlessly.")
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
    print(f"  Constellation : {summary['total']} sats "
          f"({summary['compute_nodes']} compute / {summary['relay_nodes']} relay)")
    print(f"  Timesteps     : {len(result.telemetry)}")
    print(f"  Jobs routed   : {economics.jobs_completed}")
    print(f"  Total compute : {economics.total_gflops:,.0f} GFLOP")
    print(f"  Energy saved  : {economics.terrestrial_energy_kwh:,.2f} kWh")
    print(f"  Carbon offset : {economics.carbon_offset_kg:,.2f} kg CO2")
    print(f"  Cost / GFLOP  : ${economics.cost_per_gflop_usd:.6g}")
    print(f"  Net value     : ${economics.net_value_usd:,.2f}")
    print(f"  ROI ratio     : {economics.roi_ratio:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
