"""Plotly visualizations for OrbiCloud-Sim.

Pure presentation helpers: they consume simulation/economics data structures and
return Plotly figures. No physics or routing logic lives here.
"""

from __future__ import annotations

import math
from functools import lru_cache
from importlib import resources
from pathlib import Path

import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from PIL import Image

from .config import NodeRole
from .economics import EconomicsResult
from .network_router import GROUND_NODE_ID, SimulationResult
from .orbital_engine import EARTH_RADIUS_KM, latlon_to_ecef_unit

# Modern dashboard palette (cool slate + cyan accents; avoid purple/glow defaults).
BG = "#0b1220"
PANEL = "#121a2b"
GRID = "#243044"
TEXT = "#e8eef7"
MUTED = "#93a4bd"
COLOR_COMPUTE_OK = "#34d399"
COLOR_COMPUTE_THROTTLED = "#fb7185"
COLOR_RELAY = "#38bdf8"
COLOR_GROUND = "#fbbf24"
COLOR_ROUTE = "#fde68a"
ATMOSPHERE = "rgba(125, 211, 252, 0.18)"

EARTH_TEXTURE_NAME = "earth_day.jpg"
EARTH_TEXTURE_MAX_WIDTH = 512
# Kaleido/WebGL colorscales blow up above a few hundred stops; keep a tight palette.
EARTH_PALETTE_COLORS = 64


# Default globe look-at: continental United States (geographic center).
GLOBE_FOCUS_LAT_DEG: float = 39.8
GLOBE_FOCUS_LON_DEG: float = -98.5
GLOBE_CAMERA_DISTANCE: float = 1.85


def _base_layout(**overrides: object) -> dict:
    """Shared dark layout used by 2D charts."""

    layout = dict(
        paper_bgcolor=BG,
        plot_bgcolor=PANEL,
        font=dict(family="IBM Plex Sans, Segoe UI, Helvetica Neue, sans-serif", color=TEXT, size=13),
        title=dict(font=dict(size=18, color=TEXT), x=0.02, xanchor="left"),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            bgcolor="rgba(0,0,0,0)",
            font=dict(color=MUTED, size=12),
        ),
        margin=dict(l=56, r=56, t=72, b=48),
        hoverlabel=dict(
            bgcolor=PANEL,
            font_size=12,
            font_family="IBM Plex Sans, Segoe UI, Helvetica Neue, sans-serif",
        ),
    )
    layout.update(overrides)
    return layout


def _style_cartesian(fig: go.Figure) -> None:
    fig.update_xaxes(
        showgrid=True,
        gridcolor=GRID,
        zeroline=False,
        linecolor=GRID,
        tickfont=dict(color=MUTED),
        title_font=dict(color=MUTED),
    )
    fig.update_yaxes(
        showgrid=True,
        gridcolor=GRID,
        zeroline=False,
        linecolor=GRID,
        tickfont=dict(color=MUTED),
        title_font=dict(color=MUTED),
    )


@lru_cache(maxsize=1)
def _load_earth_texture() -> Image.Image:
    """Load the packaged Blue Marble JPEG, resized for interactive rendering."""

    asset = resources.files("orbicloud_sim").joinpath("assets", EARTH_TEXTURE_NAME)
    with resources.as_file(asset) as path:
        image = Image.open(path).convert("RGB")
    if image.width > EARTH_TEXTURE_MAX_WIDTH:
        scale = EARTH_TEXTURE_MAX_WIDTH / float(image.width)
        image = image.resize(
            (EARTH_TEXTURE_MAX_WIDTH, max(1, int(round(image.height * scale)))),
            Image.Resampling.LANCZOS,
        )
    return image


def _rgb_to_indexed_texture(image: Image.Image) -> tuple[np.ndarray, list[list]]:
    """Map an RGB image to a scalar field + discrete colorscale for Plotly Surface.

    Plotly cannot apply true RGB textures to ``go.Surface``. A compact adaptive
    palette keeps the colorscale within Kaleido/WebGL limits while preserving
    land/ocean structure from the Blue Marble source.
    """

    paletted = image.quantize(colors=EARTH_PALETTE_COLORS, method=Image.Quantize.MEDIANCUT)
    indexed = np.asarray(paletted, dtype=float)
    palette = paletted.getpalette()
    if palette is None:
        raise RuntimeError("Failed to build Earth texture palette.")

    n_colors = min(EARTH_PALETTE_COLORS, max(int(indexed.max()) + 1, 1))
    rgb_palette = np.asarray(palette[: n_colors * 3], dtype=int).reshape(n_colors, 3)
    if n_colors == 1:
        r, g, b = rgb_palette[0]
        colorscale = [[0.0, f"rgb({r},{g},{b})"], [1.0, f"rgb({r},{g},{b})"]]
        return indexed, colorscale

    denom = float(n_colors - 1)
    colorscale = [
        [i / denom, f"rgb({int(r)},{int(g)},{int(b)})"]
        for i, (r, g, b) in enumerate(rgb_palette)
    ]
    return indexed, colorscale


def _earth_mesh() -> list[go.Surface]:
    """Realistic Earth sphere with Blue Marble texture plus a thin atmosphere shell."""

    image = _load_earth_texture()
    # Equirectangular Blue Marble: top = +90 lat, left = -180 lon. Do not flip.
    indexed, colorscale = _rgb_to_indexed_texture(image)

    n_lat, n_lon = indexed.shape
    lon = np.linspace(-np.pi, np.pi, n_lon)
    lat = np.linspace(np.pi / 2.0, -np.pi / 2.0, n_lat)
    lon_grid, lat_grid = np.meshgrid(lon, lat)

    x = EARTH_RADIUS_KM * np.cos(lat_grid) * np.cos(lon_grid)
    y = EARTH_RADIUS_KM * np.cos(lat_grid) * np.sin(lon_grid)
    z = EARTH_RADIUS_KM * np.sin(lat_grid)

    earth = go.Surface(
        x=x,
        y=y,
        z=z,
        surfacecolor=indexed,
        cmin=0,
        cmax=max(float(indexed.max()), 1.0),
        colorscale=colorscale,
        showscale=False,
        hoverinfo="skip",
        name="Earth",
        lighting=dict(
            ambient=0.55,
            diffuse=0.85,
            fresnel=0.15,
            specular=0.35,
            roughness=0.55,
        ),
        lightposition=dict(x=1.6e4, y=4.0e3, z=8.0e3),
    )

    # Soft atmosphere limb: slightly larger translucent cyan shell.
    atm_scale = 1.025
    atmosphere = go.Surface(
        x=x * atm_scale,
        y=y * atm_scale,
        z=z * atm_scale,
        surfacecolor=np.zeros_like(indexed),
        colorscale=[[0, ATMOSPHERE], [1, ATMOSPHERE]],
        showscale=False,
        opacity=0.22,
        hoverinfo="skip",
        name="Atmosphere",
        lighting=dict(ambient=1.0, diffuse=0.0, fresnel=0.0, specular=0.0),
    )
    return [earth, atmosphere]


def _globe_camera(
    latitude_deg: float = GLOBE_FOCUS_LAT_DEG,
    longitude_deg: float = GLOBE_FOCUS_LON_DEG,
    distance: float = GLOBE_CAMERA_DISTANCE,
) -> dict:
    """Camera aimed at a geographic focus with north toward +Z."""

    eye = latlon_to_ecef_unit(latitude_deg, longitude_deg) * distance
    return dict(
        eye=dict(x=float(eye[0]), y=float(eye[1]), z=float(eye[2])),
        up=dict(x=0.0, y=0.0, z=1.0),
        center=dict(x=0.0, y=0.0, z=0.0),
    )


def _node_color(role: NodeRole, eligible: bool) -> str:
    if role is NodeRole.RELAY:
        return COLOR_RELAY
    return COLOR_COMPUTE_OK if eligible else COLOR_COMPUTE_THROTTLED


def _scene_axes() -> dict:
    return dict(
        showbackground=False,
        showticklabels=False,
        showgrid=False,
        zeroline=False,
        title="",
        showspikes=False,
    )


def render_globe(result: SimulationResult, step: int) -> go.Figure:
    """Render the 3D globe with satellites color-coded by thermal/battery state."""

    snapshot = result.snapshots[step]
    nodes = snapshot["nodes"]

    xs, ys, zs, colors, texts, sizes = [], [], [], [], [], []
    for sat in result.satellites:
        node = nodes[sat.sat_id]
        pos = node["position_km"]
        xs.append(float(pos[0]))
        ys.append(float(pos[1]))
        zs.append(float(pos[2]))
        colors.append(_node_color(node["role"], node["eligible"]))
        sizes.append(5 if node["role"] is NodeRole.COMPUTE else 3.5)
        texts.append(
            f"<b>{sat.name}</b><br>role={node['role'].value}"
            f"<br>SoC={node['battery_fraction']*100:.0f}%"
            f"<br>T={node['temperature_c']:.1f} C"
            f"<br>{'eclipse' if node['in_eclipse'] else 'sunlight'}"
            f"<br>{'eligible' if node['eligible'] else 'throttled/idle'}"
        )

    fig = go.Figure()
    for trace in _earth_mesh():
        fig.add_trace(trace)

    fig.add_trace(
        go.Scatter3d(
            x=xs,
            y=ys,
            z=zs,
            mode="markers",
            marker=dict(size=sizes, color=colors, opacity=0.95, line=dict(width=0)),
            text=texts,
            hoverinfo="text",
            name="Satellites",
        )
    )

    ground = snapshot["ground_position_km"]
    fig.add_trace(
        go.Scatter3d(
            x=[float(ground[0])],
            y=[float(ground[1])],
            z=[float(ground[2])],
            mode="markers",
            marker=dict(size=8, color=COLOR_GROUND, symbol="diamond", opacity=1.0),
            text=[f"<b>{result.config.ground_station.name}</b>"],
            hoverinfo="text",
            name="Ground station",
        )
    )

    _add_route_trace(fig, snapshot)

    fig.update_layout(
        **_base_layout(
            title=dict(text=f"Constellation state · step {step}", font=dict(size=18, color=TEXT), x=0.02),
            height=720,
            margin=dict(l=0, r=0, t=56, b=8),
            legend=dict(orientation="h", yanchor="bottom", y=0.01, x=0.01, bgcolor="rgba(11,18,32,0.55)"),
            scene=dict(
                xaxis=_scene_axes(),
                yaxis=_scene_axes(),
                zaxis=_scene_axes(),
                aspectmode="data",
                bgcolor=BG,
                camera=_globe_camera(),
            ),
        )
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
        xs.append(float(pos[0]))
        ys.append(float(pos[1]))
        zs.append(float(pos[2]))

    fig.add_trace(
        go.Scatter3d(
            x=xs,
            y=ys,
            z=zs,
            mode="lines",
            line=dict(color=COLOR_ROUTE, width=7),
            hoverinfo="skip",
            name="Active route",
        )
    )


def render_telemetry(result: SimulationResult) -> go.Figure:
    """Time-series of mean battery SoC and eligible compute capacity."""

    telemetry = result.telemetry
    minutes = telemetry["time_s"] / 60.0
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=minutes,
            y=telemetry["mean_battery_fraction"] * 100.0,
            mode="lines",
            name="Mean battery SoC (%)",
            line=dict(color=COLOR_COMPUTE_OK, width=2.5, shape="spline"),
            fill="tozeroy",
            fillcolor="rgba(52, 211, 153, 0.12)",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=minutes,
            y=telemetry["eligible_compute_nodes"],
            mode="lines",
            name="Eligible compute nodes",
            yaxis="y2",
            line=dict(color=COLOR_RELAY, width=2.5, shape="spline"),
        )
    )
    fig.update_layout(
        **_base_layout(
            title="Telemetry",
            height=400,
            yaxis=dict(title="Battery SoC (%)", range=[0, 100], color=MUTED),
            yaxis2=dict(
                title="Eligible compute nodes",
                overlaying="y",
                side="right",
                showgrid=False,
                color=MUTED,
            ),
            xaxis=dict(title="Time (minutes)"),
        )
    )
    _style_cartesian(fig)
    return fig


def render_economics(economics: EconomicsResult) -> go.Figure:
    """Compare unit compute cost and terrestrial impacts avoided.

    Short simulation windows make absolute USD savings look tiny next to amortized
    constellation CapEx. Unit cost ($/GFLOP) and physical offsets (kWh, kg CO2,
    OpEx, cooling premium) show the operational benefit without that scale mismatch.
    """

    terrestrial_cost_per_gflop, space_cost_per_gflop = _unit_costs(economics)
    break_even = economics.break_even_months
    break_even_text = "∞" if math.isinf(break_even) else f"{break_even:.1f} months"

    fig = make_subplots(
        rows=1,
        cols=2,
        subplot_titles=("Cost per GFLOP", "Impact avoided this run"),
        column_widths=[0.48, 0.52],
        horizontal_spacing=0.12,
    )

    fig.add_trace(_cost_per_gflop_trace(terrestrial_cost_per_gflop, space_cost_per_gflop), row=1, col=1)
    fig.add_trace(_impact_trace(economics), row=1, col=2)

    fig.update_layout(
        **_base_layout(
            title=f"Space vs terrestrial economics · break-even {break_even_text}",
            height=420,
            margin=dict(l=48, r=24, t=72, b=48),
        )
    )
    fig.update_annotations(font=dict(color=MUTED, size=13))
    fig.update_yaxes(title_text="USD / GFLOP", type="log", row=1, col=1)
    fig.update_yaxes(title_text="Avoided amount", row=1, col=2)
    _style_cartesian(fig)
    return fig


def _unit_costs(economics: EconomicsResult) -> tuple[float, float]:
    if economics.total_gflops <= 0:
        return float("nan"), float("nan")
    terrestrial = (
        economics.terrestrial_rental_usd + economics.operational_energy_savings_usd
    ) / economics.total_gflops
    return terrestrial, economics.cost_per_gflop_usd


def _cost_per_gflop_trace(terrestrial: float, orbital: float) -> go.Bar:
    return go.Bar(
        x=["Terrestrial", "Orbital"],
        y=[terrestrial, orbital],
        marker=dict(color=[COLOR_RELAY, COLOR_COMPUTE_OK], line=dict(width=0)),
        text=[f"${terrestrial:.2e}", f"${orbital:.2e}"],
        textposition="outside",
        textfont=dict(color=MUTED, size=11),
        hovertemplate="%{x}<br>$%{y:.3e} / GFLOP<extra></extra>",
        showlegend=False,
        name="Cost / GFLOP",
    )


def _impact_trace(economics: EconomicsResult) -> go.Bar:
    return go.Bar(
        x=["Energy (kWh)", "Carbon (kg CO₂)", "OpEx saved ($)", "Cooling premium ($)"],
        y=[
            economics.terrestrial_energy_kwh,
            economics.carbon_offset_kg,
            economics.operational_energy_savings_usd,
            economics.cooling_premium_usd,
        ],
        marker=dict(
            color=[COLOR_COMPUTE_OK, COLOR_RELAY, COLOR_GROUND, COLOR_COMPUTE_THROTTLED],
            line=dict(width=0),
        ),
        text=[
            f"{economics.terrestrial_energy_kwh:.2f}",
            f"{economics.carbon_offset_kg:.2f}",
            f"${economics.operational_energy_savings_usd:.2f}",
            f"${economics.cooling_premium_usd:.2f}",
        ],
        textposition="outside",
        textfont=dict(color=MUTED, size=11),
        hovertemplate="%{x}<br>%{y:.4g}<extra></extra>",
        showlegend=False,
        name="Impact avoided",
    )


def render_dashboard(result: SimulationResult, economics: EconomicsResult, step: int = 0) -> go.Figure:
    """Combined dashboard figure: globe plus economics and telemetry panels."""

    if not result.snapshots:
        raise ValueError("Simulation result has no snapshots to visualize.")
    step = int(np.clip(step, 0, len(result.snapshots) - 1))

    globe = render_globe(result, step)
    telem = render_telemetry(result)
    terrestrial_cost, orbital_cost = _unit_costs(economics)

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
            f"Constellation · step {step}",
            "Cost per GFLOP",
            "Telemetry",
        ),
        vertical_spacing=0.10,
        horizontal_spacing=0.06,
    )

    for trace in globe.data:
        fig.add_trace(trace, row=1, col=1)
    fig.add_trace(_cost_per_gflop_trace(terrestrial_cost, orbital_cost), row=1, col=2)
    for trace in telem.data:
        fig.add_trace(trace, row=2, col=2)

    fig.update_layout(
        **_base_layout(
            title=dict(text="OrbiCloud-Sim", font=dict(size=22, color=TEXT), x=0.02),
            height=900,
            showlegend=True,
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=-0.06,
                bgcolor="rgba(0,0,0,0)",
                font=dict(color=MUTED),
            ),
            margin=dict(l=24, r=24, t=72, b=56),
            scene=dict(
                xaxis=_scene_axes(),
                yaxis=_scene_axes(),
                zaxis=_scene_axes(),
                aspectmode="data",
                bgcolor=BG,
                camera=_globe_camera(),
            ),
        )
    )
    fig.update_annotations(font=dict(color=MUTED, size=13))
    fig.update_yaxes(title_text="USD / GFLOP", type="log", row=1, col=2)
    fig.update_xaxes(title_text="Time (minutes)", row=2, col=2)
    fig.update_yaxes(title_text="Battery SoC (%)", range=[0, 100], row=2, col=2)
    _style_cartesian(fig)
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
