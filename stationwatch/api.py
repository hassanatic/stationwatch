"""HTTP service: register stations, post observation batches, read health, scrape Prometheus metrics."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable

from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from .fleet import Fleet, Station


class StationIn(BaseModel):
    id: str
    lat: float
    lon: float


def create_app(clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> FastAPI:
    app = FastAPI(title="stationwatch")
    fleet = Fleet()
    app.state.fleet = fleet

    @app.post("/stations", status_code=201)
    def add_station(station: StationIn) -> dict:
        fleet.add_station(Station(station.id, station.lat, station.lon))
        return {"id": station.id}

    @app.post("/observations")
    def ingest(rows: list[dict]) -> dict:
        r = fleet.ingest(rows)
        return {"accepted": r.accepted, "duplicates": r.duplicates, "flagged": r.flagged, "rejected": r.rejected}

    @app.get("/stations/health")
    def health() -> list[dict]:
        return fleet.health(clock())

    @app.get("/metrics", response_class=PlainTextResponse)
    def metrics() -> str:
        lines = [
            "# HELP stationwatch_station_up 1 if the station reported within the staleness window.",
            "# TYPE stationwatch_station_up gauge",
        ]
        report = fleet.health(clock())
        for s in report:
            lines.append(f'stationwatch_station_up{{station="{s["station_id"]}"}} {0 if s["status"] == "down" else 1}')
        lines += [
            "# HELP stationwatch_last_report_age_seconds Seconds since the station's last observation.",
            "# TYPE stationwatch_last_report_age_seconds gauge",
        ]
        for s in report:
            if s["last_report_age_s"] is not None:
                lines.append(f'stationwatch_last_report_age_seconds{{station="{s["station_id"]}"}} {s["last_report_age_s"]}')
        lines += [
            "# HELP stationwatch_flags_24h Quality-control flags raised in the last 24 hours.",
            "# TYPE stationwatch_flags_24h gauge",
        ]
        for s in report:
            for check, count in sorted(s["flags_24h"].items()):
                lines.append(f'stationwatch_flags_24h{{station="{s["station_id"]}",check="{check}"}} {count}')
        return "\n".join(lines) + "\n"

    return app


app = create_app()
