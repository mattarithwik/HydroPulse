"""Freeze the data and feature choices that precede stage-model development."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from hydropulse.config import get_settings
from hydropulse.stage1 import SPLITS


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def freeze(
    archive_cutoff: date,
    quality_report: Path,
    upstream_report: Path,
    destination: Path | None = None,
) -> Path:
    """Write once: model work must not silently change its held-out test set."""
    quality = json.loads(quality_report.read_text())
    upstream = json.loads(upstream_report.read_text())
    if upstream["archive_cutoff"] != archive_cutoff.isoformat():
        raise ValueError("upstream report cutoff does not match the requested archive cutoff")
    destination = destination or (
        get_settings().data_dir / "manifests" / f"stage-model-{archive_cutoff.isoformat()}.json"
    )
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "frozen_at": datetime.now(UTC).isoformat(),
        "archive_cutoff": archive_cutoff.isoformat(),
        "splits": {
            name: {
                "start": start.isoformat(),
                "end": end.isoformat() if end else archive_cutoff.isoformat(),
            }
            for name, (start, end) in SPLITS.items()
        },
        "target": "stage_height",
        "probability_products": "disabled_insufficient_calibration_events",
        "quality_report": {"path": str(quality_report), "sha256": sha256(quality_report)},
        "upstream_report": {"path": str(upstream_report), "sha256": sha256(upstream_report)},
        "upstream": {
            target_id: [
                {
                    "gauge_id": gauge["gauge_id"],
                    "lag_hours": gauge["lag_sweep"]["selected"]["lag_hours"],
                }
                for gauge in target["gauges"]
                if gauge["suitable"]
            ]
            for target_id, target in upstream["targets"].items()
        },
        "quality_audit_generated_at": quality.get("generated_at"),
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("x") as handle:
        json.dump(manifest, handle, indent=2)
        handle.write("\n")
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(description="Freeze the stage-model evaluation manifest")
    parser.add_argument("--end", required=True, type=date.fromisoformat)
    parser.add_argument("--quality-report", required=True, type=Path)
    parser.add_argument("--upstream-report", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    print(freeze(args.end, args.quality_report, args.upstream_report, args.output))


if __name__ == "__main__":
    main()
