"""Train and evaluate the first causal stage-height regression baseline."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from hydropulse.config import get_settings
from hydropulse.domain import HORIZONS

TRAINING_END = datetime(2017, 12, 31, 23, 59, 59, tzinfo=UTC).timestamp()
VALIDATION_START = datetime(2018, 1, 1, tzinfo=UTC).timestamp()
VALIDATION_END = datetime(2020, 12, 31, 23, 59, 59, tzinfo=UTC).timestamp()
RIDGE_PENALTY = 1e-3


def split_masks(issued_at: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return frozen training and validation masks; later data stays untouched."""
    return issued_at <= TRAINING_END, (issued_at >= VALIDATION_START) & (
        issued_at <= VALIDATION_END
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


def train(feature_path: Path, target_id: str) -> tuple[Path, Path]:
    data = np.load(feature_path)
    x, y, issued = data["x"], data["y"], data["issued_at_epoch_seconds"]
    train_mask, validation_mask = split_masks(issued)
    if not train_mask.any() or not validation_mask.any():
        raise ValueError("frozen training or validation split has no examples")
    means, scales, intercept, weights = fit_ridge(x[train_mask], y[train_mask])
    model_prediction = predict(x[validation_mask], means, scales, intercept, weights)
    persistence_prediction = np.repeat(x[validation_mask, :1], len(HORIZONS), axis=1)
    model = {
        "model_type": "direct-ridge-stage-v1",
        "target_id": target_id,
        "feature_metadata_sha256": hashlib.sha256(
            feature_path.with_suffix(".json").read_bytes()
        ).hexdigest(),
        "feature_means": means.tolist(),
        "feature_scales": scales.tolist(),
        "intercept": intercept.tolist(),
        "weights": weights.tolist(),
        "horizons_hours": list(HORIZONS),
        "training_examples": int(train_mask.sum()),
    }
    report = {
        "target_id": target_id,
        "model_type": model["model_type"],
        "training_examples": int(train_mask.sum()),
        "validation_examples": int(validation_mask.sum()),
        "test_examples_used": 0,
        "validation_mae_ft": {
            "persistence": mae_by_horizon(persistence_prediction, y[validation_mask]),
            "ridge_with_upstream": mae_by_horizon(model_prediction, y[validation_mask]),
        },
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
