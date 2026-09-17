import torch

from hydropulse.train_gru import pinball_loss


def test_pinball_loss_is_zero_for_exact_quantiles():
    actual = torch.ones((2, 5))
    prediction = torch.ones((2, 5, 7))
    assert pinball_loss(prediction, actual).item() == 0
