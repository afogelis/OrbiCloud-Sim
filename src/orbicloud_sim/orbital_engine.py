"""Orbital mechanics layer for OrbiCloud-Sim.

This module wraps Skyfield's SGP4 propagator. Walker-Delta constellations are
synthesized as Two-Line Element (TLE) sets directly from orbital elements, so no
external TLE catalog download is required. Eclipse detection uses a cylindrical
Earth-shadow model with a low-precision analytic solar vector, which avoids
needing a JPL planetary ephemeris file.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from skyfield.api import EarthSatellite, load, wgs84
from skyfield.timelib import Time, Timescale

from .config import ConstellationConfig, GroundStationConfig, NodeRole, SatelliteHardwareConfig

# Physical constants (named to avoid magic numbers in the logic below).
EARTH_RADIUS_KM: float = 6378.137  # WGS-84 equatorial radius
EARTH_MU_KM3_S2: float = 398600.4418  # Standard gravitational parameter
SECONDS_PER_DAY: float = 86400.0
OBLIQUITY_DEG: float = 23.439291  # Mean obliquity of the ecliptic (J2000)
J2000_JD: float = 2451545.0
JULIAN_CENTURY_DAYS: float = 36525.0


@dataclass(frozen=True)
class Satellite:
    """A constellation member: identity, role, hardware profile and propagator."""

    sat_id: int
    name: str
    role: NodeRole
    profile: SatelliteHardwareConfig
    body: EarthSatellite
    plane: int
    slot: int


def mean_motion_rev_per_day(altitude_km: float) -> float:
    """Return the circular-orbit mean motion in revolutions per day."""

    if altitude_km <= 0:
        raise ValueError("altitude_km must be positive.")
    semi_major_axis_km = EARTH_RADIUS_KM + altitude_km
    n_rad_per_s = math.sqrt(EARTH_MU_KM3_S2 / semi_major_axis_km**3)
    return n_rad_per_s * SECONDS_PER_DAY / (2.0 * math.pi)


def _tle_checksum(line: str) -> int:
    """Standard TLE modulo-10 checksum over the first 68 columns."""

    total = 0
    for char in line[:68]:
        if char.isdigit():
            total += int(char)
        elif char == "-":
            total += 1
    return total % 10


def _epoch_to_tle_fields(year: int, day_of_year_frac: float) -> tuple[int, float]:
    """Return (two-digit year, day-of-year with fraction) for a TLE epoch."""

    return year % 100, day_of_year_frac


def build_tle(
    catalog_number: int,
    epoch_year: int,
    epoch_day: float,
    inclination_deg: float,
    raan_deg: float,
    mean_anomaly_deg: float,
    mean_motion_rev_day: float,
    eccentricity: float = 0.0,
    arg_perigee_deg: float = 0.0,
    element_set: int = 999,
    rev_number: int = 0,
) -> tuple[str, str]:
    """Construct a valid SGP4-parseable TLE line pair from orbital elements.

    Column widths follow the NORAD TLE specification exactly so Skyfield's SGP4
    front-end accepts the synthesized elements.
    """

    yy, day = _epoch_to_tle_fields(epoch_year, epoch_day)
    intl_designator = f"{yy:02d}001A".ljust(8)

    # Each segment below is annotated with the 1-indexed NORAD TLE columns it
    # fills; the assembled string must be exactly 68 chars before the checksum.
    line1 = (
        "1 "                       # cols 1-2
        f"{catalog_number:05d}"    # cols 3-7  catalog number
        "U "                       # cols 8-9  classification + space
        f"{intl_designator}"       # cols 10-17 international designator
        " "                        # col 18
        f"{yy:02d}"                # cols 19-20 epoch year
        f"{day:012.8f}"            # cols 21-32 epoch day-of-year + fraction
        " "                        # col 33
        " .00000000"               # cols 34-43 first derivative of mean motion
        " "                        # col 44
        " 00000-0"                 # cols 45-52 second derivative (assumed decimal)
        " "                        # col 53
        " 00000-0"                 # cols 54-61 BSTAR drag term
        " "                        # col 62
        "0"                        # col 63 ephemeris type
        " "                        # col 64
        f"{element_set:4d}"        # cols 65-68 element set number
    )
    line1 = f"{line1}{_tle_checksum(line1)}"

    ecc_field = f"{int(round(eccentricity * 1e7)):07d}"
    line2 = (
        "2 "
        f"{catalog_number:05d} "
        f"{inclination_deg:8.4f} "
        f"{raan_deg:8.4f} "
        f"{ecc_field} "
        f"{arg_perigee_deg:8.4f} "
        f"{mean_anomaly_deg:8.4f} "
        f"{mean_motion_rev_day:11.8f}"
        f"{rev_number:5d}"
    )
    line2 = f"{line2}{_tle_checksum(line2)}"

    return line1, line2


def _assign_roles(total: int, num_compute: int) -> list[NodeRole]:
    """Spread compute nodes as evenly as possible across the index range."""

    roles = [NodeRole.RELAY] * total
    if num_compute <= 0:
        return roles
    if num_compute >= total:
        return [NodeRole.COMPUTE] * total
    step = total / num_compute
    for k in range(num_compute):
        roles[int(k * step)] = NodeRole.COMPUTE
    return roles


def generate_walker_delta(
    config: ConstellationConfig,
    timescale: Timescale,
    epoch: Time,
) -> list[Satellite]:
    """Generate a Walker-Delta constellation as Skyfield ``EarthSatellite`` objects.

    The pattern follows the i: t/p/f notation: ``num_planes`` equally spaced
    RAAN values, ``sats_per_plane`` satellites per plane spaced in mean anomaly,
    and an inter-plane phase offset of ``phasing_f * 360 / total`` degrees.
    """

    walker = config.walker
    total = walker.total_satellites
    sats_per_plane = walker.sats_per_plane
    num_planes = walker.num_planes

    epoch_dt = epoch.utc_datetime()
    epoch_year = epoch_dt.year
    day_of_year = (
        epoch_dt.timetuple().tm_yday
        + epoch_dt.hour / 24.0
        + epoch_dt.minute / 1440.0
        + (epoch_dt.second + epoch_dt.microsecond / 1e6) / 86400.0
    )

    n_rev_day = mean_motion_rev_per_day(walker.altitude_km)
    roles = _assign_roles(total, config.num_compute_nodes)

    satellites: list[Satellite] = []
    sat_id = 0
    for plane in range(num_planes):
        raan = (360.0 / num_planes) * plane
        for slot in range(sats_per_plane):
            mean_anomaly = (
                (360.0 / sats_per_plane) * slot
                + (360.0 / total) * walker.phasing_f * plane
            ) % 360.0
            line1, line2 = build_tle(
                catalog_number=10000 + sat_id,
                epoch_year=epoch_year,
                epoch_day=day_of_year,
                inclination_deg=walker.inclination_deg,
                raan_deg=raan,
                mean_anomaly_deg=mean_anomaly,
                mean_motion_rev_day=n_rev_day,
            )
            role = roles[sat_id]
            profile = config.compute_profile if role is NodeRole.COMPUTE else config.relay_profile
            name = f"{role.value.upper()}-{plane:02d}-{slot:02d}"
            body = EarthSatellite(line1, line2, name, timescale)
            satellites.append(
                Satellite(
                    sat_id=sat_id,
                    name=name,
                    role=role,
                    profile=profile,
                    body=body,
                    plane=plane,
                    slot=slot,
                )
            )
            sat_id += 1

    return satellites


def propagate(satellites: list[Satellite], t: Time) -> dict[int, np.ndarray]:
    """Return a mapping of satellite id to geocentric ECI position (km) at time t."""

    positions: dict[int, np.ndarray] = {}
    for sat in satellites:
        positions[sat.sat_id] = np.asarray(sat.body.at(t).position.km, dtype=float)
    return positions


def ground_station_position(
    station: GroundStationConfig,
    t: Time,
) -> np.ndarray:
    """Return the geocentric ECI position (km) of a ground station at time t."""

    location = wgs84.latlon(
        station.latitude_deg, station.longitude_deg, elevation_m=station.elevation_m
    )
    return np.asarray(location.at(t).position.km, dtype=float)


def sun_unit_vector_eci(t: Time) -> np.ndarray:
    """Low-precision geocentric unit vector toward the Sun in the ECI frame.

    Uses the Astronomical Almanac low-precision solar-position formulas. Accuracy
    is ~0.01 deg, far better than required for cylindrical eclipse geometry, and
    needs no ephemeris download.
    """

    jd_tt = float(t.tt)
    centuries = (jd_tt - J2000_JD) / JULIAN_CENTURY_DAYS

    mean_longitude = math.radians((280.460 + 36000.771 * centuries) % 360.0)
    mean_anomaly = math.radians((357.5277 + 35999.0503 * centuries) % 360.0)

    ecliptic_longitude = mean_longitude + math.radians(
        1.914666 * math.sin(mean_anomaly) + 0.019994 * math.sin(2.0 * mean_anomaly)
    )
    obliquity = math.radians(OBLIQUITY_DEG)

    x = math.cos(ecliptic_longitude)
    y = math.cos(obliquity) * math.sin(ecliptic_longitude)
    z = math.sin(obliquity) * math.sin(ecliptic_longitude)
    vector = np.array([x, y, z], dtype=float)
    return vector / np.linalg.norm(vector)


def is_in_eclipse(position_km: np.ndarray, t: Time) -> bool:
    """Cylindrical-shadow eclipse test for a geocentric ECI position.

    A point is in Earth's umbra when it lies on the anti-solar side of the
    Earth-center plane and its perpendicular distance from the Earth-Sun line is
    smaller than Earth's radius.
    """

    sun_hat = sun_unit_vector_eci(t)
    along_track = float(np.dot(position_km, sun_hat))
    if along_track >= 0.0:
        return False  # Day side: facing the Sun, cannot be in shadow.
    perpendicular = position_km - along_track * sun_hat
    return float(np.linalg.norm(perpendicular)) < EARTH_RADIUS_KM


def build_timescale() -> Timescale:
    """Return a Skyfield timescale using built-in data (no network access)."""

    return load.timescale(builtin=True)
