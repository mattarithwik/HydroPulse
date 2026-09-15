from datetime import UTC, date, datetime, timedelta

from hydropulse.quality_audit import _expected_month, _gap_summary


def test_partial_month_expected_samples_are_bounded_by_audit_dates():
    assert _expected_month(2007, 10, date(2007, 10, 15), date(2007, 10, 20)) == 6 * 96


def test_gap_summary_distinguishes_operationally_material_gaps():
    start = datetime(2024, 1, 1, tzinfo=UTC)
    samples = [(start, 1.0), (start + timedelta(hours=1), 1.0), (start + timedelta(hours=26), 1.0)]
    result = _gap_summary(samples)
    assert result["over_30_minutes"] == 2
    assert result["over_24_hours"] == 1
