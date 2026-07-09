"""Techno-economic engine for OrbiCloud-Sim.

Converts the routed-job telemetry produced by ``run_simulation`` into a
Space-vs-Terrestrial comparison: terrestrial grid energy and carbon avoided by
computing in orbit, the amortized cost of the orbital compute time, and the
resulting cost per GigaFLOP and return on investment.
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
    """Output metrics of the techno-economic comparison (RORO return object)."""

    jobs_completed: int
    total_gflops: float
    terrestrial_energy_kwh: float
    carbon_offset_kg: float
    grid_cost_saved_usd: float
    carbon_value_usd: float
    terrestrial_rental_usd: float
    space_capex_usd: float
    space_compute_cost_usd: float
    cost_per_gflop_usd: float
    net_value_usd: float
    roi_ratio: float

    def as_dict(self) -> dict:
        return asdict(self)


def _compute_seconds(gflops: float, econ: EconomicConfig) -> float:
    """Wall-clock seconds a reference terrestrial GPU needs for ``gflops`` of work."""

    return (gflops / GFLOP_PER_TFLOP) / econ.terrestrial_gpu_tflops


def _terrestrial_energy_kwh(gflops: float, econ: EconomicConfig) -> float:
    """Energy a terrestrial datacenter would burn to execute ``gflops`` of work."""

    seconds = _compute_seconds(gflops, econ)
    energy_wh = econ.terrestrial_gpu_power_w * seconds * econ.datacenter_pue / 3600.0
    return energy_wh / WH_PER_KWH


def _terrestrial_rental_usd(gflops: float, econ: EconomicConfig) -> float:
    """Cloud GPU rental cost for the same work at the configured hourly rate."""

    hours = _compute_seconds(gflops, econ) / 3600.0
    return hours * econ.terrestrial_gpu_rental_usd_per_hour


def _space_capex_usd(result: SimulationResult) -> float:
    """Total amortizable capex: per-satellite hardware plus launch."""

    econ = result.config.economics
    total = 0.0
    for sat in result.satellites:
        profile = sat.profile
        total += profile.hardware_cost_usd
        total += profile.mass_kg * econ.launch_cost_per_kg_usd
    return total


class EconomicsModel:
    """Compute Space-vs-Terrestrial economics from a completed simulation."""

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

        terrestrial_energy_kwh = _terrestrial_energy_kwh(total_gflops, self.econ)
        carbon_offset_kg = terrestrial_energy_kwh * self.econ.grid_carbon_kg_per_kwh
        grid_cost_saved_usd = terrestrial_energy_kwh * self.econ.grid_cost_per_kwh_usd
        carbon_value_usd = (carbon_offset_kg / KG_PER_TON) * self.econ.carbon_price_per_ton_usd
        terrestrial_rental_usd = _terrestrial_rental_usd(total_gflops, self.econ)

        space_capex_usd = _space_capex_usd(result)
        lifetime_s = self.econ.satellite_lifetime_years * SECONDS_PER_YEAR
        cost_per_second = space_capex_usd / lifetime_s
        space_compute_cost_usd = cost_per_second * self.config.duration_s

        cost_per_gflop_usd = (
            space_compute_cost_usd / total_gflops if total_gflops > 0 else float("inf")
        )
        # Value of orbital compute time is benchmarked against avoided grid energy,
        # carbon pricing, and the equivalent terrestrial GPU rental bill.
        terrestrial_value_usd = grid_cost_saved_usd + carbon_value_usd + terrestrial_rental_usd
        net_value_usd = terrestrial_value_usd - space_compute_cost_usd
        roi_ratio = (
            terrestrial_value_usd / space_compute_cost_usd
            if space_compute_cost_usd > 0
            else float("inf")
        )

        return EconomicsResult(
            jobs_completed=jobs_completed,
            total_gflops=total_gflops,
            terrestrial_energy_kwh=terrestrial_energy_kwh,
            carbon_offset_kg=carbon_offset_kg,
            grid_cost_saved_usd=grid_cost_saved_usd,
            carbon_value_usd=carbon_value_usd,
            terrestrial_rental_usd=terrestrial_rental_usd,
            space_capex_usd=space_capex_usd,
            space_compute_cost_usd=space_compute_cost_usd,
            cost_per_gflop_usd=cost_per_gflop_usd,
            net_value_usd=net_value_usd,
            roi_ratio=roi_ratio,
        )

    def constellation_summary(self, result: SimulationResult) -> dict[str, int]:
        """Return counts of compute vs relay nodes for dashboard captions."""

        compute = sum(1 for s in result.satellites if s.role is NodeRole.COMPUTE)
        relay = sum(1 for s in result.satellites if s.role is NodeRole.RELAY)
        return {"compute_nodes": compute, "relay_nodes": relay, "total": compute + relay}
