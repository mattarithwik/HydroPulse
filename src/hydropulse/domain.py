from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from hashlib import sha256
from typing import Iterable

from pydantic import BaseModel, ConfigDict, Field, model_validator

HORIZONS = (1, 6, 24, 48, 72)
QUANTILES = (0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95)


class EvidenceStatus(StrEnum):
    VALIDATED = "validated"
    INSUFFICIENT_EVENTS = "insufficient_events"
    DATUM_MISMATCH = "datum_mismatch"
    EXPERIMENTAL = "experimental"


class Freshness(StrEnum):
    SUPPORTED = "supported"
    DEGRADED = "degraded"
    SUPPRESSED = "suppressed"


class EventType(StrEnum):
    OBSERVED_FLOODING = "observed_flooding"
    PREDICTED_STAGE_CROSSING = "predicted_stage_crossing"


class Basin(BaseModel):
    slug: str
    name: str
    target_name: str
    usgs_id: str
    nwps_id: str
    flood_stage_ft: float
    latitude: float
    longitude: float
    river: str


BASINS = (
    Basin(
        slug="cedar-ia",
        name="Cedar, Iowa",
        target_name="Cedar Rapids",
        usgs_id="05464500",
        nwps_id="CIDI4",
        flood_stage_ft=12,
        latitude=41.971,
        longitude=-91.667,
        river="Cedar River",
    ),
    Basin(
        slug="james-va",
        name="James, Virginia",
        target_name="Cartersville",
        usgs_id="02035000",
        nwps_id="CARV2",
        flood_stage_ft=20,
        latitude=37.671,
        longitude=-78.086,
        river="James River",
    ),
    Basin(
        slug="neuse-nc",
        name="Neuse, North Carolina",
        target_name="Goldsboro",
        usgs_id="02089000",
        nwps_id="GLDN7",
        flood_stage_ft=18,
        latitude=35.337,
        longitude=-77.992,
        river="Neuse River",
    ),
)


class Observation(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    source: str
    time_series_id: str
    gauge_id: str
    parameter_code: str
    event_time: datetime
    value: float | None
    unit: str
    first_seen_at: datetime
    ingested_at: datetime
    source_modified_at: datetime | None = None
    qualifiers: tuple[str, ...] = ()
    approved: bool | None = None
    raw_payload_hash: str

    @property
    def identity(self) -> tuple[str, str, datetime]:
        return self.source, self.time_series_id, self.event_time

    @property
    def revision_identity(self) -> tuple[str, str, datetime, datetime | None, str]:
        return (*self.identity, self.source_modified_at, self.raw_payload_hash)


class WeatherFeature(BaseModel):
    provider: str
    version: str
    issued_at: datetime | None
    valid_from: datetime
    valid_to: datetime
    first_seen_at: datetime | None
    assumed_available_at: datetime | None
    variable: str
    unit: str
    basin_slug: str
    aggregation: str
    value: float | None
    coverage: float = Field(ge=0, le=1)


class QuantilePoint(BaseModel):
    horizon_hours: int
    valid_at: datetime
    quantiles: dict[str, float]

    @model_validator(mode="after")
    def ordered(self) -> "QuantilePoint":
        values = [self.quantiles[key] for key in sorted(self.quantiles, key=float)]
        if values != sorted(values):
            raise ValueError("forecast quantiles must not cross")
        return self


class ThresholdCrossing(BaseModel):
    threshold_name: str
    threshold_ft: float
    horizon_hours: int
    median_crosses: bool
    forecast_interval_straddles: bool


class Forecast(BaseModel):
    id: str
    target_id: str
    issued_at: datetime
    newest_observation_at: datetime
    observation_age_minutes: float
    available_data_cutoff: datetime
    snapshot_id: str
    stage_model_version: str
    discharge_model_version: str
    threshold_version: str
    weather_provider: str | None
    weather_cycle: datetime | None
    weather_coverage: float | None
    mode: str
    replay_run_id: str | None = None
    freshness: Freshness
    degradation_reasons: tuple[str, ...] = ()
    stage: tuple[QuantilePoint, ...]
    maximum_stage: tuple[QuantilePoint, ...]
    discharge: tuple[QuantilePoint, ...]
    threshold_crossings: tuple[ThresholdCrossing, ...] = ()
    horizon_model_mapping: dict[int, str]


def freshness_at(issued_at: datetime, observed_at: datetime) -> tuple[Freshness, float]:
    age = (issued_at - observed_at).total_seconds() / 60
    if age < 0:
        raise ValueError("observation cannot be newer than forecast issuance")
    if age <= 90:
        return Freshness.SUPPORTED, age
    if age <= 120:
        return Freshness.DEGRADED, age
    return Freshness.SUPPRESSED, age


def stable_id(*parts: object) -> str:
    return sha256("|".join(map(str, parts)).encode()).hexdigest()[:24]


@dataclass(frozen=True)
class NativeLabel:
    crossed: bool | None
    maximum: float | None


def native_window_label(
    values: Iterable[tuple[datetime, float | None]],
    issued_at: datetime,
    horizon_hours: int,
    threshold: float,
    expected_interval: timedelta = timedelta(minutes=15),
) -> NativeLabel:
    """A crossing proves positive; incomplete coverage can never prove negative."""
    end = issued_at + timedelta(hours=horizon_hours)
    samples = sorted((time, value) for time, value in values if issued_at < time <= end)
    valid = [(time, value) for time, value in samples if value is not None]
    maximum = max((value for _, value in valid), default=None)
    if maximum is not None and maximum >= threshold:
        return NativeLabel(True, maximum)
    expected = int(timedelta(hours=horizon_hours) / expected_interval)
    complete = len(valid) >= expected
    return NativeLabel(False if complete else None, maximum)
