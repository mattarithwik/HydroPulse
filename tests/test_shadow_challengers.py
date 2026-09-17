from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from hydropulse.domain import BASINS, Observation
from hydropulse.shadow_challengers import complete_hourly_history


def observation(at: datetime, value: float) -> Observation:
    return Observation(
        source="test",
        time_series_id="test-stage",
        gauge_id=BASINS[0].usgs_id,
        parameter_code="00065",
        event_time=at,
        value=value,
        unit="ft",
        first_seen_at=at,
        ingested_at=at,
        raw_payload_hash=at.isoformat(),
    )


def test_complete_hourly_history_uses_only_elapsed_hours():
    issued = datetime(2026, 1, 2, 12, 30, tzinfo=UTC)
    start = datetime(2026, 1, 2, 8, tzinfo=UTC)
    observations = [observation(start + timedelta(hours=index), float(index)) for index in range(5)]
    end, history = complete_hourly_history(observations, issued, lookback=4)
    assert end == datetime(2026, 1, 2, 11, tzinfo=UTC)
    assert np.array_equal(history, np.asarray([0, 1, 2, 3], dtype=np.float32))


def test_complete_hourly_history_rejects_a_gap():
    issued = datetime(2026, 1, 2, 12, 30, tzinfo=UTC)
    start = datetime(2026, 1, 2, 8, tzinfo=UTC)
    observations = [observation(start + timedelta(hours=index), float(index)) for index in (0, 1, 3)]
    with pytest.raises(ValueError, match="incomplete"):
        complete_hourly_history(observations, issued, lookback=4)
