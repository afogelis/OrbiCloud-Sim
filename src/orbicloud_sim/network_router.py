"""Dynamic inter-satellite-link routing and the node state machine.

This module builds a time-varying line-of-sight graph over the constellation,
advances per-node battery and thermal state, and finds the cheapest feasible
route that delivers a compute job from a ground station to an eligible
``COMPUTE`` node and returns the result to Earth.

The end-to-end ``run_simulation`` orchestrator lives here so that the Streamlit
layer stays free of physics.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta

import networkx as nx
import numpy as np
import pandas as pd
from skyfield.timelib import Time, Timescale

from .config import NodeRole, SatelliteHardwareConfig, SimulationConfig
from .orbital_engine import (
    EARTH_RADIUS_KM,
    Satellite,
    build_timescale,
    generate_walker_delta,
    ground_station_position,
    is_in_eclipse,
    propagate,
)

SPEED_OF_LIGHT_KM_S: float = 299792.458
GROUND_NODE_ID: int = -1
ABSOLUTE_ZERO_C: float = -273.15
DEEP_SPACE_SINK_C: float = -270.0  # Effective radiator sink temperature.


@dataclass
class NodeState:
    """Mutable runtime state of one satellite during the simulation."""

    sat_id: int
    role: NodeRole
    profile: SatelliteHardwareConfig
    battery_wh: float
    temperature_c: float
    in_eclipse: bool = False
    is_computing: bool = False

    @property
    def battery_fraction(self) -> float:
        return self.battery_wh / self.profile.battery_capacity_wh

    def is_compute_eligible(self) -> bool:
        """A compute node may accept work only when cool enough and charged enough."""

        if self.role is not NodeRole.COMPUTE:
            return False
        thermal_ok = self.temperature_c <= self.profile.thermal_threshold_c
        battery_ok = self.battery_fraction >= self.profile.min_battery_fraction
        return thermal_ok and battery_ok


@dataclass
class Route:
    """Result of a single routing query."""

    feasible: bool
    path: list[int] = field(default_factory=list)
    compute_node_id: int | None = None
    latency_s: float = float("inf")
    distance_km: float = float("inf")


def init_states(satellites: list[Satellite]) -> dict[int, NodeState]:
    """Initialize every node fully charged and at a benign temperature."""

    states: dict[int, NodeState] = {}
    for sat in satellites:
        states[sat.sat_id] = NodeState(
            sat_id=sat.sat_id,
            role=sat.role,
            profile=sat.profile,
            battery_wh=sat.profile.battery_capacity_wh,
            temperature_c=20.0,
        )
    return states


def advance_battery(state: NodeState, dt_s: float) -> None:
    """Integrate one timestep of charge/discharge, clamping to physical bounds."""

    profile = state.profile
    draw_w = profile.idle_draw_w + (profile.compute_draw_w if state.is_computing else 0.0)
    charge_w = profile.solar_charge_w if not state.in_eclipse else 0.0
    net_w = charge_w - draw_w
    state.battery_wh = float(
        np.clip(state.battery_wh + net_w * dt_s / 3600.0, 0.0, profile.battery_capacity_wh)
    )


def advance_thermal(state: NodeState, dt_s: float) -> None:
    """Integrate one timestep of the first-order lumped thermal model."""

    profile = state.profile
    heat_in_w = profile.idle_draw_w
    if state.is_computing:
        heat_in_w += profile.compute_draw_w * profile.compute_heat_fraction
    if not state.in_eclipse:
        heat_in_w += profile.solar_heat_load_w

    # Radiator rejection scales with how far the node sits above the deep-space sink.
    temperature_span = max(state.temperature_c - DEEP_SPACE_SINK_C, 0.0)
    reference_span = profile.thermal_threshold_c - DEEP_SPACE_SINK_C
    heat_out_w = profile.radiative_cooling_w * (temperature_span / reference_span)

    delta_t = (heat_in_w - heat_out_w) * dt_s / profile.heat_capacity_j_per_k
    state.temperature_c = max(state.temperature_c + delta_t, ABSOLUTE_ZERO_C)


def advance_state(state: NodeState, in_eclipse: bool, is_computing: bool, dt_s: float) -> None:
    """Update eclipse flag, duty flag, then battery and thermal state by ``dt_s``."""

    state.in_eclipse = in_eclipse
    state.is_computing = is_computing
    advance_battery(state, dt_s)
    advance_thermal(state, dt_s)


def line_of_sight(a_km: np.ndarray, b_km: np.ndarray, blocking_radius_km: float) -> bool:
    """Return True if the segment a->b does not pass below ``blocking_radius_km``.

    Intended for satellite-to-satellite links, where both endpoints sit well above
    the blocking sphere. It is not suitable for ground links, whose endpoint lies on
    the surface (use :func:`ground_visible` instead).
    """

    segment = b_km - a_km
    seg_len_sq = float(np.dot(segment, segment))
    if seg_len_sq == 0.0:
        return True
    t_closest = float(np.clip(-np.dot(a_km, segment) / seg_len_sq, 0.0, 1.0))
    closest_point = a_km + t_closest * segment
    return float(np.linalg.norm(closest_point)) >= blocking_radius_km


def ground_visible(
    ground_km: np.ndarray, sat_km: np.ndarray, min_elevation_deg: float
) -> bool:
    """Return True if ``sat_km`` is above the ground station's local horizon.

    The elevation angle is measured between the local geocentric vertical at the
    station and the line of sight to the satellite. This correctly handles a
    surface-level endpoint, unlike the inter-satellite occlusion test.
    """

    ground_norm = float(np.linalg.norm(ground_km))
    if ground_norm == 0.0:
        return False
    up_hat = ground_km / ground_norm
    line_of_sight_vec = sat_km - ground_km
    los_norm = float(np.linalg.norm(line_of_sight_vec))
    if los_norm == 0.0:
        return False
    sin_elevation = float(np.dot(up_hat, line_of_sight_vec / los_norm))
    elevation_deg = np.degrees(np.arcsin(np.clip(sin_elevation, -1.0, 1.0)))
    return elevation_deg >= min_elevation_deg


def build_isl_graph(
    positions: dict[int, np.ndarray],
    satellites: list[Satellite],
    ground_position: np.ndarray,
    config: SimulationConfig,
) -> nx.Graph:
    """Build the dynamic line-of-sight ISL graph at a single instant.

    Nodes are satellite ids plus ``GROUND_NODE_ID``. Edges carry ``distance_km``
    and ``latency_s`` (propagation only). Optical ISLs require mutual range and an
    unobstructed chord; ground links additionally respect ``max_ground_link_km``.
    """

    blocking_radius = EARTH_RADIUS_KM + config.routing.atmosphere_margin_km
    graph = nx.Graph()
    for sat in satellites:
        graph.add_node(sat.sat_id, role=sat.role)
    graph.add_node(GROUND_NODE_ID, role="ground")

    by_id = {sat.sat_id: sat for sat in satellites}
    ids = [sat.sat_id for sat in satellites]

    for i in range(len(ids)):
        id_a = ids[i]
        pos_a = positions[id_a]
        range_a = by_id[id_a].profile.max_isl_range_km
        for j in range(i + 1, len(ids)):
            id_b = ids[j]
            pos_b = positions[id_b]
            distance = float(np.linalg.norm(pos_a - pos_b))
            max_range = min(range_a, by_id[id_b].profile.max_isl_range_km)
            if distance > max_range:
                continue
            if not line_of_sight(pos_a, pos_b, blocking_radius):
                continue
            graph.add_edge(
                id_a, id_b, distance_km=distance, latency_s=distance / SPEED_OF_LIGHT_KM_S
            )

    for id_a in ids:
        pos_a = positions[id_a]
        distance = float(np.linalg.norm(pos_a - ground_position))
        if distance > config.routing.max_ground_link_km:
            continue
        if not ground_visible(ground_position, pos_a, config.routing.min_ground_elevation_deg):
            continue
        graph.add_edge(
            GROUND_NODE_ID, id_a, distance_km=distance, latency_s=distance / SPEED_OF_LIGHT_KM_S
        )

    return graph


def find_compute_route(
    graph: nx.Graph,
    states: dict[int, NodeState],
    config: SimulationConfig,
    source_id: int = GROUND_NODE_ID,
    ground_id: int = GROUND_NODE_ID,
) -> Route:
    """Find the cheapest route source -> compute node -> ground.

    Every reachable compute node is scored by the round-trip propagation latency
    plus a large penalty if it is currently overheating or low on battery. The
    lowest-cost candidate wins; a route is ``feasible`` only when its chosen node
    is eligible (i.e. no penalty was applied).
    """

    best = Route(feasible=False)
    best_cost = float("inf")

    for node_id, state in states.items():
        if state.role is not NodeRole.COMPUTE or not graph.has_node(node_id):
            continue
        try:
            up_path = nx.dijkstra_path(graph, source_id, node_id, weight="latency_s")
            up_len = nx.dijkstra_path_length(graph, source_id, node_id, weight="latency_s")
            down_path = nx.dijkstra_path(graph, node_id, ground_id, weight="latency_s")
            down_len = nx.dijkstra_path_length(graph, node_id, ground_id, weight="latency_s")
        except nx.NetworkXNoPath:
            continue

        eligible = state.is_compute_eligible()
        penalty = 0.0 if eligible else config.routing.infeasible_penalty_s
        cost = up_len + down_len + penalty
        if cost >= best_cost:
            continue

        best_cost = cost
        full_path = up_path + down_path[1:]
        distance_km = _path_distance(graph, full_path)
        best = Route(
            feasible=eligible,
            path=full_path,
            compute_node_id=node_id,
            latency_s=up_len + down_len,
            distance_km=distance_km,
        )

    return best


def _path_distance(graph: nx.Graph, path: list[int]) -> float:
    """Sum the ``distance_km`` edge attribute along a node path."""

    if len(path) < 2:
        return 0.0
    return float(sum(graph[path[k]][path[k + 1]]["distance_km"] for k in range(len(path) - 1)))


@dataclass
class SimulationResult:
    """Container for time-series telemetry and per-timestep snapshots."""

    telemetry: pd.DataFrame
    snapshots: list[dict]
    satellites: list[Satellite]
    config: SimulationConfig


def _timeline(timescale: Timescale, config: SimulationConfig) -> list[Time]:
    """Build the discrete sample times for the run as explicit UTC datetimes."""

    datetimes = [
        config.epoch + timedelta(seconds=step * config.timestep_s)
        for step in range(config.num_steps)
    ]
    return list(timescale.from_datetimes(datetimes))


def run_simulation(config: SimulationConfig) -> SimulationResult:
    """Run the full constellation simulation and return telemetry + snapshots."""

    timescale = build_timescale()
    epoch = timescale.from_datetime(config.epoch)
    satellites = generate_walker_delta(config.constellation, timescale, epoch)
    states = init_states(satellites)

    timeline = _timeline(timescale, config)
    dt_s = config.timestep_s

    telemetry_rows: list[dict] = []
    snapshots: list[dict] = []

    for step, t in enumerate(timeline):
        positions = propagate(satellites, t)
        ground_position = ground_station_position(config.ground_station, t)

        # Advance node state: compute nodes run work whenever they are eligible.
        for sat in satellites:
            state = states[sat.sat_id]
            eclipse = is_in_eclipse(positions[sat.sat_id], t)
            wants_compute = state.role is NodeRole.COMPUTE and state.is_compute_eligible()
            advance_state(state, in_eclipse=eclipse, is_computing=wants_compute, dt_s=dt_s)

        graph = build_isl_graph(positions, satellites, ground_position, config)
        route = find_compute_route(graph, states, config)

        # Compute actually delivered this step: the assigned node runs at its rated
        # throughput for the timestep, capped by the offered workload.
        delivered_gflops = 0.0
        if route.feasible and route.compute_node_id is not None:
            node_tflops = states[route.compute_node_id].profile.compute_power_tflops
            capacity_gflops = node_tflops * dt_s * 1000.0
            delivered_gflops = float(min(config.workload_gflops, capacity_gflops))

        eligible_compute = sum(
            1 for s in states.values() if s.role is NodeRole.COMPUTE and s.is_compute_eligible()
        )
        mean_soc = float(np.mean([s.battery_fraction for s in states.values()]))
        compute_temps = [
            s.temperature_c for s in states.values() if s.role is NodeRole.COMPUTE
        ]
        mean_temp = float(np.mean(compute_temps)) if compute_temps else float("nan")

        telemetry_rows.append(
            {
                "step": step,
                "time_s": step * dt_s,
                "route_feasible": route.feasible,
                "route_latency_ms": route.latency_s * 1e3 if route.feasible else np.nan,
                "route_distance_km": route.distance_km if route.feasible else np.nan,
                "compute_node_id": route.compute_node_id if route.feasible else -1,
                "delivered_gflops": delivered_gflops,
                "eligible_compute_nodes": eligible_compute,
                "mean_battery_fraction": mean_soc,
                "mean_compute_temp_c": mean_temp,
            }
        )

        snapshots.append(
            {
                "step": step,
                "time_s": step * dt_s,
                "ground_position_km": ground_position,
                "route_path": route.path,
                "nodes": {
                    sat.sat_id: {
                        "position_km": positions[sat.sat_id],
                        "role": states[sat.sat_id].role,
                        "battery_fraction": states[sat.sat_id].battery_fraction,
                        "temperature_c": states[sat.sat_id].temperature_c,
                        "in_eclipse": states[sat.sat_id].in_eclipse,
                        "eligible": states[sat.sat_id].is_compute_eligible(),
                    }
                    for sat in satellites
                },
            }
        )

    telemetry = pd.DataFrame(telemetry_rows)
    return SimulationResult(
        telemetry=telemetry, snapshots=snapshots, satellites=satellites, config=config
    )
