"""Techno-economic TCO engine for OrbiCloud-Sim.

Converts routed-job telemetry into CapEx / OpEx comparisons under two lenses:

* **Fleet CapEx** — full constellation hardware + launch amortized over the
  simulated window / extrapolated OpEx (CapEx-dominated for short runs).
* **Utilized compute** — CapEx of compute nodes only, amortized over lifetime
  GFLOP if the run's observed utilization were sustained (marginal operating view).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from .config import EconomicConfig, NodeRole, SimulationConfig
from .network_router import SimulationResult

SECONDS_PER_YEAR: float = 365.25 * 24.0 * 3600.0
WH_PER_KWH: float = 1000.0
GFLOP_PER_TFLOP: float = 1000.0
KG_PER_TON: float = 1000.0


@dataclass
class EconomicsResult:
    """Output metrics of the techno-economic TCO comparison (RORO return object)."""

    jobs_completed: int
    total_gflops: float
    observed_utilization: float
    terrestrial_energy_kwh: float
    carbon_offset_kg: float
    grid_cost_saved_usd: float
    cooling_premium_usd: float
    operational_energy_savings_usd: float
    carbon_value_usd: float
    terrestrial_rental_usd: float
    space_capex_usd: float
    launch_capex_usd: float
    hardware_capex_usd: float
    compute_capex_usd: float
    space_compute_cost_usd: float
    # Fleet CapEx lens (full constellation).
    cost_per_gflop_usd: float
    break_even_months: float
    # Utilized-compute lens (compute-node CapEx @ observed utilization).
    utilized_cost_per_gflop_usd: float
    utilized_break_even_months: float
    net_value_usd: float
    roi_ratio: float

    def as_dict(self) -> dict:
        return asdict(self)


def _compute_seconds(gflops: float, econ: EconomicConfig) -> float:
    """Wall-clock seconds a reference terrestrial GPU needs for ``gflops`` of work."""

    return (gflops / GFLOP_PER_TFLOP) / econ.terrestrial_gpu_tflops


def _terrestrial_it_energy_kwh(gflops: float, econ: EconomicConfig) -> float:
    """IT-load energy (GPU boards only, no facility overhead) for ``gflops``."""

    seconds = _compute_seconds(gflops, econ)
    energy_wh = econ.terrestrial_gpu_power_w * seconds / 3600.0
    return energy_wh / WH_PER_KWH


def _terrestrial_facility_energy_kwh(gflops: float, econ: EconomicConfig) -> float:
    """Total facility energy including PUE overhead for ``gflops``."""

    return _terrestrial_it_energy_kwh(gflops, econ) * econ.datacenter_pue


def _terrestrial_rental_usd(gflops: float, econ: EconomicConfig) -> float:
    """Cloud GPU rental cost for the same work at the configured hourly rate."""

    hours = _compute_seconds(gflops, econ) / 3600.0
    return hours * econ.terrestrial_gpu_rental_usd_per_hour


def _capex_breakdown(result: SimulationResult) -> tuple[float, float, float, float]:
    """Return ``(hardware, launch, total, compute_only)`` CapEx in USD."""

    econ = result.config.economics
    hardware = 0.0
    launch = 0.0
    compute_only = 0.0
    for sat in result.satellites:
        sat_hw = sat.profile.hardware_cost_usd
        sat_launch = sat.profile.mass_kg * econ.launch_cost_per_kg_usd
        hardware += sat_hw
        launch += sat_launch
        if sat.role is NodeRole.COMPUTE:
            compute_only += sat_hw + sat_launch
    return hardware, launch, hardware + launch, compute_only


def _window_compute_capacity_gflops(result: SimulationResult) -> float:
    """Peak GFLOP the compute fleet could deliver over the simulated window."""

    dt_s = result.config.duration_s
    capacity = 0.0
    for sat in result.satellites:
        if sat.role is NodeRole.COMPUTE:
            capacity += sat.profile.compute_power_tflops * GFLOP_PER_TFLOP * dt_s
    return capacity


def _break_even_months(capex_usd: float, annual_opex_savings_usd: float) -> float:
    if annual_opex_savings_usd <= 0.0:
        return float("inf")
    return (capex_usd / annual_opex_savings_usd) * 12.0


class EconomicsModel:
    """Compute CapEx / OpEx TCO metrics from a completed simulation."""

    def __init__(self, config: SimulationConfig) -> None:
        self.config = config
        self.econ = config.economics

    def evaluate(self, result: SimulationResult) -> EconomicsResult:
        """Return the full set of economic metrics for ``result`` (RORO)."""

        telemetry = result.telemetry
        if len(telemetry):
            jobs_completed = int(telemetry["route_feasible"].sum())
            total_gflops = float(telemetry["delivered_gflops"].sum())
        else:
            jobs_completed = 0
            total_gflops = 0.0

        capacity_gflops = _window_compute_capacity_gflops(result)
        observed_utilization = (
            total_gflops / capacity_gflops if capacity_gflops > 0.0 else 0.0
        )
        # Optional override: evaluate "what if" utilization instead of observed.
        utilization = (
            self.econ.assumed_compute_utilization
            if self.econ.assumed_compute_utilization is not None
            else observed_utilization
        )

        it_energy_kwh = _terrestrial_it_energy_kwh(total_gflops, self.econ)
        facility_energy_kwh = _terrestrial_facility_energy_kwh(total_gflops, self.econ)
        cooling_energy_kwh = max(facility_energy_kwh - it_energy_kwh, 0.0)

        grid_cost_saved_usd = it_energy_kwh * self.econ.grid_cost_per_kwh_usd
        cooling_premium_usd = cooling_energy_kwh * self.econ.grid_cost_per_kwh_usd
        operational_energy_savings_usd = grid_cost_saved_usd + cooling_premium_usd

        carbon_offset_kg = facility_energy_kwh * self.econ.grid_carbon_kg_per_kwh
        carbon_value_usd = (carbon_offset_kg / KG_PER_TON) * self.econ.carbon_price_per_ton_usd
        terrestrial_rental_usd = _terrestrial_rental_usd(total_gflops, self.econ)

        hardware_capex_usd, launch_capex_usd, space_capex_usd, compute_capex_usd = (
            _capex_breakdown(result)
        )
        lifetime_s = self.econ.satellite_lifetime_years * SECONDS_PER_YEAR
        cost_per_second = space_capex_usd / lifetime_s
        space_compute_cost_usd = cost_per_second * self.config.duration_s

        # Fleet lens: full constellation CapEx charged to this window's GFLOP.
        cost_per_gflop_usd = (
            space_compute_cost_usd / total_gflops if total_gflops > 0 else float("inf")
        )

        terrestrial_value_usd = (
            operational_energy_savings_usd + carbon_value_usd + terrestrial_rental_usd
        )
        if self.config.duration_s > 0:
            annual_opex_savings = terrestrial_value_usd * (
                SECONDS_PER_YEAR / self.config.duration_s
            )
        else:
            annual_opex_savings = 0.0

        break_even_months = _break_even_months(space_capex_usd, annual_opex_savings)

        # Utilized-compute lens: only compute-node CapEx, amortized over lifetime
        # GFLOP if ``utilization`` of peak compute capacity is sustained.
        lifetime_capacity_gflops = 0.0
        for sat in result.satellites:
            if sat.role is NodeRole.COMPUTE:
                lifetime_capacity_gflops += (
                    sat.profile.compute_power_tflops * GFLOP_PER_TFLOP * lifetime_s
                )
        lifetime_utilized_gflops = lifetime_capacity_gflops * utilization
        utilized_cost_per_gflop_usd = (
            compute_capex_usd / lifetime_utilized_gflops
            if lifetime_utilized_gflops > 0
            else float("inf")
        )
        utilized_break_even_months = _break_even_months(
            compute_capex_usd, annual_opex_savings
        )

        net_value_usd = terrestrial_value_usd - space_compute_cost_usd
        roi_ratio = (
            terrestrial_value_usd / space_compute_cost_usd
            if space_compute_cost_usd > 0
            else float("inf")
        )

        return EconomicsResult(
            jobs_completed=jobs_completed,
            total_gflops=total_gflops,
            observed_utilization=observed_utilization,
            terrestrial_energy_kwh=facility_energy_kwh,
            carbon_offset_kg=carbon_offset_kg,
            grid_cost_saved_usd=grid_cost_saved_usd,
            cooling_premium_usd=cooling_premium_usd,
            operational_energy_savings_usd=operational_energy_savings_usd,
            carbon_value_usd=carbon_value_usd,
            terrestrial_rental_usd=terrestrial_rental_usd,
            space_capex_usd=space_capex_usd,
            launch_capex_usd=launch_capex_usd,
            hardware_capex_usd=hardware_capex_usd,
            compute_capex_usd=compute_capex_usd,
            space_compute_cost_usd=space_compute_cost_usd,
            cost_per_gflop_usd=cost_per_gflop_usd,
            break_even_months=break_even_months,
            utilized_cost_per_gflop_usd=utilized_cost_per_gflop_usd,
            utilized_break_even_months=utilized_break_even_months,
            net_value_usd=net_value_usd,
            roi_ratio=roi_ratio,
        )

    def constellation_summary(self, result: SimulationResult) -> dict[str, int]:
        """Return counts of compute vs relay nodes for dashboard captions."""

        compute = sum(1 for s in result.satellites if s.role is NodeRole.COMPUTE)
        relay = sum(1 for s in result.satellites if s.role is NodeRole.RELAY)
        return {"compute_nodes": compute, "relay_nodes": relay, "total": compute + relay}
