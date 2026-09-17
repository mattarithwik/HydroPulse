"""Issue local, append-only shadow forecasts for trained ML challengers.

This intentionally runs outside the API container: the GRU is trained and
served on the local Apple-Metal Python environment, while the public API keeps
using the small, audited ridge candidate.  These records are evidence for a
later decision, never a change to the public forecast.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from statistics import fmean

import numpy as np

from hydropulse.config import get_settings
from hydropulse.db import Repository
from hydropulse.domain import BASINS, HORIZONS, QUANTILES, Observation
from hydropulse.stage1 import collect_live, collect_recent_stage_history

LOOKBACK_HOURS = 168


def complete_hourly_history(
    observations: list[Observation], issued_at: datetime, lookback: int = LOOKBACK_HOURS
) -> tuple[datetime, np.ndarray]:
    """Return only fully elapsed hourly buckets, rejecting gaps rather than filling them."""
    input_ends = issued_at.astimezone(UTC).replace(minute=0, second=0, microsecond=0) - timedelta(
        hours=1
    )
    buckets: dict[datetime, list[float]] = defaultdict(list)
    for observation in observations:
        if observation.value is None or observation.event_time > input_ends + timedelta(hours=1):
            continue
        hour = observation.event_time.astimezone(UTC).replace(minute=0, second=0, microsecond=0)
        buckets[hour].append(float(observation.value))
    hours = [input_ends - timedelta(hours=lookback - 1 - index) for index in range(lookback)]
    missing = [hour.isoformat() for hour in hours if hour not in buckets]
    if missing:
        raise ValueError(f"incomplete {lookback}-hour history; first missing hour is {missing[0]}")
    return input_ends, np.asarray([fmean(buckets[hour]) for hour in hours], dtype=np.float32)


def xgboost_quantiles(target_id: str, history: np.ndarray) -> np.ndarray:
    from xgboost import XGBRegressor

    model_dir = get_settings().artifact_dir / "models" / f"xgboost-{target_id}"
    manifest = json.loads((model_dir / "manifest.json").read_text())
    if int(manifest["lookback_hours"]) != len(history):
        raise ValueError("XGBoost lookback does not match live history")
    centers = []
    for horizon in HORIZONS:
        model = XGBRegressor()
        model.load_model(model_dir / f"horizon-{horizon}.json")
        centers.append(float(history[-1] + model.predict(history[None, :])[0]))
    offsets = manifest["residual_quantile_offsets"]
    return np.asarray(
        [[max(0.0, center + offsets[str(q)][index]) for q in QUANTILES] for index, center in enumerate(centers)]
    )


def gru_quantiles(target_id: str, history: np.ndarray) -> np.ndarray:
    import torch

    from hydropulse.train_gru import StageGRU

    model_dir = get_settings().artifact_dir / "models" / f"gru-{target_id}"
    manifest = json.loads((model_dir / "manifest.json").read_text())
    if int(manifest["lookback_hours"]) != len(history):
        raise ValueError("GRU lookback does not match live history")
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    model = StageGRU().to(device)
    model.load_state_dict(torch.load(model_dir / "champion.pt", map_location=device, weights_only=True))
    model.eval()
    relative = ((history - history[-1]) / float(manifest["input_scale"])).astype(np.float32)
    with torch.no_grad():
        raw = model(torch.from_numpy(relative[None, :, None]).to(device))[0]
        normalized = torch.sort(raw, dim=-1).values.cpu().numpy()
    scales = np.asarray(manifest["target_scales"], dtype=np.float32)
    return np.maximum(0.0, history[-1] + normalized * scales[:, None])


def record(target_id: str, issued_at: datetime, input_ends: datetime, name: str, values: np.ndarray) -> dict:
    return {
        "target_id": target_id,
        "issued_at": issued_at.isoformat(),
        "input_history_ends_at": input_ends.isoformat(),
        "model": name,
        "model_status": "challenger_shadow",
        "stage_quantiles_ft": {
            str(horizon): {str(quantile): float(values[index, q]) for q, quantile in enumerate(QUANTILES)}
            for index, horizon in enumerate(HORIZONS)
        },
    }


def run(collect: bool = True) -> dict:
    if collect:
        collection = {
            "live": asyncio.run(collect_live()),
            "recent_stage_history": asyncio.run(collect_recent_stage_history()),
        }
    else:
        collection = {}
    issued_at = datetime.now(UTC)
    repository = Repository()
    forecasts = []
    failures = []
    for basin in BASINS:
        try:
            observations = repository.observations(
                basin.usgs_id, issued_at - timedelta(days=9), limit=100_000
            )
            input_ends, history = complete_hourly_history(observations, issued_at)
            for name, predictor in (("xgboost", xgboost_quantiles), ("gru", gru_quantiles)):
                try:
                    forecasts.append(record(basin.usgs_id, issued_at, input_ends, name, predictor(basin.usgs_id, history)))
                except FileNotFoundError:
                    failures.append({"target_id": basin.usgs_id, "model": name, "reason": "artifact unavailable"})
        except ValueError as error:
            failures.append({"target_id": basin.usgs_id, "reason": str(error)})
    output_dir = get_settings().data_dir / "shadow-challengers"
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / f"{issued_at:%Y%m%dT%H%M%SZ}.json"
    output.write_text(json.dumps({"collection": collection, "forecasts": forecasts, "failures": failures}, indent=2) + "\n")
    return {"output": str(output), "forecast_count": len(forecasts), "failures": failures}


def main() -> None:
    parser = argparse.ArgumentParser(description="Issue local ML challenger shadow forecasts")
    parser.add_argument("--no-collect", action="store_true")
    args = parser.parse_args()
    print(json.dumps(run(collect=not args.no_collect), indent=2))


if __name__ == "__main__":
    main()
