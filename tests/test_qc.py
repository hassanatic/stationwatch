import pytest

from stationwatch import qc


def test_range_accepts_real_weather_and_rejects_sentinels():
    assert qc.range_check("air_temperature_c", -35.0) is None
    assert qc.range_check("air_temperature_c", -9999.0).check == "range"
    assert qc.range_check("relative_humidity_pct", 104.0).check == "range"
    assert qc.range_check("soil_moisture", 1.0).check == "unknown_variable"


def test_step_flags_an_impossible_jump_but_not_a_normal_change():
    assert qc.step_check("air_temperature_c", 5.0, 20.0, hours=1.0).check == "step"
    assert qc.step_check("air_temperature_c", 5.0, 9.0, hours=1.0) is None
    # a one-minute gap still gets a tenth of the hourly allowance, not almost nothing
    assert qc.step_check("air_temperature_c", 5.0, 5.5, hours=1 / 60) is None


def test_persistence_needs_a_full_window_of_identical_values():
    assert qc.persistence_check([12.3] * 12).check == "persistence"
    assert qc.persistence_check([12.3] * 11) is None
    assert qc.persistence_check([12.3] * 11 + [12.4]) is None


def test_spike_against_own_recent_history():
    recent = [20.0, 20.4, 19.8, 20.1, 20.3, 19.9, 20.2, 20.0]
    assert qc.spike_check(30.0, recent).check == "spike"
    assert qc.spike_check(20.6, recent) is None


def test_no_spike_verdict_when_reference_is_flat_or_short():
    assert qc.spike_check(30.0, [20.0] * 10) is None  # MAD of zero: no scale to judge against
    assert qc.spike_check(30.0, [20.0, 21.0]) is None


def test_spatial_disagreement_with_neighbours():
    neighbours = [10.0, 10.2, 9.9, 10.1, 10.0]
    assert qc.spatial_check(18.0, neighbours).check == "spatial"
    assert qc.spatial_check(10.3, neighbours) is None


def test_distance_helsinki_to_tampere():
    assert qc.distance_km(60.1699, 24.9384, 61.4978, 23.7610) == pytest.approx(160, abs=5)
