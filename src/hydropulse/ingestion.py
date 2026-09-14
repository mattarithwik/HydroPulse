from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from hydropulse.db import ObservationRow, WatermarkRow, session_scope
from hydropulse.domain import Observation


def persist_observations(observations: list[Observation], raw_payload: dict[str, Any]) -> int:
    """Persist all distinct revisions and advance watermarks in one transaction."""
    if not observations:
        return 0
    inserted = 0
    with session_scope() as session:
        earliest = min(item.event_time for item in observations)
        latest_time = max(item.event_time for item in observations)
        series_ids = {item.time_series_id for item in observations}
        existing = set(
            session.execute(
                select(
                    ObservationRow.time_series_id,
                    ObservationRow.event_time,
                    ObservationRow.payload_hash,
                ).where(
                    ObservationRow.time_series_id.in_(series_ids),
                    ObservationRow.event_time >= earliest,
                    ObservationRow.event_time <= latest_time,
                )
            ).all()
        )
        for observation in observations:
            event_time = observation.event_time
            naive_event_time = event_time.replace(tzinfo=None)
            identities = {
                (observation.time_series_id, event_time, observation.raw_payload_hash),
                (observation.time_series_id, naive_event_time, observation.raw_payload_hash),
            }
            if identities & existing:
                continue
            session.add(
                ObservationRow(
                    source=observation.source,
                    time_series_id=observation.time_series_id,
                    gauge_id=observation.gauge_id,
                    parameter_code=observation.parameter_code,
                    event_time=observation.event_time,
                    value=observation.value,
                    unit=observation.unit,
                    first_seen_at=observation.first_seen_at,
                    ingested_at=observation.ingested_at,
                    source_modified_at=observation.source_modified_at,
                    qualifiers=list(observation.qualifiers),
                    approved=observation.approved,
                    payload_hash=observation.raw_payload_hash,
                    raw_payload=raw_payload,
                )
            )
            inserted += 1
        for series_id in {item.time_series_id for item in observations}:
            latest = max(
                item.event_time for item in observations if item.time_series_id == series_id
            )
            watermark = session.get(WatermarkRow, {"source": "usgs", "series_key": series_id})
            if watermark is None:
                session.add(
                    WatermarkRow(
                        source="usgs",
                        series_key=series_id,
                        event_time=latest,
                        updated_at=datetime.now(UTC),
                        state={},
                    )
                )
            elif watermark.event_time.replace(tzinfo=UTC) < latest:
                watermark.event_time = latest
                watermark.updated_at = datetime.now(UTC)
    return inserted
