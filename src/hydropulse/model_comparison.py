"""Compare development challengers without touching the held-out test period."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from hydropulse.config import get_settings
from hydropulse.ml import PromotionMetrics, stage_promotion_allowed


def metrics(report: dict, variant: str | None = None) -> PromotionMetrics:
    """Extract the common promotion metrics from a training report."""
    horizon_mae = report["validation_mae_ft"]
    high_stage = report["high_stage_validation_mae_ft"]
    if variant is not None:
        horizon_mae = horizon_mae[variant]
        high_stage = high_stage[variant]
    return PromotionMetrics(
        {horizon: float(horizon_mae[str(horizon)]) for horizon in (1, 6, 24)},
        float(high_stage),
    )


def compare(target_id: str, reports_dir: Path | None = None) -> Path:
    """Write a reproducible, development-only ranking for one target."""
    reports_dir = reports_dir or get_settings().data_dir / "reports"
    ridge = json.loads((reports_dir / f"baseline-stage-{target_id}.json").read_text())
    champion = metrics(ridge, "target_only")
    candidates = {}
    for name in ("xgboost", "gru"):
        path = reports_dir / f"{name}-stage-{target_id}.json"
        if not path.exists():
            continue
        report = json.loads(path.read_text())
        candidate = metrics(report)
        candidates[name] = {
            "model_type": report["model_type"],
            "validation_mae_ft": report["validation_mae_ft"],
            "high_stage_validation_mae_ft": report["high_stage_validation_mae_ft"],
            "promotion_allowed": stage_promotion_allowed(champion, candidate),
        }
    result = {
        "target_id": target_id,
        "comparison_period": "2018-01-01 through 2020-12-31; development only",
        "held_out_test_used": False,
        "champion": {
            "name": "ridge_target_only",
            "validation_mae_ft": ridge["validation_mae_ft"]["target_only"],
            "high_stage_validation_mae_ft": ridge["high_stage_validation_mae_ft"]["target_only"],
        },
        "challengers": candidates,
        "note": "A positive development gate only permits seven-day shadow evaluation; it is not a production promotion.",
    }
    output = reports_dir / f"model-comparison-{target_id}.json"
    output.write_text(json.dumps(result, indent=2) + "\n")
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare stage-model challengers")
    parser.add_argument("--target", required=True)
    args = parser.parse_args()
    print(compare(args.target))


if __name__ == "__main__":
    main()
