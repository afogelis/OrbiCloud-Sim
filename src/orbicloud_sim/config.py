"""Pydantic configuration models for OrbiCloud-Sim.

All tunable physical, hardware, network and economic parameters live here so that
the simulation core never relies on hardcoded magic numbers. Every model is a
``pydantic.BaseModel`` and is validated on construction.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field, model_validator


class NodeRole(str, Enum):
    """Functional role of a satellite in the constellation."""

    COMPUTE = "compute"
    RELAY = "relay"


class SatelliteHardwareConfig(BaseModel):
    """Hardware profile for a single class of satellite node.

    Power figures are instantaneous draws in watts; energy storage is in
    watt-hours. Thermal state is modeled with a first-order lumped-capacitance
    model, so a heat capacity and radiator sink power are required.
    """

    role: NodeRole = Field(description="Functional role of this node class.")
    mass_kg: float = Field(gt=0, description="Wet mass of the satellite, used for launch-cost amortization.")

    # Compute.
    compute_power_tflops: float = Field(
        ge=0, description="Peak sustained FP throughput in TFLOP/s (0 for pure relays)."
    )

    # Power / battery.
    battery_capacity_wh: float = Field(gt=0, description="Usable battery energy storage in watt-hours.")
    idle_draw_w: float = Field(gt=0, description="Baseline bus + avionics power draw in watts.")
    compute_draw_w: float = Field(
        ge=0, description="Additional power draw while executing a compute workload, in watts."
    )
    solar_charge_w: float = Field(
        ge=0, description="Net solar-array charging power while in sunlight, in watts."
    )
    min_battery_fraction: float = Field(
        ge=0, le=1, description="State-of-charge floor below which the node refuses compute jobs."
    )

    # Thermal (first-order lumped model).
    heat_capacity_j_per_k: float = Field(
        gt=0, description="Lumped thermal capacitance of the node in joules per kelvin."
    )
    thermal_threshold_c: float = Field(
        description="Maximum die/radiator temperature in Celsius before compute is throttled."
    )
    radiative_cooling_w: float = Field(
        gt=0, description="Passive radiator heat-rejection power in watts (peak, in eclipse)."
    )
    solar_heat_load_w: float = Field(
        ge=0, description="External solar heat absorbed by the structure while in sunlight, in watts."
    )
    compute_heat_fraction: float = Field(
        default=0.95,
        ge=0,
        le=1,
        description="Fraction of compute_draw_w that is dissipated as heat into the node.",
    )

    # Networking.
    isl_bandwidth_gbps: float = Field(gt=0, description="Optical inter-satellite link capacity in Gbit/s.")
    max_isl_range_km: float = Field(
        gt=0, description="Maximum line-of-sight optical link range in kilometers."
    )

    # Economics.
    hardware_cost_usd: float = Field(
        gt=0, description="Bill-of-materials + integration cost of the satellite, in USD."
    )

    @model_validator(mode="after")
    def _check_compute_consistency(self) -> SatelliteHardwareConfig:
        if self.role is NodeRole.COMPUTE and self.compute_power_tflops <= 0:
            raise ValueError("A COMPUTE node must define a positive compute_power_tflops.")
        return self


class WalkerDeltaConfig(BaseModel):
    """Walker-Delta pattern parameters (notation i: t/p/f)."""

    num_planes: int = Field(gt=0, description="Number of orbital planes (p).")
    sats_per_plane: int = Field(gt=0, description="Number of satellites per plane (t/p).")
    altitude_km: float = Field(gt=0, description="Circular orbit altitude above mean sea level, in km.")
    inclination_deg: float = Field(ge=0, le=180, description="Orbital inclination in degrees (i).")
    phasing_f: int = Field(
        default=1, ge=0, description="Inter-plane phasing factor (f), 0 <= f < num_planes."
    )

    @property
    def total_satellites(self) -> int:
        return self.num_planes * self.sats_per_plane

    @model_validator(mode="after")
    def _check_phasing(self) -> WalkerDeltaConfig:
        if self.phasing_f >= self.num_planes:
            raise ValueError("phasing_f must satisfy 0 <= phasing_f < num_planes.")
        return self


class ConstellationConfig(BaseModel):
    """Full constellation definition: geometry plus a compute/relay split."""

    walker: WalkerDeltaConfig
    compute_fraction: float = Field(
        ge=0, le=1, description="Fraction of satellites configured as COMPUTE nodes."
    )
    compute_profile: SatelliteHardwareConfig
    relay_profile: SatelliteHardwareConfig

    @model_validator(mode="after")
    def _check_profiles(self) -> ConstellationConfig:
        if self.compute_profile.role is not NodeRole.COMPUTE:
            raise ValueError("compute_profile must have role COMPUTE.")
        if self.relay_profile.role is not NodeRole.RELAY:
            raise ValueError("relay_profile must have role RELAY.")
        return self

    @property
    def num_compute_nodes(self) -> int:
        return round(self.walker.total_satellites * self.compute_fraction)


class GroundStationConfig(BaseModel):
    """A single Earth ground station / workload origin."""

    name: str = Field(default="GS-1")
    latitude_deg: float = Field(ge=-90, le=90)
    longitude_deg: float = Field(ge=-180, le=180)
    elevation_m: float = Field(default=0.0)


class RoutingConfig(BaseModel):
    """Parameters that shape the inter-satellite link graph and pathfinding."""

    atmosphere_margin_km: float = Field(
        default=80.0,
        ge=0,
        description="Earth-occlusion margin: links whose chord passes below R_earth + this are blocked.",
    )
    max_ground_link_km: float = Field(
        gt=0, default=2500.0, description="Maximum ground-station to satellite optical/RF link range."
    )
    infeasible_penalty_s: float = Field(
        gt=0,
        default=1.0e6,
        description="Latency penalty (s) added when routing to an ineligible compute node.",
    )


class EconomicConfig(BaseModel):
    """Techno-economic constants for the Space-vs-Terrestrial comparison."""

    grid_cost_per_kwh_usd: float = Field(gt=0, default=0.12, description="Terrestrial grid price, USD/kWh.")
    grid_carbon_kg_per_kwh: float = Field(
        gt=0, default=0.40, description="Grid carbon intensity, kg CO2-equivalent per kWh."
    )
    terrestrial_gpu_tflops: float = Field(
        gt=0, default=67.0, description="Reference terrestrial GPU sustained FP throughput, TFLOP/s."
    )
    terrestrial_gpu_power_w: float = Field(
        gt=0, default=700.0, description="Reference terrestrial GPU board power, watts."
    )
    datacenter_pue: float = Field(
        ge=1.0, default=1.5, description="Power Usage Effectiveness of the terrestrial datacenter."
    )
    launch_cost_per_kg_usd: float = Field(
        gt=0, default=2700.0, description="Amortized launch cost to LEO, USD/kg."
    )
    satellite_lifetime_years: float = Field(
        gt=0, default=5.0, description="Operational lifetime over which capex is amortized."
    )
    carbon_price_per_ton_usd: float = Field(
        ge=0, default=85.0, description="Carbon price applied to offset CO2, USD per metric ton."
    )


class SimulationConfig(BaseModel):
    """Top-level run configuration tying the scenario together."""

    epoch: datetime = Field(
        default_factory=lambda: datetime(2026, 1, 1, tzinfo=timezone.utc),
        description="UTC start time of the simulation.",
    )
    timestep_s: float = Field(gt=0, default=60.0, description="Integration / sampling timestep, seconds.")
    duration_s: float = Field(gt=0, default=6000.0, description="Total simulated wall-clock time, seconds.")

    constellation: ConstellationConfig
    ground_station: GroundStationConfig
    routing: RoutingConfig = Field(default_factory=RoutingConfig)
    economics: EconomicConfig = Field(default_factory=EconomicConfig)

    workload_gflops: float = Field(
        gt=0,
        default=5.0e4,
        description="Size of a single AI compute job offered each timestep, in GFLOP.",
    )

    @property
    def num_steps(self) -> int:
        return max(1, int(self.duration_s // self.timestep_s))


def default_compute_profile() -> SatelliteHardwareConfig:
    """A reference H100-class orbital compute node."""

    return SatelliteHardwareConfig(
        role=NodeRole.COMPUTE,
        mass_kg=1200.0,
        compute_power_tflops=67.0,
        battery_capacity_wh=12000.0,
        idle_draw_w=400.0,
        compute_draw_w=1400.0,
        solar_charge_w=2500.0,
        min_battery_fraction=0.25,
        heat_capacity_j_per_k=45000.0,
        thermal_threshold_c=75.0,
        radiative_cooling_w=2200.0,
        solar_heat_load_w=900.0,
        compute_heat_fraction=0.95,
        isl_bandwidth_gbps=100.0,
        max_isl_range_km=5000.0,
        hardware_cost_usd=4.5e6,
    )


def default_relay_profile() -> SatelliteHardwareConfig:
    """A reference optical relay node (Starlink/Kepler-class)."""

    return SatelliteHardwareConfig(
        role=NodeRole.RELAY,
        mass_kg=300.0,
        compute_power_tflops=0.0,
        battery_capacity_wh=4000.0,
        idle_draw_w=180.0,
        compute_draw_w=0.0,
        solar_charge_w=1500.0,
        min_battery_fraction=0.15,
        heat_capacity_j_per_k=18000.0,
        thermal_threshold_c=85.0,
        radiative_cooling_w=900.0,
        solar_heat_load_w=400.0,
        compute_heat_fraction=0.9,
        isl_bandwidth_gbps=200.0,
        max_isl_range_km=5500.0,
        hardware_cost_usd=8.0e5,
    )


def default_simulation_config() -> SimulationConfig:
    """A small, sane default scenario used by tests and the dashboard."""

    constellation = ConstellationConfig(
        walker=WalkerDeltaConfig(
            num_planes=6,
            sats_per_plane=6,
            altitude_km=550.0,
            inclination_deg=53.0,
            phasing_f=1,
        ),
        compute_fraction=0.5,
        compute_profile=default_compute_profile(),
        relay_profile=default_relay_profile(),
    )
    ground_station = GroundStationConfig(
        name="Svalbard", latitude_deg=78.23, longitude_deg=15.39, elevation_m=450.0
    )
    return SimulationConfig(constellation=constellation, ground_station=ground_station)
