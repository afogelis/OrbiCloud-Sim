"""Plotly visualizations for OrbiCloud-Sim.

Pure presentation helpers: they consume simulation/economics data structures and
return Plotly figures. No physics or routing logic lives here.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from .config import NodeRole
from .economics import EconomicsResult
from .network_router import GROUND_NODE_ID, SimulationResult
from .orbital_engine import EARTH_RADIUS_KM

COLOR_COMPUTE_OK = "#2ca02c"
COLOR_COMPUTE_THROTTLED = "#d62728"
COLOR_RELAY = "#1f77b4"
COLOR_GROUND = "#ff7f0e"
COLOR_ROUTE = "#f5e642"


def _earth_mesh(resolution: int = 36) -> go.Surface:
    """A translucent Earth sphere sized in kilometers."""

    u = np.linspace(0, 2 * np.pi, resolution)
    v = np.linspace(0, np.pi, resolution)
    x = EARTH_RADIUS_KM * np.outer(np.cos(u), np.sin(v))
    y = EARTH_RADIUS_KM * np.outer(np.sin(u), np.sin(v))
    z = EARTH_RADIUS_KM * np.outer(np.ones_like(u), np.cos(v))
    return go.Surface(
        x=x,
        y=y,
        z=z,
        colorscale=[[0, "#0b1a3a"], [1, "#13315c"]],
        showscale=False,
        opacity=0.85,
        hoverinfo="skip",
        name="Earth",
    )


def _node_color(role: NodeRole, eligible: bool) -> str:
    if role is NodeRole.RELAY:
        return COLOR_RELAY
    return COLOR_COMPUTE_OK if eligible else COLOR_COMPUTE_THROTTLED


def render_globe(result: SimulationResult, step: int) -> go.Figure:
    """Render the 3D globe with satellites color-coded by thermal/battery state."""

    snapshot = result.snapshots[step]
    nodes = snapshot["nodes"]

    xs, ys, zs, colors, texts = [], [], [], [], []
    for sat in result.satellites:
        node = nodes[sat.sat_id]
        pos = node["position_km"]
        xs.append(pos[0])
        ys.append(pos[1])
        zs.append(pos[2])
        colors.append(_node_color(node["role"], node["eligible"]))
        texts.append(
            f"{sat.name}<br>role={node['role'].value}"
            f"<br>SoC={node['battery_fraction']*100:.0f}%"
            f"<br>T={node['temperature_c']:.1f} C"
            f"<br>{'eclipse' if node['in_eclipse'] else 'sunlight'}"
            f"<br>{'eligible' if node['eligible'] else 'throttled/idle'}"
        )

    fig = go.Figure()
    fig.add_trace(_earth_mesh())
    fig.add_trace(
        go.Scatter3d(
            x=xs,
            y=ys,
            z=zs,
            mode="markers",
            marker=dict(size=4, color=colors),
            text=texts,
            hoverinfo="text",
            name="Satellites",
        )
    )

    ground = snapshot["ground_position_km"]
    fig.add_trace(
        go.Scatter3d(
            x=[ground[0]],
            y=[ground[1]],
            z=[ground[2]],
            mode="markers",
            marker=dict(size=6, color=COLOR_GROUND, symbol="diamond"),
            text=[result.config.ground_station.name],
            hoverinfo="text",
            name="Ground station",
        )
    )

    _add_route_trace(fig, snapshot)

    axis = dict(showbackground=False, showticklabels=False, title="", showgrid=False, zeroline=False)
    fig.update_layout(
        title=f"Constellation state (step {step})",
        scene=dict(xaxis=axis, yaxis=axis, zaxis=axis, aspectmode="data"),
        margin=dict(l=0, r=0, t=40, b=0),
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=0.0),
        height=620,
    )
    return fig


def _add_route_trace(fig: go.Figure, snapshot: dict) -> None:
    """Overlay the active compute route as a connected polyline."""

    path = snapshot["route_path"]
    if len(path) < 2:
        return
    nodes = snapshot["nodes"]
    ground = snapshot["ground_position_km"]

    xs, ys, zs = [], [], []
    for node_id in path:
        pos = ground if node_id == GROUND_NODE_ID else nodes[node_id]["position_km"]
        xs.append(pos[0])
        ys.append(pos[1])
        zs.append(pos[2])

    fig.add_trace(
        go.Scatter3d(
            x=xs,
            y=ys,
            z=zs,
            mode="lines",
            line=dict(color=COLOR_ROUTE, width=5),
            hoverinfo="skip",
            name="Active route",
        )
    )


def render_telemetry(result: SimulationResult) -> go.Figure:
    """Time-series of mean battery SoC and eligible compute capacity."""

    telemetry = result.telemetry
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=telemetry["time_s"] / 60.0,
            y=telemetry["mean_battery_fraction"] * 100.0,
            mode="lines",
            name="Mean battery SoC (%)",
            line=dict(color=COLOR_COMPUTE_OK),
        )
    )
    fig.add_trace(
        go.Scatter(
            x=telemetry["time_s"] / 60.0,
            y=telemetry["eligible_compute_nodes"],
            mode="lines",
            name="Eligible compute nodes",
            yaxis="y2",
            line=dict(color=COLOR_RELAY),
        )
    )
    fig.update_layout(
        title="Telemetry",
        xaxis=dict(title="Time (minutes)"),
        yaxis=dict(title="Battery SoC (%)", range=[0, 100]),
        yaxis2=dict(title="Eligible compute nodes", overlaying="y", side="right"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        margin=dict(l=10, r=10, t=50, b=10),
        height=360,
    )
    return fig


def render_economics(economics: EconomicsResult) -> go.Figure:
    """Bar chart comparing terrestrial savings to orbital compute cost."""

    labels = ["Grid cost saved", "Carbon value", "GPU rental avoided", "Space compute cost"]
    values = [
        economics.grid_cost_saved_usd,
        economics.carbon_value_usd,
        economics.terrestrial_rental_usd,
        economics.space_compute_cost_usd,
    ]
    colors = [COLOR_COMPUTE_OK, COLOR_RELAY, COLOR_GROUND, COLOR_COMPUTE_THROTTLED]
    fig = go.Figure(go.Bar(x=labels, y=values, marker_color=colors))
    fig.update_layout(
        title="Space vs terrestrial value",
        yaxis=dict(title="USD"),
        margin=dict(l=10, r=10, t=50, b=10),
        height=360,
    )
    return fig


def render_dashboard(result: SimulationResult, economics: EconomicsResult, step: int = 0) -> go.Figure:
    """Combined dashboard figure: globe plus economics and telemetry panels."""

    if not result.snapshots:
        raise ValueError("Simulation result has no snapshots to visualize.")
    step = int(np.clip(step, 0, len(result.snapshots) - 1))

    globe = render_globe(result, step)
    econ = render_economics(economics)
    telem = render_telemetry(result)

    fig = make_subplots(
        rows=2,
        cols=2,
        specs=[
            [{"type": "scene", "rowspan": 2}, {"type": "xy"}],
            [None, {"type": "xy"}],
        ],
        column_widths=[0.58, 0.42],
        row_heights=[0.5, 0.5],
        subplot_titles=(
            f"Constellation (step {step})",
            "Space vs terrestrial value",
            "Telemetry",
        ),
        vertical_spacing=0.12,
        horizontal_spacing=0.08,
    )

    for trace in globe.data:
        fig.add_trace(trace, row=1, col=1)
    for trace in econ.data:
        fig.add_trace(trace, row=1, col=2)
    for trace in telem.data:
        fig.add_trace(trace, row=2, col=2)

    axis = dict(showbackground=False, showticklabels=False, title="", showgrid=False, zeroline=False)
    fig.update_layout(
        title="OrbiCloud-Sim dashboard",
        height=820,
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=-0.08),
        scene=dict(xaxis=axis, yaxis=axis, zaxis=axis, aspectmode="data"),
        margin=dict(l=20, r=20, t=60, b=40),
    )
    fig.update_yaxes(title_text="USD", row=1, col=2)
    fig.update_xaxes(title_text="Time (minutes)", row=2, col=2)
    fig.update_yaxes(title_text="Battery SoC (%)", range=[0, 100], row=2, col=2)
    return fig


def write_visualizations(
    result: SimulationResult,
    economics: EconomicsResult,
    output_dir: str | Path,
    step: int = 0,
) -> dict[str, Path]:
    """Write standalone HTML charts to ``output_dir`` and return their paths."""

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    if not result.snapshots:
        raise ValueError("Simulation result has no snapshots to visualize.")
    step = int(np.clip(step, 0, len(result.snapshots) - 1))

    figures = {
        "dashboard.html": render_dashboard(result, economics, step),
        "globe.html": render_globe(result, step),
        "telemetry.html": render_telemetry(result),
        "economics.html": render_economics(economics),
    }

    written: dict[str, Path] = {}
    for filename, figure in figures.items():
        path = out / filename
        figure.write_html(path, include_plotlyjs="cdn", full_html=True)
        written[filename] = path
    return written
