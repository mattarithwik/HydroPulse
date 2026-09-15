from datetime import UTC, datetime, timedelta

from hydropulse.events import EventState


def test_observed_crossing_opens_and_three_distinct_batches_close():
    now = datetime(2026, 1, 1, tzinfo=UTC)
    state = EventState()
    state.observe(now, "a", 12.1, 12)
    assert state.open
    state.observe(now, "same", 11, 12)
    state.observe(now, "same", 11, 12)
    assert state.open
    state.observe(now + timedelta(hours=1), "b", 11, 12)
    state.observe(now + timedelta(hours=2), "c", 11, 12)
    assert not state.open
