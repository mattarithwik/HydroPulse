from datetime import UTC, datetime

import numpy as np

from hydropulse.train_baseline import fit_ridge, predict, split_masks


def test_split_masks_leave_test_period_unused():
    issued = np.array(
        [
            datetime(2017, 12, 31, tzinfo=UTC).timestamp(),
            datetime(2018, 1, 1, tzinfo=UTC).timestamp(),
            datetime(2024, 1, 1, tzinfo=UTC).timestamp(),
        ]
    )
    train, validation = split_masks(issued)
    assert train.tolist() == [True, False, False]
    assert validation.tolist() == [False, True, False]


def test_ridge_recovers_linear_relationship():
    x = np.arange(20, dtype=float).reshape(-1, 1)
    y = np.column_stack((3 + 2 * x[:, 0], 5 - x[:, 0]))
    means, scales, intercept, weights = fit_ridge(x, y)
    assert np.allclose(predict(x, means, scales, intercept, weights), y, atol=1e-3)
