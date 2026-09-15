from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import select

from hydropulse.adapters.usgs import BASE_URL, USGSClient
from hydropulse.archive import archive_payload
from hydropulse.config import get_settings
from hydropulse.db import SourceArchiveRow, initialize, session_scope
from hydropulse.domain import BASINS, Basin
from hydropulse.ingestion import persist_observations
from hydropulse.stage1 import SourceClient, months

NLDI_BASE = "https://api.water.usgs.gov/nldi/linked-data/nwissite"
USGS_METADATA = "https://api.waterdata.usgs.gov/ogcapi/v1/collections/time-series-metadata/items"
REQUIRED_RELEASE_PROXY = "02087183"


@dataclass(frozen=True)
class Candidate:
    gauge_id: str
    name: str
    comid: int | None
    mainstem_id: str | None
    is_target_mainstem: bool
    stage_series_id: str | None
    discharge_series_id: str | None
    overlap_start: str | None
    overlap_end: str | None
    nominal_overlap_fraction: float
    selection_reason: str = ""


def _chunks(items: list[str], size: int) -> list[list[str]]:
    return [items[index : index + size] for index in range(0, len(items), size)]


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _series_by_station(payloads: list[dict[str, Any]]) -> dict[str, dict[str, dict[str, Any]]]:
    result: dict[str, dict[str, dict[str, Any]]] = {}
    for payload in payloads:
        for feature in payload.get("features", []):
            props = feature.get("properties", {})
            if props.get("computation_period_identifier") != "Points":
                continue
            if props.get("statistic_id") != "00011" or props.get("primary") != "Primary":
                continue
            parameter = props.get("parameter_code")
            if parameter not in {"00065", "00060"}:
                continue
            station = str(props.get("monitoring_location_id", "")).removeprefix("USGS-")
            existing = result.setdefault(station, {}).get(parameter)
            # Prefer the series with the latest end, then earliest begin.
            if existing is None or (
                props.get("end", ""),
                tuple(reversed(props.get("begin", ""))),
            ) > (existing.get("end", ""), tuple(reversed(existing.get("begin", "")))):
                result[station][parameter] = props
    return result


def select_candidates(
    basin: Basin,
    features: list[dict[str, Any]],
    series: dict[str, dict[str, dict[str, Any]]],
    start: date,
    cutoff: date,
) -> tuple[list[Candidate], list[Candidate]]:
    target_feature = next(
        (
            item
            for item in features
            if item.get("properties", {}).get("identifier") == f"USGS-{basin.usgs_id}"
        ),
        None,
    )
    target_mainstem = (
        target_feature.get("properties", {}).get("mainstem") if target_feature else None
    )
    total_seconds = (
        datetime.combine(cutoff, datetime.max.time(), UTC)
        - datetime.combine(start, datetime.min.time(), UTC)
    ).total_seconds()
    candidates: list[Candidate] = []
    seen: set[str] = set()
    for feature in features:
        props = feature.get("properties", {})
        gauge_id = str(props.get("identifier", "")).removeprefix("USGS-")
        if not gauge_id or gauge_id == basin.usgs_id or gauge_id in seen:
            continue
        seen.add(gauge_id)
        station_series = series.get(gauge_id, {})
        stage = station_series.get("00065")
        discharge = station_series.get("00060")
        if not stage and not discharge:
            continue
        begins = [_parse_time(item["begin"]) for item in (stage, discharge) if item]
        ends = [_parse_time(item["end"]) for item in (stage, discharge) if item]
        overlap_start = max(datetime.combine(start, datetime.min.time(), UTC), min(begins))
        overlap_end = min(datetime.combine(cutoff, datetime.max.time(), UTC), max(ends))
        overlap = max(0.0, (overlap_end - overlap_start).total_seconds() / total_seconds)
        mainstem_id = props.get("mainstem")
        candidates.append(
            Candidate(
                gauge_id=gauge_id,
                name=props.get("name", gauge_id),
                comid=props.get("comid"),
                mainstem_id=mainstem_id,
                is_target_mainstem=bool(target_mainstem and mainstem_id == target_mainstem),
                stage_series_id=stage.get("id") if stage else None,
                discharge_series_id=discharge.get("id") if discharge else None,
                overlap_start=overlap_start.isoformat(),
                overlap_end=overlap_end.isoformat(),
                nominal_overlap_fraction=overlap,
            )
        )
    suitable = [item for item in candidates if item.nominal_overlap_fraction >= 0.5]
    ranked = sorted(
        suitable,
        key=lambda item: (
            not item.is_target_mainstem,
            -(item.stage_series_id is not None and item.discharge_series_id is not None),
            -item.nominal_overlap_fraction,
            item.gauge_id,
        ),
    )
    selected: list[Candidate] = []
    mainstem = [item for item in ranked if item.is_target_mainstem][:5]
    tributaries = [item for item in ranked if not item.is_target_mainstem][:3]
    for item in mainstem:
        selected.append(
            Candidate(
                **{**item.__dict__, "selection_reason": "connected mainstem and historical overlap"}
            )
        )
    for item in tributaries:
        selected.append(
            Candidate(
                **{
                    **item.__dict__,
                    "selection_reason": "connected tributary coverage and historical overlap",
                }
            )
        )
    if basin.usgs_id == "02089000" and REQUIRED_RELEASE_PROXY in {
        item.gauge_id for item in candidates
    }:
        proxy = next(item for item in candidates if item.gauge_id == REQUIRED_RELEASE_PROXY)
        if proxy.gauge_id not in {item.gauge_id for item in selected}:
            if len(selected) >= 8:
                selected.pop()
            selected.append(
                Candidate(
                    **{
                        **proxy.__dict__,
                        "selection_reason": "required observed downstream-of-dam release proxy candidate",
                    }
                )
            )
    return ranked, selected[:8]


async def run(start: date, cutoff: date) -> Path:
    initialize()
    report: dict[str, Any] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "audit_start": start.isoformat(),
        "archive_cutoff": cutoff.isoformat(),
        "distance_limit_river_km": 300,
        "targets": {},
        "limitations": [
            "NLDI confirms hydrologic connectivity; this response does not expose per-site route distance.",
            "Nominal overlap uses series begin/end metadata and must be verified with observed coverage before training.",
            "A downstream-of-dam gauge is an observed release proxy, not a known future release schedule.",
        ],
    }
    async with httpx.AsyncClient(timeout=90, headers={"User-Agent": "HydroPulse/0.1"}) as client:
        for basin in BASINS:
            nldi_url = f"{NLDI_BASE}/USGS-{basin.usgs_id}/navigation/UT/nwissite"
            response = await client.get(nldi_url, params={"distance": 300})
            response.raise_for_status()
            topology = response.json()
            archive_payload("nldi", f"upstream-tributaries/{basin.usgs_id}/300km", topology)
            features = topology.get("features", [])
            identifiers = sorted(
                {
                    item.get("properties", {}).get("identifier")
                    for item in features
                    if item.get("properties", {}).get("identifier", "").startswith("USGS-")
                }
            )
            metadata_payloads: list[dict[str, Any]] = []
            for chunk in _chunks(identifiers, 40):
                metadata_response = await client.get(
                    USGS_METADATA,
                    params={
                        "monitoring_location_id": ",".join(chunk),
                        "parameter_code": "00065,00060",
                        "f": "json",
                        "limit": 5000,
                    },
                )
                metadata_response.raise_for_status()
                payload = metadata_response.json()
                metadata_payloads.append(payload)
                archive_payload(
                    "usgs",
                    f"time-series-metadata/upstream/{basin.usgs_id}/{len(metadata_payloads):03d}",
                    payload,
                )
            ranked, selected = select_candidates(
                basin, features, _series_by_station(metadata_payloads), start, cutoff
            )
            report["targets"][basin.usgs_id] = {
                "name": basin.target_name,
                "connected_sites_returned": len(features),
                "instantaneous_candidates": len(ranked),
                "minimum_three_suitable_met": len(selected) >= 3,
                "selected": [item.__dict__ for item in selected],
            }
    output = get_settings().data_dir / "reports" / f"upstream-audit-{cutoff.isoformat()}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n")
    return output


async def backfill_selected(report_path: Path, start: date, cutoff: date) -> dict[str, int]:
    """Backfill only frozen shortlist candidates, preserving monthly resumability."""
    initialize()
    report = json.loads(report_path.read_text())
    gauge_ids = sorted(
        {item["gauge_id"] for target in report["targets"].values() for item in target["selected"]}
    )
    source = SourceClient()
    semaphore = asyncio.Semaphore(4)
    counts = {
        "gauges": len(gauge_ids),
        "partitions_total": 0,
        "partitions_skipped": 0,
        "partitions_downloaded": 0,
        "partitions_failed": 0,
        "observations_inserted": 0,
        "bytes": 0,
    }

    async def fetch(gauge_id: str, parameter: str, begin: datetime, finish: datetime) -> None:
        resource = f"continuous/{gauge_id}/{parameter}/{begin:%Y-%m}"
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
                    "monitoring_location_id": f"USGS-{gauge_id}",
                    "parameter_code": parameter,
                    "datetime": f"{begin.isoformat()}/{finish.isoformat()}",
                    "f": "json",
                    "limit": 10000,
                },
            )
        archived = archive_payload(
            "usgs",
            resource,
            payload,
            retrieved_at=retrieved,
            metadata={
                "role": "selected_upstream",
                "start": begin.isoformat(),
                "end": finish.isoformat(),
            },
        )
        observations = USGSClient.parse(payload, gauge_id, parameter, retrieved)
        counts["observations_inserted"] += persist_observations(
            observations, {"archive_hash": archived.content_hash, "role": "selected_upstream"}
        )
        counts["partitions_downloaded"] += 1
        counts["bytes"] += archived.byte_count

    tasks: list[asyncio.Task[None]] = []
    async for begin, finish in months(start, cutoff):
        for gauge_id in gauge_ids:
            for parameter in ("00065", "00060"):
                tasks.append(asyncio.create_task(fetch(gauge_id, parameter, begin, finish)))
    counts["partitions_total"] = len(tasks)
    failures: list[str] = []
    try:
        for completed_index, task in enumerate(asyncio.as_completed(tasks), start=1):
            try:
                await task
            except Exception as exc:
                counts["partitions_failed"] += 1
                failures.append(repr(exc))
            if completed_index % 50 == 0 or completed_index == len(tasks):
                print(
                    json.dumps({"completed": completed_index, **counts}),
                    file=sys.stderr,
                    flush=True,
                )
    finally:
        await source.close()
    if failures:
        failure_path = get_settings().data_dir / "manifests" / "upstream-backfill-failures.json"
        failure_path.parent.mkdir(parents=True, exist_ok=True)
        failure_path.write_text(json.dumps(sorted(set(failures)), indent=2) + "\n")
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit and acquire connected upstream gauges")
    subparsers = parser.add_subparsers(dest="command", required=True)
    audit_parser = subparsers.add_parser("audit")
    audit_parser.add_argument("--start", type=date.fromisoformat, default=date(2007, 10, 1))
    audit_parser.add_argument("--end", type=date.fromisoformat, required=True)
    backfill_parser = subparsers.add_parser("backfill")
    backfill_parser.add_argument("--report", type=Path, required=True)
    backfill_parser.add_argument("--start", type=date.fromisoformat, default=date(2007, 10, 1))
    backfill_parser.add_argument("--end", type=date.fromisoformat, required=True)
    args = parser.parse_args()
    if args.command == "audit":
        print(asyncio.run(run(args.start, args.end)))
    else:
        print(
            json.dumps(asyncio.run(backfill_selected(args.report, args.start, args.end)), indent=2)
        )


if __name__ == "__main__":
    main()
