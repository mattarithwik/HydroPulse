from __future__ import annotations

from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Any

import httpx

from hydropulse.domain import Observation

BASE_URL = "https://api.waterdata.usgs.gov/ogcapi/v1"
NULL_SENTINELS = {-999999.0, -9999.0, -999.0}


class USGSClient:
    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self.client = client or httpx.AsyncClient(
            timeout=30, headers={"User-Agent": "HydroPulse/0.1"}
        )

    async def latest(self, gauge_id: str, parameter_code: str = "00065") -> list[Observation]:
        params = {
            "monitoring_location_id": f"USGS-{gauge_id}",
            "parameter_code": parameter_code,
            "f": "json",
        }
        response = await self.client.get(
            f"{BASE_URL}/collections/latest-continuous/items", params=params
        )
        response.raise_for_status()
        now = datetime.now(UTC)
        return self.parse(response.json(), gauge_id, parameter_code, now)

    async def overlap(
        self, gauge_id: str, start: datetime, end: datetime, parameter_code: str = "00065"
    ) -> list[Observation]:
        params = {
            "monitoring_location_id": f"USGS-{gauge_id}",
            "parameter_code": parameter_code,
            "datetime": f"{start.isoformat()}/{end.isoformat()}",
            "f": "json",
            "limit": 10000,
        }
        response = await self.client.get(f"{BASE_URL}/collections/continuous/items", params=params)
        response.raise_for_status()
        return self.parse(response.json(), gauge_id, parameter_code, datetime.now(UTC))

    @staticmethod
    def parse(
        payload: dict[str, Any], gauge_id: str, parameter_code: str, ingested_at: datetime
    ) -> list[Observation]:
        observations: list[Observation] = []
        for feature in payload.get("features", []):
            properties = feature.get("properties", {})
            raw = properties.get("value")
            value = None if raw is None or float(raw) in NULL_SENTINELS else float(raw)
            event = (
                properties.get("time")
                or properties.get("datetime")
                or properties.get("phenomenonTime")
            )
            if not event:
                continue
            serialized = repr(feature).encode()
            observations.append(
                Observation(
                    source="usgs",
                    time_series_id=str(
                        properties.get("time_series_id")
                        or properties.get("monitoring_location_id")
                        or gauge_id
                    ),
                    gauge_id=gauge_id,
                    parameter_code=parameter_code,
                    event_time=datetime.fromisoformat(event.replace("Z", "+00:00")),
                    value=value,
                    unit=str(
                        properties.get("unit_of_measure")
                        or ("ft" if parameter_code == "00065" else "ft3/s")
                    ),
                    first_seen_at=ingested_at,
                    ingested_at=ingested_at,
                    source_modified_at=None,
                    qualifiers=tuple(properties.get("qualifier", []) or []),
                    approved=properties.get("approval_status") == "Approved",
                    raw_payload_hash=sha256(serialized).hexdigest(),
                )
            )
        return observations


def reconciliation_window(kind: str, now: datetime) -> tuple[datetime, datetime]:
    widths = {
        "frequent": timedelta(hours=6),
        "nightly": timedelta(days=30),
        "monthly": timedelta(days=366),
    }
    return now - widths[kind], now
