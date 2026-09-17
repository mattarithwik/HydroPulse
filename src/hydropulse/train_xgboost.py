"""Train direct XGBoost stage-height challengers on frozen development splits."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from xgboost import XGBRegressor

from hydropulse.config import get_settings
from hydropulse.domain import HORIZONS, QUANTILES
from hydropulse.train_baseline import high_stage_mae, mae_by_horizon, split_masks


def train(feature_path: Path, target_id: str) -> tuple[Path, Path]:
    data = np.load(feature_path)
    x, y, issued = data["x"], data["y"], data["issued_at_epoch_seconds"]
    train_mask, validation_mask, calibration_mask = split_masks(issued)
    current_stage = x[:, -1]
    change_targets = y - current_stage[:, None]
    predictions = {"validation": [], "calibration": []}
    settings = get_settings()
    model_dir = settings.artifact_dir / "models" / f"xgboost-{target_id}"
    model_dir.mkdir(parents=True, exist_ok=True)
    best_iterations = []
    for index, horizon in enumerate(HORIZONS):
        model = XGBRegressor(
            objective="reg:squarederror",
            n_estimators=1000,
            learning_rate=0.04,
            max_depth=6,
            min_child_weight=5,
            subsample=0.8,
            colsample_bytree=0.8,
            reg_lambda=1.0,
            tree_method="hist",
            n_jobs=8,
            random_state=20260917,
            early_stopping_rounds=20,
        )
        model.fit(
            x[train_mask],
            change_targets[train_mask, index],
            eval_set=[(x[validation_mask], change_targets[validation_mask, index])],
            verbose=False,
        )
        model.save_model(model_dir / f"horizon-{horizon}.json")
        predictions["validation"].append(
            current_stage[validation_mask] + model.predict(x[validation_mask])
        )
        predictions["calibration"].append(
            current_stage[calibration_mask] + model.predict(x[calibration_mask])
        )
        best_iterations.append(int(model.best_iteration))
    validation_prediction = np.column_stack(predictions["validation"])
    calibration_prediction = np.column_stack(predictions["calibration"])
    residuals = y[calibration_mask] - calibration_prediction
    residual_quantiles = {
        str(quantile): np.quantile(residuals, quantile, axis=0).tolist() for quantile in QUANTILES
    }
    metadata = {
        "model_type": "direct-xgboost-stage-v1",
        "target_id": target_id,
        "lookback_hours": int(x.shape[1]),
        "prediction_target": "change_from_latest_stage",
        "horizons_hours": list(HORIZONS),
        "residual_quantile_offsets": residual_quantiles,
        "training_examples": int(train_mask.sum()),
        "calibration_examples": int(calibration_mask.sum()),
        "best_iterations": best_iterations,
    }
    model_path = model_dir / "manifest.json"
    model_path.write_text(json.dumps(metadata, indent=2) + "\n")
    thresholds = np.quantile(y[train_mask], 0.95, axis=0)
    report = {
        "target_id": target_id,
        "model_type": metadata["model_type"],
        "training_examples": int(train_mask.sum()),
        "validation_examples": int(validation_mask.sum()),
        "calibration_examples": int(calibration_mask.sum()),
        "test_examples_used": 0,
        "validation_mae_ft": mae_by_horizon(validation_prediction, y[validation_mask]),
        "high_stage_validation_mae_ft": high_stage_mae(
            validation_prediction, y[validation_mask], thresholds
        ),
        "note": "Development-only challenger; final test remains untouched.",
    }
    report_path = settings.data_dir / "reports" / f"xgboost-stage-{target_id}.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    return model_path, report_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Train direct XGBoost stage challengers")
    parser.add_argument("--target", required=True)
    parser.add_argument("--features", type=Path)
    args = parser.parse_args()
    features = args.features or (
        get_settings().data_dir / "features" / f"stage-sequence-{args.target}.npz"
    )
    for path in train(features, args.target):
        print(path)


if __name__ == "__main__":
    main()
