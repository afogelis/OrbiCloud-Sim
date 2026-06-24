"""Streamlit entry point for OrbiCloud-Sim.

Presentation only: it gathers scenario inputs, calls the simulation core in
``orbicloud_sim``, and renders the 3D globe plus techno-economic ROI metrics.
All physics, routing and economics live in the ``src`` package.

Run with:  streamlit run dashboard/app.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

# Make the src/ package importable when launched via `streamlit run`.
_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from visualizers import (  # noqa: E402
    render_economics_bar,
    render_globe,
    render_telemetry,
)

from orbicloud_sim.config import (  # noqa: E402
    ConstellationConfig,
    GroundStationConfig,
    SimulationConfig,
    WalkerDeltaConfig,
    default_compute_profile,
    default_relay_profile,
)
from orbicloud_sim.economics import EconomicsModel  # noqa: E402
from orbicloud_sim.network_router import run_simulation  # noqa: E402

st.set_page_config(page_title="OrbiCloud-Sim", layout="wide")


@st.cache_resource(show_spinner="Propagating constellation and routing jobs...")
def _run(config_json: str) -> dict:
    """Cached simulation wrapper keyed by the serialized config.

    ``cache_resource`` is used instead of ``cache_data`` because the result holds
    Skyfield ``EarthSatellite`` objects that are not reliably picklable.
    """

    config = SimulationConfig.model_validate_json(config_json)
    result = run_simulation(config)
    economics = EconomicsModel(config).evaluate(result)
    summary = EconomicsModel(config).constellation_summary(result)
    return {"result": result, "economics": economics, "summary": summary}


def _build_config() -> SimulationConfig:
    st.sidebar.header("Constellation")
    num_planes = st.sidebar.slider("Orbital planes", 2, 24, 8)
    sats_per_plane = st.sidebar.slider(
        "Satellites per plane", 2, 24, 12,
        help="At 550 km the Earth-limb ISL range is ~5000 km; >=10 per plane keeps the mesh connected.",
    )
    altitude_km = st.sidebar.slider("Altitude (km)", 350, 1200, 550, step=10)
    inclination_deg = st.sidebar.slider("Inclination (deg)", 0.0, 110.0, 53.0, step=1.0)
    compute_fraction = st.sidebar.slider("Compute-node fraction", 0.0, 1.0, 0.5, step=0.05)
    phasing_f = st.sidebar.slider("Walker phasing factor (f)", 0, max(num_planes - 1, 0), 1)

    st.sidebar.header("Workload & timeline")
    workload_gflops = st.sidebar.number_input(
        "Offered work per step (GFLOP)",
        min_value=1.0e3,
        max_value=1.0e8,
        value=1.0e7,
        step=1.0e6,
        help="Delivered compute is capped by the assigned node's throughput per timestep.",
    )
    duration_min = st.sidebar.slider("Duration (minutes)", 10, 240, 100, step=10)
    timestep_s = st.sidebar.slider("Timestep (s)", 30, 300, 60, step=30)

    st.sidebar.header("Ground station")
    latitude_deg = st.sidebar.number_input("Latitude (deg)", -90.0, 90.0, 5.16)
    longitude_deg = st.sidebar.number_input("Longitude (deg)", -180.0, 180.0, -52.65)

    constellation = ConstellationConfig(
        walker=WalkerDeltaConfig(
            num_planes=num_planes,
            sats_per_plane=sats_per_plane,
            altitude_km=float(altitude_km),
            inclination_deg=float(inclination_deg),
            phasing_f=phasing_f,
        ),
        compute_fraction=compute_fraction,
        compute_profile=default_compute_profile(),
        relay_profile=default_relay_profile(),
    )
    ground_station = GroundStationConfig(
        name="Ground station", latitude_deg=latitude_deg, longitude_deg=longitude_deg
    )
    return SimulationConfig(
        constellation=constellation,
        ground_station=ground_station,
        workload_gflops=float(workload_gflops),
        duration_s=float(duration_min * 60),
        timestep_s=float(timestep_s),
    )


def main() -> None:
    st.title("OrbiCloud-Sim: Orbital Data-Center Constellation Optimizer")
    st.caption(
        "Simulate a LEO compute constellation running AI workloads in orbit, then compare "
        "the cost, carbon and latency against terrestrial compute."
    )

    config = _build_config()
    run_clicked = st.sidebar.button("Run simulation", type="primary")

    if not run_clicked and "last_config" not in st.session_state:
        st.info("Configure the scenario in the sidebar and press **Run simulation**.")
        return

    if run_clicked:
        st.session_state["last_config"] = config.model_dump_json()

    bundle = _run(st.session_state["last_config"])
    result = bundle["result"]
    economics = bundle["economics"]
    summary = bundle["summary"]

    top = st.columns(4)
    top[0].metric("Satellites", summary["total"], f"{summary['compute_nodes']} compute")
    top[1].metric("Jobs routed", f"{economics.jobs_completed:,}")
    top[2].metric("Carbon offset", f"{economics.carbon_offset_kg:,.0f} kg")
    top[3].metric("ROI ratio", f"{economics.roi_ratio:.2f}x")

    globe_col, metrics_col = st.columns([3, 2])

    with globe_col:
        st.subheader("Constellation state")
        max_step = max(len(result.snapshots) - 1, 0)
        step = st.slider("Timestep", 0, max_step, 0) if max_step > 0 else 0
        st.plotly_chart(render_globe(result, step), use_container_width=True)
        st.caption(
            "Green = compute node eligible, red = compute node throttled/idle, "
            "blue = relay, orange diamond = ground station, yellow = active route."
        )

    with metrics_col:
        st.subheader("Economic ROI")
        econ_cols = st.columns(2)
        econ_cols[0].metric("Grid cost saved", f"${economics.grid_cost_saved_usd:,.0f}")
        econ_cols[1].metric("Space compute cost", f"${economics.space_compute_cost_usd:,.0f}")
        econ_cols[0].metric("Net value", f"${economics.net_value_usd:,.0f}")
        cost_per_gflop = economics.cost_per_gflop_usd
        econ_cols[1].metric(
            "Cost / GFLOP",
            "n/a" if cost_per_gflop == float("inf") else f"${cost_per_gflop:.2e}",
        )
        st.plotly_chart(render_economics_bar(economics), use_container_width=True)

    st.subheader("Telemetry")
    st.plotly_chart(render_telemetry(result.telemetry), use_container_width=True)
    with st.expander("Raw telemetry table"):
        st.dataframe(result.telemetry, use_container_width=True)


if __name__ == "__main__":
    main()
