"""Plotly visualizations for the OrbiCloud-Sim dashboard.

Pure presentation helpers: they consume simulation/economics data structures and
return Plotly figures. No physics or routing logic lives here.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from orbicloud_sim.config import NodeRole
from orbicloud_sim.economics import EconomicsResult
from orbicloud_sim.network_router import GROUND_NODE_ID, SimulationResult
from orbicloud_sim.orbital_engine import EARTH_RADIUS_KM

# Discrete colors for node state, chosen to remain distinguishable for common
# color-vision deficiencies.
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

    _add_route_trace(fig, result, snapshot)

    axis = dict(showbackground=False, showticklabels=False, title="", showgrid=False, zeroline=False)
    fig.update_layout(
        scene=dict(xaxis=axis, yaxis=axis, zaxis=axis, aspectmode="data"),
        margin=dict(l=0, r=0, t=0, b=0),
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=0.0),
        height=620,
    )
    return fig


def _add_route_trace(fig: go.Figure, result: SimulationResult, snapshot: dict) -> None:
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


def render_telemetry(telemetry: pd.DataFrame) -> go.Figure:
    """Time-series of mean battery SoC and eligible compute capacity."""

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
        xaxis=dict(title="Time (minutes)"),
        yaxis=dict(title="Battery SoC (%)", range=[0, 100]),
        yaxis2=dict(title="Eligible compute nodes", overlaying="y", side="right"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        margin=dict(l=10, r=10, t=30, b=10),
        height=320,
    )
    return fig


def render_economics_bar(economics: EconomicsResult) -> go.Figure:
    """Bar chart comparing terrestrial savings to orbital compute cost."""

    labels = ["Grid cost saved", "Carbon value", "Space compute cost"]
    values = [
        economics.grid_cost_saved_usd,
        economics.carbon_value_usd,
        economics.space_compute_cost_usd,
    ]
    colors = [COLOR_COMPUTE_OK, COLOR_RELAY, COLOR_COMPUTE_THROTTLED]
    fig = go.Figure(go.Bar(x=labels, y=values, marker_color=colors))
    fig.update_layout(
        yaxis=dict(title="USD"),
        margin=dict(l=10, r=10, t=30, b=10),
        height=320,
        title="Space vs Terrestrial value over the simulated window",
    )
    return fig
