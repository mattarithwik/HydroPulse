from __future__ import annotations

import argparse
import json
from calendar import monthrange
from collections import Counter, defaultdict
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from statistics import median
from typing import Any

import numpy as np
from sqlalchemy import select

from hydropulse.config import get_settings
from hydropulse.db import ObservationRow, StationSnapshotRow, initialize, session_scope
from hydropulse.domain import BASINS
from hydropulse.stage1 import SPLITS, cluster_episodes, cluster_split, find_episodes

SEASONS = {
    12: "winter",
    1: "winter",
    2: "winter",
    3: "spring",
    4: "spring",
    5: "spring",
    6: "summer",
    7: "summer",
    8: "summer",
    9: "autumn",
    10: "autumn",
    11: "autumn",
}


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _expected_month(year: int, month: int, start: date, end: date) -> int:
    first = max(date(year, month, 1), start)
    last = min(date(year, month, monthrange(year, month)[1]), end)
    return max(0, (last - first).days + 1) * 96


def _canonical(
    rows: list[tuple[datetime, float | None, datetime, str]],
) -> list[tuple[datetime, float | None]]:
    latest: dict[datetime, tuple[datetime, float | None]] = {}
    for event_at, value, ingested_at, _ in rows:
        event_at, ingested_at = _utc(event_at), _utc(ingested_at)
        if event_at not in latest or ingested_at >= latest[event_at][0]:
            latest[event_at] = (ingested_at, value)
    return sorted((at, item[1]) for at, item in latest.items())


def _gap_summary(samples: list[tuple[datetime, float | None]]) -> dict[str, Any]:
    gaps = [
        (right[0] - left[0])
        for left, right in zip(samples, samples[1:])
        if right[0] - left[0] > timedelta(minutes=30)
    ]
    return {
        "over_30_minutes": len(gaps),
        "over_6_hours": sum(gap > timedelta(hours=6) for gap in gaps),
        "over_24_hours": sum(gap > timedelta(hours=24) for gap in gaps),
        "longest_hours": max((gap.total_seconds() / 3600 for gap in gaps), default=0),
    }


def _coverage(
    samples: list[tuple[datetime, float | None]], start: date, end: date
) -> tuple[list[dict[str, Any]], dict[str, float]]:
    counts = Counter((at.year, at.month) for at, value in samples if value is not None)
    monthly: list[dict[str, Any]] = []
    cursor = date(start.year, start.month, 1)
    while cursor <= end:
        expected = _expected_month(cursor.year, cursor.month, start, end)
        observed = counts[(cursor.year, cursor.month)]
        monthly.append(
            {
                "month": cursor.strftime("%Y-%m"),
                "observed": observed,
                "expected": expected,
                "coverage": observed / expected if expected else None,
            }
        )
        cursor = date(
            cursor.year + (cursor.month == 12), 1 if cursor.month == 12 else cursor.month + 1, 1
        )
    seasonal: dict[str, list[float]] = defaultdict(list)
    for item in monthly:
        seasonal[SEASONS[int(item["month"][-2:])]].append(item["coverage"])
    return monthly, {name: sum(values) / len(values) for name, values in seasonal.items()}


def run_quality_audit(cutoff: date) -> Path:
    initialize()
    start = date(2007, 10, 1)
    cutoff_exclusive = datetime.combine(cutoff + timedelta(days=1), datetime.min.time(), UTC)
    report: dict[str, Any] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "archive_cutoff": cutoff.isoformat(),
        "targets": {},
        "prediction_recommendation": {},
    }
    threshold_episodes: dict[str, dict[str, list]] = defaultdict(dict)
    with session_scope() as session:
        snapshots = {
            row.gauge_id: row
            for row in session.scalars(
                select(StationSnapshotRow).order_by(StationSnapshotRow.captured_at)
            ).all()
        }
        for basin in BASINS:
            rows = session.execute(
                select(
                    ObservationRow.event_time,
                    ObservationRow.value,
                    ObservationRow.ingested_at,
                    ObservationRow.payload_hash,
                )
                .where(
                    ObservationRow.gauge_id == basin.usgs_id,
                    ObservationRow.parameter_code == "00065",
                    ObservationRow.source == "usgs",
                    ObservationRow.event_time < cutoff_exclusive,
                )
                .order_by(ObservationRow.event_time, ObservationRow.ingested_at)
            ).all()
            samples = _canonical(rows)
            monthly, seasonal = _coverage(samples, start, cutoff)
            valid_values = [value for _, value in samples if value is not None]
            training_values = [
                value
                for at, value in samples
                if value is not None and at.date() <= SPLITS["training"][1]
            ]
            snapshot = snapshots.get(basin.usgs_id)
            official = snapshot.thresholds_json if snapshot else {}
            thresholds = {
                name: details.get("stage")
                for name, details in official.items()
                if isinstance(details, dict) and details.get("stage") not in (None, -9999)
            }
            thresholds["training_p95_high_water"] = float(np.quantile(training_values, 0.95))
            thresholds["training_p99_high_water"] = float(np.quantile(training_values, 0.99))
            threshold_summary: dict[str, Any] = {}
            for name, threshold in thresholds.items():
                episodes = find_episodes(samples, float(threshold), basin.usgs_id)
                threshold_episodes[name][basin.usgs_id] = episodes
                counts = {split: 0 for split in SPLITS}
                for episode in episodes:
                    midpoint = episode.started_at + (episode.last_above_at - episode.started_at) / 2
                    for split, (split_start, configured_end) in SPLITS.items():
                        if split_start <= midpoint.date() <= (configured_end or cutoff):
                            counts[split] += 1
                            break
                threshold_summary[name] = {
                    "stage_ft": threshold,
                    "episodes": len(episodes),
                    "episodes_by_split": counts,
                    "uncertain_episodes": sum(item.uncertain_end for item in episodes),
                }
            identity_counts = Counter((at, payload_hash) for at, _, _, payload_hash in rows)
            revisions_by_time = Counter(at for at, _, _, _ in rows)
            datum = (
                snapshot.metadata_json.get("datums", {}).get("vertical", {}).get("value", [])
                if snapshot
                else []
            )
            report["targets"][basin.usgs_id] = {
                "name": basin.target_name,
                "valid_samples": len(valid_values),
                "null_samples": sum(value is None for _, value in samples),
                "minimum_ft": min(valid_values),
                "median_ft": median(valid_values),
                "maximum_ft": max(valid_values),
                "duplicate_revision_rows": len(rows) - len(identity_counts),
                "observation_times_with_revisions": sum(
                    count > 1 for count in revisions_by_time.values()
                ),
                "gaps": _gap_summary(samples),
                "seasonal_mean_coverage": seasonal,
                "months_below_90_percent": [
                    item
                    for item in monthly
                    if item["coverage"] is not None and item["coverage"] < 0.9
                ],
                "monthly_coverage": monthly,
                "thresholds": threshold_summary,
                "current_datum": datum,
                "datum_history_status": "unresolved_single_current_snapshot",
            }
    gate_results: dict[str, Any] = {}
    for threshold_name, per_target in threshold_episodes.items():
        episodes = [episode for items in per_target.values() for episode in items]
        clusters = cluster_episodes(episodes)
        cluster_counts = {split: 0 for split in SPLITS}
        for cluster in clusters:
            split = cluster_split(cluster, cutoff)
            if split:
                cluster_counts[split] += 1
        target_counts = {gauge: {split: 0 for split in SPLITS} for gauge in per_target}
        for gauge, items in per_target.items():
            for episode in items:
                midpoint = episode.started_at + (episode.last_above_at - episode.started_at) / 2
                for split, (split_start, configured_end) in SPLITS.items():
                    if split_start <= midpoint.date() <= (configured_end or cutoff):
                        target_counts[gauge][split] += 1
                        break
        pooled_eligible = (
            cluster_counts["training"] >= 30
            and cluster_counts["validation"] >= 10
            and cluster_counts["calibration"] >= 10
        )
        eligible_targets = [
            gauge
            for gauge, counts in target_counts.items()
            if pooled_eligible and counts["training"] >= 3 and counts["calibration"] >= 3
        ]
        gate_results[threshold_name] = {
            "clusters_by_split": cluster_counts,
            "target_episodes_by_split": target_counts,
            "pooled_screening_gate_passed": pooled_eligible,
            "screening_eligible_targets": eligible_targets,
            "status": (
                "eligible_for_calibration_experiment" if eligible_targets else "insufficient_events"
            ),
            "warning": (
                "Screening eligibility is not validation; reliability and independent "
                "evaluation must still pass."
            ),
        }
    report["prediction_recommendation"] = {
        "primary_product": "continuous_stage_quantiles_and_intervals",
        "official_probability_status": "insufficient_events",
        "threshold_gate_results": gate_results,
        "scientifically_sound_path": [
            "fit normalization and percentile thresholds on training years only",
            "evaluate persistence before XGBoost and GRU challengers",
            "use blocked chronological validation and storm-cluster bootstrap intervals",
            "publish stage and interval even when probability calibration is ineligible",
            "keep every official threshold and high-water percentile claim separate",
        ],
    }
    output = get_settings().data_dir / "reports" / f"quality-audit-{cutoff.isoformat()}.json"
    output.write_text(json.dumps(report, default=str, indent=2) + "\n")
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the detailed data-quality audit")
    parser.add_argument(
        "--end", type=date.fromisoformat, default=datetime.now(UTC).date() - timedelta(days=1)
    )
    args = parser.parse_args()
    print(run_quality_audit(args.end))


if __name__ == "__main__":
    main()
