"""Dynamic inter-satellite-link routing and the node state machine.

This module builds a time-varying line-of-sight graph over the constellation,
advances per-node battery and thermodynamic mass, and finds the cheapest
feasible route that delivers a compute job from a ground station to an eligible
``COMPUTE`` node and returns the result to Earth.

ISL edges use vector Earth-occlusion checks and health-penalized distance
weights so pathfinding prefers thermally/power-healthy nodes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta

import networkx as nx
import numpy as np
import pandas as pd
from skyfield.timelib import Time, Timescale

from .config import NodeRole, SatelliteHardwareConfig, SimulationConfig, ThermalConfig
from .orbital_engine import (
    EARTH_RADIUS_KM,
    Satellite,
    build_timescale,
    generate_walker_delta,
    ground_station_position,
    ground_station_position_ecef,
    integrate_thermal_mass,
    is_sunlit,
    kelvin_to_celsius,
    propagate,
    propagate_ecef,
)

SPEED_OF_LIGHT_KM_S: float = 299792.458
GROUND_NODE_ID: int = -1


@dataclass
class NodeState:
    """Mutable runtime state of one satellite during the simulation."""

    sat_id: int
    role: NodeRole
    profile: SatelliteHardwareConfig
    battery_wh: float
    temperature_k: float
    is_sunlit: bool = False
    is_computing: bool = False

    @property
    def battery_fraction(self) -> float:
        return self.battery_wh / self.profile.battery_capacity_wh

    @property
    def temperature_c(self) -> float:
        return kelvin_to_celsius(self.temperature_k)

    @property
    def in_eclipse(self) -> bool:
        return not self.is_sunlit

    def is_compute_eligible(self) -> bool:
        """A compute node may accept work only when cool enough and charged enough."""

        if self.role is not NodeRole.COMPUTE:
            return False
        thermal_ok = self.temperature_k <= self.profile.thermal_threshold_k
        battery_ok = self.battery_fraction >= self.profile.min_battery_fraction
        return thermal_ok and battery_ok

    def is_dead(self, critical_battery_fraction: float) -> bool:
        """True when the node is past structural thermal max or critically discharged."""

        return self.battery_fraction <= critical_battery_fraction

    def is_unhealthy(self, battery_floor: float, thermal_fraction: float) -> bool:
        """True when battery or temperature warrants a heavy routing penalty."""

        thermal_warn_k = self.profile.thermal_threshold_k * thermal_fraction
        return self.battery_fraction < battery_floor or self.temperature_k > thermal_warn_k


@dataclass
class Route:
    """Result of a single routing query."""

    feasible: bool
    path: list[int] = field(default_factory=list)
    compute_node_id: int | None = None
    latency_s: float = float("inf")
    distance_km: float = float("inf")
    weight_cost: float = float("inf")


def init_states(satellites: list[Satellite], thermal: ThermalConfig) -> dict[int, NodeState]:
    """Initialize every node fully charged at the configured initial temperature."""

    states: dict[int, NodeState] = {}
    for sat in satellites:
        states[sat.sat_id] = NodeState(
            sat_id=sat.sat_id,
            role=sat.role,
            profile=sat.profile,
            battery_wh=sat.profile.battery_capacity_wh,
            temperature_k=thermal.initial_temperature_k,
        )
    return states


def advance_battery(state: NodeState, dt_s: float) -> None:
    """Integrate one timestep of charge/discharge, clamping to physical bounds."""

    profile = state.profile
    draw_w = profile.idle_draw_w + (profile.compute_draw_w if state.is_computing else 0.0)
    charge_w = profile.solar_charge_w if state.is_sunlit else 0.0
    net_w = charge_w - draw_w
    state.battery_wh = float(
        np.clip(state.battery_wh + net_w * dt_s / 3600.0, 0.0, profile.battery_capacity_wh)
    )


def advance_thermal(state: NodeState, dt_s: float, thermal: ThermalConfig) -> None:
    """Integrate one timestep of the thermodynamic mass accumulator."""

    state.temperature_k = integrate_thermal_mass(
        state.temperature_k,
        is_sunlit_now=state.is_sunlit,
        is_computing=state.is_computing,
        dt_s=dt_s,
        thermal=thermal,
    )


def advance_state(
    state: NodeState,
    *,
    is_sunlit_now: bool,
    is_computing: bool,
    dt_s: float,
    thermal: ThermalConfig,
) -> None:
    """Update sunlight/duty flags, then battery and thermal state by ``dt_s``."""

    state.is_sunlit = is_sunlit_now
    state.is_computing = is_computing
    advance_battery(state, dt_s)
    advance_thermal(state, dt_s, thermal)


def line_of_sight(a_km: np.ndarray, b_km: np.ndarray, blocking_radius_km: float) -> bool:
    """Return True if segment a->b clears Earth's occlusion sphere.

    Uses the clamped closest-approach projection:
    ``t = -dot(a, V) / dot(V, V)`` with ``V = b - a``, then
    ``closest = a + clamp(t, 0, 1) * V``. The link is blocked when
    ``norm(closest) < blocking_radius_km``.
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
    """Return True if ``sat_km`` is above the ground station's local horizon."""

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


def _edge_weight(
    distance_km: float,
    target: NodeState | None,
    config: SimulationConfig,
) -> float | None:
    """Return health-aware pathfinding weight, or ``None`` to drop the edge."""

    if target is None:
        return distance_km

    routing = config.routing
    if target.is_dead(routing.critical_battery_fraction):
        return None
    # Past structural thermal clamp means the node is offline for routing.
    if target.temperature_k >= config.thermal.structural_max_k:
        return None

    weight = distance_km
    if target.is_unhealthy(routing.health_battery_floor, routing.health_thermal_fraction):
        weight *= routing.health_penalty_multiplier
    return weight


def build_isl_graph(
    positions: dict[int, np.ndarray],
    satellites: list[Satellite],
    ground_position: np.ndarray,
    states: dict[int, NodeState],
    config: SimulationConfig,
) -> nx.Graph:
    """Build the dynamic LOS ISL graph with health-penalized edge weights.

    Nodes are satellite ids plus ``GROUND_NODE_ID``. Surviving edges carry
    ``distance_km``, ``latency_s``, and ``weight`` (health-aware distance used by
    Dijkstra). Optical ISLs require mutual range and an unobstructed chord.
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

            # Undirected graph: penalize if *either* endpoint is unhealthy so
            # traffic avoids degraded nodes in both directions.
            weight_ab = _edge_weight(distance, states[id_b], config)
            weight_ba = _edge_weight(distance, states[id_a], config)
            if weight_ab is None or weight_ba is None:
                continue
            weight = max(weight_ab, weight_ba)
            graph.add_edge(
                id_a,
                id_b,
                distance_km=distance,
                latency_s=distance / SPEED_OF_LIGHT_KM_S,
                weight=weight,
            )

    for id_a in ids:
        pos_a = positions[id_a]
        distance = float(np.linalg.norm(pos_a - ground_position))
        if distance > config.routing.max_ground_link_km:
            continue
        if not ground_visible(ground_position, pos_a, config.routing.min_ground_elevation_deg):
            continue
        weight = _edge_weight(distance, states[id_a], config)
        if weight is None:
            continue
        graph.add_edge(
            GROUND_NODE_ID,
            id_a,
            distance_km=distance,
            latency_s=distance / SPEED_OF_LIGHT_KM_S,
            weight=weight,
        )

    return graph


def find_compute_route(
    graph: nx.Graph,
    states: dict[int, NodeState],
    config: SimulationConfig,
    source_id: int = GROUND_NODE_ID,
    ground_id: int = GROUND_NODE_ID,
) -> Route:
    """Find the cheapest health-aware route source -> compute node -> ground.

    Pathfinding uses the ``weight`` edge attribute (distance × health penalty).
    A route is ``feasible`` only when the chosen compute node is eligible.
    """

    best = Route(feasible=False)
    best_cost = float("inf")

    for node_id, state in states.items():
        if state.role is not NodeRole.COMPUTE or not graph.has_node(node_id):
            continue
        if not state.is_compute_eligible():
            continue
        try:
            up_path = nx.shortest_path(graph, source_id, node_id, weight="weight")
            up_weight = nx.shortest_path_length(graph, source_id, node_id, weight="weight")
            down_path = nx.shortest_path(graph, node_id, ground_id, weight="weight")
            down_weight = nx.shortest_path_length(graph, node_id, ground_id, weight="weight")
        except nx.NetworkXNoPath:
            continue

        cost = up_weight + down_weight
        if cost >= best_cost:
            continue

        best_cost = cost
        full_path = up_path + down_path[1:]
        distance_km = _path_distance(graph, full_path)
        latency_s = _path_latency(graph, full_path)
        best = Route(
            feasible=True,
            path=full_path,
            compute_node_id=node_id,
            latency_s=latency_s,
            distance_km=distance_km,
            weight_cost=cost,
        )

    return best


def _path_distance(graph: nx.Graph, path: list[int]) -> float:
    """Sum the ``distance_km`` edge attribute along a node path."""

    if len(path) < 2:
        return 0.0
    return float(sum(graph[path[k]][path[k + 1]]["distance_km"] for k in range(len(path) - 1)))


def _path_latency(graph: nx.Graph, path: list[int]) -> float:
    """Sum the ``latency_s`` edge attribute along a node path."""

    if len(path) < 2:
        return 0.0
    return float(sum(graph[path[k]][path[k + 1]]["latency_s"] for k in range(len(path) - 1)))


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
    states = init_states(satellites, config.thermal)

    timeline = _timeline(timescale, config)
    dt_s = config.timestep_s

    telemetry_rows: list[dict] = []
    snapshots: list[dict] = []

    for step, t in enumerate(timeline):
        positions = propagate(satellites, t)
        positions_ecef = propagate_ecef(satellites, t)
        ground_position = ground_station_position(config.ground_station, t)
        ground_position_ecef = ground_station_position_ecef(config.ground_station, t)

        # Advance node state: compute nodes run work whenever they are eligible.
        for sat in satellites:
            state = states[sat.sat_id]
            sunlit = is_sunlit(positions[sat.sat_id], t)
            wants_compute = state.role is NodeRole.COMPUTE and state.is_compute_eligible()
            advance_state(
                state,
                is_sunlit_now=sunlit,
                is_computing=wants_compute,
                dt_s=dt_s,
                thermal=config.thermal,
            )

        graph = build_isl_graph(positions, satellites, ground_position, states, config)
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
                "route_weight": route.weight_cost if route.feasible else np.nan,
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
                # Globe rendering uses Earth-fixed coordinates so continents stay put.
                "ground_position_km": ground_position_ecef,
                "route_path": route.path,
                "nodes": {
                    sat.sat_id: {
                        "position_km": positions_ecef[sat.sat_id],
                        "role": states[sat.sat_id].role,
                        "battery_fraction": states[sat.sat_id].battery_fraction,
                        "temperature_c": states[sat.sat_id].temperature_c,
                        "temperature_k": states[sat.sat_id].temperature_k,
                        "in_eclipse": states[sat.sat_id].in_eclipse,
                        "is_sunlit": states[sat.sat_id].is_sunlit,
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
