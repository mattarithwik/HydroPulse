from datetime import UTC, datetime, timedelta

from hydropulse.features import examples


def test_examples_only_use_upstream_values_available_at_issuance():
    start = datetime(2020, 1, 1, tzinfo=UTC)
    stage = {start + timedelta(hours=index): float(index) for index in range(75)}
    upstream = {"up": {start + timedelta(hours=index): float(100 + index) for index in range(75)}}
    x, y, issued, names = examples(stage, upstream, {"up": 1})
    assert names[-1] == "upstream_up_cfs_lag_1h"
    assert issued[0] == int((start + timedelta(hours=1)).timestamp())
    assert x[0].tolist() == [1.0, 1.0, 100.0]
    assert y[0].tolist() == [2.0, 7.0, 25.0, 49.0, 73.0]
