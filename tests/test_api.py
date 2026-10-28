from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from stationwatch.api import create_app

T0 = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)


def client():
    return TestClient(create_app(clock=lambda: T0 + timedelta(minutes=30)))


def test_register_ingest_health_and_metrics():
    c = client()
    assert c.post("/stations", json={"id": "hki-1", "lat": 60.17, "lon": 24.94}).status_code == 201
    assert c.post("/stations", json={"id": "hki-2", "lat": 60.20, "lon": 24.90}).status_code == 201

    body = [
        {"station_id": "hki-1", "at": T0.isoformat(), "variable": "air_temperature_c", "value": 8.0},
        {"station_id": "hki-1", "at": (T0 + timedelta(minutes=20)).isoformat(), "variable": "air_temperature_c", "value": 30.0},
        {"station_id": "ghost", "at": T0.isoformat(), "variable": "air_temperature_c", "value": 8.0},
    ]
    r = c.post("/observations", json=body).json()
    assert r["accepted"] == 2
    assert r["rejected"] == [{"row": 2, "error": "unknown station 'ghost'"}]
    assert r["flagged"][0]["flags"] == ["step"]

    health = {s["station_id"]: s["status"] for s in c.get("/stations/health").json()}
    assert health == {"hki-1": "degraded", "hki-2": "down"}

    metrics = c.get("/metrics").text
    assert 'stationwatch_station_up{station="hki-1"} 1' in metrics
    assert 'stationwatch_station_up{station="hki-2"} 0' in metrics
    assert 'stationwatch_flags_24h{station="hki-1",check="step"} 1' in metrics
    assert 'stationwatch_last_report_age_seconds{station="hki-1"} 600' in metrics
