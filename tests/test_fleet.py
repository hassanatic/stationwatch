from datetime import datetime, timedelta, timezone

from stationwatch import Fleet, Station

T0 = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
TEMP = "air_temperature_c"

# six stations within ~20 km of central Helsinki, so each has five neighbours inside 50 km
STATIONS = [
    Station("hki-1", 60.170, 24.940), Station("hki-2", 60.200, 24.900), Station("hki-3", 60.250, 25.000),
    Station("esp-1", 60.205, 24.655), Station("van-1", 60.295, 25.040), Station("kau-1", 60.220, 25.180),
]


def fleet():
    f = Fleet()
    for s in STATIONS:
        f.add_station(s)
    return f


def row(station, minutes, value, variable=TEMP):
    return {"station_id": station, "at": (T0 + timedelta(minutes=minutes)).isoformat(), "variable": variable, "value": value}


def test_bad_rows_are_reported_by_index_and_good_rows_still_land():
    f = fleet()
    r = f.ingest([
        row("hki-1", 0, 10.0),
        {"station_id": "nowhere", "at": T0.isoformat(), "variable": TEMP, "value": 1.0},
        row("hki-1", 10, 10.0, variable="soil_moisture"),
        {"station_id": "hki-1", "at": "2026-10-01T12:20:00", "variable": TEMP, "value": 1.0},
        row("hki-1", 30, "warm"),
        row("hki-1", 40, True),
    ])
    assert r.accepted == 1
    assert [x["row"] for x in r.rejected] == [1, 2, 3, 4, 5]
    assert "timezone" in r.rejected[2]["error"]


def test_resending_a_batch_is_idempotent():
    f = fleet()
    batch = [row("hki-1", m, 10.0 + m / 100) for m in (0, 10, 20)]
    assert f.ingest(batch).accepted == 3
    again = f.ingest(batch)
    assert again.accepted == 0 and again.duplicates == 3
    assert len(f.series[("hki-1", TEMP)]) == 3


def test_step_flag_is_raised_at_ingest():
    f = fleet()
    r = f.ingest([row("hki-1", 0, 5.0), row("hki-1", 60, 21.0)])
    assert r.flagged == [{"row": 1, "station": "hki-1", "variable": TEMP, "flags": ["step"]}]


def test_stuck_sensor_is_flagged_once_the_window_fills():
    f = fleet()
    r = f.ingest([row("hki-2", 10 * i, 7.3) for i in range(12)])
    assert [x["row"] for x in r.flagged] == [11]
    assert r.flagged[0]["flags"] == ["persistence"]


def test_station_disagreeing_with_its_neighbours_is_flagged():
    f = fleet()
    others = ["hki-1", "hki-2", "hki-3", "esp-1", "van-1"]
    f.ingest([row(s, 0, v) for s, v in zip(others, [10.0, 10.2, 9.9, 10.1, 10.0])])
    r = f.ingest([row("kau-1", 5, 18.0)])
    assert r.flagged[0]["flags"] == ["spatial"]


def test_a_flagged_neighbour_is_not_used_as_a_reference():
    f = fleet()
    f.ingest([row(s, 0, v) for s, v in zip(["hki-1", "hki-2", "hki-3", "esp-1"], [10.0, 10.2, 9.9, 10.1])])
    f.ingest([row("van-1", 0, -9999.0)])  # range-flagged, must not count as a neighbour value
    r = f.ingest([row("kau-1", 5, 18.0)])
    # only four clean neighbours remain, too few for a spatial verdict
    assert r.flagged == []


def test_health_reports_ok_degraded_and_down():
    f = fleet()
    f.ingest([row("hki-1", 0, 10.0), row("hki-1", 50, 10.1)])
    f.ingest([row("hki-2", 0, 5.0), row("hki-2", 50, 25.0)])  # last value is step-flagged
    f.ingest([row("hki-3", -120, 9.0)])                       # silent for two hours
    now = T0 + timedelta(minutes=55)
    status = {s["station_id"]: s for s in f.health(now)}
    assert status["hki-1"]["status"] == "ok"
    assert status["hki-2"]["status"] == "degraded" and status["hki-2"]["variables_flagged_now"] == [TEMP]
    assert status["hki-3"]["status"] == "down"
    assert status["esp-1"]["status"] == "down" and status["esp-1"]["last_report"] is None
    assert status["hki-2"]["flags_24h"] == {"step": 1}
