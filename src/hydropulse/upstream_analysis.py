from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from math import log1p
from pathlib import Path
from statistics import fmean
from typing import Any, Iterable

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from hydropulse.config import get_settings
from hydropulse.db import ObservationRow, SourceArchiveRow, engine
from hydropulse.domain import BASINS
from hydropulse.upstream_audit import lean_selection

TRAINING_END = datetime(2017, 12, 31, 23, 59, 59, tzinfo=UTC)
PARAMETER_DISCHARGE = "00060"
PARAMETER_STAGE = "00065"


class IncompleteBackfillError(RuntimeError):
    pass


def expected_month_count(start: date, end: date) -> int:
    return (end.year - start.year) * 12 + end.month - start.month + 1


def selected_by_target(report: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for target_id, target in report["targets"].items():
        result[target_id] = target.get("model_selected") or lean_selection(
            target_id, target["selected"]
        )
    return result


def completed_partitions(session: Session, gauge_id: str, parameter: str) -> int:
    prefix = f"continuous/{gauge_id}/{parameter}/"
    resources = session.scalars(
        select(SourceArchiveRow.resource).where(
            SourceArchiveRow.source == "usgs", SourceArchiveRow.resource.like(f"{prefix}%")
        )
    ).all()
    return len(set(resources))


def canonical_values(
    session: Session,
    gauge_id: str,
    parameter: str,
    cutoff: datetime,
) -> list[tuple[datetime, float]]:
    rows = session.execute(
        select(
            ObservationRow.event_time,
            ObservationRow.value,
            ObservationRow.ingested_at,
        )
        .where(
            ObservationRow.source == "usgs",
            ObservationRow.gauge_id == gauge_id,
            ObservationRow.parameter_code == parameter,
            ObservationRow.event_time <= cutoff,
            ObservationRow.value.is_not(None),
        )
        .order_by(ObservationRow.event_time, ObservationRow.ingested_at)
    ).all()
    latest: dict[datetime, tuple[datetime, float]] = {}
    for event_at, value, ingested_at in rows:
        event_at = (
            event_at.replace(tzinfo=UTC) if event_at.tzinfo is None else event_at.astimezone(UTC)
        )
        ingested_at = (
            ingested_at.replace(tzinfo=UTC)
            if ingested_at.tzinfo is None
            else ingested_at.astimezone(UTC)
        )
        if event_at not in latest or ingested_at >= latest[event_at][0]:
            latest[event_at] = (ingested_at, float(value))
    return sorted((at, item[1]) for at, item in latest.items())


def hourly_means(values: Iterable[tuple[datetime, float]]) -> dict[datetime, float]:
    buckets: dict[datetime, list[float]] = defaultdict(list)
    for at, value in values:
        hour = at.replace(minute=0, second=0, microsecond=0)
        buckets[hour].append(value)
    return {hour: fmean(samples) for hour, samples in buckets.items()}


def hourly_changes(
    values: dict[datetime, float], transform_log: bool = False
) -> dict[datetime, float]:
    changes: dict[datetime, float] = {}
    for at, value in values.items():
        previous = values.get(at - timedelta(hours=1))
        if previous is None:
            continue
        if transform_log:
            changes[at] = log1p(max(0.0, value)) - log1p(max(0.0, previous))
        else:
            changes[at] = value - previous
    return changes


def lag_sweep(
    upstream_hourly: dict[datetime, float],
    target_hourly: dict[datetime, float],
    maximum_lag_hours: int = 72,
    minimum_pairs: int = 1000,
) -> dict[str, Any]:
    """Choose travel lag from training-only changes, with upstream leading target."""
    upstream_change = hourly_changes(upstream_hourly, transform_log=True)
    target_change = hourly_changes(target_hourly)
    candidates: list[dict[str, Any]] = []
    for lag in range(maximum_lag_hours + 1):
        delta = timedelta(hours=lag)
        pairs = [
            (change, target_change[at + delta])
            for at, change in upstream_change.items()
            if at + delta in target_change
        ]
        if len(pairs) < minimum_pairs:
            candidates.append({"lag_hours": lag, "paired_hours": len(pairs), "correlation": None})
            continue
        upstream_array = np.asarray([pair[0] for pair in pairs], dtype=float)
        target_array = np.asarray([pair[1] for pair in pairs], dtype=float)
        correlation = float(np.corrcoef(upstream_array, target_array)[0, 1])
        candidates.append(
            {
                "lag_hours": lag,
                "paired_hours": len(pairs),
                "correlation": correlation if np.isfinite(correlation) else None,
            }
        )
    eligible = [item for item in candidates if item["correlation"] is not None]
    selected = (
        max(eligible, key=lambda item: (abs(item["correlation"]), -item["lag_hours"]))
        if eligible
        else None
    )
    return {"selected": selected, "candidates": candidates}


def run(report_path: Path, start: date, cutoff: date) -> Path:
    report = json.loads(report_path.read_text())
    selections = selected_by_target(report)
    required_months = expected_month_count(start, cutoff)
    cutoff_at = datetime.combine(cutoff, datetime.max.time(), UTC)
    expected_samples = ((cutoff - start).days + 1) * 96
    output: dict[str, Any] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "archive_cutoff": cutoff.isoformat(),
        "training_lag_cutoff": TRAINING_END.isoformat(),
        "required_monthly_partitions_per_series": required_months,
        "targets": {},
        "method": (
            "Hourly first differences; log1p upstream discharge leads target stage by 0-72 hours. "
            "Lag selection uses training dates only."
        ),
    }
    with Session(engine) as session:
        incomplete: list[dict[str, Any]] = []
        for target_id, candidates in selections.items():
            for candidate in candidates:
                complete = completed_partitions(session, candidate["gauge_id"], PARAMETER_DISCHARGE)
                if complete < required_months:
                    incomplete.append(
                        {
                            "gauge_id": candidate["gauge_id"],
                            "complete": complete,
                            "required": required_months,
                        }
                    )
        if incomplete:
            raise IncompleteBackfillError(
                "upstream analysis refused partial data: "
                + json.dumps(incomplete, separators=(",", ":"))
            )
        for basin in BASINS:
            target_training = hourly_means(
                canonical_values(session, basin.usgs_id, PARAMETER_STAGE, TRAINING_END)
            )
            target_result: dict[str, Any] = {"name": basin.target_name, "gauges": []}
            for candidate in selections[basin.usgs_id]:
                gauge_id = candidate["gauge_id"]
                all_values = canonical_values(session, gauge_id, PARAMETER_DISCHARGE, cutoff_at)
                training_values = [(at, value) for at, value in all_values if at <= TRAINING_END]
                coverage = len(all_values) / expected_samples
                lags = lag_sweep(hourly_means(training_values), target_training)
                target_result["gauges"].append(
                    {
                        "gauge_id": gauge_id,
                        "name": candidate["name"],
                        "actual_15_minute_coverage": coverage,
                        "observations": len(all_values),
                        "training_observations": len(training_values),
                        "suitable": coverage >= 0.8 and lags["selected"] is not None,
                        "lag_sweep": lags,
                    }
                )
            target_result["minimum_three_suitable_met"] = (
                sum(item["suitable"] for item in target_result["gauges"]) >= 3
            )
            output["targets"][basin.usgs_id] = target_result
    destination = (
        get_settings().data_dir / "reports" / f"upstream-analysis-{cutoff.isoformat()}.json"
    )
    destination.write_text(json.dumps(output, indent=2) + "\n")
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Verify upstream coverage and select train-only lags"
    )
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--start", type=date.fromisoformat, default=date(2007, 10, 1))
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    args = parser.parse_args()
    try:
        print(run(args.report, args.start, args.end))
    except IncompleteBackfillError as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
