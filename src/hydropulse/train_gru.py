"""Train direct quantile GRU stage challengers on frozen development data."""

from __future__ import annotations

import argparse
import copy
import json
import random
from pathlib import Path

import numpy as np
import torch
from torch import nn
from torch.utils.data import DataLoader, TensorDataset

from hydropulse.config import get_settings
from hydropulse.domain import HORIZONS, QUANTILES
from hydropulse.train_baseline import high_stage_mae, mae_by_horizon, split_masks

SEEDS = (17, 29, 43)
QUANTILE_VALUES = torch.tensor(QUANTILES, dtype=torch.float32)


class StageGRU(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.gru = nn.GRU(1, 64, num_layers=2, dropout=0.1, batch_first=True)
        self.head = nn.Linear(64, len(HORIZONS) * len(QUANTILES))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        output, _ = self.gru(x)
        return self.head(output[:, -1]).reshape(-1, len(HORIZONS), len(QUANTILES))


def pinball_loss(prediction: torch.Tensor, actual: torch.Tensor) -> torch.Tensor:
    error = actual.unsqueeze(-1) - prediction
    quantiles = QUANTILE_VALUES.to(prediction.device)
    return torch.maximum(quantiles * error, (quantiles - 1) * error).mean()


def arrays(x: np.ndarray, y: np.ndarray, input_scale: float, target_scale: np.ndarray):
    current = x[:, -1]
    relative = ((x - current[:, None]) / input_scale).astype(np.float32)[..., None]
    target = ((y - current[:, None]) / target_scale).astype(np.float32)
    return relative, target, current


def predict_batches(
    model: StageGRU, x: np.ndarray, current: np.ndarray, target_scale: np.ndarray, device: str
) -> np.ndarray:
    results = []
    model.eval()
    with torch.no_grad():
        for start in range(0, len(x), 2048):
            batch = torch.from_numpy(x[start : start + 2048]).to(device)
            prediction = torch.sort(model(batch), dim=-1).values.cpu().numpy()
            results.append(prediction)
    normalized = np.concatenate(results)
    return current[:, None, None] + normalized * target_scale[None, :, None]


def train(feature_path: Path, target_id: str) -> tuple[Path, Path]:
    data = np.load(feature_path)
    x, y, issued = data["x"], data["y"], data["issued_at_epoch_seconds"]
    train_mask, validation_mask, calibration_mask = split_masks(issued)
    # Adjacent windows share 167/168 inputs. Twelve-hour thinning retains seasonal
    # and event diversity without replaying almost identical sequences.
    train_indices = np.flatnonzero(train_mask)[::12]
    validation_indices = np.flatnonzero(validation_mask)[::12]
    input_scale = float(np.std(x[train_indices] - x[train_indices, -1, None])) or 1.0
    target_scale = np.std(y[train_indices] - x[train_indices, -1, None], axis=0)
    target_scale[target_scale == 0] = 1.0
    normalized_x, normalized_y, current = arrays(x, y, input_scale, target_scale)
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    train_dataset = TensorDataset(
        torch.from_numpy(normalized_x[train_indices]), torch.from_numpy(normalized_y[train_indices])
    )
    seed_results = []
    settings = get_settings()
    model_dir = settings.artifact_dir / "models" / f"gru-{target_id}"
    model_dir.mkdir(parents=True, exist_ok=True)
    for seed in SEEDS:
        random.seed(seed)
        np.random.seed(seed)
        torch.manual_seed(seed)
        model = StageGRU().to(device)
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3)
        loader = DataLoader(train_dataset, batch_size=256, shuffle=True)
        best_state = None
        best_score = float("inf")
        stale = 0
        epochs = 0
        for epoch in range(50):
            model.train()
            for batch_x, batch_y in loader:
                optimizer.zero_grad(set_to_none=True)
                loss = pinball_loss(model(batch_x.to(device)), batch_y.to(device))
                loss.backward()
                nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                optimizer.step()
            validation = predict_batches(
                model,
                normalized_x[validation_indices],
                current[validation_indices],
                target_scale,
                device,
            )
            median = validation[:, :, QUANTILES.index(0.5)]
            metrics = mae_by_horizon(median, y[validation_indices])
            score = float(np.mean([metrics[str(h)] for h in (1, 6, 24)]))
            epochs = epoch + 1
            print(
                f"target={target_id} seed={seed} epoch={epochs} headline_mae={score:.5f}",
                flush=True,
            )
            if score < best_score - 1e-4:
                best_score = score
                best_state = copy.deepcopy(model.state_dict())
                stale = 0
            else:
                stale += 1
                if stale >= 10:
                    break
        assert best_state is not None
        model.load_state_dict(best_state)
        torch.save(best_state, model_dir / f"seed-{seed}.pt")
        validation = predict_batches(
            model,
            normalized_x[validation_mask],
            current[validation_mask],
            target_scale,
            device,
        )
        seed_results.append((best_score, seed, epochs, validation, copy.deepcopy(best_state)))
    best_score, best_seed, epochs, validation_quantiles, best_state = min(
        seed_results, key=lambda item: (item[0], item[1])
    )
    torch.save(best_state, model_dir / "champion.pt")
    median = validation_quantiles[:, :, QUANTILES.index(0.5)]
    thresholds = np.quantile(y[train_mask], 0.95, axis=0)
    manifest = {
        "model_type": "direct-quantile-gru-stage-v1",
        "target_id": target_id,
        "lookback_hours": int(x.shape[1]),
        "hidden_size": 64,
        "layers": 2,
        "dropout": 0.1,
        "horizons_hours": list(HORIZONS),
        "quantiles": list(QUANTILES),
        "input_scale": input_scale,
        "target_scales": target_scale.tolist(),
        "selected_seed": best_seed,
        "epochs": epochs,
        "training_examples": len(train_indices),
    }
    model_path = model_dir / "manifest.json"
    model_path.write_text(json.dumps(manifest, indent=2) + "\n")
    report = {
        "target_id": target_id,
        "model_type": manifest["model_type"],
        "selected_seed": best_seed,
        "seed_scores": {str(seed): score for score, seed, *_ in seed_results},
        "training_examples": len(train_indices),
        "validation_examples": int(validation_mask.sum()),
        "test_examples_used": 0,
        "validation_mae_ft": mae_by_horizon(median, y[validation_mask]),
        "high_stage_validation_mae_ft": high_stage_mae(median, y[validation_mask], thresholds),
        "note": "Development-only challenger; final test remains untouched.",
    }
    report_path = settings.data_dir / "reports" / f"gru-stage-{target_id}.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    return model_path, report_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Train direct quantile GRU stage challengers")
    parser.add_argument("--target", required=True)
    args = parser.parse_args()
    feature_path = get_settings().data_dir / "features" / f"stage-sequence-{args.target}.npz"
    for path in train(feature_path, args.target):
        print(path)


if __name__ == "__main__":
    main()
