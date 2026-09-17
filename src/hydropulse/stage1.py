from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, AsyncIterator

import httpx
from sqlalchemy import select

from hydropulse.adapters.usgs import BASE_URL, USGSClient
from hydropulse.archive import archive_payload
from hydropulse.config import get_settings
from hydropulse.db import (
    ObservationRow,
    SourceArchiveRow,
    StationSnapshotRow,
    initialize,
    session_scope,
)
from hydropulse.domain import BASINS, Basin
from hydropulse.ingestion import persist_observations

NWPS_BASE = "https://api.water.noaa.gov/nwps/v1"
IEM_LIST = "https://mesonet.agron.iastate.edu/api/1/nws/afos/list.json"
IEM_TEXT = "https://mesonet.agron.iastate.edu/api/1/nwstext"
IEM_PRODUCTS = {"CIDI4": "RVFCIW", "CARV2": "RVFJAA", "GLDN7": "RVFRAH"}
START_DATE = date(2007, 10, 1)


class SourceClient:
    def __init__(self) -> None:
        timeout = httpx.Timeout(60, connect=15)
        self.client = httpx.AsyncClient(timeout=timeout, headers={"User-Agent": "HydroPulse/0.1"})

    async def close(self) -> None:
        await self.client.aclose()

    async def json(self, url: str, params: dict[str, Any] | None = None) -> tuple[dict, datetime]:
        for attempt in range(6):
            try:
                response = await self.client.get(url, params=params)
            except httpx.RequestError:
                if attempt == 5:
                    raise
                await asyncio.sleep(min(30, 2**attempt) + random.random())
                continue
            if response.status_code == 429 or response.status_code >= 500:
                delay = float(response.headers.get("Retry-After", 2**attempt))
                await asyncio.sleep(delay + random.random())
                continue
            response.raise_for_status()
            return response.json(), datetime.now(UTC)
        raise RuntimeError(f"source remained unavailable after retries: {url}")


def months(start: date, end: date) -> AsyncIterator[tuple[datetime, datetime]]:
    async def generate():
        cursor = date(start.year, start.month, 1)
        while cursor <= end:
            following = date(
                cursor.year + (cursor.month == 12), 1 if cursor.month == 12 else cursor.month + 1, 1
            )
            yield (
                datetime.combine(max(cursor, start), datetime.min.time(), UTC),
                datetime.combine(min(following, end + timedelta(days=1)), datetime.min.time(), UTC),
            )
            cursor = following

    return generate()


async def collect_live() -> dict[str, int]:
    initialize()
    source = SourceClient()
    counts: dict[str, int] = defaultdict(int)
    try:
        for basin in BASINS:
            metadata, captured = await source.json(f"{NWPS_BASE}/gauges/{basin.nwps_id}")
            metadata_archive = archive_payload(
                "nwps", f"gauges/{basin.nwps_id}", metadata, retrieved_at=captured
            )
            stageflow, captured_flow = await source.json(
                f"{NWPS_BASE}/gauges/{basin.nwps_id}/stageflow"
            )
            archive_payload(
                "nwps", f"gauges/{basin.nwps_id}/stageflow", stageflow, retrieved_at=captured_flow
            )
            with session_scope() as session:
                already = session.scalar(
                    select(StationSnapshotRow.id).where(
                        StationSnapshotRow.content_hash == metadata_archive.content_hash
                    )
                )
                if already is None:
                    session.add(
                        StationSnapshotRow(
                            gauge_id=basin.usgs_id,
                            nwps_id=basin.nwps_id,
                            captured_at=captured,
                            content_hash=metadata_archive.content_hash,
                            metadata_json=metadata,
                            thresholds_json=metadata.get("flood", {}).get("categories", {}),
                        )
                    )
            counts["nwps_payloads"] += int(metadata_archive.created) + 1
            for parameter in ("00065", "00060"):
                window_end = datetime.now(UTC)
                window_start = window_end - timedelta(hours=6)
                payload, retrieved = await source.json(
                    f"{BASE_URL}/collections/continuous/items",
                    {
                        "monitoring_location_id": f"USGS-{basin.usgs_id}",
                        "parameter_code": parameter,
                        "datetime": f"{window_start.isoformat()}/{window_end.isoformat()}",
                        "f": "json",
                        "limit": 1000,
                    },
                )
                archived = archive_payload(
                    "usgs",
                    f"live-continuous/{basin.usgs_id}/{parameter}",
                    payload,
                    retrieved_at=retrieved,
                    metadata={"start": window_start.isoformat(), "end": window_end.isoformat()},
                )
                observations = USGSClient.parse(payload, basin.usgs_id, parameter, retrieved)
                counts["observations"] += persist_observations(
                    observations, {"archive_hash": archived.content_hash}
                )
        return dict(counts)
    finally:
        await source.close()


async def collect_recent_stage_history(days: int = 9) -> dict[str, int]:
    """Reconcile the short stage-history window needed by sequence models.

    This deliberately has its own archive resource name.  A monthly historical
    partition can already exist while new readings in that same month continue
    to arrive, so treating that partition as immutable would leave a gap.
    """
    if days < 8:
        raise ValueError("at least eight days are required for a seven-day sequence history")
    initialize()
    source = SourceClient()
    counts: dict[str, int] = defaultdict(int)
    try:
        end = datetime.now(UTC)
        start = end - timedelta(days=days)
        for basin in BASINS:
            payload, retrieved = await source.json(
                f"{BASE_URL}/collections/continuous/items",
                {
                    "monitoring_location_id": f"USGS-{basin.usgs_id}",
                    "parameter_code": "00065",
                    "datetime": f"{start.isoformat()}/{end.isoformat()}",
                    "f": "json",
                    "limit": 10_000,
                },
            )
            archived = archive_payload(
                "usgs",
                f"live-history/{basin.usgs_id}/00065/{start:%Y%m%d}",
                payload,
                retrieved_at=retrieved,
                metadata={"start": start.isoformat(), "end": end.isoformat()},
            )
            observations = USGSClient.parse(payload, basin.usgs_id, "00065", retrieved)
            counts["observations"] += persist_observations(
                observations, {"archive_hash": archived.content_hash}
            )
            counts["payloads"] += int(archived.created)
        return dict(counts)
    finally:
        await source.close()


async def backfill_usgs(start: date, end: date, concurrency: int = 4) -> dict[str, int]:
    initialize()
    source = SourceClient()
    semaphore = asyncio.Semaphore(min(4, max(1, concurrency)))
    counts: dict[str, int] = defaultdict(int)

    async def fetch(basin: Basin, parameter: str, begin: datetime, finish: datetime) -> None:
        resource = f"continuous/{basin.usgs_id}/{parameter}/{begin:%Y-%m}"
        with session_scope() as session:
            completed = session.scalar(
                select(SourceArchiveRow.content_hash).where(
                    SourceArchiveRow.source == "usgs", SourceArchiveRow.resource == resource
                )
            )
        if completed:
            counts["partitions_skipped"] += 1
            return
        async with semaphore:
            payload, retrieved = await source.json(
                f"{BASE_URL}/collections/continuous/items",
                {
                    "monitoring_location_id": f"USGS-{basin.usgs_id}",
                    "parameter_code": parameter,
                    "datetime": f"{begin.isoformat()}/{finish.isoformat()}",
                    "f": "json",
                    "limit": 10000,
                },
            )
            archive = archive_payload(
                "usgs",
                resource,
                payload,
                retrieved_at=retrieved,
                metadata={"start": begin.isoformat(), "end": finish.isoformat()},
            )
            observations = USGSClient.parse(payload, basin.usgs_id, parameter, retrieved)
            counts["observations_seen"] += len(observations)
            counts["observations_inserted"] += persist_observations(
                observations, {"archive_hash": archive.content_hash}
            )
            counts["requests"] += 1
            counts["bytes"] += archive.byte_count

    tasks: list[asyncio.Task[None]] = []
    async for begin, finish in months(start, end):
        for basin in BASINS:
            for parameter in ("00065", "00060"):
                tasks.append(asyncio.create_task(fetch(basin, parameter, begin, finish)))
    try:
        completed = 0
        failures: list[str] = []
        for task in asyncio.as_completed(tasks):
            try:
                await task
            except Exception as exc:  # one unavailable partition must not discard progress
                failures.append(repr(exc))
                counts["partitions_failed"] += 1
            completed += 1
            if completed % 25 == 0 or completed == len(tasks):
                print(
                    json.dumps(
                        {
                            "completed_partitions": completed,
                            "total_partitions": len(tasks),
                            **counts,
                        }
                    ),
                    file=sys.stderr,
                    flush=True,
                )
        if failures:
            failure_path = get_settings().data_dir / "manifests" / "usgs-backfill-failures.json"
            failure_path.parent.mkdir(parents=True, exist_ok=True)
            failure_path.write_text(json.dumps(sorted(set(failures)), indent=2) + "\n")
        return dict(counts)
    finally:
        await source.close()


@dataclass
class Episode:
    gauge_id: str
    started_at: datetime
    last_above_at: datetime
    maximum_ft: float
    uncertain_end: bool


@dataclass(frozen=True)
class StormCluster:
    started_at: datetime
    ended_at: datetime
    gauge_ids: tuple[str, ...]
    episode_count: int


def cluster_episodes(episodes: list[Episode]) -> list[StormCluster]:
    """Merge episode windows expanded by 72 hours, including across basins."""
    clusters: list[StormCluster] = []
    margin = timedelta(hours=72)
    for episode in sorted(episodes, key=lambda item: item.started_at):
        start = episode.started_at - margin
        end = episode.last_above_at + margin
        if clusters and start <= clusters[-1].ended_at:
            previous = clusters.pop()
            clusters.append(
                StormCluster(
                    started_at=min(previous.started_at, start),
                    ended_at=max(previous.ended_at, end),
                    gauge_ids=tuple(sorted(set(previous.gauge_ids) | {episode.gauge_id})),
                    episode_count=previous.episode_count + 1,
                )
            )
        else:
            clusters.append(StormCluster(start, end, (episode.gauge_id,), 1))
    return clusters


SPLITS = {
    "training": (date(2007, 10, 1), date(2017, 12, 31)),
    "validation": (date(2018, 1, 1), date(2020, 12, 31)),
    "calibration": (date(2021, 1, 1), date(2023, 12, 31)),
    "test": (date(2024, 1, 1), None),
}


def cluster_split(cluster: StormCluster, cutoff: date) -> str | None:
    for name, (start, configured_end) in SPLITS.items():
        split_end = configured_end or cutoff
        start_at = datetime.combine(start, datetime.min.time(), UTC)
        end_at = datetime.combine(split_end + timedelta(days=1), datetime.min.time(), UTC)
        if cluster.started_at >= start_at and cluster.ended_at < end_at:
            return name
    return None


def find_episodes(
    rows: list[tuple[datetime, float | None]], threshold: float, gauge_id: str
) -> list[Episode]:
    episodes: list[Episode] = []
    active: Episode | None = None
    below_since: datetime | None = None
    previous: datetime | None = None
    for at, value in rows:
        gap = previous is not None and at - previous > timedelta(minutes=30)
        previous = at
        if value is not None and value >= threshold:
            if active is None:
                active = Episode(gauge_id, at, at, value, False)
            else:
                active = Episode(
                    gauge_id,
                    active.started_at,
                    at,
                    max(active.maximum_ft, value),
                    active.uncertain_end or gap,
                )
            below_since = None
        elif active is not None:
            if value is None or gap:
                active = Episode(
                    gauge_id, active.started_at, active.last_above_at, active.maximum_ft, True
                )
                below_since = None
            elif below_since is None:
                below_since = at
            elif at - below_since >= timedelta(hours=24):
                if episodes and active.started_at - episodes[-1].last_above_at < timedelta(
                    hours=72
                ):
                    prior = episodes.pop()
                    active = Episode(
                        gauge_id,
                        prior.started_at,
                        active.last_above_at,
                        max(prior.maximum_ft, active.maximum_ft),
                        prior.uncertain_end or active.uncertain_end,
                    )
                episodes.append(active)
                active = None
                below_since = None
    if active is not None:
        episodes.append(
            Episode(gauge_id, active.started_at, active.last_above_at, active.maximum_ft, True)
        )
    return episodes


def audit(end: date) -> Path:
    initialize()
    report: dict[str, Any] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "requested_cutoff": end.isoformat(),
        "targets": {},
    }
    all_episodes: list[Episode] = []
    cutoff_exclusive = datetime.combine(end + timedelta(days=1), datetime.min.time(), UTC)
    with session_scope() as session:
        for basin in BASINS:
            rows = session.execute(
                select(ObservationRow.event_time, ObservationRow.value)
                .where(
                    ObservationRow.gauge_id == basin.usgs_id,
                    ObservationRow.parameter_code == "00065",
                    ObservationRow.source == "usgs",
                    ObservationRow.event_time < cutoff_exclusive,
                )
                .order_by(ObservationRow.event_time)
            ).all()
            canonical = {
                at.replace(tzinfo=UTC) if at.tzinfo is None else at: value for at, value in rows
            }
            ordered = sorted(canonical.items())
            episodes = find_episodes(ordered, basin.flood_stage_ft, basin.usgs_id)
            all_episodes.extend(episodes)
            expected = max(
                0,
                int(
                    (
                        datetime.combine(end + timedelta(days=1), datetime.min.time(), UTC)
                        - datetime.combine(START_DATE, datetime.min.time(), UTC)
                    ).total_seconds()
                    / 900
                ),
            )
            report["targets"][basin.usgs_id] = {
                "name": basin.target_name,
                "threshold_ft": basin.flood_stage_ft,
                "stage_samples": len(ordered),
                "expected_15_minute_samples": expected,
                "coverage_fraction": len(ordered) / expected if expected else 0,
                "first_observation": ordered[0][0].isoformat() if ordered else None,
                "last_observation": ordered[-1][0].isoformat() if ordered else None,
                "episodes": [asdict(item) for item in episodes],
            }
    report["individual_episode_count"] = len(all_episodes)
    clusters = cluster_episodes(all_episodes)
    cluster_counts = {name: 0 for name in SPLITS}
    excluded_boundary_clusters = 0
    for cluster in clusters:
        split = cluster_split(cluster, end)
        if split is None:
            excluded_boundary_clusters += 1
        else:
            cluster_counts[split] += 1
    report["storm_clusters"] = [asdict(item) for item in clusters]
    report["storm_cluster_counts_by_split"] = cluster_counts
    report["boundary_overlapping_clusters_excluded"] = excluded_boundary_clusters
    target_episode_counts: dict[str, dict[str, int]] = {}
    for gauge_id in report["targets"]:
        target_episode_counts[gauge_id] = {name: 0 for name in SPLITS}
        for episode in all_episodes:
            if episode.gauge_id != gauge_id:
                continue
            midpoint = episode.started_at + (episode.last_above_at - episode.started_at) / 2
            for name, (start, configured_end) in SPLITS.items():
                split_end = configured_end or end
                if start <= midpoint.date() <= split_end:
                    target_episode_counts[gauge_id][name] += 1
                    break
    report["target_episode_counts_by_split"] = target_episode_counts
    report["minor_probability_gate"] = {
        "required_pooled_clusters": {"training": 30, "validation": 10, "calibration": 10},
        "required_target_episodes": {"training": 3, "calibration": 3},
        "eligible": (
            cluster_counts["training"] >= 30
            and cluster_counts["validation"] >= 10
            and cluster_counts["calibration"] >= 10
            and all(
                counts["training"] >= 3 and counts["calibration"] >= 3
                for counts in target_episode_counts.values()
            )
        ),
    }
    report["complete"] = all(
        item["coverage_fraction"] >= 0.9 for item in report["targets"].values()
    )
    output = get_settings().data_dir / "reports" / f"stage1-audit-{end.isoformat()}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, default=str, indent=2) + "\n")
    return output


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="HydroPulse stage-1 acquisition and audit")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("live")
    backfill = sub.add_parser("backfill-usgs")
    backfill.add_argument("--start", type=date.fromisoformat, default=START_DATE)
    backfill.add_argument(
        "--end",
        type=date.fromisoformat,
        default=datetime.now(UTC).date() - timedelta(days=1),
    )
    backfill.add_argument("--concurrency", type=int, default=4)
    report = sub.add_parser("audit")
    report.add_argument(
        "--end", type=date.fromisoformat, default=datetime.now(UTC).date() - timedelta(days=1)
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.command == "live":
        print(json.dumps(asyncio.run(collect_live()), indent=2))
    elif args.command == "backfill-usgs":
        print(
            json.dumps(asyncio.run(backfill_usgs(args.start, args.end, args.concurrency)), indent=2)
        )
    elif args.command == "audit":
        print(audit(args.end))


if __name__ == "__main__":
    main()
