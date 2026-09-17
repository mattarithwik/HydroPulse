from datetime import UTC, datetime, timedelta

from hydropulse.sequence_features import sequence_examples


def test_sequence_examples_require_complete_history_and_future_labels():
    start = datetime(2020, 1, 1, tzinfo=UTC)
    stage = {start + timedelta(hours=i): float(i) for i in range(80)}
    x, y, issued = sequence_examples(stage, lookback=4)
    assert x[0].tolist() == [0, 1, 2, 3]
    assert y[0].tolist() == [5, 10, 28, 52, 76]
    assert issued[0] == int((start + timedelta(hours=4)).timestamp())
    del stage[start + timedelta(hours=2)]
    x, _, _ = sequence_examples(stage, lookback=4)
    assert x[0].tolist() == [3, 4, 5, 6]
