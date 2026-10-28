"""In-memory store for a station network: ingest observations, flag them, report station health."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from . import qc

RECENT_WINDOW = 24          # values used as the reference for spike detection
PERSISTENCE_WINDOW = 12     # identical values in a row before a sensor counts as stuck
NEIGHBOUR_RADIUS_KM = 50.0
NEIGHBOUR_MAX_AGE = timedelta(minutes=30)
STALE_AFTER = timedelta(minutes=60)
FLAG_LOOKBACK = timedelta(hours=24)


@dataclass(frozen=True)
class Station:
    id: str
    lat: float
    lon: float


@dataclass
class Observation:
    station_id: str
    at: datetime
    variable: str
    value: float
    flags: list[qc.Flag] = field(default_factory=list)


@dataclass
class IngestResult:
    accepted: int = 0
    duplicates: int = 0
    flagged: list[dict] = field(default_factory=list)
    rejected: list[dict] = field(default_factory=list)


class Fleet:
    def __init__(self) -> None:
        self.stations: dict[str, Station] = {}
        self.series: dict[tuple[str, str], list[Observation]] = defaultdict(list)

    def add_station(self, station: Station) -> None:
        self.stations[station.id] = station

    def ingest(self, rows: list[dict]) -> IngestResult:
        """Validate each row on its own; one bad row never blocks the rest of the batch."""
        result = IngestResult()
        for i, row in enumerate(rows):
            try:
                obs = self._parse(row)
            except ValueError as exc:
                result.rejected.append({"row": i, "error": str(exc)})
                continue
            series = self.series[(obs.station_id, obs.variable)]
            if any(o.at == obs.at for o in series):
                result.duplicates += 1  # a resent batch must not double-count or double-flag
                continue
            obs.flags = self._flags(obs, series)
            series.append(obs)
            series.sort(key=lambda o: o.at)
            result.accepted += 1
            if obs.flags:
                result.flagged.append({"row": i, "station": obs.station_id, "variable": obs.variable,
                                       "flags": [f.check for f in obs.flags]})
        return result

    def _parse(self, row: dict) -> Observation:
        station_id = row.get("station_id")
        if station_id not in self.stations:
            raise ValueError(f"unknown station {station_id!r}")
        variable = row.get("variable")
        if variable not in qc.RANGES:
            raise ValueError(f"unknown variable {variable!r}")
        try:
            at = datetime.fromisoformat(str(row.get("at")))
        except ValueError:
            raise ValueError(f"bad timestamp {row.get('at')!r}") from None
        if at.tzinfo is None:
            raise ValueError("timestamp needs a timezone")
        value = row.get("value")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"value must be a number, got {value!r}")
        return Observation(station_id, at, variable, float(value))

    def _flags(self, obs: Observation, series: list[Observation]) -> list[qc.Flag]:
        earlier = [o for o in series if o.at < obs.at]
        flags = [qc.range_check(obs.variable, obs.value)]
        if earlier:
            prev = earlier[-1]
            hours = (obs.at - prev.at).total_seconds() / 3600
            flags.append(qc.step_check(obs.variable, prev.value, obs.value, hours))
            recent = [o.value for o in earlier[-RECENT_WINDOW:]]
            flags.append(qc.spike_check(obs.value, recent))
            run = [o.value for o in earlier[-(PERSISTENCE_WINDOW - 1):]] + [obs.value]
            flags.append(qc.persistence_check(run, PERSISTENCE_WINDOW))
        flags.append(qc.spatial_check(obs.value, self._neighbour_values(obs)))
        return [f for f in flags if f is not None]

    def _neighbour_values(self, obs: Observation) -> list[float]:
        here = self.stations[obs.station_id]
        values = []
        for other in self.stations.values():
            if other.id == here.id or qc.distance_km(here.lat, here.lon, other.lat, other.lon) > NEIGHBOUR_RADIUS_KM:
                continue
            near_in_time = [o for o in self.series.get((other.id, obs.variable), [])
                            if abs(o.at - obs.at) <= NEIGHBOUR_MAX_AGE and not o.flags]
            if near_in_time:
                values.append(min(near_in_time, key=lambda o: abs(o.at - obs.at)).value)
        return values

    def health(self, now: datetime) -> list[dict]:
        report = []
        for station in sorted(self.stations.values(), key=lambda s: s.id):
            all_obs = [o for (sid, _), s in self.series.items() if sid == station.id for o in s]
            last = max((o.at for o in all_obs), default=None)
            recent_flags: dict[str, int] = defaultdict(int)
            for o in all_obs:
                if now - o.at <= FLAG_LOOKBACK:
                    for f in o.flags:
                        recent_flags[f.check] += 1
            latest_flagged = [v for (sid, v), s in self.series.items() if sid == station.id and s and s[-1].flags]
            if last is None or now - last > STALE_AFTER:
                status = "down"
            elif latest_flagged:
                status = "degraded"
            else:
                status = "ok"
            report.append({
                "station_id": station.id,
                "status": status,
                "last_report": last.isoformat() if last else None,
                "last_report_age_s": int((now - last).total_seconds()) if last else None,
                "flags_24h": dict(recent_flags),
                "variables_flagged_now": sorted(latest_flagged),
            })
        return report
