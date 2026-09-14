from datetime import UTC, datetime, timedelta

import pytest

from hydropulse.domain import BASINS, Freshness, Observation
from hydropulse.forecasting import PersistenceForecaster, StaleObservationError


def observation(at, value=5.0):
    return Observation(
        source="test",
        time_series_id="series",
        gauge_id=BASINS[0].usgs_id,
        parameter_code="00065",
        event_time=at,
        value=value,
        unit="ft",
        first_seen_at=at,
        ingested_at=at,
        raw_payload_hash=str(at),
    )


def test_horizons_anchor_to_issuance_and_long_horizons_are_no_nwp():
    now = datetime(2026, 1, 1, 12, 30, tzinfo=UTC)
    forecast = PersistenceForecaster().predict(
        BASINS[0], [observation(now - timedelta(minutes=15))], now
    )
    assert [point.horizon_hours for point in forecast.stage] == [1, 6, 24, 48, 72]
    assert forecast.stage[0].valid_at == now + timedelta(hours=1)
    assert forecast.horizon_model_mapping[72] == "no-nwp"
    assert all(r.evidence_status.value == "insufficient_events" for r in forecast.risk)


@pytest.mark.parametrize(
    "minutes,status",
    [(90, Freshness.SUPPORTED), (91, Freshness.DEGRADED), (120, Freshness.DEGRADED)],
)
def test_age_boundaries(minutes, status):
    now = datetime(2026, 1, 1, tzinfo=UTC)
    assert (
        PersistenceForecaster()
        .predict(BASINS[0], [observation(now - timedelta(minutes=minutes))], now)
        .freshness
        is status
    )


def test_forecast_is_suppressed_after_120_minutes():
    now = datetime(2026, 1, 1, tzinfo=UTC)
    with pytest.raises(StaleObservationError):
        PersistenceForecaster().predict(BASINS[0], [observation(now - timedelta(minutes=121))], now)
