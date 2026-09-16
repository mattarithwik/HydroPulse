from datetime import UTC, date, datetime, timedelta

from hydropulse.upstream_analysis import (
    expected_month_count,
    hourly_means,
    lag_sweep,
    quarter_hour_coverage,
)


def test_expected_month_count_is_inclusive():
    assert expected_month_count(date(2024, 1, 1), date(2024, 12, 31)) == 12
    assert expected_month_count(date(2024, 6, 1), date(2025, 6, 1)) == 13


def test_hourly_means_preserve_missing_hours():
    start = datetime(2015, 1, 1, tzinfo=UTC)
    result = hourly_means(
        [(start, 1), (start + timedelta(minutes=15), 3), (start + timedelta(hours=2), 9)]
    )
    assert result == {start: 2, start + timedelta(hours=2): 9}


def test_quarter_hour_coverage_counts_high_frequency_readings_once():
    start = datetime(2015, 1, 1, tzinfo=UTC)
    values = [(start + timedelta(minutes=offset), 1) for offset in (0, 5, 10, 15)]
    assert quarter_hour_coverage(values, expected_samples=2) == 1.0


def test_lag_sweep_recovers_known_upstream_lead():
    start = datetime(2010, 1, 1, tzinfo=UTC)
    upstream = {
        start + timedelta(hours=index): float(100 + (index % 13) ** 2) for index in range(1600)
    }
    target = {at + timedelta(hours=7): 4 + value / 100 for at, value in upstream.items()}
    result = lag_sweep(upstream, target, maximum_lag_hours=12, minimum_pairs=100)
    assert result["selected"]["lag_hours"] == 7
