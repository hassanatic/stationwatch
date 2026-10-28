"""Quality-control checks for observations from a network of measurement stations.

The checks are the usual first line of defence for station data: is the value physically possible,
did it jump too far since the last report, has the sensor stopped changing, is it a spike against
its own recent history, and does it agree with nearby stations. Each check answers one question and
returns a flag or None, so the caller can combine them however it likes.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import median

# Physically plausible limits per variable. Deliberately wide: a range check should only catch values
# that cannot be real (unit mix-ups, sentinel values like -9999), not unusual weather.
RANGES: dict[str, tuple[float, float]] = {
    "air_temperature_c": (-80.0, 60.0),
    "relative_humidity_pct": (0.0, 100.0),
    "air_pressure_hpa": (500.0, 1100.0),
    "wind_speed_ms": (0.0, 75.0),
}

# Largest believable change per hour between consecutive reports.
MAX_STEP_PER_HOUR: dict[str, float] = {
    "air_temperature_c": 10.0,
    "relative_humidity_pct": 50.0,
    "air_pressure_hpa": 6.0,
    "wind_speed_ms": 30.0,
}

# Robust-z threshold for spikes and for disagreement with neighbours. 1.4826 * MAD estimates the
# standard deviation for normal data, so 5 means "five robust standard deviations away".
ROBUST_Z_LIMIT = 5.0
MAD_TO_SIGMA = 1.4826


@dataclass(frozen=True)
class Flag:
    check: str
    detail: str


def range_check(variable: str, value: float) -> Flag | None:
    if variable not in RANGES:
        return Flag("unknown_variable", variable)
    lo, hi = RANGES[variable]
    if not lo <= value <= hi:
        return Flag("range", f"{value} outside {lo}..{hi}")
    return None


def step_check(variable: str, previous: float, current: float, hours: float) -> Flag | None:
    if hours <= 0 or variable not in MAX_STEP_PER_HOUR:
        return None
    # Short gaps still allow at least a tenth of the hourly limit, so two reports a minute apart are
    # not held to a near-zero allowance.
    allowed = MAX_STEP_PER_HOUR[variable] * max(hours, 0.1)
    if abs(current - previous) > allowed:
        return Flag("step", f"changed {abs(current - previous):.2f} in {hours:.2f} h (allowed {allowed:.2f})")
    return None


def persistence_check(values: list[float], min_points: int = 12) -> Flag | None:
    """A sensor that reports exactly the same value for a long run has usually stopped measuring."""
    if len(values) < min_points:
        return None
    if max(values) - min(values) == 0:
        return Flag("persistence", f"{len(values)} identical values ({values[0]})")
    return None


def robust_z(value: float, reference: list[float]) -> float | None:
    if len(reference) < 5:
        return None
    centre = median(reference)
    mad = median(abs(v - centre) for v in reference)
    if mad == 0:
        return None
    return (value - centre) / (MAD_TO_SIGMA * mad)


def spike_check(value: float, recent: list[float]) -> Flag | None:
    z = robust_z(value, recent)
    if z is not None and abs(z) > ROBUST_Z_LIMIT:
        return Flag("spike", f"robust z {z:.1f} against the last {len(recent)} values")
    return None


def spatial_check(value: float, neighbour_values: list[float]) -> Flag | None:
    z = robust_z(value, neighbour_values)
    if z is not None and abs(z) > ROBUST_Z_LIMIT:
        return Flag("spatial", f"robust z {z:.1f} against {len(neighbour_values)} neighbours")
    return None


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))
