from datetime import UTC, datetime, timedelta

import pytest

from hydropulse.domain import QuantilePoint, native_window_label


NOW = datetime(2026, 1, 1, tzinfo=UTC)


def test_native_crossing_is_positive_even_with_missing_samples():
    label = native_window_label(
        [(NOW + timedelta(minutes=15), None), (NOW + timedelta(minutes=30), 12.1)], NOW, 1, 12
    )
    assert label.crossed is True


def test_incomplete_window_cannot_certify_negative():
    label = native_window_label([(NOW + timedelta(minutes=15), 11.9)], NOW, 1, 12)
    assert label.crossed is None


def test_complete_window_can_certify_negative():
    samples = [(NOW + timedelta(minutes=15 * i), 11.9) for i in range(1, 5)]
    assert native_window_label(samples, NOW, 1, 12).crossed is False


def test_crossing_quantiles_are_rejected():
    with pytest.raises(ValueError):
        QuantilePoint(horizon_hours=1, valid_at=NOW, quantiles={"0.1": 2, "0.5": 1})
