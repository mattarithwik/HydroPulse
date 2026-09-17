"""Build seven-day hourly target-stage sequences for tree and GRU challengers."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
from sqlalchemy.orm import Session

from hydropulse.config import get_settings
from hydropulse.db import engine
from hydropulse.domain import HORIZONS
from hydropulse.features import manifest_hash
from hydropulse.upstream_analysis import PARAMETER_STAGE, canonical_values, hourly_means

LOOKBACK_HOURS = 168


def sequence_examples(
    stage: dict[datetime, float], lookback: int = LOOKBACK_HOURS
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    if not stage:
        return (
            np.empty((0, lookback), dtype=np.float32),
            np.empty((0, len(HORIZONS))),
            np.empty(0, dtype=np.int64),
        )
    first, last = min(stage), max(stage)
    size = int((last - first).total_seconds() // 3600) + 1
    values = np.full(size, np.nan, dtype=np.float32)
    for at, value in stage.items():
        index = int((at - first).total_seconds() // 3600)
        values[index] = value
    windows = np.lib.stride_tricks.sliding_window_view(values, lookback)
    # Each bucket summarizes readings taken during that clock hour.  It is
    # therefore available only when the following hour begins.  The extra
    # one-hour offset keeps every label strictly after that availability time:
    # a one-hour forecast issued at 01:00 must target 02:00, not the 01:00
    # bucket that was still being observed while the input hour was forming.
    end_indices = np.arange(lookback - 1, size - max(HORIZONS) - 1)
    histories = windows[end_indices - lookback + 1]
    labels = np.column_stack([values[end_indices + horizon + 1] for horizon in HORIZONS])
    valid = np.isfinite(histories).all(axis=1) & np.isfinite(labels).all(axis=1)
    issued = np.asarray(
        [
            int((first + timedelta(hours=int(index) + 1)).timestamp())
            for index in end_indices[valid]
        ],
        dtype=np.int64,
    )
    return histories[valid].copy(), labels[valid], issued


def build(manifest_path: Path, target_id: str) -> Path:
    manifest = json.loads(manifest_path.read_text())
    cutoff = datetime.fromisoformat(manifest["archive_cutoff"] + "T23:59:59+00:00")
    with Session(engine) as session:
        stage = hourly_means(canonical_values(session, target_id, PARAMETER_STAGE, cutoff))
    x, y, issued = sequence_examples(stage)
    if not len(x):
        raise ValueError(f"no complete seven-day sequences for {target_id}")
    output = get_settings().data_dir / "features" / f"stage-sequence-{target_id}.npz"
    np.savez_compressed(output, x=x, y=y.astype(np.float32), issued_at_epoch_seconds=issued)
    output.with_suffix(".json").write_text(
        json.dumps(
            {
                "target_id": target_id,
                "manifest_sha256": manifest_hash(manifest_path),
                "lookback_hours": LOOKBACK_HOURS,
                "label_horizons_hours": list(HORIZONS),
                "examples": len(x),
                "missing_policy": "complete hourly histories only; no invented observations",
            },
            indent=2,
        )
        + "\n"
    )
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Build seven-day stage sequences")
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--target", required=True)
    args = parser.parse_args()
    print(build(args.manifest, args.target))


if __name__ == "__main__":
    main()
