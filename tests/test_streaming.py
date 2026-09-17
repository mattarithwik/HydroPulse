from datetime import UTC, datetime

import pytest

from hydropulse.domain import Observation
from hydropulse.streaming import decode_observation_event, observation_event


def observation() -> Observation:
    at = datetime(2026, 1, 1, tzinfo=UTC)
    return Observation(
        source="usgs", time_series_id="series", gauge_id="05464500", parameter_code="00065",
        event_time=at, value=4.2, unit="ft", first_seen_at=at, ingested_at=at,
        raw_payload_hash="abc",
    )


def test_kafka_event_round_trips_the_canonical_observation():
    event = observation_event(observation(), {"archive_hash": "raw"})
    restored, raw = decode_observation_event(__import__("json").dumps(event))
    assert restored == observation()
    assert raw == {"archive_hash": "raw"}


def test_kafka_event_rejects_unknown_contract():
    with pytest.raises(ValueError, match="unsupported"):
        decode_observation_event('{"schema_version":2}')
