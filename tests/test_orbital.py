"""Pytest cases for the OrbiCloud-Sim orbital engine and routing core."""

from __future__ import annotations

import math

import numpy as np
import pytest

from orbicloud_sim.config import (
    NodeRole,
    default_compute_profile,
    default_simulation_config,
)
from orbicloud_sim.orbital_engine import (
    EARTH_RADIUS_KM,
    build_timescale,
    build_tle,
    generate_walker_delta,
    is_in_eclipse,
    is_sunlit,
    mean_motion_rev_per_day,
    propagate,
    sun_unit_vector_eci,
)
from orbicloud_sim.economics import EconomicsModel
from orbicloud_sim.export import export_results
from orbicloud_sim.network_router import (
    GROUND_NODE_ID,
    NodeState,
    find_compute_route,
    init_states,
    line_of_sight,
    run_simulation,
)


@pytest.fixture(scope="module")
def timescale():
    return build_timescale()


def test_mean_motion_leo_is_about_15_rev_per_day():
    # A ~550 km LEO orbit completes roughly 15 revolutions per day.
    n = mean_motion_rev_per_day(550.0)
    assert 14.5 < n < 16.0


def test_mean_motion_rejects_nonpositive_altitude():
    with pytest.raises(ValueError):
        mean_motion_rev_per_day(0.0)


def test_build_tle_lines_have_valid_format_and_checksum():
    line1, line2 = build_tle(
        catalog_number=10000,
        epoch_year=2026,
        epoch_day=1.0,
        inclination_deg=53.0,
        raan_deg=120.0,
        mean_anomaly_deg=45.0,
        mean_motion_rev_day=15.2,
    )
    assert len(line1) == 69
    assert len(line2) == 69
    assert line1.startswith("1 ")
    assert line2.startswith("2 ")

    # Recompute and verify the modulo-10 checksum on each line.
    for line in (line1, line2):
        total = sum(int(c) for c in line[:68] if c.isdigit())
        total += sum(1 for c in line[:68] if c == "-")
        assert int(line[68]) == total % 10


def test_walker_delta_has_expected_count_and_roles(timescale):
    config = default_simulation_config()
    epoch = timescale.from_datetime(config.epoch)
    sats = generate_walker_delta(config.constellation, timescale, epoch)

    assert len(sats) == config.constellation.walker.total_satellites
    compute = [s for s in sats if s.role is NodeRole.COMPUTE]
    assert len(compute) == config.constellation.num_compute_nodes


def test_propagated_altitude_matches_configuration(timescale):
    config = default_simulation_config()
    epoch = timescale.from_datetime(config.epoch)
    sats = generate_walker_delta(config.constellation, timescale, epoch)
    positions = propagate(sats, epoch)

    expected_radius = EARTH_RADIUS_KM + config.constellation.walker.altitude_km
    for pos in positions.values():
        radius = float(np.linalg.norm(pos))
        # Circular orbit: geocentric radius should be within ~50 km of nominal.
        assert abs(radius - expected_radius) < 50.0


def test_sun_unit_vector_is_normalized(timescale):
    epoch = timescale.from_datetime(default_simulation_config().epoch)
    vec = sun_unit_vector_eci(epoch)
    assert math.isclose(float(np.linalg.norm(vec)), 1.0, rel_tol=1e-9)


def test_eclipse_true_directly_behind_earth(timescale):
    epoch = timescale.from_datetime(default_simulation_config().epoch)
    sun_hat = sun_unit_vector_eci(epoch)
    # A point one Earth-radius-plus-altitude on the anti-solar axis is in shadow.
    anti_sun_point = -sun_hat * (EARTH_RADIUS_KM + 550.0)
    assert is_in_eclipse(anti_sun_point, epoch) is True


def test_no_eclipse_on_the_sunlit_side(timescale):
    epoch = timescale.from_datetime(default_simulation_config().epoch)
    sun_hat = sun_unit_vector_eci(epoch)
    sunlit_point = sun_hat * (EARTH_RADIUS_KM + 550.0)
    assert is_in_eclipse(sunlit_point, epoch) is False


def test_no_eclipse_when_offset_beyond_earth_radius(timescale):
    epoch = timescale.from_datetime(default_simulation_config().epoch)
    sun_hat = sun_unit_vector_eci(epoch)
    # Anti-solar along-track but laterally offset well outside Earth's disk.
    lateral = np.cross(sun_hat, np.array([0.0, 0.0, 1.0]))
    lateral = lateral / np.linalg.norm(lateral)
    point = -sun_hat * (EARTH_RADIUS_KM + 550.0) + lateral * (EARTH_RADIUS_KM + 1000.0)
    assert is_in_eclipse(point, epoch) is False


def test_is_sunlit_matches_eclipse_complement(timescale):
    config = default_simulation_config()
    epoch = timescale.from_datetime(config.epoch)
    sats = generate_walker_delta(config.constellation, timescale, epoch)
    sat = sats[0]
    assert is_sunlit(sat, epoch) is (not is_in_eclipse(propagate(sats, epoch)[sat.sat_id], epoch))


def test_line_of_sight_blocked_through_earth():
    a = np.array([EARTH_RADIUS_KM + 500.0, 0.0, 0.0])
    b = np.array([-(EARTH_RADIUS_KM + 500.0), 0.0, 0.0])
    assert line_of_sight(a, b, EARTH_RADIUS_KM) is False


def test_line_of_sight_clear_for_adjacent_satellites():
    a = np.array([EARTH_RADIUS_KM + 500.0, 0.0, 0.0])
    b = np.array([EARTH_RADIUS_KM + 500.0, 200.0, 0.0])
    assert line_of_sight(a, b, EARTH_RADIUS_KM) is True


def test_routing_prefers_eligible_compute_node(timescale):
    config = default_simulation_config()
    epoch = timescale.from_datetime(config.epoch)
    sats = generate_walker_delta(config.constellation, timescale, epoch)
    states = init_states(sats)

    # Build a tiny hand-made graph: ground -> A (throttled) and ground -> B (ok).
    import networkx as nx

    compute_ids = [s.sat_id for s in sats if s.role is NodeRole.COMPUTE][:2]
    assert len(compute_ids) == 2
    a_id, b_id = compute_ids

    # Force A ineligible (overheated) and B eligible.
    states[a_id].temperature_c = states[a_id].profile.thermal_threshold_c + 50.0
    states[b_id].temperature_c = 10.0

    graph = nx.Graph()
    graph.add_node(GROUND_NODE_ID, role="ground")
    graph.add_node(a_id, role=NodeRole.COMPUTE)
    graph.add_node(b_id, role=NodeRole.COMPUTE)
    graph.add_edge(GROUND_NODE_ID, a_id, distance_km=300.0, latency_s=300.0 / 299792.458)
    graph.add_edge(GROUND_NODE_ID, b_id, distance_km=900.0, latency_s=900.0 / 299792.458)

    route = find_compute_route(graph, states, config)
    assert route.feasible is True
    assert route.compute_node_id == b_id


def test_routing_prefers_eclipse_over_sunlit_suboptimal(timescale):
    config = default_simulation_config()
    epoch = timescale.from_datetime(config.epoch)
    sats = generate_walker_delta(config.constellation, timescale, epoch)
    states = init_states(sats)

    import networkx as nx

    compute_ids = [s.sat_id for s in sats if s.role is NodeRole.COMPUTE][:2]
    a_id, b_id = compute_ids

    # Both eligible, but A is sunlit with low-ish SoC; B is in eclipse.
    states[a_id].in_eclipse = False
    states[a_id].battery_wh = states[a_id].profile.battery_capacity_wh * 0.50
    states[a_id].temperature_c = 20.0
    states[b_id].in_eclipse = True
    states[b_id].battery_wh = states[b_id].profile.battery_capacity_wh * 0.50
    states[b_id].temperature_c = 20.0

    graph = nx.Graph()
    graph.add_node(GROUND_NODE_ID, role="ground")
    graph.add_node(a_id, role=NodeRole.COMPUTE)
    graph.add_node(b_id, role=NodeRole.COMPUTE)
    # Make A slightly closer so without the soft penalty it would win.
    graph.add_edge(GROUND_NODE_ID, a_id, distance_km=300.0, latency_s=300.0 / 299792.458)
    graph.add_edge(GROUND_NODE_ID, b_id, distance_km=400.0, latency_s=400.0 / 299792.458)

    route = find_compute_route(graph, states, config)
    assert route.feasible is True
    assert route.compute_node_id == b_id


def test_node_state_eligibility_rules():
    profile = default_compute_profile()
    state = NodeState(
        sat_id=0,
        role=NodeRole.COMPUTE,
        profile=profile,
        battery_wh=profile.battery_capacity_wh,
        temperature_c=20.0,
    )
    assert state.is_compute_eligible() is True

    state.temperature_c = profile.thermal_threshold_c + 1.0
    assert state.is_compute_eligible() is False

    state.temperature_c = 20.0
    state.battery_wh = profile.battery_capacity_wh * (profile.min_battery_fraction / 2.0)
    assert state.is_compute_eligible() is False


def test_economics_reports_energy_and_rental_value():
    config = default_simulation_config()
    config.duration_s = 120.0
    config.timestep_s = 60.0
    config.constellation.walker.num_planes = 4
    config.constellation.walker.sats_per_plane = 10
    result = run_simulation(config)
    economics = EconomicsModel(config).evaluate(result)

    assert economics.jobs_completed >= 0
    assert economics.terrestrial_energy_kwh >= 0.0
    assert economics.terrestrial_rental_usd >= 0.0
    assert economics.space_capex_usd > 0.0
    assert "terrestrial_rental_usd" in economics.as_dict()


def test_short_simulation_produces_telemetry():
    config = default_simulation_config()
    config.duration_s = 180.0
    config.timestep_s = 60.0
    config.constellation.walker.num_planes = 4
    config.constellation.walker.sats_per_plane = 10
    result = run_simulation(config)
    assert len(result.telemetry) == 3
    assert len(result.snapshots) == 3
    assert {"delivered_gflops", "route_feasible", "mean_battery_fraction"}.issubset(
        result.telemetry.columns
    )


def test_export_writes_csvs_and_html_visualizations(tmp_path):
    config = default_simulation_config()
    config.duration_s = 120.0
    config.timestep_s = 60.0
    config.constellation.walker.num_planes = 4
    config.constellation.walker.sats_per_plane = 10
    result = run_simulation(config)
    economics = EconomicsModel(config).evaluate(result)
    written = export_results(result, economics, tmp_path)

    expected = {
        "scenario.csv",
        "satellites.csv",
        "telemetry.csv",
        "node_states.csv",
        "routes.csv",
        "economics_summary.csv",
        "economics_breakdown.csv",
        "dashboard.html",
        "globe.html",
        "telemetry.html",
        "economics.html",
    }
    assert set(written) == expected
    for path in written.values():
        assert path.exists()
        assert path.stat().st_size > 0
