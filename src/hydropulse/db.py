from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Iterator

from sqlalchemy import JSON, DateTime, Float, String, Text, UniqueConstraint, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from hydropulse.config import get_settings
from hydropulse.domain import Forecast, Observation


class Base(DeclarativeBase):
    pass


class ObservationRow(Base):
    __tablename__ = "observation_revisions"
    __table_args__ = (UniqueConstraint("source", "time_series_id", "event_time", "payload_hash"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(32), index=True)
    time_series_id: Mapped[str] = mapped_column(String(128))
    gauge_id: Mapped[str] = mapped_column(String(32), index=True)
    parameter_code: Mapped[str] = mapped_column(String(8), index=True)
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    unit: Mapped[str] = mapped_column(String(24))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source_modified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    qualifiers: Mapped[list[str]] = mapped_column(JSON, default=list)
    approved: Mapped[bool | None] = mapped_column(nullable=True)
    payload_hash: Mapped[str] = mapped_column(String(64))
    raw_payload: Mapped[dict] = mapped_column(JSON)

    def to_domain(self) -> Observation:
        def utc(value: datetime | None) -> datetime | None:
            if value is None:
                return None
            return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)

        return Observation(
            source=self.source,
            time_series_id=self.time_series_id,
            gauge_id=self.gauge_id,
            parameter_code=self.parameter_code,
            event_time=utc(self.event_time),
            value=self.value,
            unit=self.unit,
            first_seen_at=utc(self.first_seen_at),
            ingested_at=utc(self.ingested_at),
            source_modified_at=utc(self.source_modified_at),
            qualifiers=tuple(self.qualifiers),
            approved=self.approved,
            raw_payload_hash=self.payload_hash,
        )


class ForecastRow(Base):
    __tablename__ = "forecasts"
    id: Mapped[str] = mapped_column(String(24), primary_key=True)
    target_id: Mapped[str] = mapped_column(String(32), index=True)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    payload: Mapped[dict] = mapped_column(JSON)


class EventRow(Base):
    __tablename__ = "event_log"
    sequence: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    target_id: Mapped[str] = mapped_column(String(32), index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    payload: Mapped[dict] = mapped_column(JSON)


class SourceArchiveRow(Base):
    __tablename__ = "source_archives"
    content_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    source: Mapped[str] = mapped_column(String(32), index=True)
    resource: Mapped[str] = mapped_column(String(256), index=True)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source_modified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    media_type: Mapped[str] = mapped_column(String(64))
    byte_count: Mapped[int]
    relative_path: Mapped[str] = mapped_column(Text)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)


class WatermarkRow(Base):
    __tablename__ = "watermarks"
    source: Mapped[str] = mapped_column(String(32), primary_key=True)
    series_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    state: Mapped[dict] = mapped_column(JSON, default=dict)


class StationSnapshotRow(Base):
    __tablename__ = "station_snapshots"
    id: Mapped[int] = mapped_column(primary_key=True)
    gauge_id: Mapped[str] = mapped_column(String(32), index=True)
    nwps_id: Mapped[str] = mapped_column(String(16), index=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    content_hash: Mapped[str] = mapped_column(String(64))
    metadata_json: Mapped[dict] = mapped_column(JSON)
    thresholds_json: Mapped[dict] = mapped_column(JSON)


engine = create_engine(get_settings().database_url)


def initialize() -> None:
    get_settings().data_dir.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(engine)


@contextmanager
def session_scope() -> Iterator[Session]:
    with Session(engine) as session:
        with session.begin():
            yield session


class Repository:
    def observations(
        self, gauge_id: str, start: datetime | None = None, limit: int = 1000
    ) -> list[Observation]:
        with Session(engine) as session:
            query = select(ObservationRow).where(ObservationRow.gauge_id == gauge_id)
            if start:
                query = query.where(ObservationRow.event_time >= start)
            rows = session.scalars(
                query.order_by(ObservationRow.event_time.desc()).limit(limit)
            ).all()
            # Select the newest ingested revision per scientific identity.
            canonical: dict[tuple[str, str, datetime], ObservationRow] = {}
            for row in sorted(rows, key=lambda item: item.ingested_at):
                canonical[(row.source, row.time_series_id, row.event_time)] = row
            return [
                row.to_domain()
                for row in sorted(canonical.values(), key=lambda item: item.event_time)
            ]

    def save_forecast(self, forecast: Forecast) -> None:
        with session_scope() as session:
            session.merge(
                ForecastRow(
                    id=forecast.id,
                    target_id=forecast.target_id,
                    issued_at=forecast.issued_at,
                    payload=forecast.model_dump(mode="json"),
                )
            )

    def latest_forecast(self, target_id: str) -> Forecast | None:
        with Session(engine) as session:
            row = session.scalar(
                select(ForecastRow)
                .where(ForecastRow.target_id == target_id)
                .order_by(ForecastRow.issued_at.desc())
                .limit(1)
            )
            return Forecast.model_validate(row.payload) if row else None

    def forecast(self, forecast_id: str) -> Forecast | None:
        with Session(engine) as session:
            row = session.get(ForecastRow, forecast_id)
            return Forecast.model_validate(row.payload) if row else None
