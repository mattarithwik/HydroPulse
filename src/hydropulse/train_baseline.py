"""Train and evaluate the first causal stage-height regression baseline."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from hydropulse.config import get_settings
from hydropulse.domain import HORIZONS, QUANTILES
from hydropulse.ml import PromotionMetrics, stage_promotion_allowed

TRAINING_END = datetime(2017, 12, 31, 23, 59, 59, tzinfo=UTC).timestamp()
VALIDATION_START = datetime(2018, 1, 1, tzinfo=UTC).timestamp()
VALIDATION_END = datetime(2020, 12, 31, 23, 59, 59, tzinfo=UTC).timestamp()
CALIBRATION_START = datetime(2021, 1, 1, tzinfo=UTC).timestamp()
CALIBRATION_END = datetime(2023, 12, 31, 23, 59, 59, tzinfo=UTC).timestamp()
RIDGE_PENALTY = 1e-3


def split_masks(issued_at: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return frozen development masks; 2024 onward stays untouched."""
    return (
        issued_at <= TRAINING_END,
        (issued_at >= VALIDATION_START) & (issued_at <= VALIDATION_END),
        (issued_at >= CALIBRATION_START) & (issued_at <= CALIBRATION_END),
    )


def fit_ridge(
    x: np.ndarray, y: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Fit one direct model per horizon using training-set normalization only."""
    means = x.mean(axis=0)
    scales = x.std(axis=0)
    scales[scales == 0] = 1.0
    standardized = (x - means) / scales
    design = np.column_stack((np.ones(len(standardized)), standardized))
    penalty = np.eye(design.shape[1]) * RIDGE_PENALTY
    penalty[0, 0] = 0.0
    weights = np.linalg.solve(design.T @ design + penalty, design.T @ y)
    return means, scales, weights[0], weights[1:]


def predict(
    x: np.ndarray, means: np.ndarray, scales: np.ndarray, intercept: np.ndarray, weights: np.ndarray
) -> np.ndarray:
    return intercept + ((x - means) / scales) @ weights


def mae_by_horizon(prediction: np.ndarray, actual: np.ndarray) -> dict[str, float]:
    return {
        str(horizon): float(np.mean(np.abs(prediction[:, index] - actual[:, index])))
        for index, horizon in enumerate(HORIZONS)
    }


def high_stage_mae(prediction: np.ndarray, actual: np.ndarray, thresholds: np.ndarray) -> float:
    errors = [
        np.abs(prediction[:, index] - actual[:, index])[actual[:, index] >= thresholds[index]]
        for index in range(len(HORIZONS))
    ]
    populated = [values for values in errors if len(values)]
    return float(np.mean(np.concatenate(populated))) if populated else float("inf")


def train(feature_path: Path, target_id: str) -> tuple[Path, Path]:
    data = np.load(feature_path)
    x, y, issued = data["x"], data["y"], data["issued_at_epoch_seconds"]
    train_mask, validation_mask, calibration_mask = split_masks(issued)
    if not train_mask.any() or not validation_mask.any() or not calibration_mask.any():
        raise ValueError("a frozen development split has no examples")
    metadata = json.loads(feature_path.with_suffix(".json").read_text())
    variants = {"target_only": np.arange(2), "target_plus_upstream": np.arange(x.shape[1])}
    fitted = {}
    validation_predictions = {}
    validation_metrics = {}
    thresholds = np.quantile(y[train_mask], 0.95, axis=0)
    for name, indices in variants.items():
        fitted[name] = fit_ridge(x[train_mask][:, indices], y[train_mask])
        validation_predictions[name] = predict(x[validation_mask][:, indices], *fitted[name])
        validation_metrics[name] = mae_by_horizon(validation_predictions[name], y[validation_mask])
    target_metrics = PromotionMetrics(
        {h: validation_metrics["target_only"][str(h)] for h in (1, 6, 24)},
        high_stage_mae(validation_predictions["target_only"], y[validation_mask], thresholds),
    )
    upstream_metrics = PromotionMetrics(
        {h: validation_metrics["target_plus_upstream"][str(h)] for h in (1, 6, 24)},
        high_stage_mae(
            validation_predictions["target_plus_upstream"], y[validation_mask], thresholds
        ),
    )
    winner = (
        "target_plus_upstream"
        if stage_promotion_allowed(target_metrics, upstream_metrics)
        else "target_only"
    )
    selected_indices = variants[winner]
    means, scales, intercept, weights = fitted[winner]
    calibration_prediction = predict(
        x[calibration_mask][:, selected_indices], means, scales, intercept, weights
    )
    residuals = y[calibration_mask] - calibration_prediction
    residual_quantiles = {
        str(quantile): np.quantile(residuals, quantile, axis=0).tolist() for quantile in QUANTILES
    }
    persistence_prediction = np.repeat(x[validation_mask, :1], len(HORIZONS), axis=1)
    model = {
        "model_type": "direct-ridge-stage-v1",
        "target_id": target_id,
        "selected_variant": winner,
        "feature_indices": selected_indices.tolist(),
        "feature_columns": [metadata["feature_columns"][index] for index in selected_indices],
        "feature_metadata_sha256": hashlib.sha256(
            feature_path.with_suffix(".json").read_bytes()
        ).hexdigest(),
        "feature_means": means.tolist(),
        "feature_scales": scales.tolist(),
        "intercept": intercept.tolist(),
        "weights": weights.tolist(),
        "horizons_hours": list(HORIZONS),
        "residual_quantile_offsets": residual_quantiles,
        "training_examples": int(train_mask.sum()),
        "calibration_examples": int(calibration_mask.sum()),
    }
    report = {
        "target_id": target_id,
        "model_type": model["model_type"],
        "training_examples": int(train_mask.sum()),
        "validation_examples": int(validation_mask.sum()),
        "calibration_examples": int(calibration_mask.sum()),
        "test_examples_used": 0,
        "validation_mae_ft": {
            "persistence": mae_by_horizon(persistence_prediction, y[validation_mask]),
            **validation_metrics,
        },
        "high_stage_validation_mae_ft": {
            "target_only": target_metrics.high_stage_mae,
            "target_plus_upstream": upstream_metrics.high_stage_mae,
        },
        "selected_variant": winner,
        "note": "Exploratory development result; final test period remains untouched.",
    }
    settings = get_settings()
    model_path = settings.artifact_dir / "models" / f"stage-ridge-{target_id}.json"
    report_path = settings.data_dir / "reports" / f"baseline-stage-{target_id}.json"
    model_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    model_path.write_text(json.dumps(model, indent=2) + "\n")
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    return model_path, report_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Train the frozen-split stage baseline")
    parser.add_argument("--target", required=True)
    parser.add_argument("--features", type=Path)
    args = parser.parse_args()
    feature_path = (
        args.features or get_settings().data_dir / "features" / f"stage-{args.target}.npz"
    )
    model, report = train(feature_path, args.target)
    print(model)
    print(report)


if __name__ == "__main__":
    main()
