"""Model contracts kept independent from orchestration and serving."""

from dataclasses import dataclass


@dataclass(frozen=True)
class PromotionMetrics:
    headline_mae: dict[int, float]
    high_stage_mae: float
    finite_inference: bool = True
    compatible: bool = True


def stage_promotion_allowed(champion: PromotionMetrics, candidate: PromotionMetrics) -> bool:
    if not candidate.finite_inference or not candidate.compatible:
        return False
    horizons = (1, 6, 24)
    degradations = [
        (candidate.headline_mae[h] - champion.headline_mae[h]) / max(0.01, champion.headline_mae[h])
        for h in horizons
    ]
    improvement = sum(
        (champion.headline_mae[h] - candidate.headline_mae[h]) / max(0.01, champion.headline_mae[h])
        for h in horizons
    ) / len(horizons)
    high_degradation = (candidate.high_stage_mae - champion.high_stage_mae) / max(
        0.01, champion.high_stage_mae
    )
    return max(degradations) <= 0.05 and improvement >= 0.02 and high_degradation <= 0.05


def nwm_metric_names() -> tuple[str, ...]:
    """The sampled operational benchmark is discharge regression only."""
    return ("mae_cfs", "rmse_cfs", "signed_bias_cfs")
