import json

from hydropulse.model_comparison import compare


def test_comparison_keeps_challenger_in_shadow_until_gate_passes(tmp_path):
    (tmp_path / "baseline-stage-x.json").write_text(
        json.dumps(
            {
                "validation_mae_ft": {"target_only": {"1": 1, "6": 1, "24": 1}},
                "high_stage_validation_mae_ft": {"target_only": 1},
            }
        )
    )
    (tmp_path / "xgboost-stage-x.json").write_text(
        json.dumps(
            {
                "model_type": "xgb",
                "validation_mae_ft": {"1": 0.98, "6": 0.97, "24": 0.96},
                "high_stage_validation_mae_ft": 1.01,
            }
        )
    )
    result = json.loads(compare("x", tmp_path).read_text())
    assert result["held_out_test_used"] is False
    assert result["challengers"]["xgboost"]["promotion_allowed"] is True
