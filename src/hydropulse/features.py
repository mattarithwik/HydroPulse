"""Create causal, hourly river-only examples for stage-height modeling."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
from sqlalchemy.orm import Session

from hydropulse.config import get_settings
from hydropulse.domain import HORIZONS
from hydropulse.upstream_analysis import (
    PARAMETER_DISCHARGE,
    PARAMETER_STAGE,
    canonical_values,
    hourly_means,
)
from hydropulse.db import engine


def manifest_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def examples(
    stage: dict[datetime, float],
    upstream: dict[str, dict[datetime, float]],
    lags: dict[str, int],
) -> tuple[np.ndarray, np.ndarray, np.ndarray, list[str]]:
    """Return complete causal rows, labels, issuance timestamps, and column names.

    An upstream value at ``issued_at - lag`` is the latest water expected to
    affect the target at issuance.  Future target values are labels only.
    """
    names = ["target_stage_ft", "target_change_1h_ft"] + [
        f"upstream_{gauge_id}_cfs_lag_{lags[gauge_id]}h" for gauge_id in sorted(lags)
    ]
    inputs: list[list[float]] = []
    labels: list[list[float]] = []
    issued: list[int] = []
    for at in sorted(stage):
        previous = stage.get(at - timedelta(hours=1))
        future = [stage.get(at + timedelta(hours=horizon)) for horizon in HORIZONS]
        if previous is None or any(value is None for value in future):
            continue
        row = [stage[at], stage[at] - previous]
        for gauge_id in sorted(lags):
            value = upstream[gauge_id].get(at - timedelta(hours=lags[gauge_id]))
            if value is None:
                break
            row.append(value)
        else:
            inputs.append(row)
            labels.append([float(value) for value in future])
            issued.append(int(at.timestamp()))
    return (
        np.asarray(inputs, dtype=np.float64),
        np.asarray(labels, dtype=np.float64),
        np.asarray(issued, dtype=np.int64),
        names,
    )


def build(manifest_path: Path, target_id: str, output: Path | None = None) -> Path:
    manifest = json.loads(manifest_path.read_text())
    upstream_report_path = Path(manifest["upstream_report"]["path"])
    if manifest_hash(upstream_report_path) != manifest["upstream_report"]["sha256"]:
        raise ValueError("upstream analysis report changed after the manifest was frozen")
    selected = manifest["upstream"][target_id]
    lags = {item["gauge_id"]: item["lag_hours"] for item in selected}
    cutoff = datetime.fromisoformat(manifest["archive_cutoff"] + "T23:59:59+00:00")
    with Session(engine) as session:
        stage = hourly_means(canonical_values(session, target_id, PARAMETER_STAGE, cutoff))
        upstream = {
            gauge_id: hourly_means(canonical_values(session, gauge_id, PARAMETER_DISCHARGE, cutoff))
            for gauge_id in lags
        }
    inputs, labels, issued, names = examples(stage, upstream, lags)
    if not len(inputs):
        raise ValueError(f"no complete training examples for target {target_id}")
    output = output or get_settings().data_dir / "features" / f"stage-{target_id}.npz"
    output.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(output, x=inputs, y=labels, issued_at_epoch_seconds=issued)
    output.with_suffix(".json").write_text(
        json.dumps(
            {
                "target_id": target_id,
                "manifest_sha256": manifest_hash(manifest_path),
                "feature_columns": names,
                "label_horizons_hours": list(HORIZONS),
                "examples": int(len(inputs)),
            },
            indent=2,
        )
        + "\n"
    )
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Build causal stage-model examples")
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--target", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    print(build(args.manifest, args.target, args.output))


if __name__ == "__main__":
    main()
