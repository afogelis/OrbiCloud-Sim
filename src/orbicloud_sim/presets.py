"""Named scenario presets for reproducible OrbiCloud-Sim runs."""

from __future__ import annotations

from copy import deepcopy

from .config import (
    ConstellationConfig,
    GroundStationConfig,
    SimulationConfig,
    WalkerDeltaConfig,
    default_compute_profile,
    default_relay_profile,
    default_simulation_config,
)

PRESET_NAMES: tuple[str, ...] = (
    "baseline_550",
    "small_demo",
    "dense_workload",
)


def _cape_canaveral() -> GroundStationConfig:
    return GroundStationConfig(
        name="Cape Canaveral",
        latitude_deg=28.39,
        longitude_deg=-80.60,
        elevation_m=3.0,
    )


def preset_baseline_550() -> SimulationConfig:
    """Default 550 km Walker 8×12 scenario used for README baseline numbers."""

    return default_simulation_config()


def preset_small_demo() -> SimulationConfig:
    """Fast smoke scenario: 4×10 constellation, 3-minute window."""

    config = default_simulation_config()
    config.constellation = ConstellationConfig(
        walker=WalkerDeltaConfig(
            num_planes=4,
            sats_per_plane=10,
            altitude_km=550.0,
            inclination_deg=53.0,
            phasing_f=1,
        ),
        compute_fraction=0.5,
        compute_profile=default_compute_profile(),
        relay_profile=default_relay_profile(),
    )
    config.ground_station = _cape_canaveral()
    config.duration_s = 180.0
    config.timestep_s = 60.0
    return config


def preset_dense_workload() -> SimulationConfig:
    """Baseline geometry with a heavier per-step AI workload."""

    config = deepcopy(default_simulation_config())
    config.workload_gflops = 5.0e7
    return config


def load_preset(name: str) -> SimulationConfig:
    """Return a fresh ``SimulationConfig`` for a named preset."""

    key = name.strip().lower()
    factories = {
        "baseline_550": preset_baseline_550,
        "small_demo": preset_small_demo,
        "dense_workload": preset_dense_workload,
    }
    if key not in factories:
        known = ", ".join(PRESET_NAMES)
        raise ValueError(f"Unknown preset {name!r}. Choose one of: {known}.")
    return factories[key]()
