from hydropulse.ml import PromotionMetrics, nwm_metric_names, stage_promotion_allowed


def test_promotion_requires_mean_improvement_without_horizon_regression():
    champion = PromotionMetrics({1: 1, 6: 1, 24: 1}, 1)
    assert stage_promotion_allowed(champion, PromotionMetrics({1: 0.98, 6: 0.97, 24: 0.96}, 1.01))
    assert not stage_promotion_allowed(champion, PromotionMetrics({1: 1.06, 6: 0.8, 24: 0.8}, 0.8))


def test_nwm_benchmark_cannot_report_flood_metrics_or_stage():
    names = nwm_metric_names()
    assert names == ("mae_cfs", "rmse_cfs", "signed_bias_cfs")
    assert all("stage" not in name and "recall" not in name for name in names)
