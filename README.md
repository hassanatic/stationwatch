# stationwatch

Quality control and health monitoring for a network of environmental measurement stations
(temperature, humidity, pressure, wind). Stations post batches of observations; every observation is
checked as it arrives, and the service reports which stations are healthy, which are sending
suspect data, and which have gone quiet, as JSON and as Prometheus metrics.

## Checks

| check | question it answers |
|---|---|
| range | is the value physically possible? (catches unit mix-ups and sentinels like -9999) |
| step | did it change more since the last report than the variable can in that time? |
| persistence | has the sensor reported the exact same value 12 times in a row? (usually a stuck sensor) |
| spike | is it more than 5 robust standard deviations (median/MAD) from its own last 24 values? |
| spatial | does it disagree with the clean, recent values of stations within 50 km, by the same robust test? |

Robust statistics are used on purpose: a mean and standard deviation are dragged around by the very
outliers you are trying to find, a median and MAD are not. A neighbour whose own latest value was
flagged is left out of the spatial reference, so one broken station cannot make its neighbours look
wrong. With fewer than five reference values a check says nothing rather than guess.

Station status: **down** if nothing arrived in the last 60 minutes, **degraded** if the latest value
of any variable is flagged, otherwise **ok**.

## API

```
POST /stations           {"id", "lat", "lon"}
POST /observations       [{"station_id", "at" (ISO 8601 with timezone), "variable", "value"}, ...]
GET  /stations/health    status, last report and age, flags in the last 24 h per station
GET  /metrics            stationwatch_station_up, stationwatch_last_report_age_seconds, stationwatch_flags_24h
```

Ingest validates every row on its own: an unknown station, unknown variable, timestamp without a
timezone or non-numeric value is reported by row index, and the rest of the batch still lands.
Resending a batch is safe: an observation already stored for the same station, variable and time is
counted as a duplicate and not checked or stored twice.

```bash
pip install -e ".[test]"
uvicorn stationwatch.api:app --reload
pytest -q
```

## Limits

A learning project with synthetic data and an in-memory store: no database, no authentication, and
the thresholds are reasonable defaults rather than values calibrated for a real network or taken from
a specific standard.
