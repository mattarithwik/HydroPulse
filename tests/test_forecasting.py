from datetime import UTC, datetime, timedelta

import pytest

from hydropulse.domain import BASINS, Freshness, Observation
from hydropulse.forecasting import (
    PersistenceForecaster,
    RidgeStageForecaster,
    StaleObservationError,
)


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
    assert forecast.threshold_crossings
    assert not hasattr(forecast, "risk")


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


def test_ridge_forecaster_serves_calibrated_stage_without_fake_discharge(tmp_path):
    model = tmp_path / "model.json"
    model.write_text(
        '{"model_type":"direct-ridge-stage-v1","target_id":"05464500",'
        '"selected_variant":"target_only","feature_means":[5,0],"feature_scales":[1,1],'
        '"intercept":[5,5,5,5,5],"weights":[[1,1,1,1,1],[0,0,0,0,0]],'
        '"residual_quantile_offsets":{"0.05":[-1,-1,-1,-1,-1],'
        '"0.1":[-0.8,-0.8,-0.8,-0.8,-0.8],"0.25":[-0.5,-0.5,-0.5,-0.5,-0.5],'
        '"0.5":[0,0,0,0,0],"0.75":[0.5,0.5,0.5,0.5,0.5],'
        '"0.9":[0.8,0.8,0.8,0.8,0.8],"0.95":[1,1,1,1,1]}}'
    )
    now = datetime(2026, 1, 1, 12, tzinfo=UTC)
    history = [observation(now - timedelta(hours=1), 4), observation(now, 5)]
    result = RidgeStageForecaster(model).predict(BASINS[0], history, now)
    assert result.stage_model_version.startswith("direct-ridge-stage-v1")
    assert result.discharge == ()
    assert result.stage[0].quantiles["0.5"] == 5
