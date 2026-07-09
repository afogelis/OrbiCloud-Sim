"""Techno-economic TCO engine for OrbiCloud-Sim.

Converts routed-job telemetry into a CapEx / OpEx comparison: rideshare launch
plus hardware CapEx amortized over orbital lifetime, terrestrial grid energy and
cooling (PUE) OpEx avoided by space solar + passive radiative cooling, carbon
offset, and break-even investment horizon.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from .config import EconomicConfig, NodeRole, SimulationConfig
from .network_router import SimulationResult

SECONDS_PER_YEAR: float = 365.25 * 24.0 * 3600.0
SECONDS_PER_MONTH: float = SECONDS_PER_YEAR / 12.0
WH_PER_KWH: float = 1000.0
GFLOP_PER_TFLOP: float = 1000.0
KG_PER_TON: float = 1000.0


@dataclass
class EconomicsResult:
    """Output metrics of the techno-economic TCO comparison (RORO return object)."""

    jobs_completed: int
    total_gflops: float
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
    space_compute_cost_usd: float
    cost_per_gflop_usd: float
    net_value_usd: float
    roi_ratio: float
    break_even_months: float

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


def _capex_breakdown(result: SimulationResult) -> tuple[float, float, float]:
    """Return ``(hardware_usd, launch_usd, total_capex_usd)``."""

    econ = result.config.economics
    hardware = 0.0
    launch = 0.0
    for sat in result.satellites:
        hardware += sat.profile.hardware_cost_usd
        launch += sat.profile.mass_kg * econ.launch_cost_per_kg_usd
    return hardware, launch, hardware + launch


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

        it_energy_kwh = _terrestrial_it_energy_kwh(total_gflops, self.econ)
        facility_energy_kwh = _terrestrial_facility_energy_kwh(total_gflops, self.econ)
        cooling_energy_kwh = max(facility_energy_kwh - it_energy_kwh, 0.0)

        # OpEx savings: grid power for IT load + cooling premium (PUE overhead
        # avoided by passive radiative cooling in orbit).
        grid_cost_saved_usd = it_energy_kwh * self.econ.grid_cost_per_kwh_usd
        cooling_premium_usd = cooling_energy_kwh * self.econ.grid_cost_per_kwh_usd
        operational_energy_savings_usd = grid_cost_saved_usd + cooling_premium_usd

        carbon_offset_kg = facility_energy_kwh * self.econ.grid_carbon_kg_per_kwh
        carbon_value_usd = (carbon_offset_kg / KG_PER_TON) * self.econ.carbon_price_per_ton_usd
        terrestrial_rental_usd = _terrestrial_rental_usd(total_gflops, self.econ)

        hardware_capex_usd, launch_capex_usd, space_capex_usd = _capex_breakdown(result)
        lifetime_s = self.econ.satellite_lifetime_years * SECONDS_PER_YEAR
        cost_per_second = space_capex_usd / lifetime_s
        space_compute_cost_usd = cost_per_second * self.config.duration_s

        cost_per_gflop_usd = (
            space_compute_cost_usd / total_gflops if total_gflops > 0 else float("inf")
        )

        # Annualized OpEx savings rate extrapolated from this run's duty cycle.
        if self.config.duration_s > 0:
            annual_opex_savings = (
                (operational_energy_savings_usd + carbon_value_usd + terrestrial_rental_usd)
                * (SECONDS_PER_YEAR / self.config.duration_s)
            )
        else:
            annual_opex_savings = 0.0

        if annual_opex_savings > 0.0:
            break_even_years = space_capex_usd / annual_opex_savings
            break_even_months = break_even_years * 12.0
        else:
            break_even_months = float("inf")

        terrestrial_value_usd = (
            operational_energy_savings_usd + carbon_value_usd + terrestrial_rental_usd
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
            space_compute_cost_usd=space_compute_cost_usd,
            cost_per_gflop_usd=cost_per_gflop_usd,
            net_value_usd=net_value_usd,
            roi_ratio=roi_ratio,
            break_even_months=break_even_months,
        )

    def constellation_summary(self, result: SimulationResult) -> dict[str, int]:
        """Return counts of compute vs relay nodes for dashboard captions."""

        compute = sum(1 for s in result.satellites if s.role is NodeRole.COMPUTE)
        relay = sum(1 for s in result.satellites if s.role is NodeRole.RELAY)
        return {"compute_nodes": compute, "relay_nodes": relay, "total": compute + relay}
