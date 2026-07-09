"""OrbiCloud-Sim: orbital data-center constellation simulator and optimizer."""

from __future__ import annotations

from .config import (
    ConstellationConfig,
    EconomicConfig,
    GroundStationConfig,
    NodeRole,
    RoutingConfig,
    SatelliteHardwareConfig,
    SatelliteNode,
    SimulationConfig,
    ThermalConfig,
    WalkerDeltaConfig,
    default_compute_profile,
    default_relay_profile,
    default_simulation_config,
)
from .presets import PRESET_NAMES, load_preset

__version__ = "0.1.0"

__all__ = [
    "__version__",
    "ConstellationConfig",
    "EconomicConfig",
    "GroundStationConfig",
    "NodeRole",
    "PRESET_NAMES",
    "RoutingConfig",
    "SatelliteHardwareConfig",
    "SatelliteNode",
    "SimulationConfig",
    "ThermalConfig",
    "WalkerDeltaConfig",
    "default_compute_profile",
    "default_relay_profile",
    "default_simulation_config",
    "load_preset",
]
